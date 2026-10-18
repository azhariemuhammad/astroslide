"""
Background jobs for video stacking.

Stacking takes from seconds to minutes and its uploads are large, so it runs as a
job: the upload is written to a job folder, a background thread stacks it, and the
client polls for progress and then downloads the result.

All job state lives on disk (status.json in the job folder), not in memory, so any
uvicorn worker process can answer a poll for a job started by another. Each process
stacks one video at a time; further jobs wait as "queued".
"""

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import stacking

JOBS_DIR = Path(os.environ.get("ASTROSLIDE_JOBS_DIR", Path(tempfile.gettempdir()) / "astroslide-jobs"))
# Finished jobs (and their results) are deleted after this long
JOB_TTL_SECONDS = 2 * 3600
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")

# One stacking job at a time per process: it already uses several cores, and
# frames from several videos at once would exhaust a small server's memory
_runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stack-job")


def new_job() -> tuple[str, Path]:
    cleanup_old_jobs()
    job_id = uuid.uuid4().hex
    folder = JOBS_DIR / job_id
    (folder / "input").mkdir(parents=True)
    write_status(folder, state="uploading", progress=0.0, message="Uploading")
    return job_id, folder


def job_folder(job_id: str) -> Optional[Path]:
    """The job's folder, or None for an unknown or malformed id (never a path outside JOBS_DIR)."""
    if not _JOB_ID.match(job_id):
        return None
    folder = JOBS_DIR / job_id
    return folder if (folder / "status.json").exists() else None


def write_status(folder: Path, **status) -> None:
    """Replace status.json atomically, so a concurrent poll never reads half a file."""
    status["updated"] = time.time()
    temporary = folder / "status.json.tmp"
    temporary.write_text(json.dumps(status))
    os.replace(temporary, folder / "status.json")


def read_status(folder: Path) -> dict:
    return json.loads((folder / "status.json").read_text())


def result_path(folder: Path) -> Optional[Path]:
    status = read_status(folder)
    name = status.get("result_file")
    return folder / name if status.get("state") == "done" and name else None


def submit(folder: Path, videos: list[Path], names: list[str], options: dict, output_stem: str) -> None:
    """Queue a stack; `options` are stacking.stack_videos keyword arguments (keep, sharpen, ...)."""
    write_status(folder, state="queued", progress=0.0, message="Waiting for the stacker")
    _runner.submit(_run, folder, videos, names, options, output_stem)


def _run(folder: Path, videos: list[Path], names: list[str], options: dict, output_stem: str) -> None:
    last_write = 0.0

    def progress(fraction: float, message: str) -> None:
        nonlocal last_write
        # Polls come about once a second; writing more often is wasted I/O
        now = time.monotonic()
        if now - last_write >= 0.5:
            last_write = now
            write_status(folder, state="running", progress=round(fraction, 3), message=message)

    try:
        progress(0.0, "Starting")
        result = stacking.stack_videos([str(v) for v in videos], progress=progress, names=names, **options)
        written = Path(stacking.save_stack(result, str(folder / output_stem), result.report))
        write_status(
            folder, state="done", progress=1.0, message="Done",
            result_file=written.name, linear=result.linear,
            notes=stacking.stack_notes(result.report), report=result.report,
        )
    except Exception as e:  # reported to the client; the job folder stays for the TTL
        write_status(folder, state="error", progress=0.0, message=str(e) or type(e).__name__)
    finally:
        # The videos are large and no longer needed
        shutil.rmtree(folder / "input", ignore_errors=True)


def cleanup_old_jobs() -> None:
    if not JOBS_DIR.exists():
        return
    cutoff = time.time() - JOB_TTL_SECONDS
    for folder in JOBS_DIR.iterdir():
        try:
            if not folder.is_dir() or folder.stat().st_mtime >= cutoff:
                continue
            fresh = read_status(folder).get("updated", 0) >= cutoff
        except (OSError, ValueError):
            fresh = False  # old folder without a readable status: abandoned
        if not fresh:
            shutil.rmtree(folder, ignore_errors=True)
