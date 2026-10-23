"""
Moon-on-stars composites: the Moon cut out of its photo, ready to place on a star field.

The browser does the placing (it has to follow a drag at screen rate), so the server
only hands over two layers, both meant to be *added* to the star field:

- moon: the full disk with the sky subtracted and everything outside the disk black.
  The disk is the circle through the sunlit limb, not just the lit surface, so on a
  crescent the dark side covers the stars behind it too (stars showing through the
  unlit part are the classic tell of a pasted Moon). The browser first paints the disk
  in the star field's own sky colour, then adds this layer: the sky in front of the Moon
  stays, the stars behind it go.
- glows: moonlight scattered by the air and optics, from the lit surface only (as
  presets.moon_halo), outside the disk, at low resolution since it is smooth. One layer
  per width in GLOW_WIDTHS, each as bright at the limb as the others: the browser mixes
  them for its Glow size control, like picking a brush size.
"""

import base64
from typing import Optional

import cv2
import numpy as np

from presets import compute_auto_stf, find_moon_mask, mtf_stretch_float, srgb_to_linear
from stacking import _fit_circle, _limb_circle

# Sky level of the prepared star field. The browser's Sky darkness control sets the final
# black point; this leaves it room both ways and keeps the faintest stars above the noise
STAR_SKY = 0.12
# Long side of the image the sky background is modelled on
SKY_MODEL_SIZE = 128
# Degree of the polynomial surface fitted to the sky: follows light-pollution and
# moonlight gradients, too stiff to follow nebulae
SKY_MODEL_DEGREE = 3

# The glow layer reaches this many Moon radii from the centre
GLOW_REACH = 3.5
# Long side of the glow layer in pixels; it is upscaled smoothly when drawn
GLOW_SIZE = 384
# Linear brightness of the glow at its brightest, beside the limb, at full Glow
GLOW_PEAK = 0.65
# Encoding of the glow layer, which is added to display values. Gentler than the sRGB
# curve: that lifted the faint glow beside the dark limb until the Moon seemed to glow
# all round, when the glow is the lit side's light and should hug the lit side
GLOW_GAMMA = 1.4
# Glow widths, narrow to wide: blur sigma as a fraction of the diameter. The wide ones
# reach round the dark side of a gibbous Moon (a ring), so the default mix is narrow
GLOW_WIDTHS = (0.02, 0.06, 0.15, 0.35)


def _png_data_url(rgb: np.ndarray) -> str:
    """0-1 float RGB -> 8-bit PNG data URL."""
    pixels = np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("PNG encoding failed")
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _crop_around(image: np.ndarray, cx: float, cy: float, side: int, scale: float = 1.0) -> np.ndarray:
    """
    A side x side square whose centre (side / 2 in continuous coordinates) is (cx, cy) in
    `image`, shrunk by `scale` (image pixels per output pixel); black beyond the image.
    """
    # Pixel i covers [i, i + 1]: output pixel i (centre i + 0.5) samples the image at
    # cx + (i + 0.5 - side / 2) * scale, i.e. at index cx - 0.5 + (i + 0.5 - side / 2) * scale
    shift = 0.5 - side / 2
    transform = np.array([[scale, 0, cx - 0.5 + shift * scale],
                          [0, scale, cy - 0.5 + shift * scale]], np.float32)
    interpolation = cv2.INTER_AREA if scale > 1 else cv2.INTER_LINEAR
    return cv2.warpAffine(image, transform, (side, side), flags=interpolation | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def find_disk(luminance: np.ndarray) -> Optional[tuple[float, float, float, np.ndarray]]:
    """(cx, cy, r, lit mask) of the full disk, in continuous pixel coordinates; None without a Moon."""
    mask = find_moon_mask(luminance)
    if mask.sum() < 200 or mask.mean() > 0.6:
        return None
    # A Moon is far brighter than its sky (a flat or cloudy frame passes the mask anyway)
    if np.median(luminance[mask]) < 2 * np.median(luminance[~mask]) + 0.02:
        return None
    circle = _limb_circle(luminance, mask, hull_only=True)
    # Equivalent circle of the lit area: right for a full Moon, too small for a crescent
    ys, xs = np.nonzero(mask)
    equivalent = (float(xs.mean()), float(ys.mean()), float(np.sqrt(mask.sum() / np.pi)))
    if circle is None or not equivalent[2] * 0.9 <= circle[2] <= 4 * equivalent[2]:
        circle = equivalent
    for _ in range(3):
        refined = _fit_circle(*_limb_points(luminance, mask, *circle))
        if refined is None or not 0.5 * circle[2] <= refined[2] <= 1.5 * circle[2]:
            break
        circle = refined
    cx, cy, r = circle
    return cx + 0.5, cy + 0.5, r, mask


def _limb_points(luminance: np.ndarray, mask: np.ndarray, cx: float, cy: float, r: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Where the sunlit limb actually is, as (xs, ys): the steepest drop across the limb in
    each direction around (cx, cy), in the directions where the limb is bright. The mask
    a first circle is fitted to reaches out into any glow (a processed Moon's halo put it
    11 px beyond the limb, and the disk drawn there hid the stars beside it); a glow falls
    off far more gently than the limb, so it can't have the steepest drop.
    """
    margin = max(8.0, 0.12 * r)
    reach = r + margin
    samples = int(reach * 2)  # half-pixel steps
    polar = cv2.warpPolar(luminance, (samples, 720), (cx, cy), reach, cv2.WARP_POLAR_LINEAR)
    radii = np.arange(samples) * reach / samples
    window = np.nonzero(np.abs(radii - r) < margin)[0]
    profiles = cv2.GaussianBlur(polar[:, window], (0, 0), 1.0)
    drop = profiles[:, :-4] - profiles[:, 4:]  # over 2 px
    edge = np.argmax(drop, axis=1)
    rows = np.arange(len(edge))
    surface = profiles[rows, np.maximum(edge - 2, 0)]
    bright = float(np.percentile(luminance[mask], 90))
    lit_limb = (surface > 0.5 * bright) & (drop[rows, edge] > 0.25 * surface)
    radius = radii[window][edge + 2][lit_limb]
    angle = rows[lit_limb] * 2 * np.pi / len(rows)
    return cx + radius * np.cos(angle), cy + radius * np.sin(angle)


def moon_layers(image: np.ndarray) -> dict:
    """
    The Moon and its glow as layers to add onto a star field (see the module docstring).

    Args:
        image: display-referred RGB (H, W, 3), 0-1, such as an enhanced Moon photo

    Returns:
        "moon": PNG data URL; "glows": PNG data URLs, one per GLOW_WIDTHS; "moon_size":
        side of the moon layer in pixels, centred on the disk; "radius": disk radius in
        those pixels; "glow_reach": the glow layers span the centre +- glow_reach * radius

    Raises:
        ValueError: no Moon in the image
    """
    luminance = image.mean(axis=2).astype(np.float32)
    disk = find_disk(luminance)
    if disk is None:
        raise ValueError("Couldn't find the Moon in this image")
    cx, cy, r, lit = disk

    ys, xs = np.mgrid[:image.shape[0], :image.shape[1]]
    dist = np.hypot(xs + 0.5 - cx, ys + 0.5 - cy)
    sky_pixels = dist > 1.3 * r
    sky = (np.median(image[sky_pixels], axis=0) if sky_pixels.sum() > 1000
           else np.percentile(image.reshape(-1, 3), 1, axis=0))
    # Antialiased edge, from half a pixel inside the limb to 1.5 px out (the limb's own blur)
    alpha = np.clip((r + 1.5 - dist) / 2, 0, 1).astype(np.float32)
    moon = np.clip(image - sky, 0, 1) * alpha[..., None]

    side = 2 * int(np.ceil(r + 2))
    moon_layer = _crop_around(moon.astype(np.float32), cx, cy, side)

    # Glow from the lit surface only, in linear light, in the Moon's own colour (white for
    # a white Moon: a blue sky-scatter tint read as a cold, grey haze around it)
    reach = GLOW_REACH * r
    scale = max(1.0, 2 * reach / GLOW_SIZE)
    glow_side = max(8, int(round(2 * reach / scale)))
    # The mask reaches into any halo the photo already has; only the surface casts the glow
    lit_soft = cv2.GaussianBlur((lit & (dist <= r)).astype(np.float32), (0, 0), 2)
    source = _crop_around(srgb_to_linear(moon) * lit_soft[..., None], cx, cy, glow_side, scale)
    # Kept off the whole disk, so the dark side stays dark (a grey haze over it made the glow
    # look like a ring all round). Full strength from half a glow pixel inside the limb: it
    # is upscaled when drawn, and starting at the limb would leave a dark band beside it
    small_dist = np.hypot(*np.mgrid[:glow_side, :glow_side] + 0.5 - glow_side / 2) * scale
    outside = np.clip((small_dist - r) / scale + 0.5, 0, 1)[..., None]
    # Dither: the faint outer glow spans only a few 8-bit levels, which would show as rings
    dither = np.random.default_rng(0).uniform(-0.5, 0.5, source.shape).astype(np.float32) / 255
    glows = []
    for width in GLOW_WIDTHS:
        glow = cv2.GaussianBlur(source, (0, 0), max(0.7, width * 2 * r / scale)) * outside
        peak = float(glow.max())
        if peak > 0:
            glow = (GLOW_PEAK * glow / peak) ** (1 / GLOW_GAMMA)
        glows.append(_png_data_url(glow + dither))

    return {
        "moon": _png_data_url(moon_layer),
        "glows": glows,
        "moon_size": side,
        "radius": r,
        "glow_reach": GLOW_REACH,
    }


def _sky_surface(small: np.ndarray) -> np.ndarray:
    """Polynomial surface (SKY_MODEL_DEGREE) fitted to each channel's sky, clipping what stands above it."""
    h, w = small.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    u, v = (xx / max(w - 1, 1) * 2 - 1).ravel(), (yy / max(h - 1, 1) * 2 - 1).ravel()
    terms = np.column_stack([u ** i * v ** j for i in range(SKY_MODEL_DEGREE + 1)
                             for j in range(SKY_MODEL_DEGREE + 1 - i)])
    surface = np.empty_like(small)
    for c in range(small.shape[2]):
        values = small[..., c].ravel().astype(np.float64)
        keep = np.ones(len(values), bool)
        for _ in range(5):
            coefficients, *_ = np.linalg.lstsq(terms[keep], values[keep], rcond=None)
            residual = values - terms @ coefficients
            spread = 1.4826 * np.median(np.abs(residual[keep] - np.median(residual[keep]))) + 1e-4
            keep = (residual < 2.5 * spread) & (residual > -4 * spread)
        surface[..., c] = (terms @ coefficients).reshape(h, w)
    return surface


def star_field(image: np.ndarray, linear: bool) -> np.ndarray:
    """
    A star photo prepared as the backdrop of a composite: stretched if linear, with the
    sky's gradient and colour cast removed and the sky put at STAR_SKY, neutral grey.

    Seestar star fields are rarely dark: light pollution, moonlight (the Moon is up, after
    all) and the in-camera stretch leave a grey or tinted sky, often brighter on one side,
    which looks wrong next to a Moon cut out of a black sky. The background is modelled
    at low resolution with the stars filtered out (median) as a smooth polynomial surface
    per channel, fitted with sigma clipping so stars and nebulae don't pull it up, and
    subtracted. Large, faint nebulosity can be dimmed with it.
    at low resolution with the stars filtered out (median), blurred to a smooth surface,
    and subtracted per channel. Smooth nebulosity larger than about a sixth of the frame
    goes with it; anything smaller stays.

    Args:
        image: RGB (H, W, 3), 0-1
        linear: unstretched data (FITS): auto-stretched first

    Returns:
        RGB (H, W, 3), 0-1, sky at STAR_SKY
    """
    if linear:
        image = mtf_stretch_float(image, **compute_auto_stf(image))
    h, w = image.shape[:2]
    scale = SKY_MODEL_SIZE / max(h, w)
    small = cv2.resize(image, (max(8, int(w * scale)), max(8, int(h * scale))), interpolation=cv2.INTER_AREA)
    background = cv2.medianBlur(np.clip(small * 255, 0, 255).astype(np.uint8), 5).astype(np.float32) / 255
    background = cv2.resize(_sky_surface(background), (w, h), interpolation=cv2.INTER_CUBIC)
    return np.clip(image - background + STAR_SKY, 0, 1).astype(np.float32)
