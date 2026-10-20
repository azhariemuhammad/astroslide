# Single-container image for Heroku: FastAPI serves the API and the built
# frontend on $PORT. (docker-compose uses backend/ and frontend/ Dockerfiles.)

FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
# Empty = the API is on the same origin
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .
COPY --from=frontend /app/dist ./static

# Sized for a 512 MB Eco/Basic dyno. A dyno sees all of the host's cores but only
# gets a share of them, so cap every thread pool: more threads only add memory.
ENV ASTROSLIDE_STATIC_DIR=/app/static \
    ASTROSLIDE_THREADS=1 \
    ASTROSLIDE_MAX_STACK_GB=1 \
    ASTROSLIDE_MAX_MEGAPIXELS=2.1 \
    OPENCV_FOR_THREADS_NUM=2 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    MALLOC_ARENA_MAX=2

RUN useradd --create-home app
USER app

# One worker process: each one loads NumPy/SciPy/OpenCV (~150 MB) and stacking
# jobs are tracked per process. Heroku sets $PORT.
# exec so uvicorn gets Heroku's SIGTERM and shuts down cleanly
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --limit-concurrency 20"]
