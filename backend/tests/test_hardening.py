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


def test_refusals_carry_cors_headers_for_the_frontend_on_another_site(client, monkeypatch):
    # Without them the browser hides the reason and the frontend only sees a network error
    monkeypatch.setattr(main, "MAX_UPLOAD", 1000)
    response = client.post("/api/enhance", headers={"Origin": "https://astroslide.me"},
                           files={"file": ("big.png", b"x" * (main.UploadGuard.FORM_OVERHEAD + 2000))})
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] in ("*", "https://astroslide.me")


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


def test_api_is_kept_out_of_search_results(client):
    assert client.get("/api/health").headers["x-robots-tag"] == "noindex, nofollow"


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


# --- Per-client limits ----------------------------------------------------------

def test_token_bucket_allows_a_burst_then_the_refill_rate():
    buckets = main.TokenBuckets(capacity=6, rate=1)  # 6 tokens, 1 per second
    assert all(buckets.take("a", 3, now=0) == 0 for _ in range(2))
    assert buckets.take("a", 3, now=0) == pytest.approx(3)  # empty: wait 3 s for 3 tokens
    assert buckets.take("a", 3, now=3) == 0
    assert buckets.take("b", 3, now=3) == 0  # other clients have their own bucket


def test_token_bucket_forgets_idle_clients(monkeypatch):
    monkeypatch.setattr(main.TokenBuckets, "MAX_CLIENTS", 3)
    buckets = main.TokenBuckets(capacity=2, rate=1)
    for i in range(3):
        buckets.take(f"old{i}", 1, now=0)
    buckets.take("new", 1, now=100)
    assert set(buckets.buckets) == {"new"}


def test_client_address_ignores_what_the_client_put_in_x_forwarded_for(monkeypatch):
    monkeypatch.setattr(main, "PROXY_HOPS", 1)
    # Heroku's router appends the address it saw to whatever the client sent
    scope = {"headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.7")], "client": ("10.0.0.1", 1234)}
    assert main.client_address(scope) == "203.0.113.7"
    monkeypatch.setattr(main, "PROXY_HOPS", 0)
    assert main.client_address(scope) == "10.0.0.1"


async def _call(middleware, path: str, client: str = "1.2.3.4") -> int:
    scope = {"type": "http", "method": "POST", "path": path, "headers": [], "client": (client, 1)}
    sent = []

    async def send(message):
        sent.append(message)

    await middleware(scope, None, send)
    return sent[0]["status"]


async def _ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_rate_limit_refuses_with_429_and_retry_after(monkeypatch):
    import asyncio
    monkeypatch.setattr(main, "RATE_LIMIT", 3)  # bucket of 6
    limits = main.ClientLimits(_ok)

    async def run():
        statuses = [await _call(limits, "/api/enhance") for _ in range(3)]  # 3 units each
        statuses.append(await _call(limits, "/api/enhance", client="5.6.7.8"))
        return statuses

    assert asyncio.run(run()) == [200, 200, 429, 200]


def test_in_flight_cap_per_client(monkeypatch):
    import asyncio
    monkeypatch.setattr(main, "MAX_REQUESTS_PER_CLIENT", 2)

    async def run():
        release = asyncio.Event()

        async def slow(scope, receive, send):
            await release.wait()
            await _ok(scope, receive, send)

        limits = main.ClientLimits(slow)
        held = [asyncio.create_task(_call(limits, "/api/histogram")) for _ in range(2)]
        await asyncio.sleep(0)
        third = await _call(limits, "/api/histogram")
        other = asyncio.create_task(_call(limits, "/api/histogram", client="5.6.7.8"))
        await asyncio.sleep(0)
        release.set()
        return third, await asyncio.gather(*held, other), limits.in_flight

    third, finished, in_flight = asyncio.run(run())
    assert third == 429
    assert finished == [200, 200, 200]
    assert in_flight == {}


# --- Large JPEGs ------------------------------------------------------------------

def jpeg_bytes(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (120, 130, 140)).save(out, format="JPEG")
    return out.getvalue()


def test_large_jpeg_decodes_at_reduced_scale(monkeypatch):
    monkeypatch.setattr(main, "MAX_PIXELS", 100 * 100)
    monkeypatch.setattr(main, "MAX_DECODE_PIXELS", 150 * 150)  # 800x800 is far above this
    for decode in (main.decode_image, main.decode_image_float):
        h, w = decode(jpeg_bytes(800, 800), "camera.jpg").shape[:2]
        assert 100 <= h <= 200 and 100 <= w <= 200  # 1/4 or 1/8 scale, never full size


def test_enhance_reports_the_size_the_file_had(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_PIXELS", 100 * 100)
    response = client.post("/api/enhance", files={"file": ("camera.jpg", jpeg_bytes(800, 600), "image/jpeg")},
                           data={"preset": "nebula"})
    assert response.status_code == 200, response.text
    assert any("800x600" in note for note in response.json()["notes"])
