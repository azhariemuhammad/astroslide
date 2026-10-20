"""
Lucky imaging for Moon videos (Seestar raw .avi or .mp4), several clips at once.

The usual planetary-stacking pipeline (AutoStakkert!, PlanetarySystemStacker),
built from OpenCV's primitives rather than reimplemented:

1. Analyse every frame: find the disk, score its sharpness, reject frames with
   clouds or the moon cut off at the frame edge
2. Keep the sharpest fraction, ranked across all clips together
3. Reference = average of the best frames, aligned
4. Align each kept frame onto the reference: rotation + shift (ECC, so alt-az field
   rotation between clips is handled), then the local seeing warp (DIS optical
   flow, smoothed), applied as one resampling of the original frame
5. Average in float32, normalized per frame for brightness, so 8-bit frames
   become a stack with far more tonal depth and far less noise
6. Sharpen, as every lucky-imaging workflow ends (AutoStakkert -> RegiStax wavelets):
   the stack's low noise is what allows it. Richardson-Lucy deconvolution with the
   blur measured from the limb, then wavelet sharpening (the editor's moon tools)

Raw sensor video (8-bit Bayer, linear light) is demosaiced and stacked as linear
data and saved as 16-bit FITS; H.264 video is already tone-mapped, so its stack is
saved as a 16-bit PNG. Either goes straight into the editor's presets.

CLI:  python stacking.py clip1.avi [clip2.avi ...] -o stack.fits [--keep 0.7]
"""

import argparse
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

import cv2
import numpy as np

from presets import (estimate_moon_psf, find_moon_mask, linear_to_srgb, moon_deconvolve,
                     moon_sharpen, srgb_to_linear)

# The raw AVI's pal8 format makes OpenCV warn on every frame; the data is read correctly
cv2.setLogLevel(2)  # errors only

VIDEO_EXTENSIONS = ('.avi', '.mp4', '.mov', '.mkv')
# Larger frames are refused (unset = no limit); stacking memory grows with frame size
MAX_FRAME_PIXELS = int(float(os.environ.get("ASTROSLIDE_MAX_VIDEO_MEGAPIXELS", "0")) * 1_000_000)

# Sensor CFA order -> OpenCV conversion (OpenCV names the pattern one pixel shifted).
# Seestar S30/S50 sensors are GRBG.
BAYER_CODES = {
    "GRBG": cv2.COLOR_BayerGB2RGB,
    "RGGB": cv2.COLOR_BayerBG2RGB,
    "BGGR": cv2.COLOR_BayerRG2RGB,
    "GBRG": cv2.COLOR_BayerGR2RGB,
}

# Analysis runs on a downscaled copy; the disk only needs to be located there
ANALYSIS_SCALE = 4
# Seeing distortions are smooth: flow detail finer than this (px) is noise
FLOW_SMOOTH_SIGMA = 8.0
MAX_FLOW = 6.0
# ECC runs on a downscaled crop (rotation + shift need no fine detail)
ECC_SCALE = 0.5
# Final resampling of each frame (Lanczos measured no sharper than cubic here)
INTERPOLATION = cv2.INTER_CUBIC

Progress = Callable[[float, str], None]


@dataclass
class Clip:
    path: str
    name: str
    frame_count: int
    fps: float
    width: int
    height: int
    bayer: Optional[str]   # CFA pattern when the video holds raw sensor data
    linear: bool           # raw sensor data is linear light; H.264 video is tone-mapped


@dataclass
class FrameStats:
    clip: int
    index: int
    usable: bool
    center: tuple = (0.0, 0.0)   # disk bounding-box centre, full-resolution px
    size: float = 0.0            # disk bounding-box extent (diameter, also for a crescent)
    sky: float = 0.0
    level: float = 0.0           # median disk brightness above the sky
    quality: float = 0.0
    reason: str = ""


@dataclass
class StackResult:
    image: np.ndarray            # float32 RGB, 0-1
    linear: bool
    report: dict = field(default_factory=dict)


def open_clip(path: str, bayer: str = "GRBG", name: Optional[str] = None) -> Clip:
    """Probe a video: frame count, and whether it holds raw Bayer data. `name` is shown to the user."""
    name = name or Path(path).name
    cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise ValueError(f"Can't read video {name}")
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"{name} contains no frames")
    finally:
        cap.release()

    if MAX_FRAME_PIXELS and frame.shape[0] * frame.shape[1] > MAX_FRAME_PIXELS:
        raise ValueError(
            f"{name} is {frame.shape[1]}x{frame.shape[0]}; this server stacks videos up to "
            f"{MAX_FRAME_PIXELS / 1e6:g} megapixels per frame"
        )

    pattern = bayer if _looks_like_bayer(frame) else None
    return Clip(path=path, name=name, frame_count=frame_count, fps=fps,
                width=frame.shape[1], height=frame.shape[0],
                bayer=pattern, linear=pattern is not None)


def _looks_like_bayer(frame: np.ndarray) -> bool:
    """
    A raw colour-sensor frame is grey with a 2x2 pattern: the two green sites of each
    cell agree, while red and blue differ from each other. Mono or colour video doesn't.
    """
    if frame.ndim == 3 and not (np.array_equal(frame[..., 0], frame[..., 1])
                                and np.array_equal(frame[..., 1], frame[..., 2])):
        return False
    grey = frame[..., 0] if frame.ndim == 3 else frame
    h, w = grey.shape[0] // 2 * 2, grey.shape[1] // 2 * 2
    sites = [grey[dy:h:2, dx:w:2].astype(np.float32) for dy, dx in ((0, 0), (0, 1), (1, 0), (1, 1))]
    bright = (sites[0] + sites[1] + sites[2] + sites[3]) > 4 * 0.3 * float(grey.max())
    if bright.sum() < 500:
        return False
    means = [float(s[bright].mean()) for s in sites]
    mean = sum(means) / 4
    greens_agree = abs(means[0] - means[3]) < 0.01 * mean
    others_differ = abs(means[1] - means[2]) > 0.03 * mean
    return greens_agree and others_differ


def iter_frames(clip: Clip, wanted: Optional[set] = None) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (index, uint8 RGB frame); with `wanted`, decode only those indices."""
    cap = cv2.VideoCapture(clip.path, cv2.CAP_FFMPEG)
    last = max(wanted) if wanted else None
    try:
        index = 0
        while last is None or index <= last:
            if wanted is not None and index not in wanted:
                # grab() skips the colour conversion; compressed video still has to decode
                if not cap.grab():
                    break
                index += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            if clip.bayer:
                yield index, cv2.cvtColor(frame[..., 0], BAYER_CODES[clip.bayer])
            else:
                yield index, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            index += 1
    finally:
        cap.release()


def analyse_frame(rgb: np.ndarray, clip: int, index: int) -> FrameStats:
    """Locate the disk on a downscaled copy and score sharpness at full resolution."""
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(grey, None, fx=1 / ANALYSIS_SCALE, fy=1 / ANALYSIS_SCALE, interpolation=cv2.INTER_AREA)
    top = float(np.percentile(small, 99.5))
    if top < 8:
        return FrameStats(clip, index, False, reason="no moon")
    mask = small > 0.25 * top
    sky = float(np.median(small[~mask])) if (~mask).any() else 0.0

    ys, xs = np.nonzero(mask)
    if len(ys) < 50:
        return FrameStats(clip, index, False, reason="no moon")
    h, w = small.shape
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    if y0 == 0 or x0 == 0 or y1 == h or x1 == w:
        return FrameStats(clip, index, False, reason="cut off")

    s = ANALYSIS_SCALE
    center = ((x0 + x1) / 2 * s, (y0 + y1) / 2 * s)
    size = float(max(x1 - x0, y1 - y0) * s)

    # Sharpness: Laplacian energy inside the disk, relative to its brightness, so
    # thin cloud or a brightness change doesn't count as blur
    crop = grey[y0 * s:y1 * s, x0 * s:x1 * s].astype(np.float32)
    disk = cv2.resize(mask[y0:y1, x0:x1].astype(np.uint8), (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST)
    disk = cv2.erode(disk, np.ones((9, 9), np.uint8)).astype(bool)
    if disk.sum() < 200:
        return FrameStats(clip, index, False, reason="no moon")
    level = float(np.median(crop[disk])) - sky
    laplacian = cv2.Laplacian(cv2.GaussianBlur(crop, (0, 0), 1.0), cv2.CV_32F)
    quality = float(laplacian[disk].var()) / max(level, 1.0) ** 2
    return FrameStats(clip, index, True, center, size, sky, level, quality)


def select_frames(stats: list[FrameStats], keep: float) -> list[FrameStats]:
    """
    Drop unusable frames and cloud dips (brightness well below the clip's typical
    level), then keep the sharpest `keep` fraction, ranked across all clips.
    """
    usable = [s for s in stats if s.usable]
    for clip in {s.clip for s in usable}:
        levels = np.array([s.level for s in usable if s.clip == clip])
        typical = float(np.median(levels))
        for s in usable:
            if s.clip == clip and s.level < 0.7 * typical:
                s.usable, s.reason = False, "dim (cloud?)"
    usable = [s for s in usable if s.usable]
    if not usable:
        return []
    ranked = sorted(usable, key=lambda s: s.quality, reverse=True)
    count = min(len(ranked), max(min(10, len(ranked)), int(round(keep * len(ranked)))))
    return ranked[:count]


def _crop_transform(center: tuple, side: int) -> np.ndarray:
    """Output-crop pixel -> frame pixel, for a crop of `side` px centred on `center`."""
    return np.float32([[1, 0, center[0] - side / 2], [0, 1, center[1] - side / 2]])


def _normalized(rgb_or_grey: np.ndarray, sky: float, level: float) -> np.ndarray:
    """Sky-subtracted, brightness-normalized float32 (disk median = 1)."""
    return (rgb_or_grey.astype(np.float32) - sky) / max(level, 1e-3)


def _to_uint8_guide(grey: np.ndarray) -> np.ndarray:
    """Grey image with disk median 1 -> uint8 for ECC/optical flow (disk spans the range)."""
    return np.clip(grey * 110.0, 0, 255).astype(np.uint8)


class Aligner:
    """Aligns frames onto a reference crop: Euclidean ECC, then smoothed DIS optical flow."""

    def __init__(self, reference_grey: np.ndarray, local: bool):
        self.side = reference_grey.shape[0]
        self.local = local
        # Seeing warps are smooth, so the flow is measured at half resolution (4x faster)
        self.flow_side = self.side // 2
        self.reference8 = _to_uint8_guide(cv2.resize(reference_grey, (self.flow_side, self.flow_side), interpolation=cv2.INTER_AREA))
        self.small_side = int(round(self.side * ECC_SCALE))
        self.reference_small = cv2.GaussianBlur(
            cv2.resize(reference_grey, (self.small_side, self.small_side), interpolation=cv2.INTER_AREA), (0, 0), 1.0
        )
        self.disk = cv2.resize((reference_grey > 0.25).astype(np.float32), (self.flow_side, self.flow_side), interpolation=cv2.INTER_AREA)
        self.flow_weight = cv2.GaussianBlur(self.disk, (0, 0), FLOW_SMOOTH_SIGMA / 2) + 1e-3
        grid_y, grid_x = np.mgrid[0:self.side, 0:self.side].astype(np.float32)
        self.grid = (grid_x, grid_y)

    def global_transform(self, grey: np.ndarray, stats: FrameStats) -> tuple[np.ndarray, bool]:
        """
        Crop pixel -> frame pixel (2x3), from the disk centre refined by ECC on a
        downscaled crop (rotation + sub-pixel shift). Falls back to the centre alone.
        """
        initial = _crop_transform(stats.center, self.side)
        k = self.small_side / self.side
        # Cut the crop first, then downscale: cheaper than downscaling the whole frame
        crop = cv2.warpAffine(grey, initial, (self.side, self.side), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        frame_small = cv2.resize(crop, (self.small_side, self.small_side), interpolation=cv2.INTER_AREA)
        frame_small = cv2.GaussianBlur(frame_small, (0, 0), 1.0)
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            _, warp = cv2.findTransformECC(
                self.reference_small, frame_small, warp, cv2.MOTION_EUCLIDEAN,
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), None, 1
            )
        except cv2.error:
            return initial, False
        if abs(warp[0, 2]) > self.small_side / 8 or abs(warp[1, 2]) > self.small_side / 8:
            return initial, False
        # Compose: crop -> (ECC at reduced scale, translation scaled up) -> frame
        combined = initial.copy()
        combined[:, :2] = warp[:, :2]
        combined[:, 2] = initial[:, 2] + warp[:, 2] / k
        return combined, True

    def maps(self, grey: np.ndarray, transform: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """remap() maps: crop pixel -> frame pixel, including the local seeing warp."""
        gx, gy = self.grid
        if self.local:
            half = transform.copy()
            half[:, :2] *= 2  # half-resolution crop pixel -> frame pixel
            warped = cv2.warpAffine(grey, half, (self.flow_side, self.flow_side), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
            flow = _dis().calc(self.reference8, _to_uint8_guide(warped), None)
            # Only the disk carries signal: smooth the flow over it, keep it small
            for c in range(2):
                flow[..., c] = cv2.GaussianBlur(flow[..., c] * self.disk, (0, 0), FLOW_SMOOTH_SIGMA / 2) / self.flow_weight
            flow = 2 * cv2.resize(flow, (self.side, self.side), interpolation=cv2.INTER_LINEAR)
            np.clip(flow, -MAX_FLOW, MAX_FLOW, out=flow)
            px, py = gx + flow[..., 0], gy + flow[..., 1]
        else:
            px, py = gx, gy
        a = transform
        return (a[0, 0] * px + a[0, 1] * py + a[0, 2]).astype(np.float32), \
               (a[1, 0] * px + a[1, 1] * py + a[1, 2]).astype(np.float32)


_dis_local = threading.local()


def _dis():
    """One DIS optical-flow instance per thread (instances aren't thread-safe)."""
    if not hasattr(_dis_local, "flow"):
        _dis_local.flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    return _dis_local.flow


def _pipelined(pool: ThreadPoolExecutor, items: Iterable[tuple], work: Callable, window: int) -> Iterator:
    """work(*item) for each item on the pool, results in order, at most `window` in flight (bounds memory)."""
    pending: deque = deque()
    for item in items:
        pending.append(pool.submit(work, *item))
        if len(pending) >= window:
            yield pending.popleft().result()
    while pending:
        yield pending.popleft().result()


def _worker_count() -> int:
    # cpu_count() sees the whole host on shared hosts (Heroku), not this container's share
    cap = int(os.environ.get("ASTROSLIDE_THREADS", "4"))
    return max(1, min(cap, (os.cpu_count() or 2) - 1))


def stack_videos(
    paths: list[str],
    keep: float = 0.7,
    local_align: bool = True,
    sharpen: float = 0.5,
    bayer: str = "GRBG",
    progress: Optional[Progress] = None,
    names: Optional[list[str]] = None,
) -> StackResult:
    """
    Stack one or more Moon videos into a single image.

    Args:
        paths: video files; clips from the same night can be combined
        keep: fraction of usable frames to stack (0.05-1). Seestar's small aperture
            shows little frame-to-frame sharpness variation, so most of the gain is
            noise averaging and the default keeps most frames.
        local_align: correct local seeing distortion with optical flow
        sharpen: 0-1, post-stack sharpening: 0.5 = restores what the data holds (default),
            higher = crisper for taste, 0 = none
        bayer: CFA pattern for raw sensor video
        progress: callback(fraction 0-1, message)
        names: clip names for messages and the report (default: file names)

    Returns:
        StackResult with the float32 RGB image (0-1) and a report
    """
    report_progress = progress or (lambda fraction, message: None)
    started = time.perf_counter()
    clips = [open_clip(p, bayer, name) for p, name in zip(paths, names or [None] * len(paths))]
    if len({c.linear for c in clips}) > 1:
        raise ValueError("Can't combine raw (.avi) and processed (.mp4) video in one stack")
    total_frames = sum(max(c.frame_count, 1) for c in clips)

    # Budget: analysis ~25%, reference ~10%, alignment + stacking ~65%.
    # Decoding is sequential; the per-frame work runs on a thread pool alongside it
    # (OpenCV releases the GIL), so a pass costs about as long as decoding the video.
    workers = _worker_count()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        stats: list[FrameStats] = []
        for ci, clip in enumerate(clips):
            report_progress(0.25 * len(stats) / total_frames, f"Analysing {clip.name}")
            frames = ((rgb, ci, index) for index, rgb in iter_frames(clip))
            for frame_stats in _pipelined(pool, frames, analyse_frame, 2 * workers):
                stats.append(frame_stats)
                if len(stats) % 20 == 0:
                    report_progress(0.25 * min(len(stats) / total_frames, 1.0), f"Analysing {clip.name}")

        selected = select_frames(stats, max(0.05, min(1.0, keep)))
        if not selected:
            raise ValueError("No usable frames: the moon wasn't found, or it is cut off at the frame edge")

        # Square crop around the disk with room for a halo; never larger than the frame
        disk_size = float(np.median([s.size for s in selected]))
        side = int(min([disk_size * 1.6] + [min(c.width, c.height) for c in clips])) // 2 * 2

        # Reference: best frames aligned on the best one (ECC), averaged
        report_progress(0.25, "Building reference")
        best = selected[:max(3, min(25, len(selected) // 5))]
        reference = _build_reference(clips, best, side)

        # Align every selected frame and accumulate
        aligner = Aligner(reference, local_align)

        def align_one(rgb: np.ndarray, s: FrameStats):
            grey = _normalized(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), s.sky, s.level)
            transform, ecc_ok = aligner.global_transform(grey, s)
            map_x, map_y = aligner.maps(grey, transform)
            # Convert only the part of the frame the crop samples (plus the kernel's reach)
            h, w = rgb.shape[:2]
            x0, y0 = max(0, int(map_x.min()) - 3), max(0, int(map_y.min()) - 3)
            x1, y1 = min(w, int(map_x.max()) + 4), min(h, int(map_y.max()) + 4)
            roi = _normalized(rgb[y0:y1, x0:x1], s.sky, s.level)
            warped = cv2.remap(roi, map_x - x0, map_y - y0, INTERPOLATION, borderValue=np.nan)
            # Crop pixels outside the frame are NaN: count coverage, then zero them
            valid = np.isfinite(warped[..., 0])
            warped[~valid] = 0
            return warped, valid.astype(np.float32), ecc_ok

        by_clip: dict[int, dict[int, FrameStats]] = {}
        for s in selected:
            by_clip.setdefault(s.clip, {})[s.index] = s
        jobs = (
            (rgb, frames[index])
            for ci, frames in by_clip.items()
            for index, rgb in iter_frames(clips[ci], set(frames))
        )
        total = np.zeros((side, side, 3), np.float32)
        coverage = np.zeros((side, side), np.float32)
        used_ecc = processed = 0
        for warped, valid, ecc_ok in _pipelined(pool, jobs, align_one, 2 * workers):
            total += warped
            coverage += valid
            used_ecc += ecc_ok
            processed += 1
            if processed % 10 == 0:
                report_progress(0.35 + 0.65 * processed / len(selected), f"Stacking frame {processed} of {len(selected)}")

    stack = (total / np.maximum(coverage, 1)[..., None]).astype(np.float32)
    stack[coverage == 0] = 0
    stack = np.clip(stack, 0, None)
    stack /= max(float(np.percentile(stack, 99.99)), 1e-6) * 1.02  # disk median was 1; use the range
    stack = np.clip(stack, 0, 1)
    report_progress(0.99, "Sharpening")
    stack, psf_before, psf_after = sharpen_stack(stack, sharpen, clips[0].linear)

    report = _report(clips, stats, selected, side, used_ecc, time.perf_counter() - started, local_align)
    report.update(sharpen=sharpen, psf_before=psf_before, psf_after=psf_after)
    report_progress(1.0, "Done")
    return StackResult(stack, clips[0].linear, report)


def _build_reference(clips: list[Clip], best: list[FrameStats], side: int) -> np.ndarray:
    """Average of the best frames, each ECC-aligned onto the sharpest one (grey)."""
    def grey_of(rgb: np.ndarray, s: FrameStats) -> np.ndarray:
        return _normalized(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), s.sky, s.level)

    # The sharpest frame first (it defines the alignment), then the rest streamed:
    # holding up to 25 full float frames at once would need ~200 MB
    anchor = best[0]
    _, anchor_rgb = next(iter_frames(clips[anchor.clip], {anchor.index}))
    first = cv2.warpAffine(grey_of(anchor_rgb, anchor), _crop_transform(anchor.center, side), (side, side),
                           flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    del anchor_rgb
    aligner = Aligner(first, local=False)

    wanted: dict[int, dict[int, FrameStats]] = {}
    for s in best:
        wanted.setdefault(s.clip, {})[s.index] = s
    total = np.zeros((side, side), np.float32)
    for ci, frames in wanted.items():
        for index, rgb in iter_frames(clips[ci], set(frames)):
            grey = grey_of(rgb, frames[index])
            transform, _ = aligner.global_transform(grey, frames[index])
            total += cv2.warpAffine(grey, transform, (side, side), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    return total / len(best)


def sharpen_stack(image: np.ndarray, amount: float, linear: bool) -> tuple[np.ndarray, Optional[float], Optional[float]]:
    """
    Deconvolve and wavelet-sharpen the stack's luminance, colour unchanged.
    Tone-mapped (video) stacks are sharpened in linear light, like the editor does JPEGs.

    Returns (image 0-1, blur sigma in px before, after); sigmas are None without a usable limb.
    """
    if amount <= 0:
        return image, None, None
    lin = image if linear else srgb_to_linear(image)
    luminance = lin.mean(axis=2)
    mask = find_moon_mask(luminance)
    if not mask.any():
        return image, None, None
    diameter = 2 * np.sqrt(mask.sum() / np.pi)
    before = estimate_moon_psf(luminance, mask)
    # Calibrated against synthetic videos with a known scene (tests/test_stacking.py):
    # the Gaussian fitted to the limb overstates the blur of fine detail (a stacked seeing
    # PSF has a sharp core and wide wings), so a few RL iterations (amount 0.5 here) bring
    # the stack closest to the true moon. Beyond that, more iterations and wavelets look
    # crisper but exaggerate edges past what is real.
    sharpened = moon_deconvolve(luminance, mask, diameter, 0.3 * min(amount, 1.0), before)
    if amount > 0.5:
        sharpened = moon_sharpen(sharpened, mask, diameter, 0.8 * (amount - 0.5))
    ratio = np.where(luminance > 1e-6, sharpened / np.maximum(luminance, 1e-6), 1.0)[..., None]
    lin = np.clip(lin * ratio, 0, None)
    lin /= max(float(np.percentile(lin, 99.99)) * 1.02, 1.0)  # only scale down if sharpening overshot
    after = estimate_moon_psf(lin.mean(axis=2), mask)
    out = lin if linear else linear_to_srgb(lin)
    return np.clip(out, 0, 1).astype(np.float32), before, after


def _report(clips, stats, selected, side, used_ecc, seconds, local_align) -> dict:
    used = {(s.clip, s.index) for s in selected}
    per_clip = []
    for ci, clip in enumerate(clips):
        frames = [s for s in stats if s.clip == ci]
        usable = [s for s in frames if s.usable]
        rejected: dict[str, int] = {}
        for s in frames:
            if not s.usable:
                rejected[s.reason] = rejected.get(s.reason, 0) + 1
        per_clip.append({
            "name": clip.name,
            "frames": len(frames),
            "usable": len(usable),
            "used": sum(1 for s in frames if (ci, s.index) in used),
            "raw": clip.bayer is not None,
            "rejected": rejected,
        })
    qualities = np.array([s.quality for s in stats if s.usable])
    spread = float(qualities.max() / np.median(qualities)) if len(qualities) else 1.0
    return {
        "clips": per_clip,
        "frames_used": len(selected),
        "frames_total": len(stats),
        "quality_spread": spread,
        "size": side,
        "ecc_aligned": used_ecc,
        "local_align": local_align,
        "seconds": round(seconds, 1),
        "linear": clips[0].linear,
    }


def stack_notes(report: dict) -> list[str]:
    """Plain-language feedback on the capture, like the editor's moon notes."""
    notes = []
    used, total = report["frames_used"], report["frames_total"]
    notes.append(f"Stacked {used} of {total} frames in {report['seconds']:.0f} s.")
    if report.get("sharpen", 0) > 0 and report.get("psf_before"):
        wavelets = " plus wavelet sharpening" if report["sharpen"] > 0.5 else ""
        notes.append(
            f"Sharpened while stacking: deconvolution of the {report['psf_before']:.1f} px blur measured on the limb{wavelets}. "
            "Deblur and Sharpen in the editor start at 0 so it isn't sharpened twice."
        )
    if report["quality_spread"] < 1.3:
        usable = sum(c["usable"] for c in report["clips"])
        if used >= 0.6 * usable:
            notes.append(
                "Sharpness barely varied between frames (steady seeing, small aperture), so keeping most of them "
                "costs no detail and lowers the noise."
            )
        else:
            notes.append(
                f"Sharpness barely varied between frames, so keeping only {used / max(usable, 1):.0%} of them gained no "
                "detail but left more noise: try keeping 70% or more."
            )
    for clip in report["clips"]:
        lost = clip["frames"] - clip["usable"]
        if clip["frames"] and lost > 0.2 * clip["frames"]:
            reasons = ", ".join(f"{n} {r}" for r, n in clip["rejected"].items())
            notes.append(f"{clip['name']}: {lost} frames skipped ({reasons}).")
    if not report["linear"]:
        notes.append("This video was already processed by the telescope; for the best result record in RAW (.avi) mode.")
    return notes


def save_stack(result: StackResult, path: str, report: Optional[dict] = None) -> str:
    """
    Write the stack as 16-bit: FITS for linear data (the editor treats FITS as linear),
    PNG for tone-mapped video. Returns the path written (extension chosen to match).
    """
    data = np.clip(result.image * 65535.0 + 0.5, 0, 65535).astype(np.uint16)
    target = Path(path).with_suffix(".fits" if result.linear else ".png")
    if result.linear:
        import astropy.io.fits as fits
        hdu = fits.PrimaryHDU(np.moveaxis(data, -1, 0))
        hdu.header["CREATOR"] = "AstroSlide video stacker"
        if report:
            hdu.header["STACKCNT"] = (report["frames_used"], "frames stacked")
            hdu.header["FRAMES"] = (report["frames_total"], "frames analysed")
        hdu.writeto(target, overwrite=True)
    else:
        cv2.imwrite(str(target), cv2.cvtColor(data, cv2.COLOR_RGB2BGR))
    return str(target)


def main():
    parser = argparse.ArgumentParser(description="Stack Moon videos (lucky imaging)")
    parser.add_argument("videos", nargs="+")
    parser.add_argument("-o", "--output", default="stack.fits")
    parser.add_argument("--keep", type=float, default=0.7)
    parser.add_argument("--no-local", action="store_true", help="skip optical-flow local alignment")
    parser.add_argument("--sharpen", type=float, default=0.5, help="post-stack sharpening, 0-1 (0 = none, 0.5 = faithful)")
    args = parser.parse_args()

    def show(fraction, message):
        print(f"\r{fraction * 100:5.1f}%  {message:<50}", end="", flush=True)

    result = stack_videos(args.videos, keep=args.keep, local_align=not args.no_local, sharpen=args.sharpen, progress=show)
    print()
    written = save_stack(result, args.output, result.report)
    for note in stack_notes(result.report):
        print(" -", note)
    print("Wrote", written)


if __name__ == "__main__":
    main()
