# Heroku image: FastAPI serves the API on $PORT. The frontend is on GitHub Pages
# (.github/workflows/pages.yml); docker-compose uses backend/ and frontend/ Dockerfiles.

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .

# Sized for a 512 MB Eco/Basic dyno. A dyno sees all of the host's cores but only
# gets a share of them, so cap every thread pool: more threads only add memory.
# Stack uploads arrive in chunks on disk (~311 GB free on the host), not in memory;
# 3 GB is about 3 minutes of full-resolution RAW.
# Fixed malloc thresholds: by default glibc raises its mmap threshold after the first
# big free, so later image buffers come from the heap and stay with the process
# (idle RSS grew 83 -> 280 MB after a few enhances, then into swap on the dyno).
# With 128 KB thresholds every image buffer goes back to the OS; no speed cost measured.
ENV ASTROSLIDE_THREADS=1 \
    ASTROSLIDE_MAX_STACK_GB=3 \
    ASTROSLIDE_MAX_MEGAPIXELS=2.1 \
    OPENCV_FOR_THREADS_NUM=2 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    MALLOC_ARENA_MAX=2 \
    MALLOC_MMAP_THRESHOLD_=131072 \
    MALLOC_TRIM_THRESHOLD_=131072

# Hardening for a public dyno: only the frontend's site may call the API; redirect
# http to https (Heroku's router sets X-Forwarded-Proto); no public API docs; refuse
# images and videos too large to decode in 512 MB
ENV ASTROSLIDE_CORS_ORIGINS="https://astroslide.me" \
    ASTROSLIDE_FORCE_HTTPS=1 \
    ASTROSLIDE_API_DOCS=0 \
    ASTROSLIDE_MAX_DECODE_MEGAPIXELS=16 \
    ASTROSLIDE_MAX_VIDEO_MEGAPIXELS=2.1 \
    ASTROSLIDE_MAX_STACK_UPLOADS=1 \
    ASTROSLIDE_MAX_STACK_JOBS=3

# Per-client limits; Heroku's router is the one proxy appending to X-Forwarded-For
ENV ASTROSLIDE_PROXY_HOPS=1 \
    ASTROSLIDE_RATE_LIMIT=180 \
    ASTROSLIDE_MAX_REQUESTS_PER_CLIENT=4 \
    ASTROSLIDE_STACK_JOBS_PER_HOUR=6

RUN useradd --create-home app
USER app

# One worker process: each one loads NumPy/SciPy/OpenCV (~150 MB) and stacking
# jobs are tracked per process. Heroku sets $PORT.
# exec so uvicorn gets Heroku's SIGTERM and shuts down cleanly
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --limit-concurrency 20 --no-server-header"]
