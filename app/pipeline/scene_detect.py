"""Scene detection module — PySceneDetect wrapper."""

import logging
from typing import Optional

from app.models.database import get_session_factory
from app.models.job import Job
from app.models.video import Video
from app.models.clip import Clip
from app.config import get_settings

logger = logging.getLogger(__name__)


def _detect_scenes_in_video(filepath: str, threshold: float = 27.0,
                             method: str = "content",
                             min_scene_duration: float = 1.0,
                             fps: Optional[float] = None) -> list[tuple[float, float]]:
    """Run PySceneDetect on a single video file.

    Returns a list of (start_sec, end_sec) tuples for each detected scene.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector, AdaptiveDetector

        video = open_video(filepath)

        scene_manager = SceneManager()

        if method == "adaptive":
            scene_manager.add_detector(AdaptiveDetector(
                adaptive_threshold=threshold,
                min_scene_len=int((fps or 30) * min_scene_duration),
            ))
        else:
            scene_manager.add_detector(ContentDetector(
                threshold=threshold,
                min_scene_len=int((fps or 30) * min_scene_duration),
            ))

        scene_manager.detect_scenes(video, show_progress=False)
        scene_list = scene_manager.get_scene_list()

        scenes = []
        for start, end in scene_list:
            start_sec = start.get_seconds()
            end_sec = end.get_seconds()
            duration = end_sec - start_sec
            if duration >= min_scene_duration:
                scenes.append((start_sec, end_sec))

        return scenes

    except ImportError:
        logger.warning("PySceneDetect not available — using fallback uniform segmentation")
        return _fallback_segment(filepath, fps)
    except Exception as e:
        logger.error(f"Scene detection failed for {filepath}: {e}")
        return _fallback_segment(filepath, fps)


def _fallback_segment(filepath: str, fps: Optional[float] = None,
                       segment_sec: float = 10.0) -> list[tuple[float, float]]:
    """Fallback: split video into uniform segments when scene detection is unavailable."""
    import subprocess
    import json

    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
    except Exception:
        duration = 60.0  # Assume 60 seconds

    scenes = []
    t = 0.0
    while t < duration:
        end = min(t + segment_sec, duration)
        if end - t >= 1.0:
            scenes.append((t, end))
        t = end

    return scenes


def detect_scenes(job_id: str) -> int:
    """Run scene detection on all videos for a job.

    Creates Clip records for each detected scene.
    Returns total number of clips created.
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Get config from job or defaults
        config = job.config or {}
        threshold = config.get("scene_detect_threshold", settings.scene_detect_threshold)
        method = config.get("scene_detect_method", settings.scene_detect_method)
        min_dur = config.get("min_scene_duration_sec", settings.min_scene_duration_sec)

        videos = db.query(Video).filter(Video.job_id == job_id).all()
        total_clips = 0

        for video in videos:
            logger.info(f"Detecting scenes in {video.filename}")

            scenes = _detect_scenes_in_video(
                filepath=video.filepath,
                threshold=threshold,
                method=method,
                min_scene_duration=min_dur,
                fps=video.fps,
            )

            logger.info(f"Found {len(scenes)} scenes in {video.filename}")

            for start_sec, end_sec in scenes:
                clip = Clip(
                    video_id=video.id,
                    job_id=job_id,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    duration_sec=round(end_sec - start_sec, 3),
                )
                db.add(clip)
                total_clips += 1

        db.commit()
        logger.info(f"Created {total_clips} clips for job {job_id}")
        return total_clips

    finally:
        db.close()
