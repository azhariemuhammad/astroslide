"""
Image enhancement presets for different astrophotography subjects.
Each preset is optimized for specific types of celestial objects.
"""

import cv2
import numpy as np
from typing import Literal, Tuple, Optional
from skimage.restoration import denoise_wavelet, estimate_sigma
from skimage import img_as_float, img_as_ubyte

PresetType = Literal["mineral_moon_subtle", "deep_sky", "general", "moon_hdr", "nebula", "galaxy", "star_cluster"]
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


def wavelet_denoise(
    img: np.ndarray, 
    strength: float = 1.0,
    preserve_details: bool = True
) -> np.ndarray:
    """
    Wavelet-based denoising using BayesShrink thresholding.
    
    This method decomposes the image into different frequency bands using wavelets,
    applies soft thresholding to remove noise while preserving structure, then
    reconstructs. Much better at preserving fine details like nebula filaments
    and dust lanes compared to spatial domain methods.
    
    Based on techniques used in GraXpert and professional astrophotography software.
    
    Args:
        img: Input BGR image (0-255 uint8)
        strength: Denoising strength multiplier (0.5 = gentle, 1.0 = normal, 2.0 = aggressive)
        preserve_details: If True, uses more conservative thresholding to preserve fine structure
    
    Returns:
        Denoised image
    """
    # Convert BGR to RGB for skimage processing
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    # Convert to float (0-1 range) for wavelet processing
    img_float = img_as_float(img_rgb)
    
    # Estimate noise sigma per channel for adaptive thresholding
    # This gives BayesShrink the actual noise level to work with
    sigma_est = estimate_sigma(img_float, channel_axis=-1, average_sigmas=False)
    
    # Convert to numpy array and scale by strength (higher = more aggressive denoising)
    sigma_scaled = np.array(sigma_est) * strength
    
    # Choose wavelet method based on preservation preference
    # BayesShrink is more conservative (better for astrophotography)
    # VisuShrink is more aggressive
    method = 'BayesShrink' if preserve_details else 'VisuShrink'
    
    # Apply wavelet denoising
    # Using 'db1' (Haar) wavelet - good balance of speed and quality
    # 'soft' thresholding preserves more detail than 'hard'
    denoised_float = denoise_wavelet(
        img_float,
        channel_axis=-1,
        convert2ycbcr=True,  # Process in YCbCr for better color preservation
        method=method,
        mode='soft',
        sigma=sigma_scaled,
        rescale_sigma=True
    )
    
    # Convert back to uint8 BGR
    denoised_rgb = img_as_ubyte(np.clip(denoised_float, 0, 1))
    denoised_bgr = cv2.cvtColor(denoised_rgb, cv2.COLOR_RGB2BGR)
    
    return denoised_bgr


def astro_denoise(
    img: np.ndarray,
    strength: float = 1.0,
    protect_stars: bool = True,
    edge_aware: bool = True
) -> np.ndarray:
    """
    Hybrid astrophotography-optimized denoising.
    
    Combines multiple techniques for optimal results:
    1. Wavelet denoising for fine detail preservation (nebula filaments, dust lanes)
    2. Optional bilateral filtering for smooth background transitions
    3. Star protection to prevent bloating bright stars
    
    This is the recommended denoising function for deep-sky images.
    
    Args:
        img: Input BGR image (0-255 uint8)
        strength: Overall denoising strength (0.5 = gentle, 1.0 = normal, 2.0 = aggressive)
        protect_stars: If True, reduces denoising effect on bright star regions
        edge_aware: If True, applies additional bilateral filtering for smooth backgrounds
    
    Returns:
        Denoised image optimized for astrophotography
    """
    # Step 1: Apply wavelet denoising (primary method)
    # Use slightly conservative strength to preserve details
    wavelet_strength = strength * 0.9
    denoised = wavelet_denoise(img, strength=wavelet_strength, preserve_details=True)
    
    # Step 2: Optional edge-aware smoothing for backgrounds
    # Bilateral filter smooths noise while preserving edges
    if edge_aware:
        # Light bilateral filter - smooths gradual background transitions
        # Low sigma values to avoid over-smoothing
        sigma_color = int(30 * strength)  # 30 for normal strength
        sigma_space = int(10 * strength)  # 10 for normal strength
        sigma_color = max(10, min(sigma_color, 75))
        sigma_space = max(5, min(sigma_space, 20))
        
        bilateral = cv2.bilateralFilter(denoised, 5, sigma_color, sigma_space)
        
        # Blend bilateral with wavelet result (favoring wavelet in detailed areas)
        # Use luminance to detect detailed vs smooth areas
        gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
        
        # Calculate local variance to detect textured areas
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        local_var = cv2.absdiff(gray, blur).astype(np.float32) / 255.0
        local_var = cv2.GaussianBlur(local_var, (15, 15), 0)
        
        # In low-variance areas, use more bilateral; in high-variance, use wavelet
        detail_mask = np.clip(local_var * 5, 0, 1)[:, :, np.newaxis]
        
        denoised = (denoised.astype(np.float32) * detail_mask + 
                    bilateral.astype(np.float32) * (1 - detail_mask))
        denoised = np.clip(denoised, 0, 255).astype(np.uint8)
    
    # Step 3: Star protection - reduce denoising effect on very bright regions
    # This prevents stars from becoming bloated or losing their sharp cores
    if protect_stars:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Find bright regions (potential stars)
        mean_val = np.mean(gray)
        std_val = np.std(gray)
        star_threshold = mean_val + std_val * 2
        
        # Create soft mask for bright regions
        bright_mask = np.clip((gray.astype(np.float32) - star_threshold) / 50, 0, 1)
        bright_mask = cv2.GaussianBlur(bright_mask, (7, 7), 0)
        bright_mask = bright_mask[:, :, np.newaxis]
        
        # Blend original back in bright regions (protect star cores)
        denoised = (denoised.astype(np.float32) * (1 - bright_mask * 0.7) + 
                    img.astype(np.float32) * bright_mask * 0.7)
        denoised = np.clip(denoised, 0, 255).astype(np.uint8)
    
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


# =============================================================================
# STAR REMOVAL FUNCTIONS (PixInsight-inspired)
# =============================================================================

def detect_stars_aggressive(
    img: np.ndarray, 
    sensitivity: float = 1.0
) -> np.ndarray:
    """
    Aggressively detect stars using adaptive thresholding and morphological analysis.
    
    This method is more reliable for detecting stars of various sizes:
    - Uses local adaptive thresholding to find bright spots
    - Filters by circularity to identify star-like objects
    - Lower sensitivity = detect more stars
    
    Args:
        img: Input BGR image
        sensitivity: Detection sensitivity (0.5 = aggressive, 1.5 = conservative)
    
    Returns:
        Binary mask where stars are white (255)
    """
    # Convert to grayscale
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    
    # Method 1: Adaptive threshold to find locally bright spots
    # Block size should be odd and large enough to capture star surroundings
    block_size = 31
    c_value = int(-3 * sensitivity)  # Negative C means we're looking for bright spots
    
    adaptive_thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, block_size, c_value
    )
    
    # Method 2: Also use global bright spot detection
    mean_val = np.mean(gray)
    std_val = np.std(gray)
    global_thresh = mean_val + std_val * (1.5 * sensitivity)
    _, global_mask = cv2.threshold(gray, global_thresh, 255, cv2.THRESH_BINARY)
    
    # Combine both methods
    combined = cv2.bitwise_or(adaptive_thresh, global_mask)
    
    # Morphological cleanup - close small gaps, remove noise
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    kernel_medium = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    
    # Open removes small noise
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel_small)
    # Close fills small gaps in stars
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel_medium)
    
    # Dilate to ensure we cover full star area
    star_mask = cv2.dilate(cleaned, kernel_medium, iterations=1)
    
    return star_mask


def remove_stars_inpaint(
    img: np.ndarray, 
    star_mask: np.ndarray, 
    method: str = "telea",
    inpaint_radius: int = 3
) -> np.ndarray:
    """
    Remove stars by inpainting with surrounding texture.
    
    Uses OpenCV's inpainting algorithms to fill star regions with
    interpolated values from the surrounding nebula/galaxy.
    
    Args:
        img: Input BGR image
        star_mask: Binary mask where stars are white (255)
        method: "telea" (fast, good for small regions) or "ns" (Navier-Stokes, smoother)
        inpaint_radius: Radius of circular neighborhood for inpainting
    
    Returns:
        Image with stars removed/inpainted
    """
    if method == "telea":
        flags = cv2.INPAINT_TELEA
    else:
        flags = cv2.INPAINT_NS
    
    # Inpaint the star regions
    result = cv2.inpaint(img, star_mask, inpaint_radius, flags)
    
    return result


def reduce_stars(
    img: np.ndarray, 
    star_mask: np.ndarray = None,
    reduction_amount: float = 0.5,
    preserve_color: bool = True,
    use_multiscale_detection: bool = True
) -> np.ndarray:
    """
    Reduce/remove stars by replacing them with local median background.
    
    This is a direct, aggressive approach:
    - Detects stars using adaptive thresholding
    - Replaces star pixels with median-filtered background
    - Blends based on reduction_amount for control
    
    Args:
        img: Input BGR image
        star_mask: Optional pre-computed star mask, will auto-detect if None
        reduction_amount: How much to reduce stars (0.0 = no change, 1.0 = full removal)
        preserve_color: If True, preserve some star color at core
        use_multiscale_detection: Ignored (uses aggressive detection)
    
    Returns:
        Image with reduced/removed stars
    """
    # Clamp reduction amount
    reduction_amount = max(0.0, min(1.0, reduction_amount))
    
    if reduction_amount == 0.0:
        return img.copy()
    
    # Detect stars using aggressive method
    if star_mask is None:
        # Lower sensitivity means more stars detected
        sensitivity = 1.0 - (reduction_amount * 0.3)  # 0.7-1.0 based on reduction
        star_mask = detect_stars_aggressive(img, sensitivity=sensitivity)
    
    # Check if we actually detected any stars
    star_count = np.sum(star_mask > 0)
    if star_count == 0:
        return img.copy()
    
    # Create median-filtered background (stars replaced with surrounding pixels)
    # Use larger kernel for better background estimation
    kernel_size = 15
    median_bg = np.zeros_like(img)
    for c in range(3):
        median_bg[:, :, c] = cv2.medianBlur(img[:, :, c], kernel_size)
    
    # Create feathered star mask for smooth blending
    star_mask_float = star_mask.astype(np.float32) / 255.0
    
    # Feather edges for smooth transition
    feather_kernel = 7
    star_mask_feathered = cv2.GaussianBlur(star_mask_float, (feather_kernel, feather_kernel), 0)
    
    # Expand to 3 channels
    star_mask_3ch = np.stack([star_mask_feathered] * 3, axis=-1)
    
    # Apply reduction: blend original with median background in star regions
    img_float = img.astype(np.float32)
    median_float = median_bg.astype(np.float32)
    
    # result = original * (1 - mask * reduction) + median * (mask * reduction)
    blend_mask = star_mask_3ch * reduction_amount
    result = img_float * (1.0 - blend_mask) + median_float * blend_mask
    
    if preserve_color and reduction_amount < 0.9:
        # For partial reduction, keep some star core color
        # Create a smaller core mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        core_mask = cv2.erode(star_mask, kernel, iterations=2)
        core_float = core_mask.astype(np.float32) / 255.0
        core_feathered = cv2.GaussianBlur(core_float, (5, 5), 0)
        core_3ch = np.stack([core_feathered] * 3, axis=-1)
        
        # Preserve 30% of original in the core
        core_preserve = 0.3 * (1.0 - reduction_amount)
        result = result * (1.0 - core_3ch * core_preserve) + img_float * core_3ch * core_preserve
    
    return np.clip(result, 0, 255).astype(np.uint8)


def add_star_spikes(
    img: np.ndarray,
    spike_length: float = 0.5,
    spike_brightness: float = 0.6,
    threshold_factor: float = 2.0,
    num_spikes: int = 4
) -> np.ndarray:
    """
    Add subtle 4-point diffraction spikes to bright stars.
    
    Creates a natural-looking diffraction spike effect similar to what's seen
    in images taken with Newtonian reflectors or cameras with spider vanes.
    The spikes are rendered with Gaussian falloff for a soft, photographic look.
    
    Args:
        img: Input BGR image
        spike_length: Length of spikes relative to star brightness (0.3-1.0, default 0.5 for subtle)
        spike_brightness: Base brightness of spikes (0.3-1.0, default 0.6 for subtle)
        threshold_factor: How bright a star must be to get spikes (lower = more stars)
        num_spikes: Number of spike points (4 for classic X pattern)
    
    Returns:
        Image with star spikes added
    """
    # Convert to grayscale for star detection
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    
    # Calculate threshold for star detection
    mean_val = np.mean(gray)
    std_val = np.std(gray)
    threshold = mean_val + (std_val * threshold_factor)
    
    # Find bright spots (potential stars)
    _, bright_mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    
    # Find contours (individual stars)
    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if len(contours) == 0:
        return img.copy()
    
    # Create output image
    result = img.astype(np.float32)
    spike_layer = np.zeros_like(result)
    
    # Calculate spike angles (4-point = 45° offset for X pattern)
    angles = [np.pi / 4 + (i * 2 * np.pi / num_spikes) for i in range(num_spikes)]
    
    for contour in contours:
        # Get star center and size
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
            
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        
        # Get star brightness and size
        area = cv2.contourArea(contour)
        if area < 2:  # Skip very small spots (noise)
            continue
        
        # Get the star's peak brightness
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, -1)
        star_brightness = np.max(gray[mask > 0])
        
        # Calculate spike properties based on star brightness
        # Brighter stars get longer, more visible spikes
        brightness_factor = (star_brightness - threshold) / (255 - threshold)
        brightness_factor = np.clip(brightness_factor, 0, 1)
        
        # Spike length scales with brightness and area
        base_length = max(15, int(np.sqrt(area) * 3))
        actual_length = int(base_length * spike_length * (0.5 + brightness_factor * 0.5))
        
        # Spike intensity scales with star brightness
        spike_intensity = spike_brightness * brightness_factor
        
        # Get the star's color for colored spikes
        if len(img.shape) == 3:
            star_color = img[cy, cx].astype(np.float32)
            # Normalize and boost to make spikes visible
            star_color = star_color / 255.0 * spike_intensity * 255
        else:
            star_color = np.array([spike_intensity * 255])
        
        # Draw spikes with Gaussian falloff
        for angle in angles:
            for dist in range(1, actual_length + 1):
                # Calculate pixel position along spike
                dx = int(np.cos(angle) * dist)
                dy = int(np.sin(angle) * dist)
                
                px, py = cx + dx, cy + dy
                
                # Check bounds
                if 0 <= px < img.shape[1] and 0 <= py < img.shape[0]:
                    # Gaussian falloff - intensity decreases with distance
                    falloff = np.exp(-dist * dist / (actual_length * actual_length / 4))
                    
                    # Also add slight width falloff (thinner at tips)
                    width_factor = 1 - (dist / actual_length) * 0.7
                    
                    intensity = falloff * width_factor * spike_intensity
                    
                    # Add to spike layer with star color
                    spike_layer[py, px] = np.maximum(
                        spike_layer[py, px], 
                        star_color * intensity
                    )
    
    # Apply subtle blur to spike layer for softer look
    spike_layer = cv2.GaussianBlur(spike_layer, (3, 3), 0)
    
    # Additive blend - spikes add to existing brightness
    result = result + spike_layer
    
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


def scnr_green_removal(img: np.ndarray, amount: float = 0.5, preserve_lightness: bool = True) -> np.ndarray:
    """
    Subtractive Chromatic Noise Reduction (SCNR) - removes green tint.
    
    Based on Siril's SCNR algorithm. Green cast is common in deep sky images
    due to sensor characteristics and light pollution.
    
    Uses "Average Neutral" method: G_new = min(G, (R + B) / 2)
    
    Args:
        img: Input BGR image
        amount: Strength of green removal (0-1, default 0.5)
        preserve_lightness: If True, preserve original luminance
    
    Returns:
        Image with reduced green tint
    """
    img_float = img.astype(np.float32)
    b, g, r = img_float[:, :, 0], img_float[:, :, 1], img_float[:, :, 2]
    
    # Calculate the neutral replacement for green
    # Average neutral: replace green with average of red and blue if lower
    neutral_g = (r + b) / 2.0
    
    # Only reduce green where it exceeds neutral
    # This preserves areas where green is legitimate
    excess_green = np.maximum(g - neutral_g, 0)
    
    # Apply reduction based on amount parameter
    new_g = g - (excess_green * amount)
    
    if preserve_lightness:
        # Preserve original luminance
        original_lum = 0.299 * r + 0.587 * g + 0.114 * b
        new_lum = 0.299 * r + 0.587 * new_g + 0.114 * b
        
        # Scale to maintain luminance
        lum_ratio = original_lum / (new_lum + 1e-6)
        lum_ratio = np.clip(lum_ratio, 0.9, 1.1)  # Limit adjustment
        
        new_g = new_g * lum_ratio
    
    result = np.stack([b, new_g, r], axis=-1)
    return np.clip(result, 0, 255).astype(np.uint8)


def asinh_stretch(img: np.ndarray, stretch_factor: float = 3.0, black_point: float = 0.0) -> np.ndarray:
    """
    Asinh (inverse hyperbolic sine) histogram stretch.
    
    Based on Siril's asinh transformation. This stretching method:
    - Preserves colors better than linear stretch
    - Prevents highlight burnout in bright nebula cores
    - Reveals faint details while maintaining dynamic range
    
    Args:
        img: Input BGR image (0-255)
        stretch_factor: Controls how much to stretch (higher = more stretch)
        black_point: Normalized black point (0-1), pixels below this become black
    
    Returns:
        Stretched image
    """
    # Normalize to 0-1
    img_float = img.astype(np.float32) / 255.0
    
    # Apply black point
    img_float = np.maximum(img_float - black_point, 0) / (1.0 - black_point + 1e-6)
    
    # Calculate luminance for color-preserving stretch
    # We stretch the luminance and apply the same ratio to all channels
    b, g, r = img_float[:, :, 0], img_float[:, :, 1], img_float[:, :, 2]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    
    # Asinh stretch on luminance
    # The formula: stretched = asinh(factor * x) / asinh(factor)
    stretched_lum = np.arcsinh(stretch_factor * luminance) / np.arcsinh(stretch_factor)
    
    # Apply stretch ratio to all channels to preserve color
    ratio = stretched_lum / (luminance + 1e-6)
    ratio = np.clip(ratio, 0, 5)  # Limit extreme ratios
    
    stretched_r = r * ratio
    stretched_g = g * ratio
    stretched_b = b * ratio
    
    result = np.stack([stretched_b, stretched_g, stretched_r], axis=-1)
    result = np.clip(result * 255, 0, 255).astype(np.uint8)
    
    return result


def background_protected_saturation(
    img: np.ndarray, 
    saturation_boost: float = 1.5, 
    background_threshold: float = 0.15
) -> np.ndarray:
    """
    Boost saturation while protecting background from color noise.
    
    Based on Siril's color saturation tool with background factor.
    Only pixels brighter than the threshold get saturation boost.
    
    Args:
        img: Input BGR image
        saturation_boost: Multiplier for saturation (1.5 = 50% boost)
        background_threshold: Normalized brightness below which saturation is not boosted
    
    Returns:
        Image with boosted saturation on bright areas
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    
    # Normalize value channel to 0-1
    value_normalized = hsv[:, :, 2] / 255.0
    
    # Create smooth ramp for blending (avoids hard edges)
    # Pixels below threshold get 0, above get gradual increase to 1
    blend_factor = np.clip((value_normalized - background_threshold) / (1.0 - background_threshold), 0, 1)
    
    # Square the blend factor for smoother transition
    blend_factor = blend_factor ** 2
    
    # Apply saturation boost scaled by blend factor
    boosted_sat = hsv[:, :, 1] * saturation_boost
    hsv[:, :, 1] = hsv[:, :, 1] * (1 - blend_factor) + boosted_sat * blend_factor
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


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
    
    # 4. Medium star reduction (PixInsight-inspired morphological erosion)
    # 45% reduction for balanced effect on deep sky objects
    enhanced = reduce_stars(enhanced, reduction_amount=0.85, preserve_color=True)
    
    # 4b. Brightness compensation for star removal
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = hsv[:, :, 2] * 1.15  # 15% brightness boost
    hsv[:, :, 2] = np.clip(hsv[:, :, 2], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 5. Wavelet-based noise reduction for deep sky
    # Uses astro_denoise for better preservation of faint nebula/galaxy details
    enhanced = astro_denoise(enhanced, strength=1.2, protect_stars=True, edge_aware=True)
    
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


def enhance_nebula(img_array: np.ndarray) -> np.ndarray:
    """
    Nebula preset - Optimized for emission nebulae.
    
    Based on the proven deep_sky approach with targeted adjustments:
    - Slightly higher saturation for Ha/OIII colors
    - Stronger star reduction to emphasize nebula structure
    
    Best for: Orion, Lagoon, Rosette, and other emission nebulae
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Histogram stretch (same as deep_sky - proven reliable)
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
    
    # 2. Higher saturation boost for nebula colors (Ha red, OIII teal)
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = hsv[:, :, 1] * 1.5  # 50% boost (vs 40% in deep_sky)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 3. Star sharpening with unsharp mask
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    enhanced = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    
    # 4. Stronger star reduction to emphasize nebula structure
    enhanced = reduce_stars(enhanced, reduction_amount=0.90, preserve_color=True)
    
    # 4b. Brightness compensation for star removal
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = hsv[:, :, 2] * 1.15  # 15% brightness boost
    hsv[:, :, 2] = np.clip(hsv[:, :, 2], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 5. Wavelet-based noise reduction
    enhanced = astro_denoise(enhanced, strength=1.2, protect_stars=True, edge_aware=True)
    
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


def enhance_galaxy(img_array: np.ndarray) -> np.ndarray:
    """
    Galaxy preset - Optimized for spiral and elliptical galaxies.
    
    Based on the proven deep_sky approach with targeted adjustments:
    - Gentle CLAHE to reveal spiral arm structure
    - Lower saturation to keep natural galaxy colors
    
    Best for: Andromeda, Whirlpool, Pinwheel, and other galaxies
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Histogram stretch (same as deep_sky - proven reliable)
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
    
    # 2. Gentle CLAHE for spiral arm structure (galaxy-specific)
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    
    # 3. Moderate saturation boost (less than nebula to keep natural colors)
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = hsv[:, :, 1] * 1.35  # 35% boost
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 4. Star sharpening with unsharp mask
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    enhanced = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    
    # 5. Star reduction to emphasize galaxy structure
    enhanced = reduce_stars(enhanced, reduction_amount=0.85, preserve_color=True)
    
    # 5b. Brightness compensation for star removal
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = hsv[:, :, 2] * 1.12  # 12% brightness boost (less for galaxies)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 6. Wavelet-based noise reduction (lighter for galaxies)
    enhanced = astro_denoise(enhanced, strength=1.0, protect_stars=True, edge_aware=True)
    
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


def enhance_star_cluster(img_array: np.ndarray) -> np.ndarray:
    """
    Star Cluster preset - Optimized for open and globular clusters.
    
    Based on the proven deep_sky approach with targeted adjustments:
    - Higher saturation to reveal star spectral colors (red giants, blue stars)
    - No star reduction (we want to emphasize stars, not reduce them)
    - Tighter sharpening for crisp star profiles
    
    Best for: Pleiades, M13, Double Cluster, and other clusters
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Histogram stretch (same as deep_sky - proven reliable)
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
    
    # 2. Higher saturation boost to reveal star spectral colors
    hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = hsv[:, :, 1] * 1.5  # 50% boost for visible star colors
    hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
    enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # 3. Tighter sharpening for crisp star profiles (smaller radius)
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.5)
    enhanced = cv2.addWeighted(enhanced, 1.6, gaussian, -0.6, 0)
    
    # 4. NO star reduction for clusters (we want to emphasize stars)
    
    # 5. Light wavelet-based noise reduction (preserve star detail)
    enhanced = astro_denoise(enhanced, strength=0.8, protect_stars=True, edge_aware=False)
    
    return cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)


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
    },
    "nebula": {
        "function": enhance_nebula,
        "name": "Nebula",
        "description": "Optimized for emission nebulae with strong SCNR and saturation",
        "best_for": "Orion, Lagoon, Rosette, and other emission nebulae"
    },
    "galaxy": {
        "function": enhance_galaxy,
        "name": "Galaxy",
        "description": "Gentle processing for spiral and elliptical galaxies",
        "best_for": "Andromeda, Whirlpool, Pinwheel, and other galaxies"
    },
    "star_cluster": {
        "function": enhance_star_cluster,
        "name": "Star Cluster",
        "description": "Strong sharpening with natural star colors preserved",
        "best_for": "Pleiades, M13, Double Cluster, and other clusters"
    }
}


def enhance_with_preset(
    img_array: np.ndarray, 
    preset: PresetType = "general", 
    intensity: float = 0.75,
    star_spikes: bool = False
) -> np.ndarray:
    """
    Apply the specified enhancement preset to an image with adjustable intensity.
    
    Args:
        img_array: Input image as numpy array (RGB)
        preset: One of the available preset types
        intensity: Enhancement intensity from 0.0 (minimal) to 1.0 (full)
                   Default is 0.75 for balanced results
        star_spikes: If True, add subtle 4-point diffraction spikes to bright stars
    
    Returns:
        Enhanced image as numpy array (RGB)
    """
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}. Available: {list(PRESETS.keys())}")
    
    # Clamp intensity to valid range
    intensity = max(0.0, min(1.0, intensity))
    
    enhance_func = PRESETS[preset]["function"]
    
    # Apply full enhancement
    enhanced = enhance_func(img_array)
    
    # Blend with original based on intensity
    # intensity=1.0 -> 100% enhanced
    # intensity=0.0 -> 100% original (but still with some basic processing)
    if intensity < 1.0:
        # Blend: result = original * (1 - intensity) + enhanced * intensity
        original_float = img_array.astype(np.float32)
        enhanced_float = enhanced.astype(np.float32)
        blended = original_float * (1.0 - intensity) + enhanced_float * intensity
        enhanced = np.clip(blended, 0, 255).astype(np.uint8)
    
    # Apply star spikes if enabled
    if star_spikes:
        # Convert RGB to BGR for the star spikes function
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_RGB2BGR)
        # Apply subtle star spikes (4-point, gentle settings)
        enhanced_bgr = add_star_spikes(
            enhanced_bgr,
            spike_length=0.5,      # Subtle length
            spike_brightness=0.6,  # Not too bright
            threshold_factor=2.0,  # Only bright stars
            num_spikes=4           # Classic 4-point X pattern
        )
        # Convert back to RGB
        enhanced = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)
    
    return enhanced

