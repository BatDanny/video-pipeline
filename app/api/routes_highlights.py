"""API routes for Highlight Reel assembly and export."""

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.job import Job
from app.models.clip import Clip
from app.models.highlight import HighlightReel
from app.schemas.highlight import (
    HighlightCreate, HighlightUpdate, HighlightResponse, HighlightListResponse,
)
from app.pipeline.highlight_builder import auto_assemble_highlight
from app.export.fcpxml import FCPXMLBuilder
from app.export.metadata import write_metadata_bundle

router = APIRouter()


@router.post("/jobs/{job_id}/highlights", response_model=HighlightResponse, status_code=201)
async def create_highlight(
    job_id: str,
    req: HighlightCreate,
    db: Session = Depends(get_db),
):
    """Create a new highlight reel, optionally auto-assembling from scored clips."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if req.auto_assemble:
        # Use scoring algorithm to select clips
        clip_ids, actual_dur = auto_assemble_highlight(
            db=db,
            job_id=job_id,
            target_duration_sec=req.target_duration_sec,
            min_score=req.min_score,
            activity_focus=req.activity_focus,
        )
    else:
        clip_ids = []
        actual_dur = 0.0

    reel = HighlightReel(
        job_id=job_id,
        name=req.name,
        clip_ids=clip_ids,
        target_duration_sec=req.target_duration_sec,
        actual_duration_sec=actual_dur,
        transition_type=req.transition_type,
        transition_duration_sec=req.transition_duration_sec,
    )
    db.add(reel)
    db.commit()
    db.refresh(reel)

    return HighlightResponse.model_validate(reel)


@router.get("/jobs/{job_id}/highlights", response_model=HighlightListResponse)
async def list_highlights(job_id: str, db: Session = Depends(get_db)):
    """List all highlight reels for a job."""
    reels = db.query(HighlightReel).filter(HighlightReel.job_id == job_id).all()
    return HighlightListResponse(
        highlights=[HighlightResponse.model_validate(r) for r in reels],
        total=len(reels),
    )


@router.get("/highlights/{highlight_id}", response_model=HighlightResponse)
async def get_highlight(highlight_id: str, db: Session = Depends(get_db)):
    """Get a single highlight reel."""
    reel = db.query(HighlightReel).filter(HighlightReel.id == highlight_id).first()
    if not reel:
        raise HTTPException(404, "Highlight reel not found")
    return HighlightResponse.model_validate(reel)


@router.patch("/highlights/{highlight_id}", response_model=HighlightResponse)
async def update_highlight(
    highlight_id: str,
    update: HighlightUpdate,
    db: Session = Depends(get_db),
):
    """Update a highlight reel — reorder clips, change transitions."""
    reel = db.query(HighlightReel).filter(HighlightReel.id == highlight_id).first()
    if not reel:
        raise HTTPException(404, "Highlight reel not found")

    if update.name is not None:
        reel.name = update.name
    if update.clip_ids is not None:
        reel.clip_ids = update.clip_ids
        # Recalculate actual duration
        total_dur = 0.0
        for cid in update.clip_ids:
            clip = db.query(Clip).filter(Clip.id == cid).first()
            if clip:
                total_dur += clip.duration_sec
        reel.actual_duration_sec = total_dur
    if update.transition_type is not None:
        reel.transition_type = update.transition_type
    if update.transition_duration_sec is not None:
        reel.transition_duration_sec = update.transition_duration_sec

    db.commit()
    db.refresh(reel)
    return HighlightResponse.model_validate(reel)


@router.get("/highlights/{highlight_id}/export/fcpxml")
async def export_fcpxml(
    highlight_id: str,
    media_path: str = Query(None, description="Local media folder path for FCP relink (e.g. /Volumes/SSD/MyProject/)"),
    db: Session = Depends(get_db),
):
    """Generate and download FCPXML file for a highlight reel."""
    reel = db.query(HighlightReel).filter(HighlightReel.id == highlight_id).first()
    if not reel:
        raise HTTPException(404, "Highlight reel not found")

    job = db.query(Job).filter(Job.id == reel.job_id).first()
    if not job:
        raise HTTPException(404, "Associated job not found")

    # Gather clip data
    clips_data = []
    for clip_id in (reel.clip_ids or []):
        clip = db.query(Clip).filter(Clip.id == clip_id).first()
        if clip:
            video = db.query(Video).filter(Video.id == clip.video_id).first()
            clips_data.append({
                "clip": clip,
                "video": video,
            })

    if not clips_data:
        raise HTTPException(400, "No clips found for this highlight reel")

    # Build FCPXML
    builder = FCPXMLBuilder(
        reel_name=reel.name,
        job_name=job.name,
        transition_type=reel.transition_type,
        transition_duration_sec=reel.transition_duration_sec,
        client_base_path=media_path,
    )
    xml_content = builder.build(clips_data)

    # Save to output dir
    output_dir = job.output_dir or "/tmp"
    fcpxml_path = os.path.join(output_dir, f"{reel.name.replace(' ', '_')}.fcpxml")
    with open(fcpxml_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    reel.fcpxml_path = fcpxml_path
    db.commit()

    return FileResponse(
        fcpxml_path,
        media_type="application/xml",
        filename=os.path.basename(fcpxml_path),
    )


@router.get("/highlights/{highlight_id}/export/metadata")
async def export_metadata(highlight_id: str, db: Session = Depends(get_db)):
    """Download JSON metadata bundle for a highlight reel."""
    reel = db.query(HighlightReel).filter(HighlightReel.id == highlight_id).first()
    if not reel:
        raise HTTPException(404, "Highlight reel not found")

    job = db.query(Job).filter(Job.id == reel.job_id).first()
    if not job:
        raise HTTPException(404, "Associated job not found")

    clips = []
    for clip_id in (reel.clip_ids or []):
        clip = db.query(Clip).filter(Clip.id == clip_id).first()
        if clip:
            clips.append(clip)

    output_dir = job.output_dir or "/tmp"
    metadata_path = write_metadata_bundle(reel, clips, output_dir)

    reel.metadata_path = metadata_path
    db.commit()

    return FileResponse(
        metadata_path,
        media_type="application/json",
        filename=os.path.basename(metadata_path),
    )


# Need this import here to avoid circular imports
from app.models.video import Video  # noqa: E402
