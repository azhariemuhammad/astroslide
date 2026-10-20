"""
Limits and headers that protect a small public server (see UploadGuard and
SecurityHeaders in main.py).
"""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
import stack_jobs
from main import app
from synthetic import to_fits_bytes


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def png_bytes(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height)).save(out, format="PNG")
    return out.getvalue()


def test_upload_over_the_limit_is_refused_before_reading(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD", 1000)
    response = client.post("/api/enhance", files={"file": ("big.png", b"x" * (main.UploadGuard.FORM_OVERHEAD + 2000))})
    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/api/enhance", "/api/histogram", "/api/auto-stf", "/api/stretch"])
def test_image_with_too_many_pixels_is_refused_before_decoding(client, monkeypatch, path):
    monkeypatch.setattr(main, "MAX_DECODE_PIXELS", 100 * 100)
    response = client.post(path, files={"file": ("bomb.png", png_bytes(200, 200), "image/png")})
    assert response.status_code == 413, response.text
    assert "megapixels" in response.json()["detail"]


def test_fits_with_too_many_pixels_is_refused(monkeypatch):
    monkeypatch.setattr(main, "MAX_DECODE_PIXELS", 100 * 100)
    contents = to_fits_bytes(np.zeros((200, 200, 3), np.float32), color=True)
    with pytest.raises(main.HTTPException) as error:
        main.decode_image_float(contents, "big.fits")
    assert error.value.status_code == 413


def test_image_within_the_limit_still_decodes(monkeypatch):
    monkeypatch.setattr(main, "MAX_DECODE_PIXELS", 200 * 200)
    assert main.decode_image(png_bytes(200, 200), "ok.png").shape == (200, 200, 3)


def test_security_headers(client):
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers  # plain http


def test_http_behind_proxy_redirects_to_https(client, monkeypatch):
    monkeypatch.setattr(main, "FORCE_HTTPS", True)
    response = client.get("/api/health?x=1", headers={"x-forwarded-proto": "http"}, follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "https://testserver/api/health?x=1"
    # Direct requests (no proxy) are served as they are, e.g. a local docker run
    assert client.get("/api/health").status_code == 200


def test_stacking_refuses_new_jobs_when_busy(client, monkeypatch):
    monkeypatch.setattr(stack_jobs, "active_jobs", lambda: main.MAX_STACK_JOBS)
    response = client.post("/api/stack", files=[("files", ("moon.mp4", b"0" * 100, "video/mp4"))])
    assert response.status_code == 503
