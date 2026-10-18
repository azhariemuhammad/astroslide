"""
Mineral Moon checked against a synthetic moon with known mineral colours
(see synthetic.make_synthetic_moon and mineral_metrics for what is measured).
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app
from mineral_metrics import mineral_metrics, srgb_to_linear
from presets import align_color_channels, find_moon_mask, mineral_moon
from synthetic import linear_to_srgb, make_synthetic_moon, to_fits_bytes


@pytest.fixture(scope="module")
def moon() -> dict:
    return make_synthetic_moon(size=500)


@pytest.fixture(scope="module")
def moon_jpeg(moon) -> np.ndarray:
    return (linear_to_srgb(moon["linear"]) * 255 + 0.5).astype(np.uint8)


def test_dispersion_is_measured_and_corrected(moon):
    lin = moon["linear"]
    _, (red_shift, blue_shift) = align_color_channels(lin, find_moon_mask(lin.mean(axis=2)))
    dy_red, dy_blue = moon["dispersion"]
    # The correction moves each channel back by the dispersion that displaced it
    assert red_shift[1] == pytest.approx(-dy_red, abs=0.15)
    assert blue_shift[1] == pytest.approx(-dy_blue, abs=0.15)
    assert abs(red_shift[0]) < 0.15 and abs(blue_shift[0]) < 0.15


@pytest.mark.parametrize("source", ["jpeg", "linear"])
def test_mineral_colours_land_in_the_right_maria(moon, moon_jpeg, source):
    out = mineral_moon(moon_jpeg, 0.75, True) if source == "jpeg" else mineral_moon(moon["linear"], 0.75, False)
    m = mineral_metrics(out, moon)
    assert m["blue_minus_red_blue_mare"] > 0.3     # titanium-rich mare reads blue
    assert m["blue_minus_red_orange_mare"] < -0.3  # iron-rich mare reads orange
    assert m["limb_fringe"] < 0.1                  # no dispersion rims
    assert m["chroma_noise"] < 0.05                # colour is smooth
    assert m["sky_level"] < 0.01 and m["sky_chroma"] < 0.005


def test_input_colour_cast_is_removed_before_boosting(moon, moon_jpeg):
    # The synthetic moon has a warm cast; without white balance both maria come out orange
    raw = mineral_metrics(moon_jpeg, moon)
    assert raw["blue_minus_red_blue_mare"] < 0  # the cast hides the blue mare in the input
    assert mineral_metrics(mineral_moon(moon_jpeg, 0.75, True), moon)["blue_minus_red_blue_mare"] > 0


def test_strength_controls_colour_amount(moon, moon_jpeg):
    separations = [mineral_metrics(mineral_moon(moon_jpeg, s, True), moon)["separation"] for s in (0.0, 0.4, 0.8)]
    assert separations[0] < separations[1] < separations[2]
    assert separations[0] < 0.3  # strength 0 is close to the true (subtle) colours


def test_brightness_is_preserved(moon, moon_jpeg):
    out = mineral_moon(moon_jpeg, 1.0, True)
    disk = moon["disk"]
    lum_in = srgb_to_linear(moon_jpeg / 255.0).mean(axis=2)[disk]
    lum_out = srgb_to_linear(out / 255.0).mean(axis=2)[disk]
    assert np.corrcoef(lum_in, lum_out)[0, 1] > 0.97


def test_clipped_highlights_stay_neutral(moon):
    overexposed = np.clip(moon["linear"] * 2.5, 0, 1)  # most of the disk clips
    out = mineral_moon(overexposed, 1.0, False)
    lin = srgb_to_linear(out / 255.0)
    clipped = (overexposed >= 0.99).any(axis=2)
    chroma = lin / np.maximum(lin.mean(axis=2, keepdims=True), 1e-4) - 1
    assert np.abs(chroma[clipped]).mean() < 0.03


def test_enhance_endpoint_mineral_moon_fits(moon):
    response = TestClient(app).post(
        "/api/enhance",
        files={"file": ("moon.fits", to_fits_bytes(moon["linear"], color=True), "application/fits")},
        data={"preset": "mineral_moon", "intensity": "0.6"},
    )
    assert response.status_code == 200, response.text


# --- Halo ---------------------------------------------------------------------

def _distance_from_disk(moon: dict) -> np.ndarray:
    import cv2
    return cv2.distanceTransform((~moon["disk"]).astype(np.uint8), cv2.DIST_L2, 5)


def test_halo_zero_changes_nothing(moon, moon_jpeg):
    assert np.array_equal(mineral_moon(moon_jpeg, 0.75, True, halo=0.0), mineral_moon(moon_jpeg, 0.75, True))


def test_halo_glows_outside_and_fades_with_distance(moon, moon_jpeg):
    lum = lambda img: srgb_to_linear(img / 255.0).mean(axis=2)
    base, glow = lum(mineral_moon(moon_jpeg, 0.75, True)), lum(mineral_moon(moon_jpeg, 0.75, True, halo=0.8))
    added = glow - base
    dist = _distance_from_disk(moon)

    near = added[(dist > 3) & (dist < 12)].mean()
    mid = added[(dist > 30) & (dist < 45)].mean()
    far = added[dist > 90].mean()
    assert near > mid > far >= 0       # bright near the limb, long faint tail
    assert near > 0.01                 # actually visible
    assert far < 0.25 * near


def test_halo_leaves_the_surface_alone(moon, moon_jpeg):
    import cv2
    inside = cv2.erode(moon["disk"].astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    plain, glow = mineral_moon(moon_jpeg, 0.75, True), mineral_moon(moon_jpeg, 0.75, True, halo=1.0)
    assert np.abs(plain.astype(int) - glow)[inside].max() <= 1


def test_halo_grows_with_strength_and_is_slightly_blue(moon, moon_jpeg):
    dist = _distance_from_disk(moon)
    ring = (dist > 3) & (dist < 25)
    brightness = []
    for amount in (0.0, 0.5, 1.0):
        out = srgb_to_linear(mineral_moon(moon_jpeg, 0.75, True, halo=amount) / 255.0)
        brightness.append(out[ring].mean())
    assert brightness[0] < brightness[1] < brightness[2]
    ring_rgb = srgb_to_linear(mineral_moon(moon_jpeg, 0.75, True, halo=1.0) / 255.0)[ring].mean(axis=0)
    assert ring_rgb[2] > ring_rgb[0]


def test_halo_works_on_linear_fits_data(moon):
    out = mineral_moon(moon["linear"], 0.75, False, halo=0.8)
    plain = mineral_moon(moon["linear"], 0.75, False)
    dist = _distance_from_disk(moon)
    assert out[(dist > 3) & (dist < 12)].mean() > plain[(dist > 3) & (dist < 12)].mean()


def test_enhance_endpoint_accepts_halo(moon):
    client = TestClient(app)
    files = {"file": ("moon.fits", to_fits_bytes(moon["linear"], color=True), "application/fits")}
    response = client.post("/api/enhance", files=files, data={"preset": "mineral_moon", "halo": "0.6"})
    assert response.status_code == 200, response.text


# --- HDR ----------------------------------------------------------------------

def _luminance(img: np.ndarray) -> np.ndarray:
    return srgb_to_linear(img / 255.0).mean(axis=2)


def _inner(moon: dict) -> np.ndarray:
    import cv2
    return cv2.erode(moon["disk"].astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)


def test_hdr_zero_changes_nothing(moon, moon_jpeg):
    assert np.array_equal(mineral_moon(moon_jpeg, 0.75, True, hdr=0.0), mineral_moon(moon_jpeg, 0.75, True))


def test_hdr_adds_fine_detail_and_keeps_brightness(moon, moon_jpeg):
    import cv2

    def fine_contrast(img):
        lum = _luminance(img)
        return (lum - cv2.GaussianBlur(lum, (0, 0), 3))[_inner(moon)].std() / lum[_inner(moon)].mean()

    plain, hdr = mineral_moon(moon_jpeg, 0.75, True), mineral_moon(moon_jpeg, 0.75, True, hdr=1.0)
    assert fine_contrast(hdr) > 1.3 * fine_contrast(plain)
    assert np.median(_luminance(hdr)[_inner(moon)]) == pytest.approx(np.median(_luminance(plain)[_inner(moon)]), rel=0.05)


def test_hdr_compresses_large_scale_lighting(moon):
    # Light fading from left to right (like a terminator): HDR should flatten it
    size = moon["linear"].shape[1]
    ramp = np.linspace(1.0, 0.25, size, dtype=np.float32)[None, :, None]
    lit = moon["linear"] * ramp
    left, right = np.zeros_like(moon["disk"]), np.zeros_like(moon["disk"])
    left[:, size // 3: size // 2] = True
    right[:, size // 2: 2 * size // 3] = True
    left, right = left & _inner(moon), right & _inner(moon)

    def imbalance(img):
        lum = _luminance(img)
        return np.median(lum[left]) / np.median(lum[right])

    plain = imbalance(mineral_moon(lit, 0.75, False))
    mapped = imbalance(mineral_moon(lit, 0.75, False, hdr=1.0))
    assert plain > 1.2
    assert 1.0 <= mapped < plain - 0.08


def test_hdr_leaves_mineral_colours_and_limb_alone(moon, moon_jpeg):
    plain = mineral_metrics(mineral_moon(moon_jpeg, 0.75, True), moon)
    hdr_img = mineral_moon(moon_jpeg, 0.75, True, hdr=1.0)
    hdr = mineral_metrics(hdr_img, moon)
    assert hdr["separation"] == pytest.approx(plain["separation"], rel=0.05)
    assert hdr["limb_fringe"] < 0.1 and hdr["chroma_noise"] < 0.05

    import cv2
    dist = cv2.distanceTransform(moon["disk"].astype(np.uint8), cv2.DIST_L2, 5)
    band = (dist > 3) & (dist < 12)

    def rim_ratio(img):
        lum = _luminance(img)
        return np.median(lum[band]) / np.median(lum[_inner(moon)])

    assert rim_ratio(hdr_img) > 0.93 * rim_ratio(mineral_moon(moon_jpeg, 0.75, True))  # no dark rim


def test_hdr_and_halo_combine(moon, moon_jpeg):
    both = mineral_moon(moon_jpeg, 0.75, True, halo=0.6, hdr=0.6)
    halo_only = mineral_moon(moon_jpeg, 0.75, True, halo=0.6)
    assert both.shape == moon_jpeg.shape and both.dtype == np.uint8
    outside = ~moon["disk"]
    # The glow is computed from the moon's light, which HDR keeps at the same brightness
    assert _luminance(both)[outside].mean() == pytest.approx(_luminance(halo_only)[outside].mean(), rel=0.15)


def test_enhance_endpoint_accepts_hdr(moon):
    files = {"file": ("moon.fits", to_fits_bytes(moon["linear"], color=True), "application/fits")}
    response = TestClient(app).post("/api/enhance", files=files, data={"preset": "mineral_moon", "halo": "0.4", "hdr": "0.5"})
    assert response.status_code == 200, response.text


# --- Sharpen & dither ---------------------------------------------------------

def _fine_contrast(img: np.ndarray, moon: dict) -> float:
    import cv2
    lum = _luminance(img)
    return float((lum - cv2.GaussianBlur(lum, (0, 0), 1.5))[_inner(moon)].std() / lum[_inner(moon)].mean())


def test_sharpen_controls_detail_and_color_controls_color_independently(moon, moon_jpeg):
    results = {(c, s): mineral_moon(moon_jpeg, c, True, sharpen=s) for c in (0.1, 0.9) for s in (0.0, 1.0)}

    # Sharpen changes detail, at any colour strength...
    for c in (0.1, 0.9):
        assert _fine_contrast(results[(c, 1.0)], moon) > 1.25 * _fine_contrast(results[(c, 0.0)], moon)
    # ...and colour strength leaves detail alone (this used to be coupled)
    for s in (0.0, 1.0):
        assert _fine_contrast(results[(0.1, s)], moon) == pytest.approx(_fine_contrast(results[(0.9, s)], moon), rel=0.05)
    # Colour changes colour, at any sharpness
    for s in (0.0, 1.0):
        weak = mineral_metrics(results[(0.1, s)], moon)["separation"]
        strong = mineral_metrics(results[(0.9, s)], moon)["separation"]
        assert strong > 3 * weak


def test_sharpen_does_not_amplify_noise_or_touch_colour(moon, moon_jpeg):
    plain, sharp = mineral_moon(moon_jpeg, 0.75, True, sharpen=0.0), mineral_moon(moon_jpeg, 0.75, True, sharpen=1.0)
    a, b = mineral_metrics(plain, moon), mineral_metrics(sharp, moon)
    assert b["separation"] == pytest.approx(a["separation"], rel=0.05)
    assert b["chroma_noise"] < 0.05
    assert b["limb_fringe"] < 0.1


def test_sharpen_leaves_no_rim_at_the_limb(moon, moon_jpeg):
    import cv2
    dist = cv2.distanceTransform(moon["disk"].astype(np.uint8), cv2.DIST_L2, 5)
    band = (dist > 3) & (dist < 12)

    def rim_ratio(img):
        lum = _luminance(img)
        return np.median(lum[band]) / np.median(lum[_inner(moon)])

    assert rim_ratio(mineral_moon(moon_jpeg, 0.75, True, sharpen=1.0)) == pytest.approx(
        rim_ratio(mineral_moon(moon_jpeg, 0.75, True, sharpen=0.0)), rel=0.07
    )


def test_sharpen_ignores_pure_noise():
    # A flat moon with only noise on it: the noise floor must not be boosted
    rng = np.random.default_rng(3)
    size = 300
    yy, xx = np.mgrid[0:size, 0:size]
    disk = (yy - size / 2) ** 2 + (xx - size / 2) ** 2 < (size * 0.4) ** 2
    flat = np.where(disk, 0.5, 0.01).astype(np.float32)[..., None].repeat(3, axis=2)
    noisy = np.clip(flat + rng.normal(0, 0.01, flat.shape).astype(np.float32), 0, 1)

    def noise_level(img):
        lum = _luminance(img)
        inner = (yy - size / 2) ** 2 + (xx - size / 2) ** 2 < (size * 0.3) ** 2
        return lum[inner].std()

    quiet = noise_level(mineral_moon(noisy, 0.5, False, sharpen=0.0))
    loud = noise_level(mineral_moon(noisy, 0.5, False, sharpen=1.0))
    assert loud < 1.6 * quiet


def test_glow_is_dithered_not_banded(moon, moon_jpeg):
    out = mineral_moon(moon_jpeg, 0.75, True, halo=1.0)
    dist = _distance_from_disk(moon)
    tail = (dist > 40) & (dist < 120)
    values = out[tail].astype(int)
    # Undithered, the faint tail is a few flat terraces; dithered, neighbouring pixels
    # at the same distance take different levels
    ring = (dist > 60) & (dist < 62)
    assert len(np.unique(out[ring][:, 1])) >= 2
    assert values.min() >= 0 and values.max() < 80
    # Pure black far from the moon stays pure black
    assert (out[dist > 330] == 0).all() or (out[dist > 330].max() <= 1)


# --- Silver look, palette, warmth, levels -------------------------------------

def _chroma(img: np.ndarray) -> np.ndarray:
    lin = srgb_to_linear(img / 255.0)
    return lin / np.maximum(lin.mean(axis=2, keepdims=True), 1e-4) - 1


def test_colour_that_only_follows_brightness_is_removed(moon):
    # Simulate a camera tone-curve mismatch: blue rises with brightness on its own
    lin = moon["linear"].copy()
    lum = lin.mean(axis=2)
    lin[..., 2] *= (1 + 0.15 * (lum / lum.max()))
    out = mineral_moon(lin, 0.75, False, protect_highlights=False)
    c = _chroma(out)
    inner = _inner(moon)
    bmr, lum_out = (c[..., 2] - c[..., 0])[inner], _luminance(out)[inner]
    assert abs(np.corrcoef(bmr, np.log(lum_out))[0, 1]) < 0.3
    raw = mineral_moon(lin, 0.75, False, detrend=False, protect_highlights=False)
    assert abs(np.corrcoef((_chroma(raw)[..., 2] - _chroma(raw)[..., 0])[inner], np.log(_luminance(raw)[inner]))[0, 1]) > 0.3


def test_bright_highlands_stay_silver(moon, moon_jpeg):
    out = mineral_moon(moon_jpeg, 1.0, True, warmth=0.0)
    c = np.sqrt((_chroma(out) ** 2).sum(axis=2))
    inner = _inner(moon)
    highlands = inner & ~moon["blue_mare"] & ~moon["orange_mare"]
    maria = inner & (moon["blue_mare"] | moon["orange_mare"])
    assert np.median(c[highlands]) < 0.5 * np.median(c[maria])


def test_palette_renders_warm_maria_as_rust_not_yellow(moon, moon_jpeg):
    out = mineral_moon(moon_jpeg, 1.0, True)
    c = _chroma(out)[moon["orange_mare"] & _inner(moon)].mean(axis=0)
    assert c[0] > 0 and c[2] < 0      # red up, blue down
    assert c[1] < (c[0] + c[2]) / 2   # green below the midpoint: rust, not orange-yellow
    b = _chroma(out)[moon["blue_mare"] & _inner(moon)].mean(axis=0)
    assert b[2] > 0 and b[0] < 0 and b[1] < (b[0] + b[2]) / 2  # slate blue, not cyan


def test_warmth_slider_direction(moon, moon_jpeg):
    def mean_b_minus_r(w):
        c = _chroma(mineral_moon(moon_jpeg, 0.75, True, warmth=w))[_inner(moon)]
        return float((c[:, 2] - c[:, 0]).mean())

    assert mean_b_minus_r(-0.5) > mean_b_minus_r(0.0) > mean_b_minus_r(0.5)


def test_levels_brighten_dim_jpeg_but_never_darken(moon, moon_jpeg):
    dim = (moon_jpeg.astype(np.float32) * 0.5).astype(np.uint8)
    bright_hi = np.percentile(_luminance(mineral_moon(dim, 0.5, True))[_inner(moon)], 99)
    assert bright_hi > 0.75   # dim input lifted so highlands read near white
    normal_hi = np.percentile(_luminance(mineral_moon(moon_jpeg, 0.5, True))[_inner(moon)], 99)
    assert normal_hi >= np.percentile(_luminance(moon_jpeg)[_inner(moon)], 99) * 0.95


def test_enhance_endpoint_accepts_warmth(moon):
    files = {"file": ("moon.fits", to_fits_bytes(moon["linear"], color=True), "application/fits")}
    response = TestClient(app).post("/api/enhance", files=files, data={"preset": "mineral_moon", "warmth": "-0.4"})
    assert response.status_code == 200, response.text


# --- Detail quality: colour edges and chromatic-aberration fringes --------------

def test_colour_stays_inside_maria(moon, moon_jpeg):
    from detail_metrics import colour_bleed
    assert colour_bleed(mineral_moon(moon_jpeg, 0.75, True, warmth=0.0), moon) < 0.07


def test_chromatic_aberration_on_bright_points_is_not_amplified(moon):
    import cv2
    from detail_metrics import bright_point_fringe

    # Add small bright craters with a lens-style fringe: warm core, blue ring
    rng = np.random.default_rng(11)
    lin = moon["linear"].copy()
    size = lin.shape[0]
    yy, xx = np.mgrid[0:size, 0:size]
    inner = _inner(moon)
    ys, xs = np.where(inner & ~moon["blue_mare"] & ~moon["orange_mare"])
    for i in rng.choice(len(ys), 60, replace=False):
        d = np.sqrt((yy - ys[i]) ** 2 + (xx - xs[i]) ** 2)
        core, ring = d < 1.6, (d >= 1.6) & (d < 4)
        lin[core] *= 1.8 * np.array([1.08, 1.0, 0.92], dtype=np.float32)
        lin[ring] *= np.array([0.96, 1.0, 1.04], dtype=np.float32)
    jpeg = (linear_to_srgb(np.clip(lin, 0, 1)) * 255 + 0.5).astype(np.uint8)

    fringe_in = bright_point_fringe(jpeg, jpeg, moon["disk"])
    fringe_out = bright_point_fringe(jpeg, mineral_moon(jpeg, 0.9, True, warmth=0.0), moon["disk"])
    input_fringe = abs(fringe_in["core"] - fringe_in["surroundings"])
    output_fringe = abs(fringe_out["core"] - fringe_out["surroundings"])
    # Without care, a ~10x colour gain would multiply the fringe ~10x
    assert output_fringe < 1.5 * input_fringe
