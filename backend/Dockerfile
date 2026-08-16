# syntax=docker/dockerfile:1

# --- Build stage ------------------------------------------------------------
# Wheels are built here so the runtime image needs no compiler toolchain.
FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# --- Runtime stage ----------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr is the OCR engine; libGL/libglib are OpenCV's runtime
# dependencies. Installed here rather than in the builder because they are
# needed at run time, not to compile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user: a container that never needs to write outside its
# own data directory should not be able to.
RUN useradd --create-home --uid 10001 officeiq

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=officeiq:officeiq alembic.ini ./
COPY --chown=officeiq:officeiq alembic ./alembic
COPY --chown=officeiq:officeiq scripts ./scripts
COPY --chown=officeiq:officeiq app ./app

# Face-recognition models are fetched at build time with pinned checksums
# rather than baked into git — see scripts/download_face_models.py.
RUN mkdir -p /app/models /app/storage && chown -R officeiq:officeiq /app/models /app/storage

USER officeiq

EXPOSE 8000

# Liveness only — the deep check at /health/ready is for the orchestrator,
# which should use it as a readiness probe, not to decide on a restart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# One worker per container by default: scale with replicas, so the in-memory
# rate limiter stays meaningful per process and the pool size below stays
# predictable. Override WEB_CONCURRENCY if you would rather scale in-process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='*'"]
