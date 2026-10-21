from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import cv2
import astropy.io.fits as fits
import numpy as np
import io
import json
import os
import re
import base64
import asyncio
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
import stack_jobs
from stacking import VIDEO_EXTENSIONS
from presets import enhance_with_preset, apply_interactive_stretch, compute_auto_stf, float_to_uint8, PRESETS, OutputFormat

# Interactive API docs (/docs, /redoc, /openapi.json); off in the Heroku image
API_DOCS = os.environ.get("ASTROSLIDE_API_DOCS", "1") == "1"
app = FastAPI(
    title="AstroSlide API", version="1.1.0",
    **({} if API_DOCS else {"docs_url": None, "redoc_url": None, "openapi_url": None}),
)

# Thread pool executor for CPU-intensive operations. ASTROSLIDE_THREADS caps it on
# small hosts (a 512 MB Heroku dyno can't hold four images in flight)
THREADS = int(os.environ.get("ASTROSLIDE_THREADS", "4"))
executor = ThreadPoolExecutor(max_workers=THREADS)

# Built frontend to serve from this app (single-process deploys such as Heroku);
# unset when nginx serves it (docker-compose)
STATIC_DIR = os.environ.get("ASTROSLIDE_STATIC_DIR")

# Larger images are downscaled before processing. Unset = no limit; set on small hosts,
# where the Nebula preset needs ~140 bytes per pixel (an 8 MP image ~1.2 GB)
MAX_PIXELS = int(float(os.environ.get("ASTROSLIDE_MAX_MEGAPIXELS", "0")) * 1_000_000)

# Images larger than this are refused before decoding: a small file can declare a huge
# image (a 50 MB PNG of one colour can hold gigapixels), and decoding it would exhaust memory
MAX_DECODE_PIXELS = int(float(os.environ.get("ASTROSLIDE_MAX_DECODE_MEGAPIXELS", "180")) * 1_000_000)
# JPEGs decode at down to 1/8 scale (see _open_image), so they may declare 64x more.
# Every other format is checked against MAX_DECODE_PIXELS before decoding
Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS * 64 if MAX_DECODE_PIXELS else None

MAX_UPLOAD = int(float(os.environ.get("ASTROSLIDE_MAX_UPLOAD_MB", "50")) * 1024 ** 2)
# A 4-minute raw Seestar AVI is ~4 GB, so the limit is far above the image limit
MAX_STACK_UPLOAD = int(float(os.environ.get("ASTROSLIDE_MAX_STACK_GB", "6")) * 1024 ** 3)
MAX_STACK_CLIPS = 8
# Video uploads received at once; more are refused instead of filling the disk
MAX_STACK_UPLOADS = int(os.environ.get("ASTROSLIDE_MAX_STACK_UPLOADS", "2"))
# Stacking jobs uploading, queued or running at once
MAX_STACK_JOBS = int(os.environ.get("ASTROSLIDE_MAX_STACK_JOBS", "4"))

# Browser origins allowed to call the API from another site, comma-separated ("*" = any).
# Not needed when the frontend is served from the same origin (Heroku, nginx)
CORS_ORIGINS = [o.strip() for o in os.environ.get("ASTROSLIDE_CORS_ORIGINS", "*").split(",") if o.strip()]

# Per-client limits on the processing endpoints (0 = off). Costs are in "units": a
# preview or histogram is 1, a full render 2-3; each client's bucket refills at
# RATE_LIMIT units per minute and holds two minutes' worth, for bursts of slider work
RATE_LIMIT = int(os.environ.get("ASTROSLIDE_RATE_LIMIT", "0"))
# Stacking jobs a client can start per hour (bucket of half that, at least 1)
STACK_JOBS_PER_HOUR = int(os.environ.get("ASTROSLIDE_STACK_JOBS_PER_HOUR", "0"))
# Processing requests one client may have running or waiting for a slot (0 = no limit)
MAX_REQUESTS_PER_CLIENT = int(os.environ.get("ASTROSLIDE_MAX_REQUESTS_PER_CLIENT", "0"))
# Proxies in front of the app that append the caller to X-Forwarded-For (Heroku's router: 1).
# The client is that many entries from the right; entries further left are whatever the
# client sent, so trusting them would let anyone pick a fresh address per request
PROXY_HOPS = int(os.environ.get("ASTROSLIDE_PROXY_HOPS", "0"))

# Redirect http:// to https:// behind a TLS-terminating proxy that sets X-Forwarded-Proto
FORCE_HTTPS = os.environ.get("ASTROSLIDE_FORCE_HTTPS") == "1"


async def _send_error(send, status: int, detail: str, headers: Optional[list] = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start", "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())] + (headers or []),
    })
    await send({"type": "http.response.body", "body": body})


class UploadGuard:
    """
    Refuse oversized and excess uploads from their headers, before the body is read:
    Starlette spools a multipart body to disk before any endpoint can look at it.
    """

    # Multipart framing and the form fields around the files
    FORM_OVERHEAD = 1024 ** 2

    def __init__(self, app):
        self.app = app
        self.stack_uploads = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)

        stacking = scope["path"] == "/api/stack"
        limit = (MAX_STACK_UPLOAD if stacking else MAX_UPLOAD) + self.FORM_OVERHEAD
        headers = dict(scope["headers"])
        length = headers.get(b"content-length")
        if length is None:
            # Browsers always send a length with a form; without one the size is unknown
            if b"transfer-encoding" in headers:
                return await _send_error(send, 411, "Uploads need a Content-Length header")
        elif not length.isdigit():
            return await _send_error(send, 400, "Invalid Content-Length")
        elif int(length) > limit:
            what = f"{MAX_STACK_UPLOAD / 1024 ** 3:g} GB" if stacking else f"{MAX_UPLOAD / 1024 ** 2:g} MB"
            return await _send_error(send, 413, f"Upload too large: the limit is {what}")

        if not stacking:
            return await self.app(scope, receive, send)
        if self.stack_uploads >= MAX_STACK_UPLOADS:
            return await _send_error(
                send, 503, "The server is busy receiving other videos. Try again in a few minutes.",
                [(b"retry-after", b"60")],
            )
        self.stack_uploads += 1
        try:
            return await self.app(scope, receive, send)
        finally:
            self.stack_uploads -= 1


def client_address(scope) -> str:
    """The caller's IP: the X-Forwarded-For entry PROXY_HOPS from the right, else the socket peer."""
    if PROXY_HOPS:
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for", b"").decode("latin-1")
        hosts = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hosts) >= PROXY_HOPS:
            return hosts[-PROXY_HOPS]
    return scope["client"][0] if scope.get("client") else "unknown"


class TokenBuckets:
    """
    One token bucket per client: holds up to `capacity` tokens, refills `rate` per second,
    and a request spends its cost. Bursts up to the capacity, a steady `rate` after that.
    """

    # Clients remembered at most; idle ones (full buckets) are forgotten first
    MAX_CLIENTS = 10_000

    def __init__(self, capacity: float, rate: float):
        self.capacity, self.rate = capacity, rate
        self.buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens, last update)

    def take(self, client: str, cost: float, now: float) -> float:
        """Spend `cost` tokens; returns 0 if allowed, else seconds until it would be."""
        tokens, last = self.buckets.get(client, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < cost:
            self.buckets[client] = (tokens, now)
            return (cost - tokens) / self.rate
        self.buckets[client] = (tokens - cost, now)
        if len(self.buckets) > self.MAX_CLIENTS:
            self._forget_idle(now)
        return 0.0

    def _forget_idle(self, now: float) -> None:
        full_after = self.capacity / self.rate
        for client, (_, last) in list(self.buckets.items()):
            if now - last >= full_after:
                del self.buckets[client]
        while len(self.buckets) > self.MAX_CLIENTS:  # all active: drop the first seen
            del self.buckets[next(iter(self.buckets))]


class ClientLimits:
    """
    Per-client request rate (token buckets) and in-flight cap for the processing endpoints.
    The rate limit bounds how much work a client can ask for over time; the in-flight cap
    bounds its share of the queue for the processing slots, so one busy client delays
    others by at most a few requests. Limits live in this process, which is the whole
    app on a single dyno; several processes would each need their own share, or a
    shared store such as Redis.
    """

    COSTS = {"/api/enhance": 3, "/api/stretch": 2, "/api/stretch-preview": 1, "/api/auto-stf": 1, "/api/histogram": 1}

    def __init__(self, app):
        self.app = app
        self.images = TokenBuckets(2 * RATE_LIMIT, RATE_LIMIT / 60) if RATE_LIMIT else None
        self.stacks = (TokenBuckets(max(1, STACK_JOBS_PER_HOUR // 2), STACK_JOBS_PER_HOUR / 3600)
                       if STACK_JOBS_PER_HOUR else None)
        self.in_flight: dict[str, int] = {}

    async def __call__(self, scope, receive, send):
        path = scope.get("path")
        if scope["type"] != "http" or scope["method"] != "POST" or (path not in self.COSTS and path != "/api/stack"):
            return await self.app(scope, receive, send)

        client = client_address(scope)
        buckets, cost = (self.stacks, 1) if path == "/api/stack" else (self.images, self.COSTS[path])
        wait = buckets.take(client, cost, time.monotonic()) if buckets else 0.0
        if wait:
            seconds = max(1, int(wait + 0.999))
            what = "stacking jobs" if path == "/api/stack" else "requests"
            return await _send_error(
                send, 429, f"Too many {what} from your address. Try again in {seconds} s.",
                [(b"retry-after", str(seconds).encode())],
            )

        if path == "/api/stack" or not MAX_REQUESTS_PER_CLIENT:
            return await self.app(scope, receive, send)
        if self.in_flight.get(client, 0) >= MAX_REQUESTS_PER_CLIENT:
            return await _send_error(send, 429, "Too many requests at once from your address. Wait for them to finish.",
                                     [(b"retry-after", b"2")])
        self.in_flight[client] = self.in_flight.get(client, 0) + 1
        try:
            return await self.app(scope, receive, send)
        finally:
            self.in_flight[client] -= 1
            if not self.in_flight[client]:
                del self.in_flight[client]


class SecurityHeaders:
    """Browser security headers on every response, and the https redirect (FORCE_HTTPS)."""

    # The SPA loads only its own files; images are data: URLs from the API or blob: URLs of local files
    CSP = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if FORCE_HTTPS and dict(scope["headers"]).get(b"x-forwarded-proto") == b"http":
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            query = scope.get("query_string", b"").decode("latin-1")
            location = f"https://{host}{scope.get('raw_path', b'').decode('latin-1') or scope['path']}"
            location += f"?{query}" if query else ""
            await send({"type": "http.response.start", "status": 308,
                        "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")]})
            return await send({"type": "http.response.body", "body": b""})

        extra = list(self.HEADERS)
        if not scope["path"].startswith(("/docs", "/redoc")):  # Swagger UI loads from a CDN
            extra.append((b"content-security-policy", self.CSP.encode()))
        if scope.get("scheme") == "https":
            extra.append((b"strict-transport-security", b"max-age=31536000"))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        return await self.app(scope, receive, send_with_headers)


class HeavyRequestLimit:
    """
    Run at most THREADS image requests at a time, from upload read to encoded reply.
    Limiting only the executor isn't enough: each waiting request would already hold its
    decoded image (several copies at float32), which is what fills a small server's memory.
    Waiting requests hold only their upload, which Starlette spools to disk.
    """

    PATHS = {"/api/enhance", "/api/stretch", "/api/stretch-preview", "/api/auto-stf", "/api/histogram"}

    def __init__(self, app, limit: int):
        self.app = app
        self.slots = asyncio.Semaphore(limit)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] in self.PATHS:
            async with self.slots:
                return await self.app(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(HeavyRequestLimit, limit=THREADS)

# The app uses no cookies or auth, so cross-origin calls never need credentials
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])

# Added last = run first: refuse floods and uploads before CORS or the request limit see them
app.add_middleware(UploadGuard)
app.add_middleware(ClientLimits)
app.add_middleware(SecurityHeaders)


@app.get("/")
async def root():
    """The editor when the frontend is bundled in, otherwise a health check"""
    if STATIC_DIR:
        return FileResponse(Path(STATIC_DIR) / "index.html")
    return {"status": "ok", "message": "AstroSlide API is running"}


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/presets")
async def get_presets():
    """
    Get available enhancement presets with descriptions.
    """
    return {
        "presets": [
            {
                "id": preset_id,
                "name": preset_data["name"],
                "description": preset_data["description"],
                "best_for": preset_data["best_for"]
            }
            for preset_id, preset_data in PRESETS.items()
        ]
    }


@app.get("/api/output-formats")
async def get_output_formats():
    """
    Get available output formats.
    """
    return {
        "formats": [
            {
                "id": "jpeg",
                "name": "JPEG",
                "description": "Compressed format, smaller file size",
                "extension": ".jpg",
                "mime_type": "image/jpeg"
            },
            {
                "id": "png",
                "name": "PNG",
                "description": "Lossless format, preserves quality",
                "extension": ".png",
                "mime_type": "image/png"
            },
            {
                "id": "tiff",
                "name": "TIFF",
                "description": "Professional format, maximum quality",
                "extension": ".tiff",
                "mime_type": "image/tiff"
            }
        ]
    }


def validate_image_file(file: UploadFile) -> bool:
    """Validate uploaded file type and size"""
    allowed_types = ["image/jpeg", "image/png", "image/tiff", "application/fits", "image/fits"]
    allowed_extensions = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".fits", ".fit"]
    
    # Check file extension
    file_ext = file.filename.lower() if file.filename else ""
    has_valid_ext = any(file_ext.endswith(ext) for ext in allowed_extensions)
    
    return has_valid_ext or file.content_type in allowed_types


FITS_EXTENSIONS = ('.fits', '.fit')
# PIL modes holding more than 8 bits per pixel (16-bit grayscale PNG/TIFF)
HIGH_BIT_DEPTH_MODES = ('I;16', 'I;16B', 'I;16L', 'I')


class ImageTooLarge(ValueError):
    pass


def _check_pixels(count: int) -> None:
    """Refuse an image from its declared size, before its pixels are decoded."""
    if MAX_DECODE_PIXELS and count > MAX_DECODE_PIXELS:
        raise ImageTooLarge(
            f"The image has {count / 1e6:.0f} megapixels; this server accepts up to {MAX_DECODE_PIXELS / 1e6:g}"
        )


def _open_image(contents: bytes) -> Image.Image:
    """
    Open with PIL (header only) and refuse it if too large to decode. A JPEG larger than
    MAX_PIXELS is set to decode at 1/2, 1/4 or 1/8 scale: libjpeg scales while decoding,
    so a 24 MP camera JPEG never exists in memory at full size. The scale is the smallest
    that still covers MAX_PIXELS; fit_pixel_budget then resizes the rest of the way.
    """
    img = Image.open(io.BytesIO(contents))
    if img.format == "JPEG" and MAX_PIXELS and img.width * img.height > MAX_PIXELS:
        scale = (MAX_PIXELS / (img.width * img.height)) ** 0.5
        img.draft("RGB", (max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    _check_pixels(img.width * img.height)
    return img


def declared_size(contents: bytes, filename: str) -> Optional[tuple[int, int]]:
    """(height, width) as stored in the file, before any reduced-size decode; None for FITS."""
    if filename.lower().endswith(FITS_EXTENSIONS):
        return None
    try:
        width, height = Image.open(io.BytesIO(contents)).size
        return height, width
    except Exception:
        return None


def _read_fits_data(contents: bytes) -> np.ndarray:
    """
    Read FITS pixel data as float32, (H, W) or (H, W, 3), in the file's own units.
    """
    with fits.open(io.BytesIO(contents)) as hdul:
        # Compressed FITS keeps the image in an extension, not the primary HDU.
        # The header gives the shape, so huge images are refused before their data is read
        images = (fits.PrimaryHDU, fits.ImageHDU, fits.CompImageHDU)
        hdu = next((h for h in hdul if isinstance(h, images) and h.shape and np.prod(h.shape) > 0), None)
        if hdu is None:
            raise ValueError("FITS file contains no image data")
        _check_pixels(int(np.prod(hdu.shape)) // (3 if len(hdu.shape) == 3 else 1))
        data = np.squeeze(np.asarray(hdu.data, dtype=np.float32))

    # Color FITS is stored channels-first (C, H, W); OpenCV needs (H, W, C)
    if data.ndim == 3 and data.shape[0] in (3, 4) and data.shape[-1] not in (3, 4):
        data = np.moveaxis(data, 0, -1)
    if data.ndim == 3 and data.shape[2] == 4:
        data = data[:, :, :3]  # drop alpha

    if data.ndim not in (2, 3) or (data.ndim == 3 and data.shape[2] != 3):
        raise ValueError(f"Unsupported FITS image shape {data.shape}")

    # Stacks often have NaN borders from registration
    return np.ascontiguousarray(np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0))


def _gray_to_rgb(data: np.ndarray) -> np.ndarray:
    return np.repeat(data[:, :, np.newaxis], 3, axis=2) if data.ndim == 2 else data


def _maybe_16_bit(contents: bytes) -> bool:
    """16-bit PNG (bit depth in the IHDR chunk), or any TIFF."""
    if contents[:8] == b'\x89PNG\r\n\x1a\n':
        return len(contents) > 24 and contents[24] == 16
    return contents[:4] in (b'II*\x00', b'MM\x00*')


def decode_image_float(contents: bytes, filename: str) -> np.ndarray:
    """
    Decode image to float32 RGB (H, W, 3) in 0-1, keeping full bit depth.
    
    FITS is min-max normalized but stays linear with full precision; 16-bit
    PNG/TIFF keep all 16 bits. Use this for stretching, where 8-bit data
    posterizes the faint background.
    """
    try:
        if filename.lower().endswith(FITS_EXTENSIONS):
            data = _read_fits_data(contents)
            low, high = float(data.min()), float(data.max())
            data = (data - low) / (high - low) if high > low else np.zeros_like(data)
            return _gray_to_rgb(data)

        img = _open_image(contents)
        if _maybe_16_bit(contents):
            # PIL reduces 16-bit RGB to 8 bits; OpenCV keeps them (e.g. our own 16-bit exports, stacks)
            data = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_UNCHANGED)
            if data is not None and data.dtype == np.uint16:
                if data.ndim == 3:
                    data = cv2.cvtColor(data[..., :3], cv2.COLOR_BGR2RGB)
                return np.ascontiguousarray(_gray_to_rgb(data.astype(np.float32) / 65535.0))

        if img.mode in HIGH_BIT_DEPTH_MODES:
            data = np.clip(np.asarray(img, dtype=np.float32) / 65535.0, 0, 1)
            return np.ascontiguousarray(_gray_to_rgb(data))
        return np.asarray(img.convert('RGB'), dtype=np.float32) / 255.0
    except (ImageTooLarge, Image.DecompressionBombError) as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {str(e)}")


def decode_image(contents: bytes, filename: str) -> np.ndarray:
    """Decode image to uint8 RGB (H, W, 3), handling FITS and standard formats"""
    try:
        if filename.lower().endswith(FITS_EXTENSIONS):
            data = _read_fits_data(contents)
            # Normalize FITS data to 0-255 range
            data = cv2.normalize(data, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            return np.ascontiguousarray(_gray_to_rgb(data))

        img = _open_image(contents)
        if img.mode in HIGH_BIT_DEPTH_MODES:
            # PIL's convert('RGB') clips 16-bit values at 255; scale down instead
            return float_to_uint8(decode_image_float(contents, filename))
        return np.array(img.convert('RGB'))
    except HTTPException:
        raise
    except (ImageTooLarge, Image.DecompressionBombError) as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {str(e)}")


def fit_pixel_budget(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Downscale to MAX_PIXELS if it's set and exceeded; also says whether it did."""
    h, w = img.shape[:2]
    if not MAX_PIXELS or h * w <= MAX_PIXELS:
        return img, False
    scale = (MAX_PIXELS / (h * w)) ** 0.5
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA), True


def encode_output(img_array: np.ndarray, output_format: OutputFormat = "jpeg") -> tuple[bytes, str]:
    """
    Encode enhanced image to specified format.
    
    Args:
        img_array: Enhanced image as numpy array (RGB)
        output_format: "jpeg", "png", or "tiff"
    
    Returns:
        Tuple of (image_bytes, mime_type)
    """
    if img_array.dtype == np.uint16 and output_format in ("png", "tiff"):
        # 16-bit RGB: PIL can't write it, OpenCV can (it expects BGR)
        ok, encoded = cv2.imencode(".png" if output_format == "png" else ".tiff", cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR))
        if not ok:
            raise ValueError("16-bit encoding failed")
        return encoded.tobytes(), "image/png" if output_format == "png" else "image/tiff"
    if img_array.dtype == np.uint16:
        img_array = (img_array >> 8).astype(np.uint8)

    enhanced_img = Image.fromarray(img_array)
    buffered = io.BytesIO()
    
    if output_format == "jpeg":
        enhanced_img.save(buffered, format="JPEG", quality=98, subsampling=0)
        mime_type = "image/jpeg"
    elif output_format == "png":
        enhanced_img.save(buffered, format="PNG", compress_level=6)
        mime_type = "image/png"
    elif output_format == "tiff":
        enhanced_img.save(buffered, format="TIFF", compression="lzw")
        mime_type = "image/tiff"
    else:
        # Default to JPEG
        enhanced_img.save(buffered, format="JPEG", quality=98, subsampling=0)
        mime_type = "image/jpeg"
    
    return buffered.getvalue(), mime_type


def moon_notes(info: dict, deconvolve: float, display_referred: bool) -> list[str]:
    """Plain-language feedback on the capture, from what the Moon preset measured."""
    notes = []
    if not info:
        return notes
    clipped = info.get("clipped_fraction", 0.0)
    if clipped > 0.01:
        notes.append(
            f"{clipped * 100:.0f}% of the moon is overexposed (pure white): that detail and colour can't be recovered. "
            "Next time use manual exposure and slightly underexpose; you can brighten later."
        )
    sigma = info.get("psf_sigma")
    if sigma is not None and deconvolve > 0:
        if sigma < 0.5:
            notes.append("The limb is already very sharp (likely sharpened in-camera), so deconvolution was skipped.")
        else:
            notes.append(f"Deconvolution used a blur of {sigma:.1f} px, measured from the moon's edge.")
    if display_referred and sigma is not None and sigma < 0.5:
        notes.append("For the best colour and detail, process the FITS file instead of the JPEG.")
    return notes


@app.post("/api/enhance")
async def enhance_uploaded_image(
    file: UploadFile = File(...),
    preset: Optional[str] = Form("mineral_moon"),
    output_format: Optional[str] = Form("jpeg"),
    intensity: Optional[float] = Form(0.75),
    halo: Optional[float] = Form(0.0),
    hdr: Optional[float] = Form(0.0),
    sharpen: Optional[float] = Form(0.5),
    warmth: Optional[float] = Form(0.0),
    deconvolve: Optional[float] = Form(0.0),
    # Pro Mode fine-tuning (neutral defaults = no change)
    denoise: Optional[float] = Form(0.0),
    star_reduction: Optional[float] = Form(0.0),
    saturation: Optional[float] = Form(1.0),
    sharpening: Optional[float] = Form(0.0)
):
    """
    Upload an image and receive an enhanced version using the specified preset.
    
    Args:
        file: Image file (JPEG, PNG, TIFF, FITS)
        preset: Enhancement preset - "mineral_moon" (default) or "nebula"
        output_format: Output format - "jpeg" (default), "png", or "tiff"
        intensity: Enhancement intensity from 0.0 to 1.0 (default 0.75)
        halo: Glow around the moon from 0.0 to 1.0 (Mineral Moon only, default 0)
        hdr: Local tone mapping strength from 0.0 to 1.0 (Mineral Moon only, default 0)
        sharpen: Multi-scale sharpening strength from 0.0 to 1.0 (Mineral Moon only, default 0.5)
        warmth: Colour balance from -1.0 (cool) to 1.0 (warm) (Mineral Moon only, default 0)
        deconvolve: Deconvolution strength from 0.0 to 1.0, PSF measured from the limb (Mineral Moon only, default 0)
        denoise, star_reduction, sharpening: Pro Mode amounts from 0.0 to 1.0 (default 0)
        saturation: Pro Mode saturation multiplier from 0.0 to 2.0 (default 1.0)
    
    Returns:
        JSON with enhanced image as base64 data URL
    """
    # Validate file
    if not validate_image_file(file):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Supported formats: JPEG, PNG, TIFF, FITS"
        )
    
    # Validate preset
    if preset not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{preset}'. Available presets: {list(PRESETS.keys())}"
        )
    
    # Validate output format
    valid_formats = ["jpeg", "png", "tiff"]
    if output_format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid output format '{output_format}'. Available formats: {valid_formats}"
        )
    
    # Read file contents (UploadGuard has already refused oversized uploads)
    contents = await file.read()
    
    # Decode image
    filename = file.filename or ""
    # Presets that work at full bit depth only need the float decode, and to know if the data is linear (FITS)
    img_float = decode_image_float(contents, filename) if PRESETS[preset].get("float_input") else None
    img_array = img_float if img_float is not None else decode_image(contents, filename)
    original_size = declared_size(contents, filename) or img_array.shape[:2]
    img_array, downscaled = fit_pixel_budget(img_array)
    downscaled = downscaled or tuple(original_size) != img_array.shape[:2]
    if img_float is not None:
        img_float = img_array
    display_referred = not filename.lower().endswith(FITS_EXTENSIONS)
    
    # Validate and clamp intensity
    intensity = max(0.0, min(1.0, intensity))
    adjustments = {
        "denoise": max(0.0, min(1.0, denoise)),
        "star_reduction": max(0.0, min(1.0, star_reduction)),
        "saturation": max(0.0, min(2.0, saturation)),
        "sharpening": max(0.0, min(1.0, sharpening)),
    }
    
    # Full-precision presets keep 16 bits for lossless formats, for further editing
    bit_depth = 16 if PRESETS[preset].get("float_input") and output_format in ("png", "tiff") else 8
    deconvolve = max(0.0, min(1.0, deconvolve))
    info: dict = {}

    # Apply enhancement with selected preset (run in thread pool to avoid blocking)
    try:
        loop = asyncio.get_event_loop()
        enhanced_array = await loop.run_in_executor(
            executor,
            lambda: enhance_with_preset(
                img_array, preset, intensity, adjustments, img_float, display_referred,
                max(0.0, min(1.0, halo)), max(0.0, min(1.0, hdr)), max(0.0, min(1.0, sharpen)),
                max(-1.0, min(1.0, warmth)), deconvolve, bit_depth, info
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enhancement failed: {str(e)}")
    
    # Encode to selected output format (run in thread pool to avoid blocking)
    try:
        loop = asyncio.get_event_loop()
        output_bytes, mime_type = await loop.run_in_executor(
            executor,
            encode_output,
            enhanced_array,
            output_format
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to encode output: {str(e)}")
    
    # Return as base64
    enhanced_base64 = base64.b64encode(output_bytes).decode('utf-8')
    
    # Determine file extension for response
    ext_map = {"jpeg": "jpg", "png": "png", "tiff": "tiff"}
    output_ext = ext_map.get(output_format, "jpg")
    
    return JSONResponse({
        "status": "success",
        "enhanced_image": f"data:{mime_type};base64,{enhanced_base64}",
        "original_filename": file.filename,
        "preset_used": preset,
        "preset_name": PRESETS[preset]["name"],
        "output_format": output_format,
        "output_extension": output_ext,
        "intensity": intensity,
        "bit_depth": 16 if enhanced_array.dtype == np.uint16 else 8,
        "notes": moon_notes(info, deconvolve, display_referred) + ([
            f"This {original_size[1]}x{original_size[0]} image was processed at "
            f"{enhanced_array.shape[1]}x{enhanced_array.shape[0]}: this server's limit is {MAX_PIXELS / 1e6:g} megapixels."
        ] if downscaled else []),
        "message": f"Image enhanced successfully using {PRESETS[preset]['name']} at {int(intensity * 100)}% intensity"
    })


@app.post("/api/auto-stf")
async def auto_stf_endpoint(file: UploadFile = File(...)):
    """
    Compute PixInsight-style AutoSTF parameters (shadows, midtones, highlights)
    for the MTF stretch, based on background median and noise.
    """
    if not validate_image_file(file):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    contents = await file.read()
    img_array = decode_image_float(contents, file.filename or "")
    
    loop = asyncio.get_event_loop()
    params = await loop.run_in_executor(executor, compute_auto_stf, img_array)
    
    return JSONResponse({"status": "success", **params})


@app.post("/api/histogram")
async def calculate_histogram(file: UploadFile = File(...)):
    """
    Calculate RGB and luminance histogram for an image.
    
    Returns histogram data for visualization (256 bins per channel).
    """
    if not validate_image_file(file):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Supported formats: JPEG, PNG, TIFF, FITS"
        )
    
    contents = await file.read()
    img_array = decode_image(contents, file.filename or "")
    
    # Convert to BGR for OpenCV
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # Calculate histograms for each channel
    hist_b = cv2.calcHist([img_bgr], [0], None, [256], [0, 256]).flatten().tolist()
    hist_g = cv2.calcHist([img_bgr], [1], None, [256], [0, 256]).flatten().tolist()
    hist_r = cv2.calcHist([img_bgr], [2], None, [256], [0, 256]).flatten().tolist()
    
    # Calculate luminance histogram
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    hist_lum = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten().tolist()
    
    return JSONResponse({
        "status": "success",
        "histogram": {
            "red": hist_r,
            "green": hist_g,
            "blue": hist_b,
            "luminance": hist_lum
        }
    })


class StretchForm:
    """MTF stretch + optional star removal parameters shared by the stretch endpoints."""

    def __init__(
        self,
        shadows: float = Form(0.0),
        midtones: float = Form(0.5),
        highlights: float = Form(1.0),
        remove_stars: bool = Form(False),
        star_sensitivity: float = Form(0.5),
        inpaint_radius: int = Form(3),
    ):
        self.params = {
            "shadows": shadows,
            "midtones": midtones,
            "highlights": highlights,
            "remove_stars_flag": remove_stars,
            "star_sensitivity": star_sensitivity,
            "inpaint_radius": inpaint_radius,
        }


async def _run_stretch(file: UploadFile, stretch: StretchForm, output_format: str, max_size: Optional[int] = None):
    """Decode at full bit depth, optionally downscale, stretch, and encode. Returns a data URL."""
    if not validate_image_file(file):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    contents = await file.read()
    img_array, _ = fit_pixel_budget(decode_image_float(contents, file.filename or ""))
    
    h, w = img_array.shape[:2]
    if max_size and max(h, w) > max_size:
        scale = max_size / max(h, w)
        img_array = cv2.resize(img_array, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    
    try:
        loop = asyncio.get_event_loop()
        stretched = await loop.run_in_executor(executor, lambda: apply_interactive_stretch(img_array, **stretch.params))
        output_bytes, mime_type = await loop.run_in_executor(executor, encode_output, stretched, output_format)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stretch failed: {str(e)}")
    
    return f"data:{mime_type};base64,{base64.b64encode(output_bytes).decode('utf-8')}"


@app.post("/api/stretch")
async def interactive_stretch_endpoint(
    file: UploadFile = File(...),
    stretch: StretchForm = Depends(),
    output_format: Optional[str] = Form("jpeg")
):
    """
    Interactive MTF stretch at full resolution.
    """
    image = await _run_stretch(file, stretch, output_format)
    return JSONResponse({"status": "success", "enhanced_image": image, "output_format": output_format})


@app.post("/api/stretch-preview")
async def interactive_stretch_preview_endpoint(
    file: UploadFile = File(...),
    stretch: StretchForm = Depends()
):
    """
    Fast interactive stretch preview (downscaled to 800px, JPEG).
    """
    image = await _run_stretch(file, stretch, "jpeg", max_size=800)
    return JSONResponse({"status": "success", "preview_image": image})


# ---------------------------------------------------------------------------
# Video stacking: upload -> background job -> poll -> download (see stack_jobs.py)
# ---------------------------------------------------------------------------


@app.post("/api/stack", status_code=202)
async def start_stack(
    files: list[UploadFile] = File(...),
    keep: float = Form(0.7),
    local_align: bool = Form(True),
    sharpen: float = Form(0.5),
):
    """
    Start stacking one or more Moon videos (.avi raw or .mp4) from the same night.

    Args:
        files: the video clips
        keep: fraction of usable frames to stack, 0.05-1 (default 0.7)
        local_align: correct local seeing distortion (default on)
        sharpen: post-stack sharpening, 0-1 (default 0.5 = restores what the data holds; 0 = none)

    Returns:
        {"job_id"}; poll GET /api/stack/{job_id}, then fetch /api/stack/{job_id}/result
    """
    if not 1 <= len(files) <= MAX_STACK_CLIPS:
        raise HTTPException(status_code=400, detail=f"Upload 1 to {MAX_STACK_CLIPS} video clips")
    for f in files:
        if not (f.filename or "").lower().endswith(VIDEO_EXTENSIONS):
            raise HTTPException(status_code=400, detail=f"{f.filename}: not a video. Supported: {', '.join(VIDEO_EXTENSIONS)}")
    total = sum(f.size or 0 for f in files)
    if total > MAX_STACK_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"Videos too large: {total / 1024 ** 3:.1f} GB, the limit is {MAX_STACK_UPLOAD / 1024 ** 3:.0f} GB"
        )
    if stack_jobs.active_jobs() >= MAX_STACK_JOBS:
        raise HTTPException(status_code=503, detail="The stacker is busy with other videos. Try again in a few minutes.")

    job_id, folder = stack_jobs.new_job()
    loop = asyncio.get_event_loop()
    videos = []
    try:
        for i, f in enumerate(files):
            target = folder / "input" / f"{i:02d}{Path(f.filename).suffix.lower()}"
            # The upload is already spooled to a temp file; copy it off the event loop
            with open(target, "wb") as out:
                await loop.run_in_executor(None, shutil.copyfileobj, f.file, out, 4 * 1024 * 1024)
            videos.append(target)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    stem = re.sub(r"[^\w.-]", "_", Path(files[0].filename).stem)[:80] or "moon"
    options = {"keep": max(0.05, min(1.0, keep)), "local_align": local_align, "sharpen": max(0.0, min(1.0, sharpen))}
    stack_jobs.submit(folder, videos, [Path(f.filename).name for f in files], options, f"{stem}_stacked")
    return {"status": "accepted", "job_id": job_id}


@app.get("/api/stack/{job_id}")
async def stack_status(job_id: str):
    """Job state: uploading | queued | running | done | error, with progress 0-1 and, when done, notes and report."""
    folder = stack_jobs.job_folder(job_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Unknown or expired stacking job")
    return stack_jobs.read_status(folder)


@app.get("/api/stack/{job_id}/result")
async def stack_result(job_id: str):
    """The stacked image: 16-bit FITS (linear, from raw video) or 16-bit PNG."""
    folder = stack_jobs.job_folder(job_id)
    path = stack_jobs.result_path(folder) if folder else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No result for this job (not finished, failed, or expired)")
    media_type = "image/png" if path.suffix == ".png" else "application/fits"
    return FileResponse(path, media_type=media_type, filename=path.name)


# Registered last so every /api route above takes precedence
if STATIC_DIR:
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
