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
    output_format: Optional[str] = Form("jpeg")
):
    """
    Upload an image and receive an enhanced version using the specified preset.
    
    Args:
        file: Image file (JPEG, PNG, TIFF, FITS)
        preset: Enhancement preset - "mineral_moon_subtle", "deep_sky", or "general" (default)
        output_format: Output format - "jpeg" (default), "png", or "tiff"
    
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
    
    # Apply enhancement with selected preset (run in thread pool to avoid blocking)
    try:
        loop = asyncio.get_event_loop()
        enhanced_array = await loop.run_in_executor(
            executor,
            enhance_with_preset,
            img_array,
            preset
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
        "message": f"Image enhanced successfully using {PRESETS[preset]['name']}"
    })
