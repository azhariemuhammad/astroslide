"""
Objective quality metrics for Mineral Moon output against synthetic ground truth.
Used by the unit tests and handy for comparing implementations.
"""

import cv2
import numpy as np


def srgb_to_linear(img: np.ndarray) -> np.ndarray:
    img = np.clip(img, 0, 1)
    return np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)


def chroma(rgb_linear: np.ndarray) -> np.ndarray:
    """Per-pixel colour as deviation from neutral: rgb / mean(rgb) - 1 (zero for grey)."""
    lum = rgb_linear.mean(axis=2, keepdims=True)
    return rgb_linear / np.maximum(lum, 1e-4) - 1


def mineral_metrics(output_u8: np.ndarray, truth: dict) -> dict:
    """
    output_u8: processed display image (sRGB, uint8). truth: dict from make_synthetic_moon.

    blue_minus_red_*: (B - R) chroma averaged over each mare; blue mare should be > 0, orange < 0
    separation: blue mare minus orange mare along the B-R axis (bigger = colours more visible)
    limb_fringe: R/B colour difference across the limb (top vs bottom edge) relative to
                 separation; atmospheric dispersion shows up here as coloured rims
    chroma_noise: fine-scale colour noise inside the disk, relative to separation
    sky_level, sky_chroma: brightness and colour of the background (should be ~0)
    """
    lin = srgb_to_linear(output_u8.astype(np.float32) / 255.0)
    c = chroma(lin)
    b_minus_r = c[..., 2] - c[..., 0]

    disk = truth["disk"]
    interior = cv2.erode(disk.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    blue_val = float(b_minus_r[truth["blue_mare"] & interior].mean())
    orange_val = float(b_minus_r[truth["orange_mare"] & interior].mean())
    separation = blue_val - orange_val

    # Dispersion is vertical, so it colours the top and bottom limb in opposite directions
    h = disk.shape[0]
    rim = disk & ~cv2.erode(disk.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    top, bottom = rim.copy(), rim.copy()
    top[h // 2:] = False
    bottom[: h // 2] = False
    limb_fringe = abs(float(b_minus_r[top].mean() - b_minus_r[bottom].mean()))

    fine = b_minus_r - cv2.GaussianBlur(b_minus_r.astype(np.float32), (0, 0), 3)
    chroma_noise = float(fine[interior].std())

    sky = ~cv2.dilate(disk.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    sky_rgb = lin[sky]

    scale = max(abs(separation), 1e-6)
    return {
        "blue_minus_red_blue_mare": blue_val,
        "blue_minus_red_orange_mare": orange_val,
        "separation": separation,
        "limb_fringe": limb_fringe / scale,
        "chroma_noise": chroma_noise / scale,
        "sky_level": float(sky_rgb.mean()),
        "sky_chroma": float(np.abs(sky_rgb - sky_rgb.mean(axis=1, keepdims=True)).mean()),
    }
