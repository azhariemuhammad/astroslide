"""
Background jobs for video stacking.

Stacking takes from seconds to minutes and its uploads are large, so it runs as a
job: the upload is written to a job folder, a background thread stacks it, and the
client polls for progress and then downloads the result.

Large videos are uploaded in chunks (new_upload, then one request per chunk, then
finish_upload): each request stays short, so router timeouts and dropped connections
cost one retried chunk instead of the whole upload.

All job state lives on disk (status.json in the job folder), not in memory, so any
uvicorn worker process can answer a poll for a job started by another. Each process
stacks one video at a time; further jobs wait as "queued".

A job can be cancelled at any stage. That too goes through the folder (a "cancel"
file), since the request may reach a different process than the one stacking.
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
# A chunked upload that receives nothing for this long is abandoned (it holds a job slot)
UPLOAD_IDLE_SECONDS = 15 * 60
# Largest chunk accepted: ~16 s at 1 MB/s, well inside a router's request timeout
CHUNK_BYTES = 16 * 1024 ** 2

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


def active_jobs() -> int:
    """Jobs uploading, queued or running (finished ones only wait for their download)."""
    if not JOBS_DIR.exists():
        return 0
    cleanup_old_jobs()  # abandoned uploads would otherwise hold their slot
    count = 0
    for folder in JOBS_DIR.iterdir():
        try:
            count += read_status(folder).get("state") in ("uploading", "queued", "running")
        except (OSError, ValueError):
            pass
    return count


def cancel(folder: Path) -> dict:
    """
    Abandon the job: an upload stops accepting chunks and its files are deleted; a
    queued stack never starts; a running one stops at its next progress step.
    Finished jobs are left as they are. Returns the job's status.
    """
    status = read_status(folder)
    if status.get("state") not in ("uploading", "queued", "running"):
        return status
    (folder / "cancel").touch()
    if status.get("state") == "uploading":
        shutil.rmtree(folder / "input", ignore_errors=True)
    # Queued and running jobs delete their input themselves once the runner lets go of it
    write_status(folder, state="cancelled", progress=0.0, message="Cancelled")
    return read_status(folder)


def _cancelled(folder: Path) -> bool:
    return (folder / "cancel").exists()


class Cancelled(Exception):
    pass


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


def new_upload(files: list[tuple[str, int]], options: dict, output_stem: str) -> tuple[str, Path]:
    """Start a chunked upload of `files` (name, size); stacked with `options` once complete."""
    job_id, folder = new_job()
    manifest = {
        "files": [{"name": name, "size": size, "path": f"{i:02d}{Path(name).suffix.lower()}"}
                  for i, (name, size) in enumerate(files)],
        "options": options,
        "output_stem": output_stem,
    }
    (folder / "upload.json").write_text(json.dumps(manifest))
    return job_id, folder


def upload_manifest(folder: Path) -> Optional[dict]:
    """The chunked upload's manifest, or None if the job isn't a chunked upload still receiving files."""
    try:
        if read_status(folder).get("state") != "uploading":
            return None
        return json.loads((folder / "upload.json").read_text())
    except (OSError, ValueError):
        return None


def received_bytes(folder: Path, manifest: dict) -> list[int]:
    """Bytes received so far for each file."""
    sizes = []
    for f in manifest["files"]:
        path = folder / "input" / f["path"]
        sizes.append(path.stat().st_size if path.exists() else 0)
    return sizes


def record_upload_progress(folder: Path, manifest: dict) -> None:
    """Refresh the status (also marks the upload as alive for cleanup_old_jobs)."""
    total = sum(f["size"] for f in manifest["files"])
    done = sum(received_bytes(folder, manifest))
    write_status(folder, state="uploading", progress=round(done / max(total, 1), 3), message="Uploading")


def finish_upload(folder: Path, manifest: dict) -> list[str]:
    """Queue the stack if every file arrived complete; returns the names of incomplete files."""
    incomplete = [f["name"] for f, got in zip(manifest["files"], received_bytes(folder, manifest)) if got != f["size"]]
    if not incomplete:
        submit(folder, [folder / "input" / f["path"] for f in manifest["files"]],
               [f["name"] for f in manifest["files"]], manifest["options"], manifest["output_stem"])
    return incomplete


def submit(folder: Path, videos: list[Path], names: list[str], options: dict, output_stem: str) -> None:
    """Queue a stack; `options` are stacking.stack_videos keyword arguments (keep, sharpen, ...)."""
    write_status(folder, state="queued", progress=0.0, message="Waiting for the stacker")
    _runner.submit(_run, folder, videos, names, options, output_stem)


def _run(folder: Path, videos: list[Path], names: list[str], options: dict, output_stem: str) -> None:
    last_write = 0.0

    def progress(fraction: float, message: str) -> None:
        nonlocal last_write
        if _cancelled(folder):
            raise Cancelled()
        # Polls come about once a second; writing more often is wasted I/O
        now = time.monotonic()
        if now - last_write >= 0.5:
            last_write = now
            write_status(folder, state="running", progress=round(fraction, 3), message=message)

    try:
        progress(0.0, "Starting")
        result = stacking.stack_videos([str(v) for v in videos], progress=progress, names=names, **options)
        written = Path(stacking.save_stack(result, str(folder / output_stem), result.report))
        if _cancelled(folder):
            raise Cancelled()
        write_status(
            folder, state="done", progress=1.0, message="Done",
            result_file=written.name, linear=result.linear,
            notes=stacking.stack_notes(result.report), report=result.report,
        )
    except Exception as e:  # reported to the client; the job folder stays for the TTL
        if _cancelled(folder):  # also an error caused by cancelling, e.g. a deleted input
            write_status(folder, state="cancelled", progress=0.0, message="Cancelled")
        else:
            write_status(folder, state="error", progress=0.0, message=str(e) or type(e).__name__)
    finally:
        # The videos are large and no longer needed
        shutil.rmtree(folder / "input", ignore_errors=True)


def cleanup_old_jobs() -> None:
    if not JOBS_DIR.exists():
        return
    now = time.time()
    cutoff = now - JOB_TTL_SECONDS
    for folder in JOBS_DIR.iterdir():
        try:
            if not folder.is_dir():
                continue
            status = read_status(folder)
            if status.get("state") == "uploading" and (folder / "upload.json").exists():
                # A chunked upload the client stopped sending
                fresh = status.get("updated", 0) >= now - UPLOAD_IDLE_SECONDS
            elif folder.stat().st_mtime >= cutoff:
                continue
            else:
                fresh = status.get("updated", 0) >= cutoff
        except (OSError, ValueError):
            try:
                fresh = folder.stat().st_mtime >= cutoff
            except OSError:
                continue
            # without a readable status, an old folder is abandoned
        if not fresh:
            shutil.rmtree(folder, ignore_errors=True)
