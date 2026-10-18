"""
Detail-level quality metrics for Mineral Moon (100%-crop defects).
"""

import cv2
import numpy as np

from mineral_metrics import srgb_to_linear


def _chroma_magnitude(img_u8: np.ndarray) -> np.ndarray:
    lin = srgb_to_linear(img_u8.astype(np.float32) / 255.0)
    c = lin / np.maximum(lin.mean(axis=2, keepdims=True), 1e-4) - 1
    return np.sqrt((c ** 2).sum(axis=2))


def colour_bleed(output_u8: np.ndarray, truth: dict) -> float:
    """
    Colour leaking from the maria into the neutral highlands: mean chroma in a band
    4-14 px outside each mare, relative to the chroma inside the maria. 0 = crisp edges.
    """
    maria = (truth["blue_mare"] | truth["orange_mare"]).astype(np.uint8)
    dist = cv2.distanceTransform(1 - maria, cv2.DIST_L2, 5)
    inner_disk = cv2.erode(truth["disk"].astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)
    band = (dist > 4) & (dist < 14) & inner_disk
    inside = cv2.erode(maria, np.ones((15, 15), np.uint8)).astype(bool)
    c = _chroma_magnitude(output_u8)
    return float(c[band].mean() / max(c[inside].mean(), 1e-6))


def bright_feature_bloat(input_u8: np.ndarray, output_u8: np.ndarray, mask: np.ndarray, percentile: float = 99.5) -> float:
    """
    How much small bright features (crater rims, ray spots) grow: mean area of bright blobs
    above the given luminance percentile, output vs input. 1 = same size.
    """
    def mean_blob_area(img):
        lum = srgb_to_linear(img.astype(np.float32) / 255.0).mean(axis=2)
        thr = np.percentile(lum[mask], percentile)
        blobs = ((lum > thr) & mask).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(blobs)
        areas = stats[1:, cv2.CC_STAT_AREA]
        areas = areas[areas < 200]  # small features only
        return float(areas.mean()) if len(areas) else 0.0, int(len(areas))

    a_in, n_in = mean_blob_area(input_u8)
    a_out, n_out = mean_blob_area(output_u8)
    return a_out / max(a_in, 1e-6)


def bright_point_fringe(input_u8: np.ndarray, output_u8: np.ndarray, mask: np.ndarray) -> dict:
    """
    Colour on small bright features (crater spots) vs their surroundings, measured in the
    output at the feature positions found in the input. Chromatic aberration shows up as a
    core/ring colour different from the surroundings; amplified, it makes peach dots.
    Returns B-R for core, ring (1-4 px) and surroundings (6-10 px).
    """
    lin_in = srgb_to_linear(input_u8.astype(np.float32) / 255.0)
    lum = lin_in.mean(axis=2)
    inner = cv2.erode(mask.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)
    local = cv2.GaussianBlur(lum, (0, 0), 4)
    peak = inner & (lum > 1.35 * local) & (lum > np.percentile(lum[inner], 70))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(peak.astype(np.uint8))
    keep = np.where((stats[:, cv2.CC_STAT_AREA] >= 2) & (stats[:, cv2.CC_STAT_AREA] <= 40))[0]
    small = np.isin(labels, keep[keep > 0])
    dist = cv2.distanceTransform((~small).astype(np.uint8), cv2.DIST_L2, 5)

    lin = srgb_to_linear(output_u8.astype(np.float32) / 255.0)
    c = lin / np.maximum(lin.mean(axis=2, keepdims=True), 1e-4) - 1
    bmr = c[..., 2] - c[..., 0]
    return {
        "core": float(bmr[small].mean()),
        "ring": float(bmr[inner & (dist >= 1) & (dist < 4)].mean()),
        "surroundings": float(bmr[inner & (dist >= 6) & (dist < 10)].mean()),
    }
