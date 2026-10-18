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


def _error_against_scene(img: np.ndarray, scene: np.ndarray) -> float:
    """RMS difference from the (slightly blurred) scene over the disk, after registration."""
    side = img.shape[0]
    canvas = np.zeros((side, side, 3), np.float32)
    offset = (side - scene.shape[0]) // 2
    canvas[offset:offset + scene.shape[0], offset:offset + scene.shape[1]] = scene
    target = cv2.GaussianBlur(canvas.mean(axis=2), (0, 0), 1.0)
    grey = img.mean(axis=2).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    # Start from the centroid offset, then refine (rotation + shift)
    m_img, m_tgt = cv2.moments((grey > 0.3 * grey.max()).astype(np.uint8)), cv2.moments((target > 0.3 * target.max()).astype(np.uint8))
    warp[0, 2] = m_img["m10"] / m_img["m00"] - m_tgt["m10"] / m_tgt["m00"]
    warp[1, 2] = m_img["m01"] / m_img["m00"] - m_tgt["m01"] / m_tgt["m00"]
    _, warp = cv2.findTransformECC(target, grey, warp, cv2.MOTION_EUCLIDEAN,
                                   (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6), None, 5)
    aligned = cv2.warpAffine(grey, warp, (side, side), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP)
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


def test_raw_bayer_video_is_detected(videos):
    assert stacking.open_clip(videos["raw"]).bayer == "GRBG"
    assert stacking.open_clip(videos["colour"]).bayer is None
    grey = np.full((64, 64, 3), 120, np.uint8)  # mono video: grey without a CFA pattern
    assert not stacking._looks_like_bayer(grey)


def test_stack_is_closer_to_the_scene_than_the_best_frame(videos):
    result = stacking.stack_videos([videos["colour"]], keep=0.8)
    single = _best_single_frame(videos["colour"], result.image.shape[0])
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


def test_clips_with_field_rotation_stack_together(videos):
    single_clip = stacking.stack_videos([videos["colour"]])
    combined = stacking.stack_videos([videos["colour"], videos["rotated"]])
    assert combined.report["ecc_aligned"] == combined.report["frames_used"]
    assert [c["used"] > 0 for c in combined.report["clips"]] == [True, True]
    # Rotation is corrected: more frames make the stack better, not smeared
    assert _error_against_scene(combined.image, videos["scene"]) <= 1.05 * _error_against_scene(single_clip.image, videos["scene"])


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
