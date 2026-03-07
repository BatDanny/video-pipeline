"""API routes for Job CRUD and pipeline control."""

import os
import uuid
import shutil
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.models.database import get_db
from app.models.job import Job, JobStatus
from app.models.video import Video
from app.models.clip import Clip
from app.schemas.job import JobCreate, JobUpdate, JobResponse, JobListResponse, JobStartRequest
from app.config import get_settings

router = APIRouter()


def _job_to_response(job: Job, db: Session) -> JobResponse:
    """Convert a Job ORM object to a response schema."""
    video_count = db.query(func.count(Video.id)).filter(Video.job_id == job.id).scalar() or 0
    clip_count = db.query(func.count(Clip.id)).filter(Clip.job_id == job.id).scalar() or 0
    top_score = db.query(func.max(Clip.overall_score)).filter(Clip.job_id == job.id).scalar()

    return JobResponse(
        id=job.id,
        name=job.name,
        status=job.status.value if isinstance(job.status, JobStatus) else job.status,
        config=job.config or {},
        source_dir=job.source_dir,
        output_dir=job.output_dir,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        progress_pct=job.progress_pct or 0.0,
        video_count=video_count,
        clip_count=clip_count,
        top_score=top_score,
    )


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(
    name: str = Form(...),
    source_path: Optional[str] = Form(None),
    activity_focus: str = Form(""),  # Comma-separated
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """Create a new pipeline job.

    Supports two modes:
    1. source_path: Reference files on NAS/server (no copy, reads in-place)
    2. files: Upload files directly (for small batches/testing)
    """
    settings = get_settings()
    job_id = str(uuid.uuid4())

    # Build config from form data
    activities = [a.strip() for a in activity_focus.split(",") if a.strip()] if activity_focus else []
    config = {"activity_focus": activities}

    # Determine source directory
    if source_path:
        # NAS/server path reference mode — validate path exists
        if not os.path.isdir(source_path):
            raise HTTPException(400, f"Source path does not exist or is not a directory: {source_path}")
        source_dir = source_path
    elif files and len(files) > 0 and files[0].filename:
        # File upload mode — save uploaded files
        source_dir = os.path.join(settings.upload_dir, job_id)
        os.makedirs(source_dir, exist_ok=True)
        for f in files:
            if f.filename:
                dest = os.path.join(source_dir, f.filename)
                with open(dest, "wb") as buf:
                    content = await f.read()
                    buf.write(content)
    else:
        raise HTTPException(400, "Must provide either source_path or upload files")

    # Create output directory for this job
    output_dir = os.path.join(settings.output_dir, job_id)
    os.makedirs(output_dir, exist_ok=True)

    # Create job record
    job = Job(
        id=job_id,
        name=name,
        status=JobStatus.PENDING,
        config=config,
        source_dir=source_dir,
        output_dir=output_dir,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return _job_to_response(job, db)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(db: Session = Depends(get_db)):
    """List all jobs with summary stats."""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return JobListResponse(
        jobs=[_job_to_response(j, db) for j in jobs],
        total=len(jobs),
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    """Get a single job by ID."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_response(job, db)


@router.patch("/jobs/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: str,
    update: JobUpdate,
    db: Session = Depends(get_db),
):
    """Update a job's name and/or config.

    Only permitted if job is in PENDING, COMPLETE, or FAILED status.
    Cannot change config for a job that is currently RUNNING.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Guard against updates while running
    running_statuses = [
        JobStatus.INGESTING, JobStatus.DETECTING_SCENES,
        JobStatus.ANALYZING, JobStatus.SCORING,
        JobStatus.ASSEMBLING, JobStatus.ENHANCING,
    ]
    if job.status in running_statuses:
        raise HTTPException(400, "Cannot update job while it is running")

    if update.name is not None:
        job.name = update.name

    if update.config is not None:
        # Merge with existing config
        current_config = job.config or {}
        current_config.update(update.config)
        job.config = current_config

    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_to_response(job, db)


@router.post("/jobs/{job_id}/start", response_model=JobResponse)
async def start_job(job_id: str, db: Session = Depends(get_db)):
    """Start pipeline execution for a job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(400, f"Job cannot be started from status '{job.status.value}'")

    # Launch Celery pipeline task
    try:
        from app.pipeline.orchestrator import run_pipeline
        task = run_pipeline.delay(job_id)
        job.celery_task_id = task.id
        job.status = JobStatus.INGESTING
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error_message = f"Failed to start pipeline: {str(e)}"
        db.commit()
        db.refresh(job)

    return _job_to_response(job, db)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Cancel a running job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    active_statuses = [
        JobStatus.INGESTING, JobStatus.DETECTING_SCENES,
        JobStatus.ANALYZING, JobStatus.SCORING,
        JobStatus.ASSEMBLING, JobStatus.ENHANCING,
    ]
    if job.status not in active_statuses:
        raise HTTPException(400, f"Job is not running (status: {job.status.value})")

    # Revoke Celery task
    if job.celery_task_id:
        try:
            from app.workers.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            pass  # Best effort

    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    return _job_to_response(job, db)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Delete a job and all associated data."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Clean up output directory (but NOT source_dir — that may be on NAS)
    if job.output_dir and os.path.isdir(job.output_dir):
        shutil.rmtree(job.output_dir, ignore_errors=True)

    # Clean up uploaded files only (source_dir inside upload_dir)
    settings = get_settings()
    if job.source_dir and job.source_dir.startswith(settings.upload_dir):
        if os.path.isdir(job.source_dir):
            shutil.rmtree(job.source_dir, ignore_errors=True)

    db.delete(job)
    db.commit()
