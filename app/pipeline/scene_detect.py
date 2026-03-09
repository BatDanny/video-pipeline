"""Scene detection module — TransNetV2 (GPU) wrapper.

Uses the TransNetV2 deep learning model for shot boundary detection,
running inference on CUDA for maximum speed. Falls back to uniform
segmentation if TransNetV2 or CUDA is unavailable.
"""

import logging
from typing import Optional

import torch

from app.models.database import get_session_factory
from app.models.job import Job
from app.models.video import Video
from app.models.clip import Clip
from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level model cache — loaded once, reused across calls within a worker
_model = None


def _get_model():
    """Load or return the cached TransNetV2 model on GPU."""
    global _model
    if _model is not None:
        return _model

    try:
        from transnetv2_pytorch import TransNetV2
        import unittest.mock

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading TransNetV2 model on {device}...")

        # Monkeypatch torch.load to enforce weights_only=True to silence PyTorch security warning
        original_load = torch.load
        
        def safe_load(*args, **kwargs):
            kwargs['weights_only'] = True
            return original_load(*args, **kwargs)

        with unittest.mock.patch('torch.load', side_effect=safe_load):
            _model = TransNetV2()
            
        _model.eval()
        _model = _model.to(device)

        logger.info("TransNetV2 model loaded successfully")
        return _model
    except ImportError:
        logger.warning("transnetv2-pytorch not installed — will use fallback")
        return None
    except Exception as e:
        logger.error(f"Failed to load TransNetV2: {e}")
        return None


def _unload_model():
    """Unload the TransNetV2 model to free VRAM for other pipeline stages."""
    global _model
    if _model is not None:
        del _model
        _model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("TransNetV2 model unloaded, VRAM freed")


def _detect_scenes_in_video(filepath: str, threshold: float = 0.5,
                             min_scene_duration: float = 1.0,
                             fps: Optional[float] = None) -> list[tuple[float, float]]:
    """Run TransNetV2 shot boundary detection on a single video file.

    Returns a list of (start_sec, end_sec) tuples for each detected scene.
    """
    model = _get_model()
    if model is None:
        logger.warning("TransNetV2 not available — using fallback uniform segmentation")
        return _fallback_segment(filepath, fps)

    try:
        # predict_video uses ffmpeg internally to decode frames, then runs
        # the neural network on them. Returns:
        #   video_frames: np.array [n_frames, 27, 48, 3]
        #   single_frame_predictions: np.array [n_frames]
        #   all_frame_predictions: np.array [n_frames]
        #
        # AMP (FP16) on Ampere GPUs (RTX 3090) uses Tensor Cores for ~2x speedup
        # and ~40% lower VRAM usage with negligible accuracy loss.
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=torch.cuda.is_available()):
            video_frames, single_frame_predictions, all_frame_predictions = \
                model.predict_video(filepath)

        # Ensure predictions are numpy arrays, not PyTorch tensors, as predictions_to_scenes expects numpy
        if hasattr(single_frame_predictions, "cpu"):
            single_frame_predictions = single_frame_predictions.cpu().detach().numpy()

        # Convert raw predictions to scene boundaries (frame indices)
        # predictions_to_scenes returns an array of [start_frame, end_frame] pairs
        scene_frames = model.predictions_to_scenes(
            single_frame_predictions, threshold=threshold
        )

        # Determine the video FPS for frame→seconds conversion
        video_fps = fps or _probe_fps(filepath) or 30.0
        total_frames = len(single_frame_predictions)

        scenes = []
        for start_frame, end_frame in scene_frames:
            start_sec = start_frame / video_fps
            end_sec = (end_frame + 1) / video_fps  # end_frame is inclusive
            duration = end_sec - start_sec

            if duration >= min_scene_duration:
                scenes.append((round(start_sec, 3), round(end_sec, 3)))

        logger.info(
            f"TransNetV2 detected {len(scenes)} scenes "
            f"(from {len(scene_frames)} raw boundaries, "
            f"{total_frames} frames @ {video_fps:.1f} fps)"
        )
        return scenes

    except Exception as e:
        logger.error(f"TransNetV2 scene detection failed for {filepath}: {e}")
        return _fallback_segment(filepath, fps)


def _probe_fps(filepath: str) -> Optional[float]:
    """Get video FPS via ffprobe."""
    import subprocess
    import json

    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            r_frame_rate = streams[0].get("r_frame_rate", "30/1")
            num, den = r_frame_rate.split("/")
            return float(num) / float(den)
    except Exception:
        pass
    return None


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


def detect_scenes(job_id: str, progress_callback=None) -> int:
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
        min_dur = config.get("min_scene_duration_sec", settings.min_scene_duration_sec)

        videos = db.query(Video).filter(Video.job_id == job_id).all()
        total_clips = 0
        total_videos = len(videos)

        for i, video in enumerate(videos):
            if progress_callback:
                pct = 15.0 + (9.0 * i / total_videos)  # scene detect = 15% to 24%
                progress_callback({
                    "stage": "detecting_scenes",
                    "message": f"Detecting scenes in {video.filename} ({i+1}/{total_videos})...",
                    "progress_pct": round(pct, 1),
                    "file_progress_pct": (i / total_videos) * 100,
                    "file_name": video.filename
                })

            logger.info(f"Detecting scenes in {video.filename}")

            scenes = _detect_scenes_in_video(
                filepath=video.filepath,
                threshold=threshold,
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

            if progress_callback:
                pct = 15.0 + (9.0 * (i + 1) / total_videos)
                progress_callback({
                    "stage": "detecting_scenes",
                    "message": f"Found {len(scenes)} scenes in {video.filename} ({total_clips} total)",
                    "progress_pct": round(pct, 1),
                    "file_progress_pct": ((i + 1) / total_videos) * 100,
                    "file_name": video.filename
                })

        db.commit()
        
        hardware_used = "GPU (TransNetV2)" if _model is not None else "CPU (Fallback)"
        
        logger.info(f"Created {total_clips} clips for job {job_id}")
        return total_clips, hardware_used

    finally:
        # Free GPU VRAM so CLIP/YOLO/Whisper have the full 24GB available
        _unload_model()
        db.close()
