"""Pipeline orchestrator — top-level runner that chains Celery tasks."""

import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.models.database import get_session_factory
from app.models.job import Job, JobStatus

logger = logging.getLogger(__name__)


def _update_job_status(job_id: str, status: JobStatus, progress_pct: float = None,
                       error_message: str = None):
    """Update job status in the database."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if progress_pct is not None:
                job.progress_pct = progress_pct
            if error_message:
                job.error_message = error_message
            job.updated_at = datetime.now(timezone.utc)
            if status in (JobStatus.COMPLETE, JobStatus.COMPLETE_WITH_ERRORS, JobStatus.FAILED):
                job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

def _update_job_telemetry(job_id: str, stage_name: str, stage_data: dict):
    """Update telemetry measurements for a specific pipeline stage."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            # We must assign a new dict to trigger SQLAlchemy's JSON mutation tracking
            current_telemetry = dict(job.telemetry or {})
            current_telemetry[stage_name] = stage_data
            job.telemetry = current_telemetry
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _update_task_meta(task, info: dict):
    """Update Celery task metadata for WebSocket consumers and sidebar widget."""
    task.update_state(state="PROGRESS", meta=info)
    # Also write to a known Redis key for fast sidebar widget lookup
    try:
        import json
        from app.config import get_settings
        import redis as redis_lib
        settings = get_settings()
        r = redis_lib.Redis.from_url(settings.redis_url)
        r.setex("videopipe:active_pipeline", 30, json.dumps(info))
    except Exception:
        pass


@celery_app.task(bind=True, name="app.pipeline.orchestrator.run_pipeline")
def run_pipeline(self, job_id: str):
    """Execute the full pipeline for a job.

    Stages:
    1. Ingest — validate files, probe with ffprobe, create Video records
    2. Scene Detection — run TransNetV2 on GPU, create Clip records
    3. Analysis — CLIP tagging (+ YOLOv8, Whisper, Motion in future)
    4. Scoring — compute weighted composite scores
    5. (Optional) Enhancement — Gyroflow, RIFE, etc.
    """
    logger.info(f"Starting pipeline for job {job_id}")

    try:
        import time

        # ---- Stage 1: Ingest ----
        _update_job_status(job_id, JobStatus.INGESTING, progress_pct=0.0)
        _update_job_telemetry(job_id, "ingest", {"status": "running", "start_time": time.time(), "hardware": "CPU (ffprobe)"})
        _update_task_meta(self, {
            "stage": "ingesting",
            "message": "Validating and probing video files...",
            "progress_pct": 0.0,
        })

        from app.pipeline.ingest import ingest_videos
        start_t = time.time()
        video_count, total_bytes = ingest_videos(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        
        _update_job_telemetry(job_id, "ingest", {
            "status": "completed", 
            "duration": dur, 
            "hardware": "CPU (ffprobe)",
            "file_size_bytes": total_bytes
        })

        _update_task_meta(self, {
            "stage": "ingesting",
            "message": f"Ingested {video_count} video files",
            "progress_pct": 14.0,
        })
        logger.info(f"Ingested {video_count} videos for job {job_id}")

        # ---- Stage 2: Scene Detection ----
        _update_job_status(job_id, JobStatus.DETECTING_SCENES, progress_pct=15.0)
        _update_job_telemetry(job_id, "detecting_scenes", {"status": "running", "start_time": time.time(), "hardware": "GPU (TransNetV2)"})
        
        _update_task_meta(self, {
            "stage": "detecting_scenes",
            "message": "Running scene detection...",
            "progress_pct": 15.0,
        })

        from app.pipeline.scene_detect import detect_scenes
        start_t = time.time()
        clip_count, hw_used = detect_scenes(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        
        _update_job_telemetry(job_id, "detecting_scenes", {
            "status": "completed",
            "duration": dur,
            "hardware": hw_used
        })

        _update_task_meta(self, {
            "stage": "detecting_scenes",
            "message": f"Found {clip_count} scenes across {video_count} videos",
            "progress_pct": 24.0,
        })
        logger.info(f"Detected {clip_count} scenes for job {job_id}")

        # ---- Stage 3: Analysis ----
        # Each module loads/unloads its GPU model sequentially to manage VRAM

        from app.config import get_settings as _gs
        _settings = _gs()

        # 3a: CLIP Activity Tagging
        _update_job_status(job_id, JobStatus.ANALYZING, progress_pct=25.0)
        _update_job_telemetry(job_id, "clip_tagging", {"status": "running", "start_time": time.time(), "hardware": f"GPU (CLIP {_settings.clip_model})"})
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "clip_tagging",
            "message": f"Loading CLIP {_settings.clip_model} — tagging {clip_count} clips...",
            "progress_pct": 25.0,
        })

        from app.pipeline.analysis.clip_tagger import run_clip_tagging
        start_t = time.time()
        run_clip_tagging(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        _update_job_telemetry(job_id, "clip_tagging", {"status": "completed", "duration": dur, "hardware": f"GPU (CLIP {_settings.clip_model})"})

        # 3b: YOLOv8 Object Detection
        _update_job_telemetry(job_id, "object_detection", {"status": "running", "start_time": time.time(), "hardware": f"GPU (YOLO {_settings.yolo_model})"})
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "object_detection",
            "message": f"Loading YOLO {_settings.yolo_model} @ {_settings.yolo_imgsz}px...",
            "progress_pct": 40.0,
        })

        from app.pipeline.analysis.object_detect import detect_objects_for_job
        start_t = time.time()
        detect_objects_for_job(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        _update_job_telemetry(job_id, "object_detection", {"status": "completed", "duration": dur, "hardware": f"GPU (YOLO {_settings.yolo_model})"})

        # 3c: Whisper Transcription
        _update_job_telemetry(job_id, "transcription", {"status": "running", "start_time": time.time(), "hardware": f"GPU (Whisper {_settings.whisper_model})"})
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "transcription",
            "message": f"Loading Whisper {_settings.whisper_model}...",
            "progress_pct": 55.0,
        })

        from app.pipeline.analysis.transcribe import transcribe_clips_for_job
        start_t = time.time()
        transcribe_clips_for_job(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        _update_job_telemetry(job_id, "transcription", {"status": "completed", "duration": dur, "hardware": f"GPU (Whisper {_settings.whisper_model})"})

        # 3d: Motion Analysis (CPU-only, runs fast)
        _update_job_telemetry(job_id, "motion", {"status": "running", "start_time": time.time(), "hardware": "CPU (OpenCV)"})
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "motion",
            "message": "Analyzing motion intensity...",
            "progress_pct": 65.0,
        })

        from app.pipeline.analysis.motion import analyze_motion_for_job
        start_t = time.time()
        analyze_motion_for_job(job_id, progress_callback=lambda info: _update_task_meta(self, info))
        dur = time.time() - start_t
        _update_job_telemetry(job_id, "motion", {"status": "completed", "duration": dur, "hardware": "CPU (OpenCV)"})

        # ---- Stage 4: Scoring ----
        _update_job_status(job_id, JobStatus.SCORING, progress_pct=75.0)
        _update_job_telemetry(job_id, "scoring", {"status": "running", "start_time": time.time(), "hardware": "CPU (Math/Pandas)"})
        _update_task_meta(self, {
            "stage": "scoring",
            "message": "Computing clip scores...",
            "progress_pct": 75.0,
        })

        from app.pipeline.scoring import score_clips
        start_t = time.time()
        score_clips(job_id)
        dur = time.time() - start_t
        _update_job_telemetry(job_id, "scoring", {"status": "completed", "duration": dur, "hardware": "CPU (Math/Pandas)"})

        # ---- Stage 5: Generate thumbnails ----
        _update_task_meta(self, {
            "stage": "scoring",
            "message": "Generating thumbnails...",
            "progress_pct": 85.0,
        })

        from app.export.thumbnail import generate_thumbnails
        generate_thumbnails(job_id)

        # ---- Stage 6 (Optional): Enhancement ----
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            config = job.config or {}
        finally:
            db.close()

        if config.get("enhancements_enabled"):
            _update_job_status(job_id, JobStatus.ENHANCING, progress_pct=90.0)
            _update_task_meta(self, {
                "stage": "enhancing",
                "message": "Running enhancement pipeline...",
                "progress_pct": 90.0,
            })
            # Enhancement modules would run here

        # ---- Complete ----
        _update_job_status(job_id, JobStatus.COMPLETE, progress_pct=100.0)
        _update_task_meta(self, {
            "stage": "complete",
            "message": "Pipeline complete!",
            "progress_pct": 100.0,
            "finished": True,
        })

        logger.info(f"Pipeline complete for job {job_id}")
        return {"status": "complete", "job_id": job_id}

    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}: {e}")
        _update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        _update_task_meta(self, {
            "stage": "failed",
            "message": f"Pipeline failed: {str(e)}",
            "progress_pct": 0.0,
            "finished": True,
        })
        raise
