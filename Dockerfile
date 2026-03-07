# ============================================
# VideoPipe — AI Video Highlight Reel Generator
# ============================================
# GPU-flexible: works with any NVIDIA GPU (RTX 3090, 5090, etc.)
# CUDA 12.4 runtime — matches host driver 550+
#
# To change GPU target:
#   - RTX 3090 (24GB): works as-is with CUDA 12.4
#   - RTX 5090 (32GB): works as-is (same CUDA, more VRAM = bigger models)
#   - Different CUDA: change base image tag to match nvidia-smi CUDA version

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip python3-setuptools \
    ffmpeg mediainfo \
    libgl1-mesa-glx libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Use python3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && python3 -m pip install --upgrade pip

WORKDIR /app

# Install base Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install GPU/AI packages with CUDA support
# setuptools + wheel needed before GPU builds (whisper requires pkg_resources)
RUN pip install --no-cache-dir setuptools wheel

# Install PyTorch with CUDA 12.4 support first (other packages depend on it)
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124

# Install AI packages (whisper needs --no-build-isolation to see setuptools)
RUN pip install --no-cache-dir open-clip-torch==2.29.0 ultralytics==8.3.57 transnetv2-pytorch==1.0.5
RUN pip install --no-cache-dir --no-build-isolation openai-whisper==20240930

# Copy application code
COPY . .

# Create data directories and setup non-root user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser && \
    mkdir -p /app/data/uploads /app/data/outputs /app/data/models /app/data/db /app/data/logs && \
    chown -R appuser:appuser /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
