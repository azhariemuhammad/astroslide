"""
Deterministic synthetic test images that mimic linear (unstretched) smart telescope stacks.

Real FITS samples aren't in the repo, so these stand in for them: a dark background
with a light pollution gradient and green cast, faint nebulosity, a galaxy, a star
field with a few saturated stars, and noise. Same seed -> identical image every run.
"""

import io

import astropy.io.fits as fits
import numpy as np


def make_linear_deep_sky(height: int = 600, width: int = 900, seed: int = 42) -> np.ndarray:
    """
    Returns a linear float32 RGB image (H, W, 3) in the 0-1 range.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx, ny = xx / width, yy / height

    # Background: sky level + diagonal light pollution gradient + vignetting
    vignette = 1.0 - 0.25 * ((nx - 0.5) ** 2 + (ny - 0.5) ** 2)
    sky = (0.02 + 0.015 * nx + 0.008 * ny) * vignette
    img = np.stack([sky * 0.9, sky * 1.15, sky * 0.8], axis=-1)  # green cast, typical of OSC stacks

    # Emission nebula: overlapping gaussians, mostly red (H-alpha) with some teal (OIII)
    for _ in range(6):
        cx, cy = rng.uniform(0.2, 0.6), rng.uniform(0.3, 0.7)
        sigma = rng.uniform(0.05, 0.12)
        blob = np.exp(-(((nx - cx) ** 2 + (ny - cy) ** 2) / (2 * sigma ** 2)))
        amp = rng.uniform(0.01, 0.03)
        img += blob[..., None] * amp * np.array([1.0, 0.35, 0.45], dtype=np.float32)

    # Galaxy: tilted elliptical profile with a bright core
    gx, gy, angle = 0.75, 0.35, 0.6
    dx, dy = nx - gx, ny - gy
    rx = dx * np.cos(angle) + dy * np.sin(angle)
    ry = -dx * np.sin(angle) + dy * np.cos(angle)
    r = np.sqrt((rx / 0.08) ** 2 + (ry / 0.03) ** 2)
    galaxy = 0.06 * np.exp(-r * 2.5) + 0.2 * np.exp(-r * 12)
    img += galaxy[..., None] * np.array([1.0, 0.95, 0.85], dtype=np.float32)

    # Stars: power-law fluxes, gaussian PSF, varied colour temperature
    n_stars = 350
    sx = rng.uniform(0, width, n_stars)
    sy = rng.uniform(0, height, n_stars)
    flux = 0.02 * rng.pareto(1.5, n_stars) + 0.01
    colors = rng.uniform(0.8, 1.2, (n_stars, 3)).astype(np.float32)
    psf_sigma = 1.3
    for x0, y0, f, c in zip(sx, sy, flux, colors):
        x_min, x_max = int(max(0, x0 - 8)), int(min(width, x0 + 9))
        y_min, y_max = int(max(0, y0 - 8)), int(min(height, y0 + 9))
        py, px = np.mgrid[y_min:y_max, x_min:x_max]
        psf = np.exp(-(((px - x0) ** 2 + (py - y0) ** 2) / (2 * psf_sigma ** 2)))
        img[y_min:y_max, x_min:x_max] += psf[..., None] * f * c

    # Shot + read noise
    img += rng.normal(0, 1, img.shape).astype(np.float32) * (0.002 + 0.01 * np.sqrt(np.clip(img, 0, None)))

    return np.clip(img, 0, 1).astype(np.float32)


def to_fits_bytes(img: np.ndarray, color: bool = True) -> bytes:
    """
    Encode a 0-1 float RGB image as a 16-bit FITS file.
    color=True writes the standard (3, H, W) cube; color=False writes 2D luminance.
    """
    if color:
        data = np.transpose(img, (2, 0, 1))
    else:
        data = img @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    data16 = np.round(data * 65535).astype(np.uint16)

    buffer = io.BytesIO()
    fits.PrimaryHDU(data16).writeto(buffer)
    return buffer.getvalue()


def make_synthetic_moon(size: int = 800, seed: int = 7) -> dict:
    """
    Full moon with known mineral colours, for validating Mineral Moon processing.

    Ground truth: highlands are neutral after white balance, one mare is bluish
    (titanium-rich, like Tranquillitatis) and one is orange (iron-rich, like
    Serenitatis), each tinted by about 4% -- the size of real lunar colour differences.
    The observed image adds atmospheric dispersion (R and B shifted vertically
    against G), seeing blur, a warm overall cast and noise.

    Returns a dict with:
        linear: observed linear float32 RGB (H, W, 3), 0-1, sunlit side unclipped
        disk, blue_mare, orange_mare: boolean ground-truth masks
        dispersion: (dy_red, dy_blue) pixel shifts applied relative to green
    """
    import cv2

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cy = cx = size / 2
    radius = size * 0.41
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    disk = r < radius

    def blob(x0, y0, rx, ry):
        return (((xx - x0) / rx) ** 2 + ((yy - y0) / ry) ** 2) < 1

    blue_mare = blob(cx + 0.30 * radius, cy - 0.05 * radius, 0.28 * radius, 0.22 * radius) & disk
    orange_mare = blob(cx - 0.20 * radius, cy - 0.40 * radius, 0.22 * radius, 0.20 * radius) & disk

    # Albedo: bright highlands, dark maria, crater texture at several scales
    albedo = np.full((size, size), 0.75, dtype=np.float32)
    albedo[blue_mare | orange_mare] = 0.45
    albedo = cv2.GaussianBlur(albedo, (0, 0), 3)
    for sigma, amp in [(1.5, 0.06), (6, 0.08), (20, 0.06)]:
        albedo += amp * cv2.GaussianBlur(rng.normal(0, 1, (size, size)).astype(np.float32), (0, 0), sigma) * sigma / 2
    for _ in range(120):
        x0, y0 = rng.uniform(cx - radius, cx + radius), rng.uniform(cy - radius, cy + radius)
        cr = rng.uniform(2, 14)
        d = np.sqrt((xx - x0) ** 2 + (yy - y0) ** 2)
        albedo += 0.12 * np.exp(-((d - cr) ** 2) / 2.0) - 0.06 * (d < cr * 0.8)
    albedo = np.clip(albedo, 0.15, 1.0)

    # Mineral colour: per-channel tint relative to neutral highlands
    tint = np.ones((size, size, 3), dtype=np.float32)
    tint[blue_mare] = (0.96, 1.0, 1.04)
    tint[orange_mare] = (1.04, 1.0, 0.96)
    tint = cv2.GaussianBlur(tint, (0, 0), 4)

    # Full-moon illumination with mild limb darkening; warm overall cast (lunar regolith + atmosphere)
    mu = np.sqrt(np.clip(1 - (r / radius) ** 2, 0, 1))
    shading = 0.6 + 0.4 * mu
    cast = np.array([1.08, 1.0, 0.88], dtype=np.float32)
    img = albedo[..., None] * shading[..., None] * tint * cast * disk[..., None] * 0.8

    # Atmospheric dispersion: red and blue displaced vertically against green
    dispersion = (-0.8, 1.1)
    for channel, dy in ((0, dispersion[0]), (2, dispersion[1])):
        shift = np.float32([[1, 0, 0], [0, 1, dy]])
        img[..., channel] = cv2.warpAffine(img[..., channel], shift, (size, size), flags=cv2.INTER_CUBIC)

    img = cv2.GaussianBlur(img, (0, 0), 1.2)  # seeing
    img += 0.01  # sky glow
    img += rng.normal(0, 1, img.shape).astype(np.float32) * (0.002 + 0.006 * np.sqrt(np.clip(img, 0, None)))

    return {
        "linear": np.clip(img, 0, 1).astype(np.float32),
        "disk": disk,
        "blue_mare": blue_mare,
        "orange_mare": orange_mare,
        "dispersion": dispersion,
    }


def linear_to_srgb(img: np.ndarray) -> np.ndarray:
    """sRGB transfer curve: what a camera/phone applies when saving a JPEG."""
    img = np.clip(img, 0, 1)
    return np.where(img <= 0.0031308, 12.92 * img, 1.055 * np.power(img, 1 / 2.4) - 0.055).astype(np.float32)


def mosaic_grbg(rgb: np.ndarray) -> np.ndarray:
    """Raw colour-sensor frame: keep one channel per pixel in the GRBG pattern (Seestar)."""
    raw = np.empty(rgb.shape[:2], dtype=rgb.dtype)
    raw[0::2, 0::2] = rgb[0::2, 0::2, 1]
    raw[0::2, 1::2] = rgb[0::2, 1::2, 0]
    raw[1::2, 0::2] = rgb[1::2, 0::2, 2]
    raw[1::2, 1::2] = rgb[1::2, 1::2, 1]
    return raw


def make_moon_video(
    path: str,
    frames: int = 40,
    raw: bool = False,
    rotation_deg: float = 0.0,
    bad_frames: int = 0,
    frame_size: tuple = (420, 360),
    seed: int = 3,
) -> np.ndarray:
    """
    Short Moon video like a Seestar capture, written losslessly (PNG-in-AVI).

    Each frame is the same scene (the synthetic moon) jittered by a few pixels,
    rotated by `rotation_deg` (field rotation), blurred by varying seeing, scaled to a
    dim 8-bit exposure and given noise. With `raw`, frames are GRBG mosaics stored as
    grey, like the Seestar's RAW .avi. The first `bad_frames` frames are unusable
    (half cloud-dimmed, half with the moon pushed off the frame edge).

    `seed` varies the jitter, seeing and noise; the scene is always the same moon.

    Returns the scene (linear float32 RGB, 0-1, 280 x 280) for comparison.
    """
    import cv2

    rng = np.random.default_rng(seed)
    scene = make_synthetic_moon(size=280, seed=7)["linear"]
    height, width = frame_size
    centre = np.array([width / 2, height / 2])
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"png "), 10, (width, height))
    for i in range(frames):
        shift = rng.uniform(-6, 6, 2)
        level = 70.0
        if i < bad_frames:
            if i % 2:
                shift = np.array([width * 0.45, 0.0])  # moon cut off at the edge
            else:
                level *= 0.4  # cloud
        rotate = cv2.getRotationMatrix2D((140, 140), rotation_deg, 1.0)
        rotate[:, 2] += centre + shift - 140
        frame = cv2.warpAffine(scene, rotate, (width, height), flags=cv2.INTER_CUBIC)
        frame = cv2.GaussianBlur(frame, (0, 0), rng.uniform(0.6, 1.8))
        frame = frame * level + rng.normal(0, 2.0, frame.shape)
        frame = np.clip(np.round(frame), 0, 255).astype(np.uint8)
        if raw:
            grey = mosaic_grbg(frame)
            writer.write(cv2.merge([grey, grey, grey]))
        else:
            writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    writer.release()
    return scene
