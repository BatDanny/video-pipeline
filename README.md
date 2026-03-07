# VideoPipe — AI-Powered Video Highlight Reel Generator

AI-powered video processing pipeline that ingests raw GoPro Hero 13 Black footage, automatically analyzes it with CLIP/YOLOv8/Whisper, scores and ranks clips, and exports highlight reels as FCPXML for Final Cut Pro and DaVinci Resolve.

## Architecture

**3 Docker containers:**

| Container | Role | GPU | Port |
|-----------|------|-----|------|
| `web` | FastAPI/Uvicorn — serves UI + REST API | No | 8000 |
| `worker` | Celery — runs AI pipeline tasks on GPU | **Yes** | — |
| `redis` | Message broker + result backend | No | 6379 |

```
Browser → web:8000 → Redis → worker (GPU) → DB/Filesystem
              ↕ WebSocket progress updates
```

**Pipeline Stages:** Ingest → Scene Detection → CLIP Tagging → YOLOv8 → Whisper → Motion → Scoring → FCPXML Export

---

## Quick Start

### Prerequisites

| Component | Required | How to check |
|-----------|----------|-------------|
| NVIDIA Driver | 550+ | `nvidia-smi` |
| CUDA | 12.4 | `nvidia-smi` (top right) |
| Docker | 24+ | `docker --version` |
| NVIDIA Container Toolkit | 1.14+ | `nvidia-ctk --version` |

### Installation (one-time)

```bash
# 1. Install Docker (Debian/Ubuntu)
sudo apt-get update
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. Install NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit

# 3. Configure Docker to use NVIDIA runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 4. Add yourself to docker group (log out/in after)
sudo usermod -aG docker $USER

# 5. Verify GPU is visible in Docker
docker run --rm --gpus all nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi
```

### Run

```bash
# Build and start all 3 containers
docker compose up --build -d

# View logs
docker compose logs -f

# Open UI
# http://<your-server-ip>:8000
```

### Stop

```bash
docker compose down          # Stop containers (keep data)
docker compose down -v       # Stop and delete all data volumes
```

---

## GPU Flexibility

The Docker setup works with **any NVIDIA GPU** that supports CUDA 12.4+:

| GPU | VRAM | Notes |
|-----|------|-------|
| **RTX 3090** | 24 GB | Current server. Runs all models comfortably. |
| **RTX 5090** | 32 GB | Future server. More VRAM = can use larger models (ViT-L/14, yolov8x). |
| **RTX 4090** | 24 GB | Same VRAM as 3090, faster inference. |

### Switching GPU / Machine

No code changes needed. The Dockerfile uses `nvidia/cuda:12.4.1-runtime-ubuntu22.04` which is compatible with any NVIDIA driver 550+.

**If your new machine has a different CUDA version** (check with `nvidia-smi`):
1. Change the `FROM` line in `Dockerfile` to match (e.g., `nvidia/cuda:12.6.0-runtime-ubuntu22.04`)
2. Rebuild: `docker compose build`

**To use larger models on machines with more VRAM**, edit `.env`:
```env
# RTX 5090 (32GB) — use larger, more accurate models
CLIP_MODEL=ViT-L-14
YOLO_MODEL=yolov8x.pt
WHISPER_MODEL=large-v3
```

---

## Configuration

All settings via environment variables (`.env` file). Copy `.env.example` to `.env` to customize.

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///...` | Database connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis broker |
| `UPLOAD_DIR` | `/app/data/uploads` | Uploaded file storage |
| `OUTPUT_DIR` | `/app/data/outputs` | Generated outputs (thumbnails, FCPXML) |
| `CLIP_MODEL` | `ViT-B-32` | CLIP model size |
| `YOLO_MODEL` | `yolov8m.pt` | YOLOv8 model size |
| `WHISPER_MODEL` | `medium` | Whisper model size |

### Scoring Weights

```env
WEIGHT_ACTIVITY_RELEVANCE=0.30
WEIGHT_MOTION_INTENSITY=0.20
WEIGHT_PEOPLE_PRESENCE=0.15
WEIGHT_AUDIO_INTEREST=0.10
WEIGHT_VISUAL_QUALITY=0.10
WEIGHT_DURATION_PENALTY=0.05
WEIGHT_UNIQUENESS=0.10
```

---

## Accessing NAS Footage

Source videos are read **in-place** from NAS paths — nothing is copied. To give the containers access to your NAS:

Add mount points in `docker-compose.yml` under both `web` and `worker` volumes:
```yaml
volumes:
  - /mnt/nas/gopro:/mnt/nas/gopro:ro    # read-only NAS mount
```

Then in the UI, enter `/mnt/nas/gopro/your-trip-folder/` as the source path.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Create job (upload or NAS path) |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Job detail |
| `POST` | `/api/jobs/{id}/start` | Start pipeline |
| `POST` | `/api/jobs/{id}/cancel` | Cancel running job |
| `GET` | `/api/jobs/{id}/clips` | List clips (filterable) |
| `PATCH` | `/api/clips/{id}` | Update score/favorite |
| `POST` | `/api/jobs/{id}/highlights` | Create highlight reel |
| `GET` | `/api/highlights/{id}/export/fcpxml` | Download FCPXML |
| `WS` | `/ws/progress/{job_id}` | Real-time progress |

---

## Project Structure

```
video-pipeline/
├── docker-compose.yml          # 3 containers: web, worker, redis
├── Dockerfile                  # NVIDIA CUDA + Python + ffmpeg
├── requirements.txt            # Base Python deps
├── requirements-gpu.txt        # GPU/AI packages (torch, CLIP, YOLO)
├── app/
│   ├── main.py                 # FastAPI app factory
│   ├── config.py               # Pydantic settings
│   ├── models/                 # SQLAlchemy ORM (Job, Video, Clip, Highlight)
│   ├── schemas/                # Pydantic request/response schemas
│   ├── api/                    # REST routes + WebSocket
│   ├── pipeline/               # Processing pipeline
│   │   ├── orchestrator.py     # Celery task chain
│   │   ├── ingest.py           # ffprobe + file validation
│   │   ├── scene_detect.py     # TransNetV2 (GPU) scene detection
│   │   ├── scoring.py          # Weighted composite scorer
│   │   ├── highlight_builder.py# Auto-assembly algorithm
│   │   ├── analysis/           # AI modules (CLIP, YOLO, Whisper, motion)
│   │   └── enhancement/        # Optional (Gyroflow, RIFE, ESRGAN, Demucs)
│   ├── export/                 # FCPXML builder, metadata, thumbnails
│   ├── templates/              # Jinja2 HTML pages
│   └── static/                 # CSS + JS
└── alembic/                    # Database migrations
```

## Tech Stack

FastAPI • Celery • Redis • SQLAlchemy • TransNetV2 • OpenCLIP • YOLOv8 • Whisper • OpenCV • lxml (FCPXML) • Docker • NVIDIA CUDA
