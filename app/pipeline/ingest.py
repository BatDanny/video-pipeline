"""Ingest module — file validation, ffprobe metadata extraction, GoPro telemetry."""

import os
import json
import subprocess
import logging
from typing import Optional

from app.models.database import get_session_factory
from app.models.job import Job
from app.models.video import Video

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
SUPPORTED_CODECS = {"hevc", "h264", "h265", "av1", "vp9"}


def _run_ffprobe(filepath: str) -> Optional[dict]:
    """Run ffprobe on a video file and return parsed JSON metadata."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"ffprobe failed for {filepath}: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"ffprobe error for {filepath}: {e}")
        return None


def _extract_video_metadata(probe_data: dict) -> dict:
    """Extract structured metadata from ffprobe output."""
    info = {
        "duration_sec": None,
        "resolution": None,
        "fps": None,
        "codec": None,
        "file_size_bytes": None,
    }

    # From format
    fmt = probe_data.get("format", {})
    info["duration_sec"] = float(fmt.get("duration", 0)) or None
    info["file_size_bytes"] = int(fmt.get("size", 0)) or None

    # From video stream
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            info["codec"] = stream.get("codec_name", "")
            width = stream.get("width", 0)
            height = stream.get("height", 0)
            if width and height:
                info["resolution"] = f"{width}x{height}"

            # Parse frame rate
            r_frame_rate = stream.get("r_frame_rate", "")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                if int(den) > 0:
                    info["fps"] = round(int(num) / int(den), 2)
            elif r_frame_rate:
                try:
                    info["fps"] = float(r_frame_rate)
                except ValueError:
                    pass
            break

    return info


def _extract_gopro_telemetry(filepath: str) -> Optional[dict]:
    """Attempt to extract GoPro GPMF telemetry from the video file.

    Uses ffprobe to check for data streams (GoPro metadata track).
    Returns basic telemetry info if present.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "d",  # Data streams
            filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        # Check for GoPro metadata stream
        for stream in streams:
            codec_tag = stream.get("codec_tag_string", "").lower()
            codec_name = stream.get("codec_name", "").lower()
            if "gpmd" in codec_tag or "gpmd" in codec_name or "gopro" in codec_tag:
                return {
                    "has_telemetry": True,
                    "stream_index": stream.get("index"),
                    "codec_tag": stream.get("codec_tag_string"),
                }

        return None

    except Exception as e:
        logger.debug(f"No GoPro telemetry in {filepath}: {e}")
        return None


def ingest_videos(job_id: str) -> int:
    """Ingest all video files for a job.

    Scans the job's source_dir, validates files, probes with ffprobe,
    and creates Video records in the database.

    Returns the number of videos ingested.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        source_dir = job.source_dir
        if not source_dir or not os.path.isdir(source_dir):
            raise ValueError(f"Source directory not found: {source_dir}")

        # Scan for video files (including subdirectories)
        video_files = []
        for root, _dirs, files in os.walk(source_dir):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    video_files.append(os.path.join(root, fname))

        if not video_files:
            raise ValueError(f"No supported video files found in {source_dir}")

        logger.info(f"Found {len(video_files)} video files for job {job_id}")

        count = 0
        for filepath in video_files:
            # Probe with ffprobe
            probe_data = _run_ffprobe(filepath)
            if not probe_data:
                logger.warning(f"Skipping {filepath} — ffprobe failed")
                continue

            metadata = _extract_video_metadata(probe_data)

            # Check for GoPro telemetry
            gopro_meta = _extract_gopro_telemetry(filepath)

            # Create Video record
            video = Video(
                job_id=job_id,
                filename=os.path.basename(filepath),
                filepath=filepath,
                duration_sec=metadata["duration_sec"],
                resolution=metadata["resolution"],
                fps=metadata["fps"],
                codec=metadata["codec"],
                file_size_bytes=metadata["file_size_bytes"],
                gopro_metadata=gopro_meta,
            )
            db.add(video)
            count += 1

        db.commit()
        logger.info(f"Ingested {count} videos for job {job_id}")
        return count

    finally:
        db.close()
