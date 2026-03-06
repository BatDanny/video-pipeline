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


def _update_task_meta(task, info: dict):
    """Update Celery task metadata for WebSocket consumers."""
    task.update_state(state="PROGRESS", meta=info)


@celery_app.task(bind=True, name="app.pipeline.orchestrator.run_pipeline")
def run_pipeline(self, job_id: str):
    """Execute the full pipeline for a job.

    Stages:
    1. Ingest — validate files, probe with ffprobe, create Video records
    2. Scene Detection — run PySceneDetect, create Clip records
    3. Analysis — CLIP tagging (+ YOLOv8, Whisper, Motion in future)
    4. Scoring — compute weighted composite scores
    5. (Optional) Enhancement — Gyroflow, RIFE, etc.
    """
    logger.info(f"Starting pipeline for job {job_id}")

    try:
        # ---- Stage 1: Ingest ----
        _update_job_status(job_id, JobStatus.INGESTING, progress_pct=0.0)
        _update_task_meta(self, {
            "stage": "ingesting",
            "message": "Validating and probing video files...",
            "progress_pct": 0.0,
        })

        from app.pipeline.ingest import ingest_videos
        video_count = ingest_videos(job_id)
        logger.info(f"Ingested {video_count} videos for job {job_id}")

        # ---- Stage 2: Scene Detection ----
        _update_job_status(job_id, JobStatus.DETECTING_SCENES, progress_pct=15.0)
        _update_task_meta(self, {
            "stage": "detecting_scenes",
            "message": "Running scene detection...",
            "progress_pct": 15.0,
        })

        from app.pipeline.scene_detect import detect_scenes
        clip_count = detect_scenes(job_id)
        logger.info(f"Detected {clip_count} scenes for job {job_id}")

        # ---- Stage 3: Analysis ----
        # Each module loads/unloads its GPU model sequentially to manage VRAM

        # 3a: CLIP Activity Tagging
        _update_job_status(job_id, JobStatus.ANALYZING, progress_pct=25.0)
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "clip_tagging",
            "message": "Running CLIP activity tagging...",
            "progress_pct": 25.0,
        })

        from app.pipeline.analysis.clip_tagger import run_clip_tagging
        run_clip_tagging(job_id, progress_callback=lambda info: _update_task_meta(self, info))

        # 3b: YOLOv8 Object Detection
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "object_detection",
            "message": "Running YOLOv8 object detection...",
            "progress_pct": 40.0,
        })

        from app.pipeline.analysis.object_detect import detect_objects_for_job
        detect_objects_for_job(job_id)

        # 3c: Whisper Transcription
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "transcription",
            "message": "Running Whisper speech transcription...",
            "progress_pct": 55.0,
        })

        from app.pipeline.analysis.transcribe import transcribe_clips_for_job
        transcribe_clips_for_job(job_id)

        # 3d: Motion Analysis (CPU-only, runs fast)
        _update_task_meta(self, {
            "stage": "analyzing",
            "sub_stage": "motion",
            "message": "Analyzing motion intensity...",
            "progress_pct": 65.0,
        })

        from app.pipeline.analysis.motion import analyze_motion_for_job
        analyze_motion_for_job(job_id)

        # ---- Stage 4: Scoring ----
        _update_job_status(job_id, JobStatus.SCORING, progress_pct=75.0)
        _update_task_meta(self, {
            "stage": "scoring",
            "message": "Computing clip scores...",
            "progress_pct": 75.0,
        })

        from app.pipeline.scoring import score_clips
        score_clips(job_id)

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
