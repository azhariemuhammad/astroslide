"""
Video stacking checked against synthetic Moon videos with a known scene
(see synthetic.make_moon_video): jitter, varying seeing, noise, field rotation,
raw Bayer frames and unusable frames.
"""

import cv2
import numpy as np
import pytest

import stacking
from main import decode_image_float
from synthetic import make_moon_video


@pytest.fixture(scope="module")
def videos(tmp_path_factory) -> dict:
    folder = tmp_path_factory.mktemp("videos")
    paths = {name: str(folder / f"{name}.avi") for name in ("colour", "raw", "rotated")}
    scene = make_moon_video(paths["colour"], frames=40, bad_frames=6, seed=3)
    make_moon_video(paths["raw"], frames=30, raw=True, seed=5)
    make_moon_video(paths["rotated"], frames=30, rotation_deg=2.0, seed=4)
    return {**paths, "scene": scene}


def _error_against_scene(img: np.ndarray, scene: np.ndarray, blur: float = 1.0) -> float:
    """RMS difference from the scene (blurred by `blur` px, 0 = none) over the disk, after registration."""
    h, w = img.shape[:2]
    canvas = np.zeros((h, w, 3), np.float32)
    oy, ox = (h - scene.shape[0]) // 2, (w - scene.shape[1]) // 2
    canvas[oy:oy + scene.shape[0], ox:ox + scene.shape[1]] = scene
    target = canvas.mean(axis=2)
    target = cv2.GaussianBlur(target, (0, 0), blur) if blur else target
    grey = img.mean(axis=2).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    # Start from the centroid offset, then refine (rotation + shift)
    m_img, m_tgt = cv2.moments((grey > 0.3 * grey.max()).astype(np.uint8)), cv2.moments((target > 0.3 * target.max()).astype(np.uint8))
    warp[0, 2] = m_img["m10"] / m_img["m00"] - m_tgt["m10"] / m_tgt["m00"]
    warp[1, 2] = m_img["m01"] / m_img["m00"] - m_tgt["m01"] / m_tgt["m00"]
    _, warp = cv2.findTransformECC(target, grey, warp, cv2.MOTION_EUCLIDEAN,
                                   (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6), None, 5)
    aligned = cv2.warpAffine(grey, warp, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP)
    disk = cv2.erode((target > 0.3 * target.max()).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    a, t = aligned[disk] / np.median(aligned[disk]), target[disk] / np.median(target[disk])
    return float(np.sqrt(np.mean((a - t) ** 2)))


def _best_single_frame(path: str, side: int) -> np.ndarray:
    clip = stacking.open_clip(path)
    stats = [stacking.analyse_frame(rgb, 0, i) for i, rgb in stacking.iter_frames(clip)]
    best = max((s for s in stats if s.usable), key=lambda s: s.quality)
    rgb = dict(stacking.iter_frames(clip, {best.index}))[best.index]
    return cv2.warpAffine(stacking._normalized(rgb, best.sky, best.level), stacking._crop_transform(best.center, side),
                          (side, side), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP)


def test_stack_keeps_the_video_frame_size(videos):
    clip = stacking.open_clip(videos["colour"])
    result = stacking.stack_videos([videos["colour"]], sharpen=0)
    assert result.image.shape[:2] == (clip.height, clip.width)


def test_raw_bayer_video_is_detected(videos):
    assert stacking.open_clip(videos["raw"]).bayer == "GRBG"
    assert stacking.open_clip(videos["colour"]).bayer is None
    grey = np.full((64, 64, 3), 120, np.uint8)  # mono video: grey without a CFA pattern
    assert stacking._bayer_pattern(stacking._site_means(grey) or [120] * 4) is None


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
def test_every_cfa_pattern_is_detected(pattern, tmp_path):
    # Unbalanced raw, as most cameras record it: the Moon reads well redder than blue
    path = str(tmp_path / "raw.avi")
    make_moon_video(path, frames=2, raw=True, bayer=pattern, tint=(1.4, 1.0, 0.7))
    assert stacking.open_clip(path).bayer == pattern


def test_white_balanced_raw_keeps_the_usual_pattern():
    # Site means of the user's Seestar RAW clips (top-left, top-right, bottom-left,
    # bottom-right): pre-white-balanced, so blue may read a little above red
    assert stacking._bayer_pattern([84.19, 84.13, 93.74, 84.26]) == "GRBG"
    assert stacking._bayer_pattern([58.92, 66.14, 52.89, 58.96]) == "GRBG"
    # The same balance on a camera with its greens on the other diagonal
    assert stacking._bayer_pattern([84.13, 84.19, 84.26, 93.74]) == "RGGB"


def test_chosen_cfa_pattern_overrides_detection(videos):
    assert stacking.open_clip(videos["raw"], bayer="BGGR").bayer == "BGGR"
    assert stacking.open_clip(videos["colour"], bayer="BGGR").bayer is None  # not raw: nothing to apply


def test_rggb_raw_video_stacks_with_the_right_colours(tmp_path):
    path = str(tmp_path / "rggb.avi")
    scene = make_moon_video(path, frames=12, raw=True, bayer="RGGB", seed=6)
    result = stacking.stack_videos([path], sharpen=0)
    assert result.report["clips"][0]["bayer"] == "RGGB"
    scene_ratio = np.median(scene[scene.mean(axis=2) > 0.2], axis=0)
    stack_ratio = np.median(result.image[result.image.mean(axis=2) > 0.3 * result.image.max()], axis=0)
    np.testing.assert_allclose(stack_ratio / stack_ratio[1], scene_ratio / scene_ratio[1], atol=0.03)
    # A detected non-Seestar pattern comes with a hint to choose it by hand if it's wrong
    assert any("Colour pattern detected as RGGB" in note for note in stacking.stack_notes(result.report))
    chosen = stacking.stack_videos([path], sharpen=0, bayer="RGGB").report
    assert not any("Colour pattern" in note for note in stacking.stack_notes(chosen))


def test_stack_is_closer_to_the_scene_than_the_best_frame(videos):
    result = stacking.stack_videos([videos["colour"]], keep=0.8, sharpen=0)
    single = _best_single_frame(videos["colour"], result.report["size"])
    stacked_error = _error_against_scene(result.image, videos["scene"])
    single_error = _error_against_scene(single, videos["scene"])
    # Noise averages down; misregistration would instead blur detail and raise the error
    assert stacked_error < 0.6 * single_error


def test_unusable_frames_are_rejected_and_reported(videos):
    report = stacking.stack_videos([videos["colour"]], keep=1.0).report
    clip = report["clips"][0]
    assert clip["rejected"] == {"cut off": 3, "dim (cloud?)": 3}
    assert clip["used"] == clip["usable"] == 34


def test_raw_video_is_demosaiced_with_the_right_colours(videos):
    result = stacking.stack_videos([videos["raw"]])
    assert result.linear
    scene = videos["scene"]
    scene_ratio = np.median(scene[scene.mean(axis=2) > 0.2], axis=0)
    stack_ratio = np.median(result.image[result.image.mean(axis=2) > 0.3 * result.image.max()], axis=0)
    # A wrong CFA order would swap red and blue (the scene has a warm cast)
    np.testing.assert_allclose(stack_ratio / stack_ratio[1], scene_ratio / scene_ratio[1], atol=0.03)


def test_bayer_drizzle_is_closer_to_the_scene_than_demosaicing(videos):
    def error(drizzle):
        result = stacking.stack_videos([videos["raw"]], sharpen=0, bayer_drizzle=drizzle)
        return _error_against_scene(result.image, videos["scene"], blur=0)

    # Demosaicing interpolates each frame before alignment resamples it again; drizzle
    # resamples the real sensor samples once (measured ~9% closer with 150 frames)
    assert error(True) < 0.97 * error(False)


def test_clips_with_field_rotation_stack_together(videos):
    single_clip = stacking.stack_videos([videos["colour"]], sharpen=0)
    combined = stacking.stack_videos([videos["colour"], videos["rotated"]], sharpen=0)
    assert combined.report["ecc_aligned"] == combined.report["frames_used"]
    assert [c["used"] > 0 for c in combined.report["clips"]] == [True, True]
    # Rotation is corrected: more frames make the stack better, not smeared
    assert _error_against_scene(combined.image, videos["scene"]) <= 1.05 * _error_against_scene(single_clip.image, videos["scene"])


def test_default_sharpening_brings_the_stack_closest_to_the_real_moon(videos):
    def error(sharpen):
        result = stacking.stack_videos([videos["colour"]], sharpen=sharpen)
        return _error_against_scene(result.image, videos["scene"], blur=0), result.report

    soft, soft_report = error(0)
    default, report = error(0.5)
    strong, _ = error(1.0)
    assert report["psf_after"] < report["psf_before"]
    # The scene is sharp, so restoring detail lowers the error; overdoing it raises it again
    assert default < 0.85 * soft
    assert default < strong
    assert any(note.startswith("Sharpened") for note in stacking.stack_notes(report))
    assert not any(note.startswith("Sharpened") for note in stacking.stack_notes(soft_report))


def test_raw_and_processed_video_cannot_be_mixed(videos, tmp_path):
    with pytest.raises(ValueError, match="combine"):
        stacking.stack_videos([videos["raw"], videos["colour"]])


def test_saved_stack_loads_back_at_16_bit(videos, tmp_path):
    raw = stacking.stack_videos([videos["raw"]])
    fits_path = stacking.save_stack(raw, str(tmp_path / "raw_stack"), raw.report)
    assert fits_path.endswith(".fits")
    colour = stacking.stack_videos([videos["colour"]])
    png_path = stacking.save_stack(colour, str(tmp_path / "colour_stack"))
    assert png_path.endswith(".png")

    for path, original in ((fits_path, raw.image), (png_path, colour.image)):
        loaded = decode_image_float(open(path, "rb").read(), path)
        assert loaded.shape == original.shape
        # 16-bit precision survives (FITS is min-max normalized on load)
        levels = len(np.unique(np.round(loaded[..., 1] * 65535)))
        assert levels > 1000


def _wait_for_job(client, job_id: str, timeout: float = 60.0) -> dict:
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/stack/{job_id}").json()
        if status["state"] in ("done", "error", "cancelled"):
            return status
        time.sleep(0.2)
    raise TimeoutError(status)


def test_stack_api_runs_a_job_and_serves_the_result(videos, tmp_path, monkeypatch):
    import stack_jobs
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(stack_jobs, "JOBS_DIR", tmp_path / "jobs")
    client = TestClient(app)
    with open(videos["raw"], "rb") as f:
        response = client.post("/api/stack", files=[("files", ("night 1.avi", f, "video/x-msvideo"))], data={"keep": "0.5"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status = _wait_for_job(client, job_id)
    assert status["state"] == "done", status
    assert status["linear"] and status["report"]["frames_used"] == 15
    assert any("Stacked 15 of 30" in note for note in status["notes"])
    assert status["report"]["clips"][0]["name"] == "night 1.avi"
    # The uploaded videos are deleted once stacked
    assert not (tmp_path / "jobs" / job_id / "input").exists()

    result = client.get(f"/api/stack/{job_id}/result")
    assert result.status_code == 200
    assert 'filename="night_1_stacked.fits"' in result.headers["content-disposition"]
    image = decode_image_float(result.content, "stack.fits")
    assert image.shape[2] == 3

    # The display preview is what the editor would render from the FITS, without uploading it
    preview = client.get(f"/api/stack/{job_id}/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    shown = decode_image_float(preview.content, "preview.jpg")
    assert shown.shape == image.shape
    assert np.abs(shown - image).mean() < 0.01


def test_stack_api_rejects_bad_requests(tmp_path, monkeypatch):
    import stack_jobs
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(stack_jobs, "JOBS_DIR", tmp_path / "jobs")
    client = TestClient(app)
    response = client.post("/api/stack", files=[("files", ("moon.jpg", b"not a video", "image/jpeg"))])
    assert response.status_code == 400
    assert client.get("/api/stack/../../etc").status_code == 404
    assert client.get("/api/stack/" + "0" * 32).status_code == 404
    assert client.get("/api/stack/" + "0" * 32 + "/result").status_code == 404
    assert client.get("/api/stack/" + "0" * 32 + "/preview").status_code == 404
    assert client.post("/api/stack/" + "0" * 32 + "/cancel").status_code == 404
    bad = client.post("/api/stack/uploads", json={"files": [{"name": "a.avi", "size": 10}], "bayer": "RGBG"})
    assert bad.status_code == 400 and "colour pattern" in bad.json()["detail"]


def test_failed_job_reports_the_error(tmp_path, monkeypatch):
    import stack_jobs
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(stack_jobs, "JOBS_DIR", tmp_path / "jobs")
    client = TestClient(app)
    response = client.post("/api/stack", files=[("files", ("broken.mp4", b"\x00" * 1000, "video/mp4"))])
    status = _wait_for_job(client, response.json()["job_id"])
    assert status["state"] == "error"
    assert status["message"] == "Can't read video broken.mp4"


def _chunked_client(tmp_path, monkeypatch, chunk=64 * 1024):
    import stack_jobs
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr(stack_jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(stack_jobs, "CHUNK_BYTES", chunk)
    return TestClient(app)


def test_chunked_upload_survives_retries_and_runs_the_job(videos, tmp_path, monkeypatch):
    client = _chunked_client(tmp_path, monkeypatch)
    data = open(videos["raw"], "rb").read()
    response = client.post("/api/stack/uploads", json={"files": [{"name": "night 1.avi", "size": len(data)}], "keep": 0.5})
    assert response.status_code == 201
    job_id, chunk = response.json()["job_id"], response.json()["chunk_size"]
    url = f"/api/stack/{job_id}/files/0"

    # A chunk ahead of what arrived is refused with where to resume
    skipped = client.put(f"{url}?offset={chunk}", content=data[chunk:2 * chunk])
    assert skipped.status_code == 409 and skipped.json()["received"] == 0
    # Starting before the upload is complete is refused
    assert client.post(f"/api/stack/{job_id}/start").status_code == 409

    offset = 0
    while offset < len(data):
        piece = data[offset:offset + chunk]
        assert client.put(f"{url}?offset={offset}", content=piece).json()["received"] == offset + len(piece)
        if offset == chunk:  # a retried chunk (its response was lost) changes nothing
            assert client.put(f"{url}?offset={offset}", content=piece).json()["received"] == offset + len(piece)
        offset += len(piece)
    assert client.get(f"/api/stack/{job_id}").json()["progress"] == 1.0

    assert client.post(f"/api/stack/{job_id}/start").status_code == 202
    status = _wait_for_job(client, job_id)
    assert status["state"] == "done", status
    assert status["report"]["frames_used"] == 15 and status["report"]["clips"][0]["name"] == "night 1.avi"
    assert client.get(f"/api/stack/{job_id}/result").status_code == 200
    # The upload is finished: no more chunks
    assert client.put(f"{url}?offset=0", content=data[:chunk]).status_code == 404


def test_chunked_upload_rejects_bad_requests(tmp_path, monkeypatch):
    client = _chunked_client(tmp_path, monkeypatch, chunk=1024)
    assert client.post("/api/stack/uploads", json={"files": [{"name": "moon.jpg", "size": 10}]}).status_code == 400
    assert client.post("/api/stack/uploads", json={"files": []}).status_code == 400
    assert client.put("/api/stack/" + "0" * 32 + "/files/0?offset=0", content=b"x").status_code == 404

    job_id = client.post("/api/stack/uploads", json={"files": [{"name": "a.avi", "size": 3000}]}).json()["job_id"]
    url = f"/api/stack/{job_id}/files"
    assert client.put(f"{url}/0?offset=0", content=b"x" * 2048).status_code == 400   # larger than chunk_size
    assert client.put(f"{url}/0?offset=2500", content=b"x" * 1000).status_code == 400  # past the declared size
    assert client.put(f"{url}/1?offset=0", content=b"x").status_code == 404           # no such file


def test_abandoned_chunked_upload_frees_its_slot(tmp_path, monkeypatch):
    import main
    import stack_jobs

    client = _chunked_client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "MAX_STACK_JOBS", 1)
    first = client.post("/api/stack/uploads", json={"files": [{"name": "a.avi", "size": 100}]}).json()["job_id"]
    assert client.post("/api/stack/uploads", json={"files": [{"name": "b.avi", "size": 100}]}).status_code == 503

    folder = stack_jobs.job_folder(first)
    status = stack_jobs.read_status(folder)
    status["updated"] -= stack_jobs.UPLOAD_IDLE_SECONDS + 1
    (folder / "status.json").write_text(__import__("json").dumps(status))
    assert client.post("/api/stack/uploads", json={"files": [{"name": "b.avi", "size": 100}]}).status_code == 201
    assert stack_jobs.job_folder(first) is None


def test_binned_raw_video_gets_a_resolution_tip():
    assert stacking._half_sensor(536, 960) and stacking._half_sensor(960, 536)
    assert not stacking._half_sensor(1080, 1920) and not stacking._half_sensor(464, 832)
    report = {"clips": [{"name": "a.avi", "frames": 10, "usable": 10, "used": 7, "raw": True, "width": 536,
                         "height": 960, "rejected": {}}],
              "frames_used": 7, "frames_total": 10, "seconds": 1, "quality_spread": 1.5, "linear": True}
    assert any("full resolution" in note for note in stacking.stack_notes(report))
    report["clips"][0]["raw"] = False  # processed .mp4 at that size: no RAW advice
    assert not any("full resolution" in note for note in stacking.stack_notes(report))


def test_cancelled_upload_stops_taking_chunks_and_frees_its_slot(tmp_path, monkeypatch):
    import main

    client = _chunked_client(tmp_path, monkeypatch, chunk=1024)
    monkeypatch.setattr(main, "MAX_STACK_JOBS", 1)
    job_id = client.post("/api/stack/uploads", json={"files": [{"name": "a.avi", "size": 3000}]}).json()["job_id"]
    assert client.put(f"/api/stack/{job_id}/files/0?offset=0", content=b"x" * 1024).status_code == 200

    assert client.post(f"/api/stack/{job_id}/cancel").json()["state"] == "cancelled"
    assert not (tmp_path / "jobs" / job_id / "input").exists()
    assert client.put(f"/api/stack/{job_id}/files/0?offset=1024", content=b"x" * 1024).status_code == 404
    assert client.post(f"/api/stack/{job_id}/start").status_code == 404
    assert client.post("/api/stack/uploads", json={"files": [{"name": "b.avi", "size": 100}]}).status_code == 201


def test_cancelled_stack_stops_while_running(videos, tmp_path, monkeypatch):
    import threading
    import time
    import stack_jobs

    client = _chunked_client(tmp_path, monkeypatch)
    started, stopped = threading.Event(), threading.Event()

    def endless_stack(paths, progress, **options):
        started.set()
        try:
            for _ in range(500):
                progress(0.5, "Stacking")
                time.sleep(0.02)
        finally:
            stopped.set()
        raise AssertionError("stacking wasn't stopped")

    monkeypatch.setattr(stacking, "stack_videos", endless_stack)
    with open(videos["raw"], "rb") as f:
        job_id = client.post("/api/stack", files=[("files", ("a.avi", f, "video/x-msvideo"))]).json()["job_id"]
    assert started.wait(10)
    assert client.post(f"/api/stack/{job_id}/cancel").json()["state"] == "cancelled"
    assert stopped.wait(5)
    status = _wait_for_job(client, job_id)
    assert status["state"] == "cancelled", status
    assert not (tmp_path / "jobs" / job_id / "input").exists()
    # Cancelling a finished job changes nothing
    assert client.post(f"/api/stack/{job_id}/cancel").json()["state"] == "cancelled"
    assert stack_jobs.active_jobs() == 0


def test_haze_glow_is_removed_without_touching_the_surface():
    # Gibbous Moon (terminator fading out on the right) in a wide haze glow, as on the
    # hazy night of 2026-10-23: ~9% of the disk's brightness at the limb, 4% 60 px out
    from synthetic import make_synthetic_moon
    size = 600
    moon = make_synthetic_moon(size=size, observed=False)
    xs = np.arange(size, dtype=np.float32)
    phase = np.clip((0.78 * size - xs) / (0.06 * size), 0, 1)  # smooth terminator
    scene = cv2.GaussianBlur(moon["linear"] * phase[None, :, None], (0, 0), 1.2)
    lit = scene.mean(axis=2)
    glow = sum(a * cv2.GaussianBlur(lit, (0, 0), s) for a, s in ((0.06, 15), (0.08, 60), (0.06, 150)))
    hazy = np.clip(scene + glow[..., None], 0, 1).astype(np.float32)

    out, measured = stacking.remove_sky_glow(hazy, np.ones((size, size), bool), linear=True)

    radius, centre = size * 0.41, size / 2
    yy, xx = np.mgrid[:size, :size]
    beyond = np.hypot(xx - centre, yy - centre) - radius
    sky = (beyond > 5) & (beyond < 80) & (xx < 0.6 * size)   # beside the bright limb
    disk = np.median(lit[lit > 0.15 * lit.max()])
    assert measured and measured > 0.05
    assert np.median(hazy.mean(axis=2)[sky]) > 0.04 * disk
    assert np.median(out.mean(axis=2)[sky]) < 0.006 * disk
    # The lit surface is untouched, and dim terrain by the terminator keeps its light
    surface = lit > 0.2 * lit.max()
    assert np.abs(out - hazy)[surface].max() < 1e-6
    dim = (lit > 0.03 * disk) & (lit < 0.12 * disk) & (beyond < -10)
    assert np.median(out.mean(axis=2)[dim] / lit[dim]) > 0.8
