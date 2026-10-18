"""
Golden-image regression harness.

Runs every processing path (presets, stretches, auto-STF, Pro Mode, star removal)
on a fixed set of inputs and compares the results with saved baselines, so
refactors can't silently change output quality.

Usage (from backend/):
    python tests/regression.py --update     # record current outputs as baselines
    python tests/regression.py              # compare against baselines, write report
    python tests/regression.py --only moon  # run cases whose name contains "moon"

Then open tests/regression_data/report.html to review changes side by side.
Exit code is 1 if any case changed, broke, or is missing a baseline.
"""

import argparse
import html
import io
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "tests"))

from main import decode_image, decode_image_float  # noqa: E402
from presets import (  # noqa: E402
    PRESETS,
    apply_interactive_stretch,
    compute_auto_stf,
    enhance_with_preset,
)
from synthetic import linear_to_srgb, make_linear_deep_sky, make_synthetic_moon, to_fits_bytes  # noqa: E402

REPO_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "tests" / "regression_data"
BASELINE_DIR = DATA_DIR / "baselines"
OUTPUT_DIR = DATA_DIR / "output"

# Real inputs are downscaled so a full run stays fast enough to use on every change
MAX_INPUT_SIZE = 1200
# Mean absolute difference (0-255 levels) above which a case counts as changed
CHANGE_THRESHOLD = 0.5


def _downscaled_png_bytes(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_INPUT_SIZE, MAX_INPUT_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def load_inputs() -> dict[str, tuple[bytes, str]]:
    """Returns {input_name: (file_bytes, filename)}; filename drives decode_image."""
    linear = make_linear_deep_sky()
    moon = make_synthetic_moon()
    moon_png = io.BytesIO()
    Image.fromarray((linear_to_srgb(moon["linear"]) * 255 + 0.5).astype(np.uint8)).save(moon_png, format="PNG")
    inputs = {
        "synthetic_moon_png": (moon_png.getvalue(), "moon.png"),
        "synthetic_moon_fits": (to_fits_bytes(moon["linear"], color=True), "moon.fits"),
        "seestar_m45_jpeg": (_downscaled_png_bytes(REPO_DIR / "samples/seestar_m45.jpg"), "m45.png"),
        "seestar_m83_jpeg": (_downscaled_png_bytes(REPO_DIR / "samples/seestar_m83.jpg"), "m83.png"),
        "linear_mono_fits": (to_fits_bytes(linear, color=False), "mono.fits"),
        "linear_color_fits": (to_fits_bytes(linear, color=True), "color.fits"),
        # Real FITS: survey cutout of M13 (mono int16) and a Seestar S30 lunar video stack (color uint16)
        "seestar_lunar_fits": (REPO_DIR / "samples/seestar_lunar_video_stack.fit", "lunar.fit"),
        "m13_fits": (REPO_DIR / "samples/m13.fits", "m13.fits"),
        "seestar_full_moon_jpeg": (REPO_DIR / "samples/Video_Stacked_Lunar_20260502-220552.JPG", "full_moon.jpg"),
    }
    # Real FITS samples are large and may not be present on every machine
    for name, (source, filename) in list(inputs.items()):
        if isinstance(source, Path):
            if source.exists():
                inputs[name] = (source.read_bytes(), filename)
            else:
                print(f"skipping {name}: {source.name} not found")
                del inputs[name]
    return inputs


# Each operation receives the decoded input the same way the API endpoints see it:
# ctx = {"u8": uint8 RGB, "float": float32 RGB at full bit depth, "display_referred": not FITS}

def _preset(name: str, **kwargs):
    return lambda ctx: enhance_with_preset(
        ctx["u8"], name, 0.75, img_float=ctx["float"], display_referred=ctx["display_referred"], **kwargs
    )


def _stretch(**params):
    return lambda ctx: apply_interactive_stretch(ctx["float"], **params)


def _auto_stf_stretch(ctx: dict) -> np.ndarray:
    return apply_interactive_stretch(ctx["float"], **compute_auto_stf(ctx["float"]))


OPERATIONS = {
    **{f"preset_{name}": _preset(name) for name in PRESETS},
    "pro_mode": _preset("nebula", adjustments={"denoise": 0.5, "star_reduction": 0.4, "saturation": 1.4, "sharpening": 0.5}),
    "stretch_mtf": _stretch(shadows=0.02, midtones=0.2, highlights=1.0),
    "stretch_auto_stf": _auto_stf_stretch,
    "stretch_remove_stars": _stretch(shadows=0.02, midtones=0.2, highlights=1.0, remove_stars_flag=True),
}


def run_case(ctx: dict, operation) -> tuple[np.ndarray, float]:
    start = time.perf_counter()
    result = operation(ctx)
    return result, time.perf_counter() - start


def save_png(img: np.ndarray, path: Path) -> None:
    Image.fromarray(img).save(path, format="PNG")


def load_png(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def compare(current: np.ndarray, baseline: np.ndarray) -> dict:
    if current.shape != baseline.shape:
        return {"mean_diff": None, "max_diff": None, "note": f"shape {baseline.shape} -> {current.shape}"}
    diff = np.abs(current.astype(np.int16) - baseline.astype(np.int16))
    return {"mean_diff": float(diff.mean()), "max_diff": int(diff.max()), "note": ""}


def write_report(rows: list[dict], path: Path) -> None:
    status_order = {"broke": 0, "changed": 1, "fixed": 2, "new": 3, "error": 4, "same": 5}
    rows = sorted(rows, key=lambda r: (status_order[r["status"]], r["case"]))

    def thumb(src: str) -> str:
        return f'<img src="{src}" loading="lazy">' if src else "<span class=none>—</span>"

    body = []
    for row in rows:
        diff = "" if row.get("mean_diff") is None else f'{row["mean_diff"]:.2f} / {row["max_diff"]}'
        detail = html.escape(row.get("error") or row.get("note") or "")
        body.append(
            f'<tr class="{row["status"]}"><td><b>{html.escape(row["case"])}</b><br>'
            f'<span class=status>{row["status"]}</span> {diff}<br><small>{detail}</small>'
            f'<br><small>{row.get("time", 0):.2f}s (baseline {row.get("baseline_time", 0):.2f}s)</small></td>'
            f'<td>{thumb(row.get("baseline_src", ""))}</td><td>{thumb(row.get("output_src", ""))}</td></tr>'
        )
    path.write_text(f"""<!doctype html><meta charset=utf-8><title>Regression report</title>
<style>
body {{ font: 14px system-ui, sans-serif; background: #111; color: #ddd; margin: 16px; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border-bottom: 1px solid #333; padding: 8px; vertical-align: top; text-align: left; }}
td:first-child {{ width: 260px; }}
img {{ max-width: 100%; max-height: 360px; }}
.status {{ text-transform: uppercase; font-weight: 700; }}
.broke .status, .error .status {{ color: #f87171; }}
.changed .status {{ color: #fbbf24; }}
.fixed .status, .new .status {{ color: #4ade80; }}
.same .status {{ color: #888; }}
.none {{ color: #555; }}
</style>
<h1>Regression report</h1>
<p>Diff = mean / max absolute difference in 0-255 levels; changed above {CHANGE_THRESHOLD}.</p>
<table><tr><th>Case</th><th>Baseline</th><th>Current</th></tr>{''.join(body)}</table>""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="record current outputs as the new baselines")
    parser.add_argument("--only", default="", help="only run cases whose name contains this text")
    args = parser.parse_args()

    target_dir = BASELINE_DIR if args.update else OUTPUT_DIR
    if args.update and not args.only and BASELINE_DIR.exists():
        shutil.rmtree(BASELINE_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = BASELINE_DIR / "manifest.json"
    baseline_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    new_manifest = dict(baseline_manifest) if args.update else {}

    rows = []
    for input_name, (file_bytes, filename) in load_inputs().items():
        try:
            img = decode_image(file_bytes, filename)
            img_float = decode_image_float(file_bytes, filename)
            decode_error = None
            # A malformed array can crash OpenCV natively (SIGBUS), so reject it up front
            if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] != 3:
                decode_error = f"decoded to dtype={img.dtype} shape={img.shape}, expected (H, W, 3) uint8"
        except Exception as exc:  # decode_image raises HTTPException with a detail message
            img, img_float, decode_error = None, None, getattr(exc, "detail", str(exc))

        for op_name, operation in OPERATIONS.items():
            case = f"{input_name}__{op_name}"
            if args.only and args.only not in case:
                continue

            entry = {"case": case}
            try:
                if decode_error:
                    raise RuntimeError(f"decode failed: {decode_error}")
                ctx = {
                    "u8": img.copy(),
                    "float": img_float.copy(),
                    "display_referred": not filename.lower().endswith((".fits", ".fit")),
                }
                result, elapsed = run_case(ctx, operation)
                if result.dtype != np.uint8 or result.ndim != 3 or result.shape[2] != 3:
                    raise RuntimeError(f"bad output: dtype={result.dtype} shape={result.shape}")
                save_png(result, target_dir / f"{case}.png")
                entry.update(ok=True, time=elapsed)
            except Exception as exc:
                last_line = traceback.format_exception_only(type(exc), exc)[-1].strip()
                entry.update(ok=False, error=last_line, time=0.0)

            if args.update:
                new_manifest[case] = {k: v for k, v in entry.items() if k != "case"}
                print(f"{'ok   ' if entry['ok'] else 'ERROR'} {case} {entry.get('error', '')}")
                continue

            baseline = baseline_manifest.get(case)
            entry["baseline_time"] = (baseline or {}).get("time", 0.0)
            if entry["ok"]:
                entry["output_src"] = f"output/{case}.png"
            if baseline and baseline["ok"]:
                entry["baseline_src"] = f"baselines/{case}.png"

            if baseline is None:
                entry["status"] = "new" if entry["ok"] else "error"
            elif not baseline["ok"] and not entry["ok"]:
                entry["status"] = "error"
            elif not baseline["ok"]:
                entry["status"] = "fixed"
            elif not entry["ok"]:
                entry["status"] = "broke"
            else:
                entry.update(compare(load_png(target_dir / f"{case}.png"), load_png(BASELINE_DIR / f"{case}.png")))
                changed = entry["mean_diff"] is None or entry["mean_diff"] > CHANGE_THRESHOLD
                entry["status"] = "changed" if changed else "same"

            rows.append(entry)
            print(f"{entry['status']:8} {case} {entry.get('error') or entry.get('note') or ''}")

    if args.update:
        manifest_path.write_text(json.dumps(new_manifest, indent=2))
        print(f"\nBaselines written to {BASELINE_DIR}")
        return 0

    report_path = DATA_DIR / "report.html"
    write_report(rows, report_path)
    counts = {s: sum(r["status"] == s for r in rows) for s in ("same", "changed", "fixed", "broke", "new", "error")}
    print("\n" + ", ".join(f"{n} {s}" for s, n in counts.items() if n))
    print(f"Report: {report_path}")
    return 1 if counts["changed"] or counts["broke"] or counts["new"] else 0


if __name__ == "__main__":
    sys.exit(main())
