"""
Moon-on-stars composites: the Moon's layers (full disk found from the sunlit limb, sky
taken out) and the star field's preparation (gradient and colour cast removed).
"""

import base64
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import composite
from main import app, decode_image_float
from presets import enhance_with_preset, float_to_uint8
from synthetic import linear_to_srgb, make_synthetic_moon

SIZE = 400


def _decode(data_url: str) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(data_url.split(",", 1)[1]), np.uint8)
    return cv2.cvtColor(cv2.imdecode(raw, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255


def _crescent(sky: float = 0.08, earthshine: float = 0.02, phase: float = 0.6) -> tuple[np.ndarray, float, float, float]:
    """A display-referred crescent on a grey sky; returns (image, cx, cy, r) of the full disk."""
    moon = make_synthetic_moon(SIZE, seed=2)
    yy, xx = np.mgrid[:SIZE, :SIZE]
    cx = cy = SIZE / 2
    r = SIZE * 0.41
    # The Sun from the right: the lit part is the disk minus a circle shifted left by phase * r
    lit = moon["disk"] & (np.hypot(xx - cx + phase * r, yy - cy) > r)
    image = moon["linear"] * lit[..., None] + earthshine * moon["disk"][..., None]
    image = linear_to_srgb(image) * (1 - sky) + sky
    # Continuous coordinates: pixel i's centre is at i + 0.5
    return image.astype(np.float32), cx + 0.5, cy + 0.5, r


def test_full_disk_is_found_from_the_sunlit_limb_of_a_crescent():
    image, cx, cy, r = _crescent()
    found = composite.find_disk(image.mean(axis=2))
    assert found is not None
    fx, fy, fr, lit = found
    # The lit crescent alone would give a much smaller, off-centre circle
    assert abs(fx - cx) < 2 and abs(fy - cy) < 2
    # The seeing-blurred limb puts the edge a pixel or two out, on the side of covering stars
    assert abs(fr - r) < 3


CRESCENT_SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "Video_Stacked_Lunar_20260519-220945.fit"


@pytest.mark.skipif(not CRESCENT_SAMPLE.exists(), reason="sample not available")
def test_thin_crescent_is_not_fitted_to_its_terminator():
    # On this processed crescent the terminator is as sharp and bright as the limb; fitted
    # to both, the circle came out too large and cut through the lit limb. Only the limb
    # is on the lit area's convex hull. The preset's halo must not widen it either
    contents = CRESCENT_SAMPLE.read_bytes()
    linear = decode_image_float(contents, CRESCENT_SAMPLE.name)
    image = enhance_with_preset(float_to_uint8(linear), "mineral_moon", 0.75, {}, linear, False,
                                0.2, 0.25, 0.3, -0.25, 0.4, 8, {}).astype(np.float32) / 255
    luminance = image.mean(axis=2)
    cx, cy, r, _ = composite.find_disk(luminance)
    # Clearly lit surface (not the halo the preset adds) all inside, and right up to the edge
    ys, xs = np.nonzero(luminance > 0.5 * np.percentile(luminance, 99.9))
    dist = np.hypot(xs + 0.5 - cx, ys + 0.5 - cy)
    assert r - 3 < np.percentile(dist, 99.9) < r + 2


def test_halo_around_a_processed_moon_does_not_widen_the_disk():
    # The Mineral Moon Halo lifts the sky beside the limb above the Moon mask's threshold;
    # the disk must still end at the limb, or it hides the stars beside it
    image, cx, cy, r = _crescent(sky=0.0)
    luminance = image.mean(axis=2)
    yy, xx = np.mgrid[:SIZE, :SIZE] + 0.5
    beyond = np.hypot(xx - cx, yy - cy) - r
    # Light scattered from the lit surface, as Mineral Moon's Halo adds it
    lit = (luminance > 0.4).astype(np.float32) * luminance
    halo = 0.6 * (cv2.GaussianBlur(lit, (0, 0), 6) + cv2.GaussianBlur(lit, (0, 0), 20)) * (beyond > 0)
    _, _, fr, _ = composite.find_disk(np.clip(luminance + halo, 0, 1).astype(np.float32))
    assert abs(fr - r) < 2


def test_moon_layer_covers_the_dark_side_and_drops_the_sky():
    image, cx, cy, r = _crescent()
    layers = composite.moon_layers(image)
    moon = _decode(layers["moon"])
    side = layers["moon_size"]
    assert moon.shape[:2] == (side, side)
    assert abs(layers["radius"] - r) < 3

    centre = side / 2
    yy, xx = np.mgrid[:side, :side] + 0.5
    dist = np.hypot(xx - centre, yy - centre)
    # Outside the disk: nothing (the star field shows there)
    assert moon[dist > layers["radius"] + 2].max() < 2 / 255
    # The sky level (0.08) is gone from the dark side: only the earthshine is left
    dark_side = (dist < 0.8 * layers["radius"]) & (xx < centre - 0.3 * layers["radius"])
    earthshine = float(linear_to_srgb(np.float32(0.02))) * (1 - 0.08)
    assert abs(float(np.median(moon[dark_side])) - earthshine) < 0.01
    # The lit surface is kept
    lit = (dist < 0.9 * layers["radius"]) & (xx > centre + 0.6 * layers["radius"])
    assert float(np.median(moon[lit])) > 0.3


def _gibbous() -> np.ndarray:
    """Waxing gibbous lit from the right, display-referred."""
    moon = make_synthetic_moon(SIZE, seed=2)
    yy, xx = np.mgrid[:SIZE, :SIZE]
    x, y = (xx - SIZE / 2) / (SIZE * 0.41), (yy - SIZE / 2) / (SIZE * 0.41)
    lit = moon["disk"] & (x > -0.6 * np.sqrt(np.clip(1 - y ** 2, 0, 1)))
    return linear_to_srgb(moon["linear"] * lit[..., None] + 0.004 * moon["disk"][..., None]).astype(np.float32)


def _glows(layers: dict) -> tuple[list, int, float]:
    """Glow layers as grey images narrow to wide, their centre index, the Moon radius in their pixels."""
    glows = [_decode(g).mean(axis=2) for g in layers["glows"]]
    side = glows[0].shape[0]
    return glows, side // 2, side / 2 / layers["glow_reach"]


def test_glow_is_off_the_lit_surface_and_brightest_beside_the_lit_limb():
    image, _, _, _ = _crescent()
    glows, mid, radius = _glows(composite.moon_layers(image))
    for glow in glows:
        assert glow[mid, int(mid + 0.7 * radius)] < 3 / 255  # on the lit crescent
        # Brightest right at the limb, not a few pixels out (no dark band beside it)
        right_at_limb = glow[mid, int(np.ceil(mid + radius))]
        assert right_at_limb >= 0.7 * glow[mid, int(mid + radius) + 1:int(mid + 1.3 * radius)].max()
        beside_lit = glow[mid, int(np.ceil(mid + radius)):int(mid + 1.3 * radius)].mean()
        beside_dark = glow[mid, int(mid - 1.3 * radius):int(mid - radius)].mean()
        assert beside_lit > 2 * beside_dark


def test_glow_sizes_spread_further_but_are_as_bright_at_the_limb():
    # Like brush sizes: the browser mixes them, and the limb shouldn't change brightness
    glows, mid, radius = _glows(composite.moon_layers(_gibbous()))
    limb = int(np.ceil(mid + radius))
    at_limb = [glow[mid, limb - 1:limb + 2].max() for glow in glows]
    assert max(at_limb) / min(at_limb) < 1.3
    further = [glow[mid, int(mid + 1.6 * radius)] for glow in glows]
    assert all(a <= b for a, b in zip(further, further[1:])) and further[1] < further[2] < further[3], further


def test_gibbous_glows_on_its_bright_side_only():
    # The glow is the lit side's scattered light, so it hugs the bright limb; the dark side
    # and the sky beside it stay dark. The default mix is of the narrow sizes; the widest
    # reach round the dark side by nature, which is the user's call
    glows, mid, radius = _glows(composite.moon_layers(_gibbous()))
    for glow in glows:
        assert glow[mid, int(mid - 0.8 * radius)] < 3 / 255  # over the dark side
    assert glows[1][mid, int(mid + 1.1 * radius)] > 0.04
    for glow in glows[:2]:
        for d in (1.1, 1.3):
            bright, dark = glow[mid, int(mid + d * radius)], glow[mid, int(mid - d * radius)]
            assert bright >= 5 * dark, (d, bright, dark)  # the narrowest is gone by 1.3 r on both


def test_glow_has_the_moons_colour():
    # Scattered moonlight is the Moon's colour: a neutral Moon gets a white glow, not a blue one
    image, _, _, _ = _crescent(sky=0.0)
    grey = np.repeat(image.mean(axis=2, keepdims=True), 3, axis=2)
    for data_url in composite.moon_layers(grey)["glows"]:
        glow = _decode(data_url)
        near = glow.mean(axis=2) > 0.2
        r, g, b = glow[near].mean(axis=0)
        assert max(r, g, b) / min(r, g, b) < 1.03


def test_image_without_a_moon_is_refused():
    with pytest.raises(ValueError):
        composite.moon_layers(np.full((200, 300, 3), 0.1, np.float32))


def _star_photo(seed: int = 1) -> tuple[np.ndarray, list]:
    """A grey, light-polluted star field: warm cast, brighter towards one corner."""
    rng = np.random.default_rng(seed)
    h, w = 360, 540
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    gradient = 0.18 + 0.2 * (xx / w + yy / h) / 2
    image = gradient[..., None] * np.array([1.15, 1.0, 0.8], np.float32)
    stars = []
    for _ in range(60):
        x, y = rng.uniform(10, w - 10), rng.uniform(10, h - 10)
        image += 0.7 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.2 ** 2))[..., None]
        stars.append((int(round(y)), int(round(x))))
    image += rng.normal(0, 0.01, image.shape).astype(np.float32)
    return np.clip(image, 0, 1).astype(np.float32), stars


def test_star_field_sky_is_flattened_neutralised_and_set_to_the_known_level():
    photo, stars = _star_photo()
    prepared = composite.star_field(photo, linear=False)
    star_free = np.ones(photo.shape[:2], bool)
    for y, x in stars:
        star_free[max(0, y - 6):y + 7, max(0, x - 6):x + 7] = False
    # Sky in each corner, per channel: flat and grey at STAR_SKY
    h, w = photo.shape[:2]
    for ys, xs in ((slice(0, h // 4), slice(0, w // 4)), (slice(-h // 4, None), slice(-w // 4, None))):
        region = prepared[ys, xs][star_free[ys, xs]]
        level = np.median(region, axis=0)
        assert np.all(np.abs(level - composite.STAR_SKY) < 0.02), level
    # Stars keep their brightness above the sky
    peaks = [prepared[y, x].mean() - composite.STAR_SKY for y, x in stars]
    assert np.median(peaks) > 0.4


def test_linear_star_field_is_stretched_first():
    photo, _ = _star_photo()
    linear = (photo ** 2.2 * 0.05).astype(np.float32)  # a dim, unstretched sub
    prepared = composite.star_field(linear, linear=True)
    assert abs(float(np.median(prepared)) - composite.STAR_SKY) < 0.03
    assert prepared.max() > 0.5


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray((np.clip(image, 0, 1) * 255 + 0.5).astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_composite_endpoints(client):
    image, _, _, _ = _crescent()
    response = client.post("/api/moon-layers", files={"file": ("moon.png", _png(image), "image/png")})
    assert response.status_code == 200
    assert response.json()["moon"].startswith("data:image/png;base64,")

    blank = np.full((100, 100, 3), 0.1, np.float32)
    response = client.post("/api/moon-layers", files={"file": ("sky.png", _png(blank), "image/png")})
    assert response.status_code == 400
    assert "Moon" in response.json()["detail"]

    photo, _ = _star_photo()
    response = client.post("/api/star-field", files={"file": ("stars.png", _png(photo), "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert (body["width"], body["height"]) == (540, 360)
    assert body["sky"] == composite.STAR_SKY
