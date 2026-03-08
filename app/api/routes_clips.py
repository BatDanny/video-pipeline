"""API routes for Clip browsing, filtering, and metadata."""

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.models.database import get_db
from app.models.clip import Clip
from app.models.video import Video
from app.schemas.clip import ClipResponse, ClipListResponse, ClipUpdate

router = APIRouter()


def _clip_to_response(clip: Clip, db: Session, video: Video = None) -> ClipResponse:
    """Convert a Clip ORM object to response schema."""
    if video is None:
        video = db.query(Video).filter(Video.id == clip.video_id).first()
    return ClipResponse(
        id=clip.id,
        video_id=clip.video_id,
        job_id=clip.job_id,
        start_sec=clip.start_sec,
        end_sec=clip.end_sec,
        duration_sec=clip.duration_sec,
        thumbnail_path=clip.thumbnail_path,
        preview_path=clip.preview_path,
        tags=clip.tags,
        objects_detected=clip.objects_detected,
        transcript=clip.transcript,
        has_speech=clip.has_speech or False,
        motion_score=clip.motion_score,
        audio_energy=clip.audio_energy,
        overall_score=clip.overall_score or 0.0,
        effective_score=clip.effective_score,
        user_score_override=clip.user_score_override,
        is_favorite=clip.is_favorite or False,
        video_filename=video.filename if video else None,
        created_at=clip.created_at,
    )


@router.get("/jobs/{job_id}/clips", response_model=ClipListResponse)
async def list_clips(
    job_id: str,
    min_score: Optional[float] = Query(None, ge=0),
    max_score: Optional[float] = Query(None, le=100),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    has_speech: Optional[bool] = Query(None),
    favorites_only: Optional[bool] = Query(None),
    sort_by: str = Query("score", regex="^(score|duration|chronological)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List clips for a job with filtering and sorting."""
    query = db.query(Clip).filter(Clip.job_id == job_id)

    # Apply filters
    if min_score is not None:
        query = query.filter(Clip.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(Clip.overall_score <= max_score)
    if has_speech is not None:
        query = query.filter(Clip.has_speech == has_speech)
    if favorites_only:
        query = query.filter(Clip.is_favorite == True)  # noqa: E712

    # Sorting
    if sort_by == "score":
        query = query.order_by(Clip.overall_score.desc())
    elif sort_by == "duration":
        query = query.order_by(Clip.duration_sec.desc())
    elif sort_by == "chronological":
        query = query.order_by(Clip.video_id, Clip.start_sec)

    # Tag filtering (in-memory since tags are JSON) — must run BEFORE pagination
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        all_clips = query.all()
        filtered = [
            c for c in all_clips
            if c.tags and any(t in {x.get("tag", "").lower() for x in c.tags} for t in tag_list)
        ]
        total = len(filtered)
        clips = filtered[offset : offset + limit]
    else:
        total = query.count()
        clips = query.offset(offset).limit(limit).all()

    # Batch-load videos to avoid N+1 queries
    video_ids = list({c.video_id for c in clips})
    videos = db.query(Video).filter(Video.id.in_(video_ids)).all() if video_ids else []
    videos_by_id = {v.id: v for v in videos}

    return ClipListResponse(
        clips=[_clip_to_response(c, db, video=videos_by_id.get(c.video_id)) for c in clips],
        total=total,
    )


@router.get("/clips/{clip_id}", response_model=ClipResponse)
async def get_clip(clip_id: str, db: Session = Depends(get_db)):
    """Get a single clip with full metadata."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    return _clip_to_response(clip, db)


@router.patch("/clips/{clip_id}", response_model=ClipResponse)
async def update_clip(clip_id: str, update: ClipUpdate, db: Session = Depends(get_db)):
    """Update a clip's user score override or favorite status."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")

    if update.user_score_override is not None:
        clip.user_score_override = update.user_score_override
    if update.is_favorite is not None:
        clip.is_favorite = update.is_favorite

    db.commit()
    db.refresh(clip)
    return _clip_to_response(clip, db)


@router.get("/clips/{clip_id}/thumbnail")
async def get_clip_thumbnail(clip_id: str, db: Session = Depends(get_db)):
    """Serve a clip's thumbnail image."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    if not clip.thumbnail_path or not os.path.isfile(clip.thumbnail_path):
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(clip.thumbnail_path, media_type="image/jpeg")


@router.get("/clips/{clip_id}/preview")
async def get_clip_preview(clip_id: str, db: Session = Depends(get_db)):
    """Serve a clip's preview video."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    if not clip.preview_path or not os.path.isfile(clip.preview_path):
        raise HTTPException(404, "Preview not found")
    return FileResponse(clip.preview_path, media_type="video/mp4")


@router.get("/clips/{clip_id}/video")
async def get_clip_source_video(clip_id: str, db: Session = Depends(get_db)):
    """Serve the original video file for a clip, used for playback via media fragments."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    video = db.query(Video).filter(Video.id == clip.video_id).first()
    if not video or not os.path.isfile(video.filepath):
        raise HTTPException(404, "Source video not found")
    return FileResponse(video.filepath, media_type="video/mp4")
