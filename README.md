# VideoPipe — AI-Powered Video Highlight Reel Generator

AI-powered video processing pipeline that ingests raw GoPro Hero 13 Black footage, automatically analyzes it with CLIP/YOLOv8/Whisper, scores and ranks clips, and exports highlight reels as FCPXML for Final Cut Pro and DaVinci Resolve.

## Quick Start

### Local Development (no GPU required)
```bash
# Install dependencies
pip install -r requirements.txt

# Run the web server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker (with GPU)
```bash
docker compose up --build
```

Then open http://localhost:8000

## Architecture

```
Upload/NAS Path → FastAPI → Celery Workers → AI Analysis → Scored Clips → FCPXML Export
                    │                              │
                    └── WebSocket Progress ─────────┘
```

**Pipeline Stages:**
1. **Ingest** — Validate files, probe with ffprobe, extract GoPro telemetry
2. **Scene Detection** — PySceneDetect identifies scene boundaries
3. **AI Analysis** — CLIP tagging, YOLOv8 detection, Whisper transcription, motion analysis
4. **Scoring** — Weighted composite scoring with configurable weights
5. **Export** — FCPXML 1.11 timelines for FCP/Resolve, JSON metadata sidecars

## Key Design Decisions

- **NAS-friendly**: Source files are read in-place from NAS paths — no copying hundreds of GB
- **GPU memory management**: Models loaded/unloaded sequentially, never all in VRAM at once
- **Graceful degradation**: Runs without GPU — AI modules return placeholder results for UI dev
- **Frame-accurate export**: FCPXML uses rational time values matching source fps

## Configuration

All settings via environment variables. See `.env.example` for the full list.

Key settings:
- `DATABASE_URL` — SQLite (dev) or PostgreSQL (prod)
- `REDIS_URL` — Redis broker for Celery
- `UPLOAD_DIR` / `OUTPUT_DIR` — File storage paths
- Scoring weights, model choices, detection thresholds — all configurable

## Tech Stack

FastAPI • Celery • Redis • SQLAlchemy • PySceneDetect • OpenCLIP • YOLOv8 • Whisper • OpenCV • lxml (FCPXML)
