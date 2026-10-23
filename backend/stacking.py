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
6. Subtract the glow that haze or dew scatters around the disk (a modelled background)
7. Sharpen, as every lucky-imaging workflow ends (AutoStakkert -> RegiStax wavelets):
   the stack's low noise is what allows it. Richardson-Lucy deconvolution with the
   blur measured from the limb, then wavelet sharpening (the editor's moon tools)

Raw sensor video (8-bit Bayer, linear light) is stacked as linear data by Bayer
drizzle (each frame's real red, green and blue samples placed straight onto the
output grid, no per-frame demosaicing) and saved as 16-bit FITS; H.264 video is already tone-mapped, so its stack is
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
from scipy.optimize import nnls

from presets import (estimate_moon_psf, find_moon_mask, linear_to_srgb, moon_deconvolve,
                     moon_sharpen, srgb_to_linear)

# The raw AVI's pal8 format makes OpenCV warn on every frame; the data is read correctly
cv2.setLogLevel(2)  # errors only

VIDEO_EXTENSIONS = ('.avi', '.mp4', '.mov', '.mkv')
# Larger frames are refused (unset = no limit); stacking memory grows with frame size
MAX_FRAME_PIXELS = int(float(os.environ.get("ASTROSLIDE_MAX_VIDEO_MEGAPIXELS", "0")) * 1_000_000)

# Sensor CFA order -> OpenCV conversion (OpenCV names the pattern one pixel shifted).
# Seestar S30/S50 sensors are GRBG; most planetary cameras (ZWO, Player One, Dwarf) RGGB.
BAYER_CODES = {
    "GRBG": cv2.COLOR_BayerGB2RGB,
    "RGGB": cv2.COLOR_BayerBG2RGB,
    "BGGR": cv2.COLOR_BayerRG2RGB,
    "GBRG": cv2.COLOR_BayerGR2RGB,
}
# Frames probed for the CFA pattern (the first ones may miss the Moon)
BAYER_PROBE_FRAMES = 10
# Red and blue sites can't be told apart by position, only by brightness: the Moon is
# reddish, so in unbalanced raw data red reads well above blue. Seestar raw is already
# white-balanced (blue/red measured 0.8-1.1), so the usual layout for where the greens
# sit is kept unless the supposed blue site is this much brighter than the supposed red.
RED_BLUE_SWAP_RATIO = 1.4

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


def open_clip(path: str, bayer: Optional[str] = None, name: Optional[str] = None) -> Clip:
    """
    Probe a video: frame count, and whether it holds raw Bayer data and in which CFA
    pattern (`bayer` overrides the detected one). `name` is shown to the user.
    """
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
        # AVI and MP4 carry no CFA tag, so the pattern is read from the frames themselves
        pattern = None
        probe = frame
        for _ in range(BAYER_PROBE_FRAMES):
            means = _site_means(probe)
            if means is not None:
                pattern = _bayer_pattern(means)
                break
            if probe.ndim == 3 and not _is_grey(probe):
                break  # colour video
            ok, probe = cap.read()
            if not ok:
                break
    finally:
        cap.release()

    if MAX_FRAME_PIXELS and frame.shape[0] * frame.shape[1] > MAX_FRAME_PIXELS:
        raise ValueError(
            f"{name} is {frame.shape[1]}x{frame.shape[0]}; this server stacks videos up to "
            f"{MAX_FRAME_PIXELS / 1e6:g} megapixels per frame"
        )

    if pattern and bayer:
        pattern = bayer
    return Clip(path=path, name=name, frame_count=frame_count, fps=fps,
                width=frame.shape[1], height=frame.shape[0],
                bayer=pattern, linear=pattern is not None)


def _is_grey(frame: np.ndarray) -> bool:
    return np.array_equal(frame[..., 0], frame[..., 1]) and np.array_equal(frame[..., 1], frame[..., 2])


def _site_means(frame: np.ndarray) -> Optional[list[float]]:
    """
    Mean brightness of the four 2x2 cell sites (top-left, top-right, bottom-left,
    bottom-right) over the bright subject; None for colour video or too little subject.
    """
    if frame.ndim == 3 and not _is_grey(frame):
        return None
    grey = frame[..., 0] if frame.ndim == 3 else frame
    h, w = grey.shape[0] // 2 * 2, grey.shape[1] // 2 * 2
    sites = [grey[dy:h:2, dx:w:2].astype(np.float32) for dy, dx in ((0, 0), (0, 1), (1, 0), (1, 1))]
    bright = (sites[0] + sites[1] + sites[2] + sites[3]) > 4 * 0.3 * float(grey.max())
    if bright.sum() < 500:
        return None
    return [float(s[bright].mean()) for s in sites]


def _bayer_pattern(means: list[float]) -> Optional[str]:
    """
    The CFA pattern from the site means, or None for mono video. A raw colour-sensor
    frame is grey with a 2x2 pattern: the two green sites of each cell, on one diagonal,
    agree, while red and blue on the other differ from each other.
    """
    top_left, top_right, bottom_left, bottom_right = means
    mean = sum(means) / 4
    if abs(top_left - bottom_right) < 0.01 * mean and abs(top_right - bottom_left) > 0.03 * mean:
        red, blue, usual, swapped = top_right, bottom_left, "GRBG", "GBRG"
    elif abs(top_right - bottom_left) < 0.01 * mean and abs(top_left - bottom_right) > 0.03 * mean:
        red, blue, usual, swapped = top_left, bottom_right, "RGGB", "BGGR"
    else:
        return None
    return swapped if blue > RED_BLUE_SWAP_RATIO * red else usual


def iter_frames(clip: Clip, wanted: Optional[set] = None, mosaic: bool = False) -> Iterator[tuple[int, np.ndarray]]:
    """
    Yield (index, uint8 RGB frame); with `wanted`, decode only those indices.
    With `mosaic`, raw clips yield the undemosaiced sensor frame (H, W) instead.
    """
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
                yield index, frame[..., 0] if mosaic else cv2.cvtColor(frame[..., 0], BAYER_CODES[clip.bayer])
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


def _bayer_masks(pattern: str, height: int, width: int, y0: int = 0, x0: int = 0) -> np.ndarray:
    """
    (H, W, 3) float32 for the sensor region starting at (y0, x0): 1 where the pixel
    samples that RGB channel, else 0. Built per region, not kept for the whole frame.
    """
    masks = np.zeros((height, width, 3), np.float32)
    for (dy, dx), colour in zip(((0, 0), (0, 1), (1, 0), (1, 1)), pattern):
        masks[(dy - y0) % 2::2, (dx - x0) % 2::2, "RGB".index(colour)] = 1.0
    return masks


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
    bayer: Optional[str] = None,
    progress: Optional[Progress] = None,
    names: Optional[list[str]] = None,
    bayer_drizzle: bool = True,
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
        bayer: CFA pattern for raw sensor video (RGGB, BGGR, GRBG, GBRG); None = detect
        bayer_drizzle: raw video only: place each frame's real red, green and blue sensor
            samples onto the output grid instead of demosaicing every frame (see align_one)
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

        drizzle = bayer_drizzle and clips[0].linear

        def align_one(frame: np.ndarray, s: FrameStats):
            rgb = cv2.cvtColor(frame, BAYER_CODES[clips[s.clip].bayer]) if drizzle else frame
            grey = _normalized(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), s.sky, s.level)
            transform, ecc_ok = aligner.global_transform(grey, s)
            map_x, map_y = aligner.maps(grey, transform)
            # Convert only the part of the frame the crop samples (plus the kernel's reach)
            h, w = rgb.shape[:2]
            x0, y0 = max(0, int(map_x.min()) - 3), max(0, int(map_y.min()) - 3)
            x1, y1 = min(w, int(map_x.max()) + 4), min(h, int(map_y.max()) + 4)
            map_x -= x0
            map_y -= y0
            if drizzle:
                # Bayer drizzle: each channel is resampled from that channel's own sensor
                # pixels only, weighted by the bilinear kernel, and the weights are summed
                # alongside. Demosaicing would interpolate the missing colours first and the
                # alignment would resample again (two blurs); here the jitter between frames
                # fills every output pixel with real samples of all three colours.
                site = _bayer_masks(clips[s.clip].bayer, y1 - y0, x1 - x0, y0, x0)
                samples = _normalized(frame[y0:y1, x0:x1], s.sky, s.level)[..., None] * site
                warped = cv2.remap(samples, map_x, map_y, cv2.INTER_LINEAR, borderValue=0)
                weight = cv2.remap(site, map_x, map_y, cv2.INTER_LINEAR, borderValue=0)
                return warped, weight, ecc_ok
            roi = _normalized(rgb[y0:y1, x0:x1], s.sky, s.level)
            warped = cv2.remap(roi, map_x, map_y, INTERPOLATION, borderValue=np.nan)
            # Crop pixels outside the frame are NaN: count coverage, then zero them
            valid = np.isfinite(warped[..., 0])
            warped[~valid] = 0
            return warped, valid.astype(np.float32)[..., None], ecc_ok

        by_clip: dict[int, dict[int, FrameStats]] = {}
        for s in selected:
            by_clip.setdefault(s.clip, {})[s.index] = s
        jobs = (
            (rgb, frames[index])
            for ci, frames in by_clip.items()
            for index, rgb in iter_frames(clips[ci], set(frames), mosaic=drizzle)
        )
        total = np.zeros((side, side, 3), np.float32)
        coverage = np.zeros((side, side, 3 if drizzle else 1), np.float32)
        used_ecc = processed = 0
        for warped, valid, ecc_ok in _pipelined(pool, jobs, align_one, 2 * workers):
            total += warped
            coverage += valid
            used_ecc += ecc_ok
            processed += 1
            if processed % 10 == 0:
                report_progress(0.35 + 0.65 * processed / len(selected), f"Stacking frame {processed} of {len(selected)}")

    # Coverage is a per-channel sum of kernel weights with drizzle, else a frame count
    stack = np.where(coverage > 1e-3, total / np.maximum(coverage, 1e-3), 0).astype(np.float32)
    stack = np.clip(stack, 0, None)
    stack /= max(float(np.percentile(stack, 99.99)), 1e-6) * 1.02  # disk median was 1; use the range
    stack = np.clip(stack, 0, 1)
    # Before sharpening, so the limb's blur is measured without the glow on it
    stack, glow = remove_sky_glow(stack, coverage.max(axis=2) > 1e-3, clips[0].linear)
    report_progress(0.99, "Sharpening")
    stack, psf_before, psf_after = sharpen_stack(stack, sharpen, clips[0].linear)
    # Stacking works on the crop to save time; the result goes back onto a frame the
    # size of the video, the Moon where the sharpest frame had it, so it isn't zoomed in
    anchor = selected[0]
    stack = _place_in_frame(stack, anchor.center, clips[anchor.clip].width, clips[anchor.clip].height)

    report = _report(clips, stats, selected, side, used_ecc, time.perf_counter() - started, local_align)
    report.update(sharpen=sharpen, psf_before=psf_before, psf_after=psf_after, bayer_chosen=bayer is not None,
                  glow=glow)
    report_progress(1.0, "Done")
    return StackResult(stack, clips[0].linear, report)


def _place_in_frame(crop: np.ndarray, center: tuple, width: int, height: int) -> np.ndarray:
    """The crop pasted onto a black (sky-subtracted) width x height frame, centred on `center`."""
    side = crop.shape[0]
    x0, y0 = int(round(center[0] - side / 2)), int(round(center[1] - side / 2))
    frame = np.zeros((height, width, crop.shape[2]), np.float32)
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(width, x0 + side), min(height, y0 + side)
    frame[fy0:fy1, fx0:fx1] = crop[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
    return frame


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


def _wide_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur; wide ones run on a downscaled copy (same result, a fraction of the time)."""
    scale = max(1, int(sigma / 6))
    if scale == 1:
        return cv2.GaussianBlur(image, (0, 0), sigma)
    h, w = image.shape[:2]
    small = cv2.resize(image, (max(1, w // scale), max(1, h // scale)), interpolation=cv2.INTER_AREA)
    return cv2.resize(cv2.GaussianBlur(small, (0, 0), sigma / scale), (w, h), interpolation=cv2.INTER_LINEAR)


def _limb_circle(luminance: np.ndarray, mask: np.ndarray, hull_only: bool = False) -> Optional[tuple[float, float, float]]:
    """
    (cx, cy, r) of the full disk, fitted to the sunlit limb only (the terminator isn't on it).
    hull_only also drops outline that isn't on the lit area's convex hull: a crescent's
    terminator can be as sharp and bright as the limb, but it curves the other way.
    """
    edge = mask & ~cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if hull_only:
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        hull = np.zeros(mask.shape, np.uint8)
        cv2.fillPoly(hull, [cv2.convexHull(np.vstack(contours))], 1)
        edge &= cv2.distanceTransform(hull, cv2.DIST_L2, 3) <= 2.5
    moon = mask.astype(np.float32)
    inside = cv2.blur(luminance * moon, (15, 15)) / np.maximum(cv2.blur(moon, (15, 15)), 1e-3)
    if edge.sum() < 50:
        return None
    # Relative to the brightest stretch of outline, not the disk: the limb can be darker
    # than the centre, and the terminator is far dimmer than either
    ys, xs = np.nonzero(edge & (inside > 0.6 * np.percentile(inside[edge], 90)))
    if len(xs) < 50:
        return None
    return _fit_circle(xs.astype(np.float64), ys.astype(np.float64))


def _fit_circle(xs: np.ndarray, ys: np.ndarray) -> Optional[tuple[float, float, float]]:
    """(cx, cy, r) through outline points, robust to a few stray ones; None if too few agree."""
    keep = np.ones(len(xs), bool)
    for _ in range(4):
        # Algebraic circle fit, then drop outliers (a crater on the limb, a stray terminator bit)
        a = np.column_stack([xs[keep], ys[keep], np.ones(keep.sum())])
        (bx, by, c), *_ = np.linalg.lstsq(a, xs[keep] ** 2 + ys[keep] ** 2, rcond=None)
        cx, cy = bx / 2, by / 2
        r = float(np.sqrt(max(c + cx ** 2 + cy ** 2, 0)))
        residual = np.abs(np.hypot(xs - cx, ys - cy) - r)
        keep = residual < max(2.0, 3 * float(np.median(residual[keep])))
        if keep.sum() < 30:
            return None
    return float(cx), float(cy), r


def remove_sky_glow(image: np.ndarray, covered: np.ndarray, linear: bool) -> tuple[np.ndarray, Optional[float]]:
    """
    Subtract the glow of moonlight scattered by haze, thin cloud or dew on the lens.

    Seestar raw video already clips the dark sky to 0, so the frame-wide sky level the
    frames are normalized by is 0, but a hazy night leaves a wide glow around the disk
    (measured 2026-10-23: 10% of the disk's brightness at the limb, 4% 60 px out). The
    display stretch makes it a grey box, cut off where the crop meets the black frame.
    The glow is modelled as the lit disk blurred by a few wide Gaussians, fitted per
    channel to the sky beyond the full disk (a circle through the sunlit limb: beside
    the terminator the pixels past the mask are dim surface, not sky), and subtracted
    everywhere outside the lit surface, the Moon's dark side included.

    Args:
        image: stack (H, W, 3), 0-1; linear, or tone-mapped when `linear` is False
        covered: pixels the frames covered (the rest is padding, left out of the fit)
        linear: whether `image` is linear light

    Returns:
        (image, glow 3-8 px beyond the bright limb as a fraction of the disk median, or
        None when no glow was modelled)
    """
    lin = image if linear else srgb_to_linear(image)
    luminance = lin.mean(axis=2)
    mask = find_moon_mask(luminance)
    if mask.sum() < 500:
        return image, None
    circle = _limb_circle(luminance, mask)
    if circle is None:
        return image, None
    diameter = 2 * np.sqrt(mask.sum() / np.pi)
    ys, xs = np.mgrid[:mask.shape[0], :mask.shape[1]]
    beyond = np.hypot(xs - circle[0], ys - circle[1]) - circle[2]
    fit = (beyond > 3) & covered
    fit[::2] = False  # a quarter of the sky pixels is plenty for 5 coefficients
    fit[:, ::2] = False
    if fit.sum() < 500:
        return image, None

    # Beside the bright limb the sky starts right at the edge; beside the terminator the
    # surface fades out gradually past the mask, so the subtraction fades in over `feather`
    moon = mask.astype(np.float32)
    sigma = max(1.5, diameter / 50)
    level = np.where(mask, cv2.GaussianBlur(luminance * moon, (0, 0), sigma)
                     / np.maximum(cv2.GaussianBlur(moon, (0, 0), sigma), 1e-3), 0).astype(np.float32)
    feather = max(4.0, 0.03 * diameter)
    reach = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * feather) | 1,) * 2)
    bright = float(np.percentile(luminance[mask], 99))
    dist = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)

    def smoothstep(x):
        x = np.clip(x, 0, 1)
        return x * x * (3 - 2 * x)

    near_limb = smoothstep((cv2.dilate(level, reach) / bright - 0.35) / 0.25)
    weight = (near_limb * smoothstep(dist / 1.5) + (1 - near_limb) * smoothstep(dist / feather)) * ~mask

    out = lin.copy()
    for c in range(3):
        basis = np.stack([_wide_blur(lin[..., c] * moon, f * diameter) for f in (0.01, 0.03, 0.08, 0.2, 0.5)], -1)
        coefficients, _ = nnls(basis[fit].astype(np.float64), lin[..., c][fit].astype(np.float64))
        model = basis @ coefficients.astype(np.float32)
        out[..., c] -= weight * np.minimum(model, lin[..., c])
        del basis, model

    band = (dist > 3) & (dist < 8) & (near_limb > 0.9) & covered
    disk = float(np.median(luminance[mask]))
    glow = float(np.median(luminance[band])) / disk if band.any() and disk > 0 else None
    return (out if linear else linear_to_srgb(out)).astype(np.float32), glow


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


def _half_sensor(width: int, height: int) -> bool:
    """A 2x2-binned frame from a 1080x1920 Seestar sensor (536x960 once aligned), either orientation."""
    short, long = sorted((width, height))
    return abs(2 * short - 1080) <= 16 and abs(2 * long - 1920) <= 16


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
            "width": clip.width,
            "height": clip.height,
            "frames": len(frames),
            "usable": len(usable),
            "used": sum(1 for s in frames if (ci, s.index) in used),
            "raw": clip.bayer is not None,
            "bayer": clip.bayer,
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
            "Deblur and Sharpen in the editor start at settings tuned for stacks."
        )
    if (report.get("glow") or 0) >= 0.02:
        notes.append(
            f"Removed a glow around the Moon ({report['glow']:.0%} of its brightness just off the limb): moonlight "
            "scattered by haze, thin cloud or dew on the lens. It also lowers contrast on the disk, so clearer "
            "nights give crisper stacks."
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
    binned = [c for c in report["clips"] if c.get("raw") and _half_sensor(c.get("width", 0), c.get("height", 0))]
    if binned:
        c = binned[0]
        notes.append(
            f"{'These RAW videos are' if len(binned) > 1 else 'This RAW video is'} {c['width']}x{c['height']}, half of the "
            f"sensor's {'1080x1920' if c['width'] < c['height'] else '1920x1080'}: the telescope combined each 2x2 block of pixels. "
            "Recording RAW at full resolution resolves finer detail (about 1.5-2x on a steady night), "
            "with files 4x larger."
        )
    # Telling red from blue is the uncertain part of detecting the CFA pattern
    detected = sorted({c["bayer"] for c in report["clips"] if c.get("bayer")})
    if detected and detected != ["GRBG"] and not report.get("bayer_chosen"):
        notes.append(
            f"Colour pattern detected as {' and '.join(detected)}. If red and blue look swapped, or the colours are "
            "off, choose your camera's pattern under Colour pattern and stack again."
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
    parser.add_argument("--bayer", choices=sorted(BAYER_CODES), help="CFA pattern of raw video (default: detect)")
    args = parser.parse_args()

    def show(fraction, message):
        print(f"\r{fraction * 100:5.1f}%  {message:<50}", end="", flush=True)

    result = stack_videos(args.videos, keep=args.keep, local_align=not args.no_local, sharpen=args.sharpen,
                          bayer=args.bayer, progress=show)
    print()
    written = save_stack(result, args.output, result.report)
    for note in stack_notes(result.report):
        print(" -", note)
    print("Wrote", written)


if __name__ == "__main__":
    main()
