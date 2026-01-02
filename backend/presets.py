"""
Image enhancement presets for different astrophotography subjects.
Each preset is optimized for specific types of celestial objects.
"""

import cv2
import numpy as np
from typing import Literal, Tuple, Optional

PresetType = Literal["mineral_moon_subtle", "deep_sky", "general", "moon_hdr"]
OutputFormat = Literal["jpeg", "png", "tiff"]


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def estimate_noise_level(img: np.ndarray) -> float:
    """
    Estimate noise level using Laplacian variance method.
    Higher values indicate more noise.
    
    Returns a value typically between 0-50 for normal images.
    """
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    
    # Use Laplacian to detect edges/noise
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    noise_estimate = laplacian.var()
    
    # Normalize to a 0-1 scale (typical astro images have variance 100-2000)
    normalized = min(noise_estimate / 1000.0, 1.0)
    return normalized


def adaptive_denoise(img: np.ndarray, base_strength: int = 5) -> np.ndarray:
    """
    Apply adaptive noise reduction based on estimated noise level.
    
    Args:
        img: Input BGR image
        base_strength: Base denoising strength (will be scaled by noise level)
    
    Returns:
        Denoised image
    """
    noise_level = estimate_noise_level(img)
    
    # Scale strength based on noise (more noise = stronger denoising)
    # Range: base_strength * 0.5 to base_strength * 2.5
    strength_multiplier = 0.5 + (noise_level * 2.0)
    h_luminance = int(base_strength * strength_multiplier)
    h_color = int(base_strength * strength_multiplier * 0.8)  # Slightly less for color
    
    # Clamp values
    h_luminance = max(1, min(h_luminance, 15))
    h_color = max(1, min(h_color, 12))
    
    # Apply denoising with adaptive strength (positional args for OpenCV compatibility)
    denoised = cv2.fastNlMeansDenoisingColored(img, None, h_luminance, h_color, 7, 21)
    
    return denoised


def auto_white_balance(img: np.ndarray, method: str = "gray_world") -> np.ndarray:
    """
    Apply automatic white balance correction.
    
    Args:
        img: Input BGR image
        method: "gray_world" or "white_patch"
    
    Returns:
        White-balanced image
    """
    img_float = img.astype(np.float32)
    
    if method == "gray_world":
        # Gray world assumption: average of each channel should be equal
        avg_b = np.mean(img_float[:, :, 0])
        avg_g = np.mean(img_float[:, :, 1])
        avg_r = np.mean(img_float[:, :, 2])
        
        # Use green as reference (most common in astro)
        avg_gray = (avg_b + avg_g + avg_r) / 3
        
        # Calculate scaling factors
        scale_b = avg_gray / (avg_b + 1e-6)
        scale_g = avg_gray / (avg_g + 1e-6)
        scale_r = avg_gray / (avg_r + 1e-6)
        
        # Apply scaling
        img_float[:, :, 0] = img_float[:, :, 0] * scale_b
        img_float[:, :, 1] = img_float[:, :, 1] * scale_g
        img_float[:, :, 2] = img_float[:, :, 2] * scale_r
        
    elif method == "white_patch":
        # White patch: brightest pixels should be white
        # Use 99.5th percentile to avoid outliers
        max_b = np.percentile(img_float[:, :, 0], 99.5)
        max_g = np.percentile(img_float[:, :, 1], 99.5)
        max_r = np.percentile(img_float[:, :, 2], 99.5)
        
        max_val = max(max_b, max_g, max_r)
        
        img_float[:, :, 0] = img_float[:, :, 0] * (max_val / (max_b + 1e-6))
        img_float[:, :, 1] = img_float[:, :, 1] * (max_val / (max_g + 1e-6))
        img_float[:, :, 2] = img_float[:, :, 2] * (max_val / (max_r + 1e-6))
    
    return np.clip(img_float, 0, 255).astype(np.uint8)


def extract_background_gradient(img: np.ndarray, grid_size: int = 8) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extract and remove background gradient (light pollution, vignetting).
    Uses median sampling in a grid to estimate background.
    
    Args:
        img: Input BGR image
        grid_size: Number of grid cells per dimension
    
    Returns:
        Tuple of (corrected_image, background_model)
    """
    h, w = img.shape[:2]
    cell_h, cell_w = h // grid_size, w // grid_size
    
    # Sample median values in grid cells
    background_samples = np.zeros((grid_size, grid_size, 3), dtype=np.float32)
    
    for i in range(grid_size):
        for j in range(grid_size):
            y1, y2 = i * cell_h, (i + 1) * cell_h
            x1, x2 = j * cell_w, (j + 1) * cell_w
            cell = img[y1:y2, x1:x2]
            
            # Use 25th percentile to get background (avoiding stars)
            for c in range(3):
                background_samples[i, j, c] = np.percentile(cell[:, :, c], 25)
    
    # Interpolate to full image size
    background_model = cv2.resize(
        background_samples, 
        (w, h), 
        interpolation=cv2.INTER_CUBIC
    )
    
    # Subtract background and normalize
    img_float = img.astype(np.float32)
    corrected = img_float - background_model
    
    # Add back a neutral gray background
    neutral_bg = np.median(background_model)
    corrected = corrected + neutral_bg
    
    corrected = np.clip(corrected, 0, 255).astype(np.uint8)
    
    return corrected, background_model.astype(np.uint8)


def create_star_mask(img: np.ndarray, threshold_factor: float = 2.5) -> np.ndarray:
    """
    Create a mask identifying star positions.
    Stars are detected as bright, small, roughly circular objects.
    
    Args:
        img: Input BGR image
        threshold_factor: Multiplier for threshold (higher = fewer stars detected)
    
    Returns:
        Binary mask where stars are white (255)
    """
    # Convert to grayscale
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    
    # Calculate threshold based on image statistics
    mean_val = np.mean(gray)
    std_val = np.std(gray)
    threshold = mean_val + (std_val * threshold_factor)
    
    # Initial threshold for bright objects
    _, bright_mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    
    # Morphological operations to clean up
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    kernel_medium = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    
    # Open to remove noise, close to fill gaps
    star_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel_small)
    star_mask = cv2.morphologyEx(star_mask, cv2.MORPH_CLOSE, kernel_medium)
    
    # Dilate slightly to create protection zone around stars
    star_mask = cv2.dilate(star_mask, kernel_medium, iterations=1)
    
    return star_mask


def apply_with_star_protection(
    img: np.ndarray, 
    enhanced: np.ndarray, 
    star_mask: np.ndarray,
    blend_amount: float = 0.7
) -> np.ndarray:
    """
    Blend enhanced image with original, protecting star regions.
    
    Args:
        img: Original image
        enhanced: Enhanced image
        star_mask: Binary mask where stars are white
        blend_amount: How much of the enhanced version to keep in star regions (0-1)
    
    Returns:
        Blended image with protected stars
    """
    # Create smooth mask for blending
    star_mask_float = star_mask.astype(np.float32) / 255.0
    star_mask_smooth = cv2.GaussianBlur(star_mask_float, (7, 7), 0)
    
    # Expand mask to 3 channels
    if len(star_mask_smooth.shape) == 2:
        star_mask_3ch = np.stack([star_mask_smooth] * 3, axis=-1)
    else:
        star_mask_3ch = star_mask_smooth
    
    # In star regions, blend more toward original
    # blend_amount controls how much enhancement to keep
    result = enhanced.astype(np.float32) * (1 - star_mask_3ch * (1 - blend_amount))
    result += img.astype(np.float32) * star_mask_3ch * (1 - blend_amount)
    
    return np.clip(result, 0, 255).astype(np.uint8)


def calculate_adaptive_saturation(img: np.ndarray, mask: np.ndarray, base_multiplier: float = 1.4) -> float:
    """
    Calculate adaptive saturation multiplier based on image statistics.
    
    Analyzes the image to determine optimal saturation boost:
    - Low saturation images get higher boost
    - Already saturated images get lower boost
    - Darker images may need more boost
    - High color variance suggests more color information to reveal
    
    Args:
        img: Input BGR image
        mask: Binary mask where processing should occur (moon region)
        base_multiplier: Base saturation multiplier (default 1.4 for subtle preset)
    
    Returns:
        Adaptive saturation multiplier (typically 1.2 to 1.8)
    """
    # Extract moon region only
    moon_region = img[mask > 0]
    
    if len(moon_region) == 0:
        return base_multiplier
    
    # Convert to HSV to analyze saturation
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]  # Brightness
    
    # Get statistics from moon region only
    moon_sat = saturation[mask > 0]
    moon_val = value[mask > 0]
    
    # Calculate key statistics
    mean_sat = np.mean(moon_sat) / 255.0  # Normalize to 0-1
    median_sat = np.median(moon_sat) / 255.0
    std_sat = np.std(moon_sat) / 255.0  # Color variance
    mean_val = np.mean(moon_val) / 255.0  # Average brightness
    
    # Calculate saturation percentiles
    p25_sat = np.percentile(moon_sat, 25) / 255.0
    p75_sat = np.percentile(moon_sat, 75) / 255.0
    
    # Adaptive adjustment factors
    # 1. Low saturation images need more boost
    #    If mean saturation is low (< 0.2), increase multiplier
    sat_factor = 1.0
    if mean_sat < 0.15:
        sat_factor = 1.3  # Very desaturated, boost more
    elif mean_sat < 0.25:
        sat_factor = 1.15  # Moderately desaturated
    elif mean_sat > 0.4:
        sat_factor = 0.85  # Already saturated, boost less
    
    # 2. High color variance suggests more color information to reveal
    #    Higher std = more variation = can boost more safely
    variance_factor = 1.0
    if std_sat > 0.15:
        variance_factor = 1.1  # High variance, safe to boost
    elif std_sat < 0.08:
        variance_factor = 0.95  # Low variance, be conservative
    
    # 3. Darker images may benefit from slightly more saturation
    #    But be careful not to oversaturate dark regions
    brightness_factor = 1.0
    if mean_val < 0.3:
        brightness_factor = 1.05  # Dark image, slight boost
    elif mean_val > 0.7:
        brightness_factor = 0.98  # Bright image, slight reduction
    
    # 4. Check saturation distribution
    #    If most pixels are already saturated (high p75), reduce boost
    distribution_factor = 1.0
    if p75_sat > 0.5:
        distribution_factor = 0.9  # Many pixels already saturated
    elif p75_sat < 0.2:
        distribution_factor = 1.1  # Most pixels are desaturated
    
    # Combine all factors
    adaptive_multiplier = base_multiplier * sat_factor * variance_factor * brightness_factor * distribution_factor
    
    # Clamp to reasonable range (1.2 to 1.8 for subtle preset)
    # This ensures we don't go too aggressive or too conservative
    adaptive_multiplier = max(1.2, min(adaptive_multiplier, 1.8))
    
    return adaptive_multiplier


# =============================================================================
# ENHANCEMENT PRESETS
# =============================================================================

def enhance_mineral_moon_subtle(img_array: np.ndarray) -> np.ndarray:
    """
    Subtle Mineral Moon - Conservative enhancement for scientific accuracy.
    
    Minimal processing to reveal natural mineral colors without adding color casts.
    Best for scientific purposes or realistic appearance.
    
    Features adaptive saturation that adjusts based on image statistics:
    - Low saturation images receive higher boost
    - Already saturated images receive lower boost
    - Adjusts for brightness and color variance
    - Saturation multiplier ranges from 1.2x to 1.8x based on image analysis
    """
    # Convert RGB to BGR for OpenCV
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # Create a mask for the moon (non-black areas)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    _, moon_mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    moon_pixels_mask = moon_mask > 0
    
    enhanced = cv_img.copy()
    
    # Step 1: Gentle CLAHE on luminance only (preserves colors exactly)
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)
    # Only apply CLAHE where moon is
    l = np.where(moon_mask > 0, l_enhanced, l)
    
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # Step 2: Adaptive saturation boost in HSV (only on moon)
    # This reveals existing mineral colors without adding any tint
    # Calculate adaptive saturation multiplier based on image statistics
    adaptive_sat_mult = calculate_adaptive_saturation(enhanced, moon_mask, base_multiplier=1.4)
    
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    
    # Only boost saturation where moon is, keep original saturation for background
    # Use adaptive multiplier that adjusts based on image characteristics
    sat_boosted = np.clip(hsv[:, :, 1] * adaptive_sat_mult, 0, 255)
    hsv[:, :, 1] = np.where(moon_mask > 0, sat_boosted, hsv[:, :, 1])
    
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # Step 3: Very subtle sharpening (only on moon)
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    sharpened = cv2.addWeighted(enhanced, 1.2, gaussian, -0.2, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, sharpened, enhanced)
    
    # Step 4: Very light noise reduction (only on moon)
    denoised = cv2.fastNlMeansDenoisingColored(enhanced, None, 2, 2, 7, 15)
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, denoised, enhanced)
    
    # Final: Force pure black background
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, enhanced, 0)
    
    # Convert back to RGB
    return cv2.cvtColor(enhanced.astype(np.uint8), cv2.COLOR_BGR2RGB)


def enhance_deep_sky(img_array: np.ndarray) -> np.ndarray:
    """
    Deep Sky enhancement - Optimized for nebulae, galaxies, and star clusters.
    
    Steps:
    1. Histogram stretch with emphasis on faint details
    2. Moderate saturation boost for nebula colors
    3. Star enhancement/sharpening
    4. Noise reduction for long exposure noise
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Histogram stretch optimized for deep sky
    stretched = np.zeros_like(cv_img, dtype=np.float32)
    for i in range(3):
        channel = cv_img[:, :, i].astype(np.float32)
        p_low = np.percentile(channel, 0.1)
        p_high = np.percentile(channel, 99.9)
        
        if p_high > p_low:
            stretched[:, :, i] = np.clip((channel - p_low) / (p_high - p_low) * 255, 0, 255)
        else:
            stretched[:, :, i] = channel
    
    enhanced = stretched.astype(np.uint8)
    
    # 2. Moderate saturation boost for nebula colors
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = hsv[:, :, 1] * 1.4  # 40% saturation boost
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 3. Star sharpening with unsharp mask
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    enhanced = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    
    # 4. Noise reduction for deep sky
    enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 6, 6, 7, 21)
    
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


def enhance_general(img_array: np.ndarray) -> np.ndarray:
    """
    General Auto enhancement - Balanced enhancement for any astrophoto.
    This is the original/default algorithm.
    
    Steps:
    1. Moderate histogram stretch
    2. Gentle saturation boost
    3. Light noise reduction
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Moderate histogram stretch
    stretched = np.zeros_like(cv_img, dtype=np.float32)
    for i in range(3):
        channel = cv_img[:, :, i].astype(np.float32)
        p_low = np.percentile(channel, 0.1)
        p_high = np.percentile(channel, 99.9)
        
        if p_high > p_low:
            stretched[:, :, i] = np.clip((channel - p_low) / (p_high - p_low) * 255, 0, 255)
        else:
            stretched[:, :, i] = channel
    
    enhanced = stretched.astype(np.uint8)
    
    # 2. Gentle saturation boost
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = hsv[:, :, 1] * 1.15  # 15% saturation boost
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 3. Light noise reduction
    enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 2, 2, 7, 15)
    
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


def enhance_moon_hdr(img_array: np.ndarray) -> np.ndarray:
    """
    Moon HDR - High dynamic range tone mapping for lunar photography.
    
    Optimized for single-frame moon captures from smart telescopes like Seestar S50.
    Brings out crater details, maria textures, and surface features with an HDR aesthetic
    while preserving natural appearance.
    
    Steps:
    1. Create moon mask to isolate lunar disk
    2. Multi-scale CLAHE for aggressive local contrast
    3. Shadow recovery with luminosity masking
    4. Highlight compression to prevent blowout
    5. Multi-radius unsharp masking for surface detail
    6. Midtone contrast enhancement
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # Create a mask for the moon (non-black areas)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    _, moon_mask = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
    
    # Clean up mask with morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    moon_mask = cv2.morphologyEx(moon_mask, cv2.MORPH_CLOSE, kernel)
    moon_mask = cv2.morphologyEx(moon_mask, cv2.MORPH_OPEN, kernel)
    
    enhanced = cv_img.copy()
    
    # Step 1: Multi-scale CLAHE on luminance for HDR-like local contrast
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # First pass: Large tiles for global tone mapping
    clahe_large = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    l_large = clahe_large.apply(l)
    
    # Second pass: Medium tiles for regional detail
    clahe_medium = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_medium = clahe_medium.apply(l)
    
    # Third pass: Small tiles for fine detail
    clahe_small = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    l_small = clahe_small.apply(l)
    
    # Blend the three scales (weighted toward fine detail)
    l_blended = (0.25 * l_large.astype(np.float32) + 
                 0.35 * l_medium.astype(np.float32) + 
                 0.40 * l_small.astype(np.float32))
    l_blended = np.clip(l_blended, 0, 255).astype(np.uint8)
    
    # Only apply where moon is
    l = np.where(moon_mask > 0, l_blended, l)
    
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # Step 2: Shadow recovery using curves-like adjustment
    # Lift shadows while preserving highlights
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_float = l.astype(np.float32) / 255.0
    
    # Apply shadow lift curve: shadows get boosted more than highlights
    # Using a modified power curve
    shadow_lift = np.power(l_float, 0.85)  # Lifts shadows
    
    # Blend based on luminosity (more lift in darker areas)
    shadow_mask = 1.0 - l_float  # Darker = higher weight
    shadow_mask = np.power(shadow_mask, 2)  # Concentrate on deep shadows
    
    l_recovered = l_float + (shadow_lift - l_float) * shadow_mask * 0.4
    l_recovered = np.clip(l_recovered * 255, 0, 255).astype(np.uint8)
    
    # Only apply where moon is
    l = np.where(moon_mask > 0, l_recovered, l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # Step 3: Highlight compression to prevent blowout
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_float = l.astype(np.float32) / 255.0
    
    # Compress highlights using soft knee
    highlight_threshold = 0.75
    highlight_mask = np.maximum(l_float - highlight_threshold, 0) / (1.0 - highlight_threshold)
    compression = 0.3  # How much to compress highlights
    
    l_compressed = l_float - (highlight_mask * compression * (l_float - highlight_threshold))
    l_compressed = np.clip(l_compressed * 255, 0, 255).astype(np.uint8)
    
    # Only apply where moon is
    l = np.where(moon_mask > 0, l_compressed, l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # Step 4: Multi-radius unsharp masking for surface detail
    # Small radius for fine crater detail
    gaussian_small = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    detail_small = cv2.addWeighted(enhanced, 1.3, gaussian_small, -0.3, 0)
    
    # Medium radius for larger surface features
    gaussian_medium = cv2.GaussianBlur(enhanced, (0, 0), 2.5)
    detail_medium = cv2.addWeighted(detail_small, 1.2, gaussian_medium, -0.2, 0)
    
    # Large radius for overall structure enhancement
    gaussian_large = cv2.GaussianBlur(enhanced, (0, 0), 5.0)
    detail_final = cv2.addWeighted(detail_medium, 1.15, gaussian_large, -0.15, 0)
    
    detail_final = np.clip(detail_final, 0, 255).astype(np.uint8)
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, detail_final, enhanced)
    
    # Step 5: Midtone contrast boost using S-curve
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Create lookup table for S-curve
    lut = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        # S-curve formula: increases midtone contrast
        x = i / 255.0
        # Sigmoid-like curve centered at 0.5
        s_curve = 1 / (1 + np.exp(-10 * (x - 0.5)))
        # Blend original with S-curve (subtle effect)
        blended = x * 0.7 + s_curve * 0.3
        lut[i] = np.clip(blended * 255, 0, 255).astype(np.uint8)
    
    l_contrast = cv2.LUT(l, lut)
    l = np.where(moon_mask > 0, l_contrast, l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # Step 6: Light noise reduction (conservative since Seestar stacks)
    denoised = cv2.fastNlMeansDenoisingColored(enhanced, None, 3, 3, 7, 15)
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, denoised, enhanced)
    
    # Final: Force pure black background
    enhanced = np.where(moon_mask[:, :, np.newaxis] > 0, enhanced, 0)
    
    return cv2.cvtColor(enhanced.astype(np.uint8), cv2.COLOR_BGR2RGB)


# =============================================================================
# PRESET REGISTRY
# =============================================================================

PRESETS = {
    "mineral_moon_subtle": {
        "function": enhance_mineral_moon_subtle,
        "name": "Mineral Moon (Subtle)",
        "description": "Conservative enhancement for scientific accuracy",
        "best_for": "Scientific/realistic lunar imaging"
    },
    "deep_sky": {
        "function": enhance_deep_sky,
        "name": "Deep Sky Boost",
        "description": "Optimized for nebulae, galaxies, and star clusters",
        "best_for": "Deep space objects"
    },
    "general": {
        "function": enhance_general,
        "name": "General Auto",
        "description": "Balanced enhancement for any astrophoto",
        "best_for": "General astrophotography"
    },
    "moon_hdr": {
        "function": enhance_moon_hdr,
        "name": "Moon HDR",
        "description": "HDR tone mapping for lunar surface detail",
        "best_for": "Seestar and smart telescope moon captures"
    }
}


def enhance_with_preset(img_array: np.ndarray, preset: PresetType = "general") -> np.ndarray:
    """
    Apply the specified enhancement preset to an image.
    
    Args:
        img_array: Input image as numpy array (RGB)
        preset: One of "mineral_moon_subtle", "deep_sky", "general"
    
    Returns:
        Enhanced image as numpy array (RGB)
    """
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}. Available: {list(PRESETS.keys())}")
    
    enhance_func = PRESETS[preset]["function"]
    return enhance_func(img_array)
