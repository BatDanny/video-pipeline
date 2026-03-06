FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Prevent interactive prompts during install
ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    ffmpeg mediainfo \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Use python3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/models /app/data/db

# Pre-download AI models (baked into image for faster startup)
# Uncomment when building for production:
# RUN python3 -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')"
# RUN python3 -c "from ultralytics import YOLO; YOLO('yolov8m.pt')"
# RUN python3 -c "import whisper; whisper.load_model('medium')"

EXPOSE 8000

# Default command: run FastAPI with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
