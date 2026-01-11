from fastapi import FastAPI, UploadFile, File, HTTPException, Form
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
from typing import Optional, Literal
from presets import enhance_with_preset, PRESETS, PresetType, OutputFormat

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
    allowed_extensions = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".fits"]
    
    # Check file extension
    file_ext = file.filename.lower() if file.filename else ""
    has_valid_ext = any(file_ext.endswith(ext) for ext in allowed_extensions)
    
    return has_valid_ext or file.content_type in allowed_types


def decode_image(contents: bytes, filename: str) -> np.ndarray:
    """Decode image from bytes, handling FITS and standard formats"""
    try:
        # Handle FITS files
        if filename.lower().endswith('.fits'):
            hdul = fits.open(io.BytesIO(contents))
            data = hdul[0].data
            hdul.close()
            
            # Normalize FITS data to 0-255 range
            if data.dtype != np.uint8:
                data = cv2.normalize(data, None, 0, 255, cv2.NORM_MINMAX)
                data = data.astype(np.uint8)
            
            # Handle grayscale FITS
            if len(data.shape) == 2:
                data = cv2.cvtColor(data, cv2.COLOR_GRAY2RGB)
            
            return data
        else:
            # Handle standard image formats
            img = Image.open(io.BytesIO(contents))
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            return np.array(img)
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
    preset: Optional[str] = Form("general"),
    output_format: Optional[str] = Form("jpeg"),
    intensity: Optional[float] = Form(0.75),
    star_spikes: Optional[bool] = Form(False)
):
    """
    Upload an image and receive an enhanced version using the specified preset.
    
    Args:
        file: Image file (JPEG, PNG, TIFF, FITS)
        preset: Enhancement preset - "mineral_moon_subtle", "deep_sky", or "general" (default)
        output_format: Output format - "jpeg" (default), "png", or "tiff"
        intensity: Enhancement intensity from 0.0 to 1.0 (default 0.75)
        star_spikes: If true, add subtle 4-point diffraction spikes to bright stars
    
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
    img_array = decode_image(contents, file.filename or "")
    
    # Validate and clamp intensity
    intensity = max(0.0, min(1.0, intensity))
    
    # Apply enhancement with selected preset (run in thread pool to avoid blocking)
    try:
        loop = asyncio.get_event_loop()
        enhanced_array = await loop.run_in_executor(
            executor,
            lambda: enhance_with_preset(img_array, preset, intensity, star_spikes)
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


@app.post("/api/preview-preset")
async def preview_preset(
    file: UploadFile = File(...),
    preset: str = Form("general")
):
    """
    Generate a small thumbnail preview of what a preset will do.
    
    Returns a 200x200px preview for fast processing.
    """
    if not validate_image_file(file):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Supported formats: JPEG, PNG, TIFF, FITS"
        )
    
    if preset not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{preset}'"
        )
    
    contents = await file.read()
    img_array = decode_image(contents, file.filename or "")
    
    # Resize to thumbnail (200x200 max, maintain aspect ratio)
    h, w = img_array.shape[:2]
    max_size = 200
    if h > w:
        new_h = max_size
        new_w = int(w * (max_size / h))
    else:
        new_w = max_size
        new_h = int(h * (max_size / w))
    
    thumbnail = cv2.resize(img_array, (new_w, new_h), interpolation=cv2.INTER_AREA)
    
    # Apply preset at full intensity
    try:
        loop = asyncio.get_event_loop()
        enhanced_thumb = await loop.run_in_executor(
            executor,
            lambda: enhance_with_preset(thumbnail, preset, 1.0, False)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")
    
    # Encode as JPEG
    enhanced_img = Image.fromarray(enhanced_thumb)
    buffered = io.BytesIO()
    enhanced_img.save(buffered, format="JPEG", quality=85)
    preview_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return JSONResponse({
        "status": "success",
        "preview_image": f"data:image/jpeg;base64,{preview_base64}",
        "preset": preset
    })


@app.post("/api/reduce-stars")
async def reduce_stars_endpoint(
    file: UploadFile = File(...),
    reduction_amount: float = Form(0.5),
    output_format: Optional[str] = Form("jpeg")
):
    """
    Standalone star reduction endpoint.
    
    Args:
        file: Image file
        reduction_amount: How much to reduce stars (0.0 = no change, 1.0 = full removal)
        output_format: Output format
    """
    from presets import reduce_stars
    
    if not validate_image_file(file):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Supported formats: JPEG, PNG, TIFF, FITS"
        )
    
    contents = await file.read()
    img_array = decode_image(contents, file.filename or "")
    
    # Convert to BGR for processing
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # Apply star reduction
    try:
        loop = asyncio.get_event_loop()
        reduced_bgr = await loop.run_in_executor(
            executor,
            lambda: reduce_stars(img_bgr, None, reduction_amount, True, True)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Star reduction failed: {str(e)}")
    
    # Convert back to RGB
    reduced_rgb = cv2.cvtColor(reduced_bgr, cv2.COLOR_BGR2RGB)
    
    # Encode output
    try:
        loop = asyncio.get_event_loop()
        output_bytes, mime_type = await loop.run_in_executor(
            executor,
            encode_output,
            reduced_rgb,
            output_format
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to encode output: {str(e)}")
    
    # Return as base64
    result_base64 = base64.b64encode(output_bytes).decode('utf-8')
    ext_map = {"jpeg": "jpg", "png": "png", "tiff": "tiff"}
    output_ext = ext_map.get(output_format, "jpg")
    
    return JSONResponse({
        "status": "success",
        "enhanced_image": f"data:{mime_type};base64,{result_base64}",
        "original_filename": file.filename,
        "output_extension": output_ext,
        "reduction_amount": reduction_amount,
        "message": f"Stars reduced by {int(reduction_amount * 100)}%"
    })
