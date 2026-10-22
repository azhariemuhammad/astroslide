"""
Image enhancement presets for different astrophotography subjects.
Each preset is optimized for specific types of celestial objects.
"""

import cv2
import numpy as np
from typing import Literal, Optional
from scipy.ndimage import map_coordinates
from scipy.special import erf
from skimage.restoration import denoise_wavelet, estimate_sigma
from skimage import img_as_float, img_as_ubyte

PresetType = Literal["mineral_moon", "nebula"]
OutputFormat = Literal["jpeg", "png", "tiff"]


# =============================================================================
# CONFIGURATION
# =============================================================================


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

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


# =============================================================================
# STRETCH FUNCTIONS
# Math runs in float32 (0-1) so 16-bit/FITS data keeps its precision;
# quantize to uint8 only once, at the end.
# =============================================================================

# Rec. 601 luminance weights for RGB data
LUM_WEIGHTS_RGB = (0.299, 0.587, 0.114)


def to_float_image(img: np.ndarray) -> np.ndarray:
    """Convert a uint8 image to float32 0-1; float input is returned as float32."""
    if img.dtype == np.uint8:
        return img.astype(np.float32) / 255.0
    return img.astype(np.float32, copy=False)


def float_to_uint8(img: np.ndarray) -> np.ndarray:
    """Quantize a float32 0-1 image to uint8 with rounding. Do this once, at the end."""
    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def mtf_stretch_float(
    img: np.ndarray,
    shadows: float = 0.0,
    midtones: float = 0.5,
    highlights: float = 1.0
) -> np.ndarray:
    """
    Midtone Transfer Function (MTF) stretch on float32 0-1 data.
    Also known as "Histogram Transformation" in Siril/PixInsight.
    
    Formula: f(x, m) = ((m - 1) * x) / ((2 * m - 1) * x - m)
    
    Args:
        img: Float32 image in 0-1
        shadows: Black point (0-1)
        midtones: Midtones balance (0-1, 0.5 is linear)
        highlights: White point (0-1)
    
    Returns:
        Stretched float32 image in 0-1
    """
    # 1. Linear clipping (Shadows/Highlights)
    img = np.clip((img - shadows) / (highlights - shadows + 1e-6), 0, 1)
    
    if abs(midtones - 0.5) < 1e-4:
        # Linear case, already handled by clipping
        return img
    
    # 2. MTF transformation, per channel (matches PixInsight and Siril)
    denom = (2 * midtones - 1) * img - midtones
    # Clip denom to avoid actual zero
    denom = np.where(np.abs(denom) < 1e-6, np.sign(denom) * 1e-6, denom)
    
    return np.clip(((midtones - 1) * img) / denom, 0, 1)


def apply_interactive_stretch(
    img: np.ndarray,
    shadows: float = 0.0,
    midtones: float = 0.5,
    highlights: float = 1.0,
    remove_stars_flag: bool = False,
    star_sensitivity: float = 0.5,
    inpaint_radius: int = 3
) -> np.ndarray:
    """
    Interactive MTF stretch (PixInsight's Histogram Transformation / STF).
    
    Args:
        img: RGB image, float32 0-1 (preferred: keeps FITS/16-bit precision) or uint8
        shadows, midtones, highlights: MTF parameters, see mtf_stretch_float
        remove_stars_flag: Remove stars before stretching (best on linear data)
    
    Returns:
        Stretched RGB image as uint8, quantized once at the end
    """
    processed_img = to_float_image(img)
    
    if remove_stars_flag:
        processed_img = remove_stars(processed_img, sensitivity=star_sensitivity, inpaint_radius=inpaint_radius)
    
    result = mtf_stretch_float(processed_img, shadows=shadows, midtones=midtones, highlights=highlights)
    return float_to_uint8(result)


def remove_stars(
    img: np.ndarray, 
    sensitivity: float = 0.5, 
    inpaint_radius: int = 3
) -> np.ndarray:
    """
    Star Removal using morphological detection and Telea inpainting.
    Yields a "starless" image.
    
    Args:
        img: RGB image, uint8 or float32 0-1; the result has the same dtype
    """
    if img is None:
        return None

    # 1. Detection runs on an 8-bit luminance view (adaptiveThreshold needs uint8)
    if img.dtype == np.uint8:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = float_to_uint8(img @ np.array(LUM_WEIGHTS_RGB, dtype=np.float32))
    
    # Precise star core detection (lower sensitivity detects more/smaller stars)
    # Threshold value adjustments based on sensitivity (0.0 to 1.0)
    c_val = int(2 + (1.0 - sensitivity) * 5) # Adaptive C parameter
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, -c_val
    )
    
    # 2. Mask Refinement
    # Dilate to cover the star halos/diffraction spikes
    kernel_size = max(1, inpaint_radius)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.dilate(thresh, kernel, iterations=1)
    
    # 3. Inpainting
    # Telea algorithm provides high quality for astronomical backgrounds.
    if img.dtype == np.uint8:
        return cv2.inpaint(img, mask, inpaint_radius, cv2.INPAINT_TELEA)
    # OpenCV inpaints 3-channel images only as uint8, and its float32 path overshoots
    # wildly (values far outside 0-1), so inpaint each channel as uint16 instead
    img16 = (np.clip(img, 0, 1) * 65535 + 0.5).astype(np.uint16)
    channels = [
        cv2.inpaint(np.ascontiguousarray(img16[:, :, c]), mask, inpaint_radius, cv2.INPAINT_TELEA)
        for c in range(img16.shape[2])
    ]
    return np.stack(channels, axis=-1).astype(np.float32) / 65535.0


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

def srgb_to_linear(img: np.ndarray) -> np.ndarray:
    """Undo the sRGB transfer curve (JPEG/PNG pixel values -> linear light)."""
    img = np.clip(img, 0, 1)
    return np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(img: np.ndarray) -> np.ndarray:
    """Apply the sRGB transfer curve (linear light -> display pixel values)."""
    img = np.clip(img, 0, 1)
    return np.where(img <= 0.0031308, 12.92 * img, 1.055 * np.power(img, 1 / 2.4) - 0.055).astype(np.float32)


def find_moon_mask(luminance: np.ndarray) -> np.ndarray:
    """
    Sunlit lunar surface as a boolean mask: smoothed luminance above 15% of the
    bright end, cleaned up, largest region only. Earthshine is far dimmer and stays out.
    """
    smooth = cv2.GaussianBlur(luminance, (0, 0), 2)
    bright = np.percentile(smooth, 99.5)
    mask = (smooth > 0.15 * bright).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count <= 1:
        return mask.astype(bool)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


def align_color_channels(img: np.ndarray, mask: np.ndarray, max_shift: float = 4.0) -> tuple[np.ndarray, list]:
    """
    Correct atmospheric dispersion: sub-pixel shift R and B onto G, measured by
    phase correlation over the moon. Without this, boosting colour paints red and
    blue rims on the limb and crater edges.

    Returns (aligned image, [(dx, dy) for R, (dx, dy) for B] as applied).
    """
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return img, [(0.0, 0.0), (0.0, 0.0)]
    pad = 16
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + pad)
    reference = np.ascontiguousarray(img[y0:y1, x0:x1, 1])
    window = cv2.createHanningWindow((x1 - x0, y1 - y0), cv2.CV_32F)

    aligned = img.copy()
    applied = []
    for channel in (0, 2):
        (dx, dy), response = cv2.phaseCorrelate(reference, np.ascontiguousarray(img[y0:y1, x0:x1, channel]), window)
        if response < 0.2 or max(abs(dx), abs(dy)) > max_shift:
            applied.append((0.0, 0.0))  # unreliable measurement: leave the channel alone
            continue
        shift = np.float32([[1, 0, -dx], [0, 1, -dy]])
        aligned[..., channel] = cv2.warpAffine(
            img[..., channel], shift, (img.shape[1], img.shape[0]),
            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT
        )
        applied.append((-dx, -dy))
    return np.clip(aligned, 0, None), applied


def guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float) -> np.ndarray:
    """
    Edge-preserving smoothing (He et al., guided image filter): smooths `src` within
    regions of similar `guide` value but not across the guide's edges. Used to smooth
    colour while keeping it inside mare boundaries and off bright crater rims.

    Args:
        guide: (H, W) float image, roughly 0-1 (here: normalized log-brightness)
        src: (H, W) or (H, W, C) float image to smooth
        radius: box radius in pixels
        eps: edge threshold; guide variations much larger than sqrt(eps) are preserved
    """
    ksize = (2 * radius + 1, 2 * radius + 1)
    box = lambda x: cv2.boxFilter(x, -1, ksize, borderType=cv2.BORDER_REFLECT)
    guide = guide.astype(np.float32)
    mean_i = box(guide)
    var_i = box(guide * guide) - mean_i * mean_i

    def filter_channel(p: np.ndarray) -> np.ndarray:
        mean_p = box(p)
        cov_ip = box(guide * p) - mean_i * mean_p
        a = cov_ip / (var_i + eps)
        b = mean_p - a * mean_i
        return box(a) * guide + box(b)

    if src.ndim == 2:
        return filter_channel(src.astype(np.float32))
    return np.stack([filter_channel(np.ascontiguousarray(src[..., c], dtype=np.float32)) for c in range(src.shape[2])], axis=-1)


def _masked_blur(values: np.ndarray, weight: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur normalized over a mask, so the sky never bleeds into the moon."""
    numerator = cv2.GaussianBlur(values * weight, (0, 0), sigma)
    denominator = cv2.GaussianBlur(weight, (0, 0), sigma)
    return np.where(denominator > 1e-3, numerator / np.maximum(denominator, 1e-3), values)


def _limb_fade(mask: np.ndarray, diameter: float) -> np.ndarray:
    """
    0 at the limb rising to 1 a few pixels inside. Pixels on the limb mix moon and sky,
    so they read as deep "detail" and local processing would turn them into a dark or
    bright rim; fading the change to zero there prevents it.
    """
    limb = max(3, int(round(diameter / 60)))
    inner = cv2.erode(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * limb + 1, 2 * limb + 1)))
    return np.clip(cv2.GaussianBlur(inner.astype(np.float32), (0, 0), limb / 1.5), 0, 1)


def _log_luminance(luminance: np.ndarray, mask: np.ndarray) -> np.ndarray:
    floor = max(float(np.percentile(luminance[mask], 1)) * 0.25, 1e-5)
    return np.log(np.maximum(luminance, floor))


def moon_tone_map(luminance: np.ndarray, mask: np.ndarray, diameter: float, amount: float) -> np.ndarray:
    """
    HDR for the moon: local tone mapping of luminance in the log domain.

    The sunlit moon spans a huge range (bright rayed highlands, dark maria, limb
    darkening). Split log-luminance into a coarse base (overall light level) and two
    detail layers (regional features such as mare edges, fine texture such as crater
    walls). Compress the base, boost the details, and put the brightness back where it
    was, so contrast is redistributed from the large scale to the small scale.

    Args:
        luminance: Linear luminance (H, W)
        mask: Boolean moon mask
        diameter: Moon diameter in pixels
        amount: 0-1 HDR strength (0 = unchanged)

    Returns:
        Tone-mapped linear luminance (same overall brightness)
    """
    if amount <= 0 or not mask.any():
        return luminance

    weight = mask.astype(np.float32)
    log_l = _log_luminance(luminance, mask)

    base = _masked_blur(log_l, weight, max(4.0, diameter / 10))
    regional = _masked_blur(log_l, weight, max(2.0, diameter / 40))
    fine = _masked_blur(log_l, weight, max(1.0, diameter / 250))

    base_mean = float(base[mask].mean())
    out_log = (
        base_mean + (base - base_mean) * (1.0 - 0.55 * amount)
        + (regional - base) * (1.0 + 0.9 * amount)
        + (fine - regional) * (1.0 + 1.3 * amount)
        + (log_l - fine) * (1.0 + 0.3 * amount)  # pixel-level layer: barely touched (noise lives here)
    )

    fade = _limb_fade(mask, diameter)
    mapped = np.exp(log_l + fade * (out_log - log_l))

    # Same overall brightness as before
    core = fade > 0.5
    scale = np.median(luminance[core]) / max(float(np.median(mapped[core])), 1e-8)
    return np.where(mask, mapped * scale, luminance)


def moon_sharpen(luminance: np.ndarray, mask: np.ndarray, diameter: float, amount: float) -> np.ndarray:
    """
    Multi-scale (wavelet-style) sharpening of luminance, like RegiStax wavelets or
    PixInsight's multiscale transform: split log-luminance into detail layers at 1, 2
    and 4 pixels, boost each, and leave the noise alone by only boosting detail that
    stands above the measured noise floor of the finest layer. Colour is untouched.

    Args:
        luminance: Linear luminance (H, W)
        mask: Boolean moon mask
        diameter: Moon diameter in pixels
        amount: 0-1 sharpening strength (0 = unchanged)

    Returns:
        Sharpened linear luminance
    """
    if amount <= 0 or not mask.any():
        return luminance

    weight = mask.astype(np.float32)
    log_l = _log_luminance(luminance, mask)
    scale = max(1.0, diameter / 450)  # detail scales with the image's resolution, not the moon's size
    blur1, blur2, blur4 = (_masked_blur(log_l, weight, sigma * scale) for sigma in (1.0, 2.0, 4.0))
    layers = (log_l - blur1, blur1 - blur2, blur2 - blur4)
    gains = (1.4 * amount, 1.0 * amount, 0.5 * amount)  # extra gain on top of the original detail

    fade = _limb_fade(mask, diameter)
    core = fade > 0.5
    noise = 1.4826 * float(np.median(np.abs(layers[0][core] - np.median(layers[0][core]))))  # MAD of the finest layer

    boost = np.zeros_like(log_l)
    for layer, gain in zip(layers, gains):
        # Soft threshold: detail below the noise floor is not amplified
        magnitude = np.maximum(np.abs(layer) - noise, 0.0)
        boost += gain * np.sign(layer) * magnitude
    return luminance * np.exp(fade * boost)


def estimate_moon_psf(luminance: np.ndarray, mask: np.ndarray) -> Optional[float]:
    """
    Measure the blur (Gaussian PSF sigma, in pixels) from the moon's own limb.

    The limb is a perfectly sharp edge on the sky, so its brightness profile across the
    edge is the step response of the optics + seeing (the edge spread function). Take
    profiles along the brightness gradient at the sharpest part of the outline (the limb,
    not the soft terminator), align them on their half-maximum, take the median and fit
    an error function. This replaces "start the PSF slider at 1 and increase it".

    Returns:
        sigma in pixels, or None when there is no usable limb
    """
    inner = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    ys, xs = np.nonzero(mask & ~inner)
    if len(ys) < 50:
        return None
    gx = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3)
    level = _masked_blur(luminance, mask.astype(np.float32), 6)

    # Sharpest edges relative to the local brightness: the limb, not the terminator
    steepness = np.hypot(gx[ys, xs], gy[ys, xs]) / np.maximum(level[ys, xs], 1e-6)
    keep = steepness >= np.percentile(steepness, 70)
    ys, xs = ys[keep], xs[keep]
    nx, ny = gx[ys, xs], gy[ys, xs]
    norm = np.hypot(nx, ny) + 1e-9
    nx, ny = nx / norm, ny / norm

    step = 0.25
    t = np.arange(-8, 8 + step / 2, step, dtype=np.float32)
    px = xs[:, None] + t[None, :] * nx[:, None]
    py = ys[:, None] + t[None, :] * ny[:, None]
    profiles = map_coordinates(luminance, [py.ravel(), px.ravel()], order=1, mode='nearest').reshape(px.shape)
    low = profiles[:, t < -5].mean(axis=1)
    high = profiles[:, t > 5].mean(axis=1)
    span = high - low
    good = span > 0.3 * np.median(span)
    profiles = (profiles[good] - low[good, None]) / span[good, None]

    aligned = []
    for profile in profiles:
        i = int(np.argmax(profile >= 0.5))
        if i == 0:
            continue
        centre = t[i - 1] + (0.5 - profile[i - 1]) / max(profile[i] - profile[i - 1], 1e-9) * step
        aligned.append(np.interp(t, t - centre, profile))
    if len(aligned) < 30:
        return None
    esf = np.median(np.array(aligned), axis=0)

    core = np.abs(t) <= 5
    sigmas = np.arange(0.3, 5.0, 0.02)
    errors = [np.mean((0.5 * (1 + erf(t[core] / (np.sqrt(2) * s))) - esf[core]) ** 2) for s in sigmas]
    return float(sigmas[int(np.argmin(errors))])


def moon_deconvolve(
    luminance: np.ndarray,
    mask: np.ndarray,
    diameter: float,
    amount: float,
    psf_sigma: Optional[float],
    protect: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    Deconvolution (Richardson-Lucy, Gaussian PSF) of linear luminance -- the step
    BlurXTerminator does in the PixInsight workflow. Unlike sharpening, which boosts
    detail that is there, this undoes a measured blur, so small craters come back.

    Kept from turning "crunchy": iterations are limited (amount 1 = 30), the change is
    soft-thresholded against the noise floor, faded out at the limb (ringing) and kept
    away from clipped areas (a flat clipped plateau would ring).

    Args:
        luminance: Linear luminance (H, W), sky at 0
        mask: Boolean moon mask
        diameter: Moon diameter in pixels
        amount: 0-1 strength (0 = unchanged)
        psf_sigma: Gaussian PSF sigma in pixels (see estimate_moon_psf); None skips
        protect: Boolean mask of pixels to leave alone (clipped highlights)
    """
    if amount <= 0 or psf_sigma is None or psf_sigma < 0.5 or not mask.any():
        return luminance

    observed = np.maximum(luminance, 0).astype(np.float32)
    floor = max(float(np.percentile(observed[mask], 1)) * 0.25, 1e-5)
    observed = observed + floor  # RL divides by the blurred estimate: keep it away from 0
    estimate = observed.copy()
    for _ in range(max(1, int(round(30 * amount)))):
        blurred = cv2.GaussianBlur(estimate, (0, 0), psf_sigma)
        estimate *= cv2.GaussianBlur(observed / np.maximum(blurred, 1e-8), (0, 0), psf_sigma)

    # The change in log space, minus what the noise alone would produce
    change = np.log(estimate) - np.log(observed)
    log_l = np.log(observed)
    fade = _limb_fade(mask, diameter)
    core = fade > 0.5
    fine = log_l - _masked_blur(log_l, mask.astype(np.float32), 1.0)
    noise = 1.4826 * float(np.median(np.abs(fine[core] - np.median(fine[core])))) if core.any() else 0.0
    change = np.sign(change) * np.maximum(np.abs(change) - 0.5 * noise, 0.0)

    if protect is not None and protect.any():
        fade = fade * (1.0 - cv2.GaussianBlur(protect.astype(np.float32), (0, 0), 2 * psf_sigma + 1))
    return luminance * np.exp(fade * change)


def moon_halo(rgb: np.ndarray, mask: np.ndarray, diameter: float, amount: float) -> np.ndarray:
    """
    Glow around the moon: light scattered by the atmosphere and optics, added in linear light.

    A real point-spread function has a bright core and long, faint wings, so the glow is
    a sum of blurs at several scales (relative to the moon's size), strongest near the
    limb and fading to nothing. It is added outside the disk only, so the surface keeps
    its contrast, and it is slightly blue, like sky scatter.

    Args:
        rgb: Linear RGB image (H, W, 3) with the moon at display brightness
        mask: Boolean moon mask
        diameter: Moon diameter in pixels
        amount: 0-1 glow strength (0 = none)

    Returns:
        Linear RGB with the glow added
    """
    if amount <= 0:
        return rgb

    # The big blurs don't need full resolution
    scale = 4 if min(rgb.shape[:2]) >= 512 else 1
    small_h, small_w = rgb.shape[0] // scale, rgb.shape[1] // scale
    moon_soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2)
    source = cv2.resize(rgb * moon_soft[..., None], (small_w, small_h), interpolation=cv2.INTER_AREA)

    # (sigma as a fraction of the moon's diameter, share of the glow)
    glow = np.zeros_like(source)
    for sigma_fraction, weight in ((0.02, 0.45), (0.06, 0.30), (0.15, 0.17), (0.35, 0.08)):
        glow += weight * cv2.GaussianBlur(source, (0, 0), max(1.0, sigma_fraction * diameter / scale))
    glow = cv2.resize(glow, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)

    outside = (1.0 - moon_soft)[..., None]
    tint = np.array([0.92, 0.98, 1.10], dtype=np.float32)
    return rgb + 0.5 * amount * outside * glow * tint


def moon_trim_scatter(rgb: np.ndarray, mask: np.ndarray, diameter: float) -> np.ndarray:
    """
    Remove the faint skirt of scattered light just outside the sunlit limb.

    The seeing PSF has wide wings that deconvolution (a Gaussian PSF) doesn't model, so
    ~1% of the limb's light spreads a few pixels into the sky. After the display curve
    that reads as a grey fringe and the edge looks soft. The skirt is modelled as the
    disk blurred, scaled to match the sky just outside, and subtracted outside the disk.
    Only next to bright disk: at the terminator the surface fades out gradually and the
    pixels past the mask are dim terrain, not scattered light.

    Args:
        rgb: Linear RGB image (H, W, 3) with the moon at display brightness
        mask: Boolean moon mask
        diameter: Moon diameter in pixels

    Returns:
        rgb, with the skirt removed in place (the disk itself is unchanged)
    """
    if not mask.any():
        return rgb
    window = moon_window(mask, diameter)
    sub, m = rgb[window], mask[window]
    lum = sub.mean(axis=2)
    moon = m.astype(np.float32)
    sigma = max(1.5, diameter / 50)
    disc = cv2.GaussianBlur(lum * moon, (0, 0), sigma)
    reach = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(8 * sigma) | 1,) * 2)
    bright = float(np.percentile(lum[m], 99))
    ring = cv2.dilate(m.astype(np.uint8), reach).astype(bool) & ~m & (disc > 0.05 * bright)
    if ring.sum() < 50 or bright <= 0:
        return rgb

    # Only a compact skirt (a raw stack: gone within a few pixels). A wide glow (telescope-
    # processed JPEG, hazy sky) is still bright past the model's reach; trimming its inner
    # part would leave a dark moat with a grey ring beyond, so leave it whole.
    dist = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5)
    span = 4 * sigma
    near = np.median(lum[(dist > 1) & (dist < span / 2)])
    far_band = (dist > span) & (dist < 2 * span)
    far = np.median(lum[far_band]) if far_band.any() else 0.0
    compact = float(np.clip((0.3 - far / max(near, 1e-8)) / 0.2, 0, 1))
    if compact <= 0:
        return rgb
    # Scaled to cover the skirt nearly everywhere (90th percentile): too much only clips sky to black
    k = float(np.percentile(lum[ring] / disc[ring], 90))

    # Brightest disk level within reach: high beside the sunlit limb, low beside the terminator
    level = np.where(m, disc / np.maximum(cv2.GaussianBlur(moon, (0, 0), sigma), 1e-3), 0).astype(np.float32)
    t = np.clip((cv2.dilate(level, reach) / bright - 0.35) / 0.25, 0, 1)
    weight = compact * (1.0 - moon) * t * t * (3 - 2 * t)

    ratio = 1.0 - weight * np.minimum(k * disc, lum) / np.maximum(lum, 1e-8)
    del disc, level, t, weight, dist
    sub *= ratio[..., None]
    return rgb


def find_blown_highlights(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    Overexposed parts of the disk in a display-referred image (JPEG, phone photo).

    Phones and cameras rarely clip at exactly 255: the highlight shoulder of their tone
    curve tops out a few levels lower, and JPEG ringing scatters the plateau by +-2, so a
    fixed threshold misses it. A clipped plateau shows instead as a spike in the
    histogram near the top, far above the smoothly falling tail of a good exposure.

    Args:
        x: display-referred float RGB, 0-1
        mask: moon disk
    """
    blown = np.zeros(mask.shape, dtype=bool)
    if mask.sum() < 100:
        return blown
    # Brightest channel, median-filtered against JPEG ringing, in 8-bit levels
    peak = cv2.medianBlur(np.round(x.max(axis=2) * 255).astype(np.uint8), 3)
    hist = np.bincount(peak[mask], minlength=256).astype(np.float64)
    level = 230 + int(np.argmax(hist[230:]))
    spike = hist[level - 1:level + 2].sum() / (3 * hist[level - 15:level - 4].mean() + 1)
    if spike > 2:
        blown = (peak >= level - 2) & mask
    return blown


def moon_window(mask: np.ndarray, diameter: float) -> tuple:
    """
    Slice of the frame holding the moon plus a margin wider than the moon stages'
    largest blur (0.1 diameter sigma, 3 sigma reach), so cropping changes nothing.
    The whole frame when there is no moon or the margin covers it anyway.
    """
    ys, xs = np.nonzero(mask.any(axis=1))[0], np.nonzero(mask.any(axis=0))[0]
    if len(ys) == 0:
        return np.s_[:, :]
    pad = int(0.35 * diameter) + 32
    h, w = mask.shape
    y0, y1 = max(0, ys[0] - pad), min(h, ys[-1] + 1 + pad)
    x0, x1 = max(0, xs[0] - pad), min(w, xs[-1] + 1 + pad)
    if (y1 - y0) * (x1 - x0) > 0.8 * h * w:
        return np.s_[:, :]
    return np.s_[y0:y1, x0:x1]


def mineral_moon(
    img: np.ndarray,
    strength: float = 0.75,
    display_referred: bool = True,
    halo: float = 0.0,
    hdr: float = 0.0,
    sharpen: float = 0.5,
    detrend: bool = True,
    protect_highlights: bool = True,
    warmth: float = 0.0,
    deconvolve: float = 0.0,
    bit_depth: int = 8,
    info: Optional[dict] = None
) -> np.ndarray:
    """
    Mineral Moon, following the standard astrophotography workflow:

    1. Work in linear light (undo the JPEG/sRGB curve; FITS is already linear)
    2. Neutralize the sky and find the sunlit moon
    3. Align R/B onto G (atmospheric dispersion)
    4. White-balance the moon so its average colour is grey; only colour
       *differences* (titanium-rich blue vs iron-rich orange maria) are signal
    5. Split luminance from colour: colour is measured as a brightness-weighted,
       smoothed ratio (mineral colour varies over large areas, so smoothing removes
       chroma noise without blurring detail), then amplified
    6. Sharpen luminance only, recombine (brightness is unchanged by the colour
       boost), keep the sky black and clipped areas uncoloured

    Args:
        img: RGB image, float32 0-1 (preferred) or uint8
        strength: 0-1, how strongly mineral colours are amplified
        display_referred: True for JPEG/PNG-style data (sRGB curve applied),
            False for linear data such as FITS stacks
        halo: 0-1, strength of the glow around the moon (0 = none)
        hdr: 0-1, strength of local tone mapping (0 = none): compresses the bright-to-dark
            range across the moon and lifts surface detail, applied to luminance only
        sharpen: 0-1, multi-scale luminance sharpening, independent of colour strength
        detrend: remove colour that only follows brightness (camera tone-curve artefact)
        protect_highlights: keep the brightest terrain silver (luminosity-masked colour)
        warmth: -1 to 1, colour balance along blue <-> orange (0 = neutral moon average)
        deconvolve: 0-1, Richardson-Lucy deconvolution with the PSF measured from the limb
        bit_depth: 8 (uint8, dithered) or 16 (uint16, for 16-bit PNG/TIFF editing)
        info: optional dict, filled with what was measured (psf_sigma, clipped_fraction,
            diameter) so the caller can explain the result

    Returns:
        uint8 (or uint16) RGB display image
    """
    x = to_float_image(img)
    lin = srgb_to_linear(x) if display_referred else x.copy()

    # Clipped pixels carry no colour information -- blown highlights, and channels
    # crushed to black (e.g. where the limb fades into a sky clipped to 0)
    clipped = (x >= 0.99).any(axis=2) | (x <= 1.5 / 255).any(axis=2)
    clipped = cv2.dilate(clipped.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

    # 2. Sky level per channel, measured away from the moon, then subtracted
    rough = lin.mean(axis=2)
    mask = find_moon_mask(rough - np.percentile(rough, 5))
    away = ~cv2.dilate(mask.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool)
    sky = np.median(lin[away], axis=0) if away.sum() > 1000 else np.percentile(lin.reshape(-1, 3), 5, axis=0)
    lin = np.clip(lin - sky, 0, None)

    # Blown highlights that sit below the top value (phones), see find_blown_highlights
    blown = find_blown_highlights(x, mask) if display_referred else np.zeros(mask.shape, dtype=bool)
    clipped |= cv2.dilate(blown.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

    # 3. Atmospheric dispersion
    lin, _ = align_color_channels(lin, mask)

    # Everything up to the halo only changes the disk and its surroundings, and the
    # widest blur there reaches ~0.3 diameters: work on a window around the moon rather
    # than the whole frame (a Seestar frame is mostly sky, so this is ~2-3x faster)
    diameter = 2 * np.sqrt(mask.sum() / np.pi)
    full_lin, full_mask = lin, mask
    window = moon_window(mask, diameter)
    lin, x, clipped, blown, mask = (np.ascontiguousarray(a[window]) for a in (lin, x, clipped, blown, mask))
    white_balance = np.ones(3, dtype=np.float32)

    # Pixels whose colour can be trusted: unclipped and away from the limb, where
    # pixels mix with the sky. The limb gets its colour from the interior instead.
    # At least 6 px: the channels' PSFs differ (seeing, optics), so the outer few pixels
    # carry a colour fringe whose width follows the seeing, not the moon's size (a crescent's
    # area-based diameter is small). Amplified, it was an orange ring around the moon.
    limb = max(6, int(round(diameter / 150)))
    interior = cv2.erode(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * limb + 1, 2 * limb + 1)))
    valid = interior.astype(bool) & ~clipped

    # 4. White balance: equal channel medians over unclipped moon
    if valid.sum() > 100:
        medians = np.median(lin[valid], axis=0)
        white_balance = (medians.mean() / np.maximum(medians, 1e-6)).astype(np.float32)
        lin *= white_balance

    # 5. Colour as brightness-weighted, smoothed ratio to luminance (1 = neutral)
    luminance = lin.mean(axis=2)
    sigma = max(2.0, diameter / 100)
    weight = valid.astype(np.float32)
    numerator = cv2.GaussianBlur(lin * weight[..., None], (0, 0), sigma)
    denominator = cv2.GaussianBlur(luminance * weight, (0, 0), sigma)[..., None]
    ratio = np.where(denominator > 1e-5, numerator / np.maximum(denominator, 1e-5), 1.0)

    # Lunar spectra are smooth: mineral differences are a spectral *slope* (blue <-> orange),
    # with green in between. Colour along green <-> magenta is mostly noise and compression
    # artefacts, so keep the slope component and suppress the other before amplifying.
    # The Gaussian-smoothed colour above bleeds across mare edges and onto bright crater
    # rims. For the colour that is actually shown, measure it at fine scale and smooth it
    # with a guided filter steered by brightness: smooth inside regions, crisp at their
    # edges (mineral boundaries follow albedo boundaries). Normalized by the valid-pixel
    # weight so clipped pixels don't pull colour towards grey.
    fine_numerator = cv2.GaussianBlur(lin * weight[..., None], (0, 0), 1.5)
    fine_denominator = cv2.GaussianBlur(luminance * weight, (0, 0), 1.5)
    fine_weight = cv2.GaussianBlur(weight, (0, 0), 1.5)
    fine_luminance = np.where(fine_weight > 1e-3, fine_denominator / np.maximum(fine_weight, 1e-3), luminance)
    fine_ratio = np.where(
        fine_denominator[..., None] > 1e-5, fine_numerator / np.maximum(fine_denominator[..., None], 1e-5), 1.0
    )
    log_fine = np.log(np.maximum(fine_luminance, 1e-6))
    # The guide ignores features smaller than a few pixels: small bright craters carry
    # chromatic-aberration fringes (warm core, blue ring) that would otherwise be kept as
    # "edges". Averaged across, the fringe cancels; mare boundaries are large and stay crisp.
    guide_log = cv2.GaussianBlur(log_fine, (0, 0), max(2.5, diameter / 180))
    if valid.any():
        g_lo, g_hi = np.percentile(guide_log[valid], [1, 99])
        guide = np.clip((guide_log - g_lo) / max(g_hi - g_lo, 1e-6), 0, 1)
    else:
        guide = np.zeros_like(log_fine)
    radius = max(3, int(round(diameter / 60)))
    trust = (fine_weight > 0.3).astype(np.float32)
    smoothed = guided_filter(guide, (fine_ratio - 1.0) * trust[..., None], radius, eps=0.01)
    smoothed_trust = np.maximum(guided_filter(guide, trust, radius, eps=0.01), 1e-3)
    edge_aware = np.where(smoothed_trust[..., None] > 0.2, smoothed / smoothed_trust[..., None], ratio - 1.0)

    deviation = edge_aware

    # Colour that simply follows brightness (bright -> blue, mid -> yellow) comes from the
    # camera's per-channel tone curves, not from minerals. Remove the straight-line trend of
    # colour against log-brightness; regional differences at equal brightness stay.
    smooth_luminance = denominator[..., 0] / np.maximum(cv2.GaussianBlur(weight, (0, 0), sigma), 1e-5)
    log_lum = np.log(np.maximum(smooth_luminance, 1e-6))
    if detrend and valid.sum() > 500:
        t = log_lum[valid]
        lo, hi = np.percentile(t, [1, 99])
        design = np.stack([np.ones_like(t), t], axis=1)
        coef, *_ = np.linalg.lstsq(design, (ratio - 1.0)[valid], rcond=None)  # (2, 3): per-channel line
        # Evaluate the trend at the scale the colour was measured (edge-aware smoothed
        # brightness). Using pixel-level brightness instead would push small bright
        # points away from "blue" and paint them warm.
        log_trend = guided_filter(guide, log_fine, radius, eps=0.01)
        t_all = np.clip(log_trend, lo, hi)
        deviation = deviation - (coef[0] + t_all[..., None] * coef[1])

    slope_axis = np.array([-1.0, 0.0, 1.0], dtype=np.float32) / np.sqrt(2)
    curvature_axis = np.array([-1.0, 2.0, -1.0], dtype=np.float32) / np.sqrt(6)
    slope = deviation @ slope_axis          # the mineral signal: + bluer, - warmer
    curvature = deviation @ curvature_axis

    # Warmth moves the neutral point along blue <-> orange, in units of the image's own
    # colour spread so the slider feels the same on any photo (+ warmer, - cooler/silver-blue)
    if warmth != 0 and valid.any():
        slope = slope - warmth * float(np.std(slope[valid]))

    # Display palette: the measured signal is one number per pixel (position on the
    # blue <-> orange axis); how it is shown is a rendering choice. The classic mineral-moon
    # rendering shows the warm end as rust (green dips with blue) and the cool end as slate
    # blue (green dips slightly), rather than plain orange/cyan. Both directions sum to zero
    # (brightness unchanged) and are scaled so B - R still equals the measured slope.
    warm_direction = np.array([0.75, -0.15, -0.60], dtype=np.float32)
    cool_direction = np.array([-0.55, -0.10, 0.65], dtype=np.float32)
    warm_direction /= -float(warm_direction @ slope_axis)
    cool_direction /= float(cool_direction @ slope_axis)
    deviation = (
        np.where(slope[..., None] >= 0, slope[..., None] * cool_direction, -slope[..., None] * warm_direction)
        + 0.25 * curvature[..., None] * curvature_axis
    )

    gain = 1.0 + 12.0 * strength
    if protect_highlights and valid.any():
        # Luminosity mask: the brightest terrain (highlands, ray systems) stays silver,
        # the colour lives in the maria -- the classic mineral-moon look
        # Fine-scale brightness, so small bright craters inside maria stay silver too
        lo, hi = np.percentile(fine_luminance[valid], [55, 99])
        h = np.clip((fine_luminance - lo) / max(hi - lo, 1e-6), 0, 1)
        h = h * h * (3 - 2 * h)
        gain = gain * (1.0 - 0.65 * h)[..., None]
    color = 1.0 + gain * deviation
    # Colour covers the moon (limb included, filled from the interior) and fades to
    # neutral in the sky and wherever no trustworthy pixels are nearby (large clipped areas)
    support = np.clip(denominator / np.maximum(cv2.GaussianBlur(luminance, (0, 0), sigma)[..., None], 1e-5), 0, 1)
    color_weight = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma / 2)[..., None] * support
    color = 1.0 + color_weight * (color - 1.0)

    white_level = np.percentile(luminance[valid if valid.any() else mask], 99.7) if mask.any() else 1.0

    # Exposure check: blown highlights on the disk have lost detail and colour for good.
    # Saturation is a plateau at the very top value (255, 65535, or FITS max after
    # normalization); 0.99 would also count the merely brightest pixels of a FITS.
    highlights = ((x >= 0.999).any(axis=2) | blown) & mask
    # Done with the colour intermediates (several full RGB float arrays): free them
    # before the luminance stages so peak memory stays within a small server
    del x, numerator, denominator, ratio, fine_numerator, fine_denominator, fine_ratio
    del smoothed, smoothed_trust, edge_aware, deviation, support, color_weight
    psf_sigma = estimate_moon_psf(luminance, mask) if deconvolve > 0 or info is not None else None
    if info is not None:
        info.update(
            psf_sigma=psf_sigma,
            clipped_fraction=float(highlights.sum() / max(mask.sum(), 1)),
            diameter=float(diameter),
        )

    # 6. Deconvolution, HDR tone mapping, then multi-scale sharpening (luminance only), then recombine
    luminance = moon_deconvolve(luminance, mask, diameter, deconvolve, psf_sigma, protect=highlights)
    luminance = moon_tone_map(luminance, valid | mask, diameter, hdr)
    luminance = moon_sharpen(luminance, valid | mask, diameter, sharpen)
    rgb = np.clip(luminance[..., None] * color, 0, None)

    # Back to the full frame: outside the window colour is neutral, so only grey sky remains
    if window != np.s_[:, :]:
        sky_grey = (full_lin @ white_balance)[..., None] / 3.0
        full_rgb = np.repeat(sky_grey, 3, axis=2)
        full_rgb[window] = rgb
        rgb, mask = full_rgb, full_mask
    del full_lin, color

    # Levels: put the bright lunar surface near white (silver highlands). Linear data has
    # no display scale yet, so always set it; a dim JPEG is only brightened, never darkened.
    # Measured before the HDR/sharpen stages change the luminance, so those sliders don't
    # also shift overall brightness.
    if mask.any():
        scale = 0.92 / max(float(white_level), 1e-6)
        rgb *= scale if not display_referred else max(scale, 1.0)

    # A crisp limb first; the halo slider then adds a controlled glow on top
    rgb = moon_trim_scatter(rgb, mask, diameter)
    rgb = moon_halo(rgb, mask, diameter, halo)

    # Gamut: scale over-range pixels down as a whole so hue survives
    rgb /= np.maximum(rgb.max(axis=2, keepdims=True), 1.0)

    if bit_depth == 16:
        return np.clip(linear_to_srgb(rgb) * 65535.0 + 0.5, 0, 65535).astype(np.uint16)

    # Dither before quantizing: the faint glow spans only a few 8-bit levels, which
    # would otherwise show as concentric rings. Triangular noise, off in pure black.
    display = linear_to_srgb(rgb) * 255.0
    rng = np.random.default_rng(0)
    noise = rng.random(display.shape, dtype=np.float32) + rng.random(display.shape, dtype=np.float32) - 1.0
    display = display + noise * np.minimum(display, 1.0)
    return np.clip(display + 0.5, 0, 255).astype(np.uint8)


def enhance_nebula(img_array: np.ndarray) -> np.ndarray:
    """
    Nebula preset - Optimized for emission nebulae.
    
    Percentile stretch with targeted adjustments for emission nebulae:
    - Slightly higher saturation for Ha/OIII colors
    - Stronger star reduction to emphasize nebula structure
    
    Best for: Orion, Lagoon, Rosette, and other emission nebulae
    """
    cv_img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
    
    # 1. Percentile histogram stretch
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
    hsv[:, :, 1] = hsv[:, :, 1] * 1.5  # 50% boost
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


# =============================================================================
# PRESET REGISTRY
# =============================================================================

PRESETS = {
    "mineral_moon": {
        "function": mineral_moon,
        "name": "Mineral Moon",
        "description": "Reveals titanium (blue) and iron (orange) maria colours; intensity sets colour strength",
        "best_for": "Full or gibbous moon, sunlit side not overexposed",
        # Takes float input (full bit depth) and uses intensity as colour strength, not a blend
        "float_input": True
    },
    "nebula": {
        "function": enhance_nebula,
        "name": "Nebula",
        "description": "Saturation and contrast for emission nebulae",
        "best_for": "Orion, Lagoon, Rosette, and other emission nebulae"
    }
}


def apply_pro_adjustments(
    img_array: np.ndarray,
    denoise: float = 0.0,
    star_reduction: float = 0.0,
    saturation: float = 1.0,
    sharpening: float = 0.0
) -> np.ndarray:
    """
    Apply Pro Mode fine-tuning on top of a preset result.
    All neutral values (0, 0, 1.0, 0) leave the image unchanged.

    Args:
        img_array: Input image as numpy array (RGB)
        denoise: Extra noise reduction (0-1)
        star_reduction: How much to shrink stars (0-1)
        saturation: Saturation multiplier (0-2, 1.0 = unchanged)
        sharpening: Unsharp mask amount on luminance (0-1)

    Returns:
        Adjusted image as numpy array (RGB)
    """
    img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

    if star_reduction > 0:
        img = reduce_stars(img, None, star_reduction, True, True)

    if denoise > 0:
        img = astro_denoise(img, strength=denoise * 2.0, protect_stars=True, edge_aware=True)

    if saturation > 1.0:
        img = background_protected_saturation(img, saturation_boost=saturation)
    elif saturation < 1.0:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] *= saturation
        img = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)

    if sharpening > 0:
        # Sharpen luminance only to avoid color fringing
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        l_channel = lab[:, :, 0]
        blurred = cv2.GaussianBlur(l_channel, (0, 0), 1.5)
        lab[:, :, 0] = l_channel + (l_channel - blurred) * sharpening * 1.5
        img = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)

    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def compute_auto_stf(
    img_array: np.ndarray,
    shadows_clipping: float = -2.8,
    target_background: float = 0.25
) -> dict:
    """
    Compute PixInsight-style AutoSTF parameters for the MTF stretch.

    Uses the median and normalized MAD of each channel (linked) to place
    the black point just below the background and choose a midtones balance
    that maps the background median to target_background.

    Args:
        img_array: RGB image, float32 0-1 (preferred) or uint8
        shadows_clipping: Black point offset in MADN units (negative = below median)
        target_background: Desired background brightness after stretch (0-1)

    Returns:
        Dict with shadows, midtones, highlights (all 0-1)
    """
    data = to_float_image(img_array)

    # Subsample large images; statistics are stable at ~1M pixels
    step = max(1, int(np.sqrt(data.shape[0] * data.shape[1] / 1_000_000)))
    data = data[::step, ::step]

    medians, madns = [], []
    for c in range(data.shape[2]):
        channel = data[:, :, c]
        med = float(np.median(channel))
        medians.append(med)
        madns.append(1.4826 * float(np.median(np.abs(channel - med))))
    median = float(np.mean(medians))
    madn = float(np.mean(madns))

    shadows = float(np.clip(median + shadows_clipping * madn, 0.0, 1.0)) if madn > 0 else 0.0

    # Midtones balance m such that MTF(m, median - shadows) = target_background,
    # which is MTF(target_background, median - shadows) by symmetry of the MTF
    x = median - shadows
    if x <= 0:
        midtones = 0.5
    else:
        t = target_background
        midtones = ((t - 1) * x) / ((2 * t - 1) * x - t)
    midtones = float(np.clip(midtones, 0.001, 0.999))

    return {"shadows": shadows, "midtones": midtones, "highlights": 1.0}


def enhance_with_preset(
    img_array: np.ndarray,
    preset: PresetType = "mineral_moon",
    intensity: float = 0.75,
    adjustments: Optional[dict] = None,
    img_float: Optional[np.ndarray] = None,
    display_referred: bool = True,
    halo: float = 0.0,
    hdr: float = 0.0,
    sharpen: float = 0.5,
    warmth: float = 0.0,
    deconvolve: float = 0.0,
    bit_depth: int = 8,
    info: Optional[dict] = None
) -> np.ndarray:
    """
    Apply the specified enhancement preset to an image with adjustable intensity.
    
    Args:
        img_array: Input image as numpy array (RGB)
        preset: One of the available preset types
        intensity: Enhancement intensity from 0.0 (minimal) to 1.0 (full)
                   Default is 0.75 for balanced results
        adjustments: Optional Pro Mode kwargs for apply_pro_adjustments
        img_float: Full bit-depth float32 version of the image, for float_input presets
        display_referred: False when the data is linear (FITS), for float_input presets
        halo: Glow around the moon, 0-1 (Mineral Moon only)
        hdr: Local tone mapping strength, 0-1 (Mineral Moon only)
        sharpen: Multi-scale sharpening strength, 0-1 (Mineral Moon only)
        warmth: Colour balance, -1 (cool) to 1 (warm) (Mineral Moon only)
        deconvolve: Deconvolution strength, 0-1 (Mineral Moon only)
        bit_depth: 16 for a uint16 result (Mineral Moon only, and only without Pro Mode
            adjustments, which work on 8-bit); otherwise uint8
        info: Optional dict the preset fills with measurements (Mineral Moon only)

    Returns:
        Enhanced image as numpy array (RGB)
    """
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}. Available: {list(PRESETS.keys())}")
    
    # Clamp intensity to valid range
    intensity = max(0.0, min(1.0, intensity))
    
    enhance_func = PRESETS[preset]["function"]
    
    if PRESETS[preset].get("float_input"):
        source = img_float if img_float is not None else img_array
        neutral = not adjustments or adjustments == {"denoise": 0.0, "star_reduction": 0.0, "saturation": 1.0, "sharpening": 0.0}
        enhanced = enhance_func(
            source, strength=intensity, display_referred=display_referred, halo=halo, hdr=hdr, sharpen=sharpen,
            warmth=warmth, deconvolve=deconvolve, bit_depth=bit_depth if neutral else 8, info=info
        )
        if not neutral:
            enhanced = apply_pro_adjustments(enhanced, **adjustments)
        return enhanced
    
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

    # Apply Pro Mode fine-tuning
    if adjustments:
        enhanced = apply_pro_adjustments(enhanced, **adjustments)
    
    return enhanced
