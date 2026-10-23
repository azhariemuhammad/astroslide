"""
Fast unit tests for decoding and processing. Run from backend/: python -m pytest tests
For whole-pipeline visual checks, use tests/regression.py instead.
"""

import io

import astropy.io.fits as fits
import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from PIL import Image

from main import app, decode_image, decode_image_float
from presets import apply_interactive_stretch, apply_pro_adjustments, compute_auto_stf, remove_stars
from synthetic import make_linear_deep_sky, to_fits_bytes


@pytest.fixture(scope="module")
def linear_image() -> np.ndarray:
    return make_linear_deep_sky(height=200, width=300)


@pytest.fixture(scope="module")
def rgb_image(linear_image) -> np.ndarray:
    return (np.clip(linear_image * 8, 0, 1) * 255).astype(np.uint8)


def _fits_bytes(data: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    fits.PrimaryHDU(data).writeto(buffer)
    return buffer.getvalue()


# --- FITS decoding ---------------------------------------------------------

@pytest.mark.parametrize("color", [False, True])
def test_fits_decodes_to_channels_last_rgb(linear_image, color):
    img = decode_image(to_fits_bytes(linear_image, color=color), "stack.fits")
    assert img.shape == (200, 300, 3)
    assert img.dtype == np.uint8
    assert img.flags["C_CONTIGUOUS"]


def test_color_fits_keeps_channel_order(linear_image):
    img = decode_image(to_fits_bytes(linear_image, color=True), "stack.fits")
    means = img.reshape(-1, 3).mean(axis=0)
    # Synthetic stack has a green cast: green must stay the strongest channel
    assert means.argmax() == 1


def test_fits_nan_borders_are_zeroed():
    data = np.full((50, 60), 1000.0, dtype=np.float32)
    data[20:30, 20:30] = 5000.0
    data[:5, :] = np.nan
    img = decode_image(_fits_bytes(data), "stack.fit")
    assert img[:5].max() == 0
    assert img[25, 25].max() == 255


def test_fits_with_image_in_extension_hdu():
    hdul = fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.arange(1200, dtype=np.uint16).reshape(30, 40))])
    buffer = io.BytesIO()
    hdul.writeto(buffer)
    assert decode_image(buffer.getvalue(), "stack.fits").shape == (30, 40, 3)


@pytest.mark.parametrize("shape", [(5, 30, 40), (2, 3, 30, 40)])
def test_unsupported_fits_shape_is_rejected_not_crashed(shape):
    with pytest.raises(HTTPException) as exc:
        decode_image(_fits_bytes(np.ones(shape, dtype=np.uint16)), "cube.fits")
    assert exc.value.status_code == 400


def test_float_decode_keeps_faint_fits_detail():
    # Faint background a few counts above zero next to one bright star, like a real stack:
    # 8-bit min-max decoding collapses the background into a couple of levels
    rng = np.random.default_rng(0)
    data = (100 + rng.normal(0, 3, (100, 100))).astype(np.float32)
    data[50, 50] = 60000.0
    data = np.clip(data, 0, 65535).astype(np.uint16)

    eight_bit = decode_image(_fits_bytes(data), "stack.fits")
    full = decode_image_float(_fits_bytes(data), "stack.fits")
    assert full.dtype == np.float32 and full.shape == (100, 100, 3)
    assert 0.0 <= full.min() and full.max() <= 1.0
    assert len(np.unique(eight_bit[..., 0])) <= 3
    assert len(np.unique(full[..., 0])) > 15


def test_16bit_png_decodes_without_clipping():
    gradient = np.tile(np.linspace(0, 65535, 64), (8, 1)).astype(np.uint16)
    buffer = io.BytesIO()
    Image.fromarray(gradient).save(buffer, format="PNG")

    full = decode_image_float(buffer.getvalue(), "frame.png")
    assert full[0, 0, 0] == 0.0 and full[0, -1, 0] == pytest.approx(1.0)
    assert len(np.unique(full[..., 0])) == 64

    # PIL's convert('RGB') would clip everything above 255 to white
    eight_bit = decode_image(buffer.getvalue(), "frame.png")
    assert eight_bit[0, 32, 0] == pytest.approx(128, abs=2)


# --- Stretch & adjustments --------------------------------------------------

def test_mtf_with_neutral_midtones_is_identity(rgb_image):
    out = apply_interactive_stretch(rgb_image, shadows=0.0, midtones=0.5, highlights=1.0)
    assert np.abs(out.astype(int) - rgb_image).max() <= 1


def test_auto_stf_maps_background_to_target(linear_image):
    rgb = (linear_image * 255).astype(np.uint8)
    params = compute_auto_stf(rgb)
    assert 0 <= params["shadows"] < 0.1
    assert 0 < params["midtones"] < 0.5  # dark linear data needs brightening

    out = apply_interactive_stretch(rgb, **params)
    assert np.median(out) / 255 == pytest.approx(0.25, abs=0.05)


def test_interactive_stretch_float_matches_uint8_for_8bit_input(rgb_image):
    params = dict(shadows=0.02, midtones=0.2, highlights=1.0)
    from_uint8 = apply_interactive_stretch(rgb_image, **params)
    from_float = apply_interactive_stretch(rgb_image.astype(np.float32) / 255.0, **params)
    assert from_float.dtype == np.uint8
    assert np.abs(from_uint8.astype(int) - from_float).max() == 0


def test_interactive_stretch_16bit_keeps_precision():
    # A smooth 16-bit ramp, as from a stacked FITS: 16-bit output keeps its levels
    ramp = np.linspace(0, 1, 4096, dtype=np.float32)
    img = np.repeat(ramp[None, :, None], 3, axis=2)
    out = apply_interactive_stretch(img, shadows=0.0, midtones=0.5, highlights=1.0, bit_depth=16)
    assert out.dtype == np.uint16
    assert np.abs(out.astype(np.float64) / 65535 - img).max() < 1e-4
    assert len(np.unique(out)) > 256


def test_float_star_removal_stays_in_range_and_matches_uint8(rgb_image):
    starless_u8 = remove_stars(rgb_image, sensitivity=0.5, inpaint_radius=3)
    starless_float = remove_stars(rgb_image.astype(np.float32) / 255.0, sensitivity=0.5, inpaint_radius=3)
    assert starless_float.dtype == np.float32
    assert 0.0 <= starless_float.min() and starless_float.max() <= 1.0
    assert np.abs(starless_u8 / 255.0 - starless_float).mean() < 0.005


def test_auto_stf_handles_flat_image():
    params = compute_auto_stf(np.full((50, 50, 3), 128, dtype=np.uint8))
    assert params == {"shadows": 0.0, "midtones": pytest.approx(0.5, abs=0.3), "highlights": 1.0}


def test_pro_adjustments_neutral_is_identity(rgb_image):
    assert np.array_equal(apply_pro_adjustments(rgb_image), rgb_image)


def test_pro_adjustments_saturation_direction(rgb_image):
    def mean_saturation(img):
        return cv2.cvtColor(img, cv2.COLOR_RGB2HSV)[:, :, 1].mean()

    assert mean_saturation(apply_pro_adjustments(rgb_image, saturation=0.0)) < 1
    assert mean_saturation(apply_pro_adjustments(rgb_image, saturation=0.5)) < mean_saturation(rgb_image)


# --- API ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_enhance_color_fits_end_to_end(client, linear_image):
    response = client.post(
        "/api/enhance",
        files={"file": ("stack.fits", to_fits_bytes(linear_image, color=True), "application/fits")},
        data={"preset": "nebula", "denoise": "0.5", "saturation": "1.3"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["enhanced_image"].startswith("data:image/jpeg;base64,")


def test_stretch_endpoint_with_color_fits(client, linear_image):
    response = client.post(
        "/api/stretch",
        files={"file": ("stack.fits", to_fits_bytes(linear_image, color=True), "application/fits")},
        data={"shadows": "0.01", "midtones": "0.1", "remove_stars": "true"},
    )
    assert response.status_code == 200, response.text


def test_auto_stf_endpoint(client, linear_image):
    response = client.post(
        "/api/auto-stf",
        files={"file": ("stack.fits", to_fits_bytes(linear_image, color=True), "application/fits")},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"shadows", "midtones", "highlights"}
