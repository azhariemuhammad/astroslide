from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
import cv2
import astropy.io.fits as fits
import numpy as np
import io
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
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


@app.post("/api/enhance")
async def enhance_uploaded_image(
    file: UploadFile = File(...),
    preset: Optional[str] = Form("moon_hdr"),
    output_format: Optional[str] = Form("jpeg"),
    intensity: Optional[float] = Form(0.75),
    halo: Optional[float] = Form(0.0),
    hdr: Optional[float] = Form(0.0),
    sharpen: Optional[float] = Form(0.5),
    warmth: Optional[float] = Form(0.0),
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
        preset: Enhancement preset - "moon_hdr" (default), "mineral_moon", or "nebula"
        output_format: Output format - "jpeg" (default), "png", or "tiff"
        intensity: Enhancement intensity from 0.0 to 1.0 (default 0.75)
        halo: Glow around the moon from 0.0 to 1.0 (Mineral Moon only, default 0)
        hdr: Local tone mapping strength from 0.0 to 1.0 (Mineral Moon only, default 0)
        sharpen: Multi-scale sharpening strength from 0.0 to 1.0 (Mineral Moon only, default 0.5)
        warmth: Colour balance from -1.0 (cool) to 1.0 (warm) (Mineral Moon only, default 0)
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
    img_array = decode_image(contents, filename)
    # Presets that work at full bit depth also need to know if the data is linear (FITS)
    img_float = decode_image_float(contents, filename) if PRESETS[preset].get("float_input") else None
    display_referred = not filename.lower().endswith(FITS_EXTENSIONS)
    
    # Validate and clamp intensity
    intensity = max(0.0, min(1.0, intensity))
    adjustments = {
        "denoise": max(0.0, min(1.0, denoise)),
        "star_reduction": max(0.0, min(1.0, star_reduction)),
        "saturation": max(0.0, min(2.0, saturation)),
        "sharpening": max(0.0, min(1.0, sharpening)),
    }
    
    # Apply enhancement with selected preset (run in thread pool to avoid blocking)
    try:
        loop = asyncio.get_event_loop()
        enhanced_array = await loop.run_in_executor(
            executor,
            lambda: enhance_with_preset(img_array, preset, intensity, adjustments, img_float, display_referred, max(0.0, min(1.0, halo)), max(0.0, min(1.0, hdr)), max(0.0, min(1.0, sharpen)), max(-1.0, min(1.0, warmth)))
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
