"""Thumbnail generator — extract representative frames from clips via ffmpeg."""

import os
import subprocess
import logging

from app.models.database import get_session_factory
from app.models.clip import Clip
from app.models.video import Video
from app.models.job import Job

logger = logging.getLogger(__name__)


def generate_thumbnail(video_path: str, timestamp_sec: float,
                        output_path: str, width: int = 320) -> bool:
    """Extract a single frame as a JPEG thumbnail.

    Args:
        video_path: Path to source video file
        timestamp_sec: Time position to extract frame
        output_path: Where to save the thumbnail JPEG
        width: Target width (height auto-scaled)

    Returns:
        True if successful
    """
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp_sec),
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            "-q:v", "3",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)

        if result.returncode == 0 and os.path.isfile(output_path):
            return True
        else:
            logger.warning(f"Thumbnail generation failed: {result.stderr.decode()[:200]}")
            return False

    except Exception as e:
        logger.error(f"Thumbnail error: {e}")
        return False


def generate_preview_clip(video_path: str, start_sec: float, duration_sec: float,
                           output_path: str, max_duration: float = 3.0) -> bool:
    """Generate a short preview clip (re-encoded, small).

    Args:
        video_path: Source video
        start_sec: Start time
        duration_sec: Clip duration
        output_path: Output file path
        max_duration: Maximum preview duration (default 3s)

    Returns:
        True if successful
    """
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        preview_dur = min(duration_sec, max_duration)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", video_path,
            "-t", str(preview_dur),
            "-vf", "scale=640:-1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)

        if result.returncode == 0 and os.path.isfile(output_path):
            return True
        else:
            logger.warning(f"Preview generation failed: {result.stderr.decode()[:200]}")
            return False

    except Exception as e:
        logger.error(f"Preview error: {e}")
        return False


def generate_thumbnails(job_id: str):
    """Generate thumbnails for all clips in a job.

    Extracts a frame from the midpoint of each clip.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        output_dir = os.path.join(job.output_dir or "/tmp", "thumbnails")
        os.makedirs(output_dir, exist_ok=True)

        clips = db.query(Clip).filter(Clip.job_id == job_id).all()

        for clip in clips:
            video = db.query(Video).filter(Video.id == clip.video_id).first()
            if not video:
                continue

            # Generate thumbnail at clip midpoint
            midpoint = clip.start_sec + (clip.duration_sec / 2)
            thumb_path = os.path.join(output_dir, f"{clip.id[:8]}_thumb.jpg")

            if generate_thumbnail(video.filepath, midpoint, thumb_path):
                clip.thumbnail_path = thumb_path

            # Generate short preview clip
            preview_dir = os.path.join(job.output_dir or "/tmp", "previews")
            os.makedirs(preview_dir, exist_ok=True)
            preview_path = os.path.join(preview_dir, f"{clip.id[:8]}_preview.mp4")

            if generate_preview_clip(video.filepath, clip.start_sec,
                                      clip.duration_sec, preview_path):
                clip.preview_path = preview_path

        db.commit()
        logger.info(f"Generated thumbnails for {len(clips)} clips in job {job_id}")

    finally:
        db.close()
