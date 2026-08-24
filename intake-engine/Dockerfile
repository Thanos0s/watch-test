# PrakritiDesk intake-engine -- kiosk edge deployment image.
#
# python:3.12-slim keeps the base image small for edge hardware. The apt
# packages below cover two things pip alone can't provide:
#   - libgl1/libglib2.0-0/libsm6/libxext6/libxrender1/libgomp1: shared
#     libraries OpenCV (and therefore PaddleOCR, if you uncomment it in
#     requirements.txt) needs at import time -- without them, `import cv2` /
#     `import paddleocr` fails with "libGL.so.1: cannot open shared object
#     file" even though pip install succeeded.
#   - tesseract-ocr(-hin): the actual Tesseract binary + Hindi language
#     pack that app/ocr_engine.py's `pytesseract` (a pip package, installed
#     via requirements.txt) calls out to as a subprocess -- pip installs
#     the Python wrapper, not the OCR engine itself. On this apt-based
#     image it lands on PATH automatically, so TESSERACT_CMD (used to
#     locate it on Windows dev machines) is never needed here.
FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout/stderr so logs show up
# immediately in `docker logs` instead of being buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

# Copied separately from the app source so `docker build` only reinstalls
# dependencies when requirements.txt actually changes, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Backed by the ./data bind mount in docker-compose.yml -- the SQLite
# database (app/database.py) and any persisted uploads live here, so they
# survive container restarts/rebuilds instead of being lost with the
# container's writable layer.
RUN mkdir -p /app/data

# Runs as a non-root user -- reasonable hardening for an internet-facing
# kiosk service, and unrelated to the OpenCV libs above.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

# PORT is injected by Railway (and other PaaS platforms). Falls back to 8001
# for local docker run / docker-compose where PORT is not set.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8001') + '/', timeout=3)"]

# JSON array form (suppresses JSONArgsRecommended lint). sh -c is required so
# the shell expands ${PORT:-8001} -- JSON exec form does NOT expand shell vars.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
