# BioAcoustic Stream Engine (BASE) — full-stack image
# Includes BirdNET (tensorflow-cpu), BatDetect2 (PyTorch), insect (OpenSoundscape),
# bee (BuzzDetect / YAMNet), and the FastAPI web UI.
#
# Live microphone capture is NOT wired up in this image — it runs the web UI,
# reports, clips library, and historical data only. Docker Desktop on Windows
# cannot share sound devices with containers without a PulseAudio TCP bridge.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TF_CPP_MIN_LOG_LEVEL=3 \
    DEBIAN_FRONTEND=noninteractive

# System libraries:
#   libportaudio2  – sounddevice runtime (loads even if no mic device is present)
#   libsndfile1    – soundfile / librosa runtime
#   ffmpeg         – pydub / librosa fallback for non-WAV formats
#   libgomp1       – OpenMP runtime used by numpy / torch / sklearn
#   git            – needed by BuzzDetect bee model auto-download
#   ca-certificates– TLS for model downloads (BirdNET, BatDetect2, BuzzDetect)
#   curl           – healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 \
        libsndfile1 \
        ffmpeg \
        libgomp1 \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Stage 1: install deps from pyproject.toml only. Stubbing src/ecoacoustics
# lets `pip install -e .` resolve deps without the full source tree, so this
# heavy layer caches across iterations on the project code.
COPY pyproject.toml README.md ./
RUN mkdir -p src/ecoacoustics \
    && echo '__version__ = "0.0.0"' > src/ecoacoustics/__init__.py \
    && pip install --upgrade pip \
    && pip install -e . \
    && pip install opensoundscape==0.10.2

# Stage 2: real source overlay.
COPY src ./src
COPY config ./config
COPY models ./models
COPY tests ./tests
COPY start_web.sh ./

# Re-install (no-deps) so the editable install picks up the real package layout.
RUN pip install --no-deps -e .

# Pre-clone BuzzDetect (bee model) so the first run is instant.
RUN mkdir -p external \
    && git clone --depth 1 --branch v1.0.1 \
        https://github.com/OSU-Bee-Lab/buzzdetect.git external/buzzdetect

RUN mkdir -p output/clips

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Strip any CR characters that Windows git checkouts may have introduced —
# Linux refuses to run a shebang with CRLF (/usr/bin/env: 'bash\r': No such
# file or directory). Defensive; works even if .gitattributes is missing.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/status || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "ecoacoustics.main", "web", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
