"""Ingest module — file validation, ffprobe metadata extraction, GoPro telemetry."""

import os
import json
import subprocess
import logging
import hashlib
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


def _get_fast_file_hash(filepath: str, chunk_size: int = 1024 * 1024) -> str:
    """Generate a fast, deterministic hash for a video file.
    
    Reads up to the first 4MB plus the file size to avoid hashing multi-GB
    files completely, which would massively slow down ingestion.
    """
    hasher = hashlib.md5()
    try:
        file_stat = os.stat(filepath)
        hasher.update(str(file_stat.st_size).encode('utf-8'))
        
        with open(filepath, 'rb') as f:
            for _ in range(4): # Read first 4MB max
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
    except Exception as e:
        logger.warning(f"Hash calculation failed for {filepath}: {e}")
        return filepath # fallback to absolute filepath if we can't hash
        
    return hasher.hexdigest()


def ingest_videos(job_id: str, progress_callback=None) -> int:
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
        logger.info(f"Scanning directory for supported videos: {source_dir}")
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
        total_files = len(video_files)
        seen_hashes = set()
        
        for filepath in video_files:
            if progress_callback:
                pct = (count / total_files) * 14.0  # ingest = 0% to 14%
                progress_callback({
                    "stage": "ingesting",
                    "message": f"Probing {os.path.basename(filepath)} ({count+1}/{total_files})...",
                    "progress_pct": round(pct, 1),
                    "file_progress_pct": (count / total_files) * 100,
                    "file_name": os.path.basename(filepath)
                })

            # Deduplication check
            file_hash = _get_fast_file_hash(filepath)
            if file_hash in seen_hashes:
                logger.info(f"[{count+1}/{total_files}] Skipping duplicate file: {filepath}")
                if progress_callback:
                    progress_callback({
                        "stage": "ingesting",
                        "message": f"Skipped duplicate: {os.path.basename(filepath)}",
                        "file_progress_pct": (count / total_files) * 100,
                        "file_name": os.path.basename(filepath)
                    })
                count += 1
                continue
                
            seen_hashes.add(file_hash)

            # Probe with ffprobe
            logger.info(f"[{count+1}/{total_files}] Probing file: {filepath}")
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
            logger.info(f"Created Video record for {filepath}")
            db.add(video)
            count += 1

            if progress_callback:
                progress_callback({
                    "stage": "ingesting",
                    "message": f"Ingested {os.path.basename(filepath)}",
                    "file_progress_pct": (count / total_files) * 100,
                    "file_name": os.path.basename(filepath)
                })

        db.commit()
        logger.info(f"Ingested {count} videos for job {job_id}")
        return count

    finally:
        db.close()
