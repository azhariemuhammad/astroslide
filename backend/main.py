from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
import cv2
import astropy.io.fits as fits
import numpy as np
import io
import os
import re
import base64
import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
import stack_jobs
from stacking import VIDEO_EXTENSIONS
from presets import enhance_with_preset, apply_interactive_stretch, compute_auto_stf, float_to_uint8, PRESETS, OutputFormat

app = FastAPI(title="AstroSlide API", version="1.1.0")

# Thread pool executor for CPU-intensive operations
executor = ThreadPoolExecutor(max_workers=4)

# CORS middleware for frontend access
# Allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint"""
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


def _read_fits_data(contents: bytes) -> np.ndarray:
    """
    Read FITS pixel data as float32, (H, W) or (H, W, 3), in the file's own units.
    """
    with fits.open(io.BytesIO(contents)) as hdul:
        # Compressed FITS keeps the image in an extension, not the primary HDU
        data = next((hdu.data for hdu in hdul if hdu.data is not None), None)
        if data is None:
            raise ValueError("FITS file contains no image data")
        data = np.squeeze(np.asarray(data, dtype=np.float32))

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

        if _maybe_16_bit(contents):
            # PIL reduces 16-bit RGB to 8 bits; OpenCV keeps them (e.g. our own 16-bit exports, stacks)
            data = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_UNCHANGED)
            if data is not None and data.dtype == np.uint16:
                if data.ndim == 3:
                    data = cv2.cvtColor(data[..., :3], cv2.COLOR_BGR2RGB)
                return np.ascontiguousarray(_gray_to_rgb(data.astype(np.float32) / 65535.0))

        img = Image.open(io.BytesIO(contents))
        if img.mode in HIGH_BIT_DEPTH_MODES:
            data = np.clip(np.asarray(img, dtype=np.float32) / 65535.0, 0, 1)
            return np.ascontiguousarray(_gray_to_rgb(data))
        return np.asarray(img.convert('RGB'), dtype=np.float32) / 255.0
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

        img = Image.open(io.BytesIO(contents))
        if img.mode in HIGH_BIT_DEPTH_MODES:
            # PIL's convert('RGB') clips 16-bit values at 255; scale down instead
            return float_to_uint8(decode_image_float(contents, filename))
        return np.array(img.convert('RGB'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode image: {str(e)}")


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
    
    # Read file contents
    contents = await file.read()
    
    # Check file size (50MB limit)
    max_size = 50 * 1024 * 1024  # 50MB
    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is 50MB, received {len(contents) / 1024 / 1024:.1f}MB"
        )
    
    # Decode image
    filename = file.filename or ""
    # Presets that work at full bit depth only need the float decode, and to know if the data is linear (FITS)
    img_float = decode_image_float(contents, filename) if PRESETS[preset].get("float_input") else None
    img_array = img_float if img_float is not None else decode_image(contents, filename)
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
        "notes": moon_notes(info, deconvolve, display_referred),
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
    img_array = decode_image_float(contents, file.filename or "")
    
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

# A 4-minute raw Seestar AVI is ~4 GB, so the limit is far above the image limit
MAX_STACK_UPLOAD = int(float(os.environ.get("ASTROSLIDE_MAX_STACK_GB", "6")) * 1024 ** 3)
MAX_STACK_CLIPS = 8


@app.post("/api/stack", status_code=202)
async def start_stack(
    files: list[UploadFile] = File(...),
    keep: float = Form(0.7),
    local_align: bool = Form(True),
):
    """
    Start stacking one or more Moon videos (.avi raw or .mp4) from the same night.

    Args:
        files: the video clips
        keep: fraction of usable frames to stack, 0.05-1 (default 0.7)
        local_align: correct local seeing distortion (default on)

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
    stack_jobs.submit(
        folder, videos, [Path(f.filename).name for f in files], max(0.05, min(1.0, keep)), local_align, f"{stem}_stacked"
    )
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
