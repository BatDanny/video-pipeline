"""YOLOv8 object detection module — detect people, animals, vehicles, sports equipment.

Uses Ultralytics YOLOv8 for frame-level object detection, then aggregates
detected objects across sampled frames to produce per-clip object lists.
"""

import os
import logging
import subprocess
import tempfile
from typing import Optional
from collections import Counter

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global model cache (one per worker process)
_yolo_model = None


def _load_model():
    """Load YOLOv8 model with GPU support."""
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model

    try:
        from ultralytics import YOLO
        import torch

        settings = get_settings()
        model_name = getattr(settings, 'yolo_model', 'yolov8m.pt')
        cache_dir = settings.model_cache_dir

        # Check for cached model
        model_path = os.path.join(cache_dir, model_name) if cache_dir else model_name

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"Loading YOLOv8 model '{model_name}' on {device}")

        _yolo_model = YOLO(model_path)
        # Warm up
        _yolo_model.predict(
            source=__import__('numpy').zeros((640, 640, 3), dtype=__import__('numpy').uint8),
            device=device, verbose=False
        )

        logger.info(f"YOLOv8 model loaded on {device}")
        return _yolo_model

    except Exception as e:
        logger.warning(f"Failed to load YOLOv8: {e}")
        return None


def _unload_model():
    """Free GPU memory by unloading the YOLO model."""
    global _yolo_model
    if _yolo_model is not None:
        del _yolo_model
        _yolo_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("YOLOv8 model unloaded")


def _extract_frames(video_path: str, start_sec: float, duration_sec: float,
                     num_frames: int = 6, output_dir: str = None) -> list[str]:
    """Extract evenly-spaced frames from a clip segment using ffmpeg."""
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="yolo_frames_")

    os.makedirs(output_dir, exist_ok=True)
    frame_paths = []

    interval = max(duration_sec / (num_frames + 1), 0.1)

    for i in range(num_frames):
        t = start_sec + interval * (i + 1)
        out_path = os.path.join(output_dir, f"frame_{i:03d}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(t), "-i", video_path,
            "-vframes", "1", "-q:v", "2", out_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.isfile(out_path):
            frame_paths.append(out_path)

    return frame_paths


# Object categories relevant to the user's use case
RELEVANT_CATEGORIES = {
    # People
    'person': 'person',
    # Animals
    'dog': 'dog', 'cat': 'cat', 'bird': 'bird', 'horse': 'horse',
    # Vehicles
    'car': 'vehicle', 'truck': 'vehicle', 'motorcycle': 'vehicle',
    'bicycle': 'bicycle', 'boat': 'boat',
    # Sports equipment
    'snowboard': 'snowboard', 'skis': 'skis', 'surfboard': 'surfboard',
    'sports ball': 'sports_ball', 'kite': 'kite',
    'skateboard': 'skateboard',
    # Other useful
    'backpack': 'backpack', 'umbrella': 'umbrella',
}


def detect_objects(video_path: str, start_sec: float, end_sec: float,
                    confidence_threshold: float = 0.35,
                    num_frames: int = 6) -> list[dict]:
    """Run YOLOv8 object detection on a clip segment.

    Args:
        video_path: Path to source video
        start_sec, end_sec: Clip boundaries
        confidence_threshold: Minimum detection confidence
        num_frames: Number of frames to sample

    Returns:
        List of dicts with 'class_name', 'count', 'avg_confidence', 'category'
    """
    model = _load_model()
    if model is None:
        logger.info("YOLOv8 not available — returning empty detections")
        return []

    duration = end_sec - start_sec
    frame_paths = []
    tmp_dir = None

    try:
        import torch

        # Extract frames
        tmp_dir = tempfile.mkdtemp(prefix="yolo_")
        frame_paths = _extract_frames(video_path, start_sec, duration, num_frames, tmp_dir)

        if not frame_paths:
            return []

        # Run inference
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        results = model.predict(
            source=frame_paths,
            device=device,
            conf=confidence_threshold,
            verbose=False,
            imgsz=640,
        )

        # Aggregate detections across all frames
        all_detections = Counter()
        confidence_sums = Counter()

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names.get(cls_id, f"class_{cls_id}")
                conf = float(box.conf[0])

                if cls_name in RELEVANT_CATEGORIES:
                    category = RELEVANT_CATEGORIES[cls_name]
                    all_detections[cls_name] += 1
                    confidence_sums[cls_name] += conf

        # Build result list
        objects = []
        for cls_name, count in all_detections.most_common():
            objects.append({
                'class_name': cls_name,
                'category': RELEVANT_CATEGORIES.get(cls_name, cls_name),
                'count': count,
                'avg_confidence': confidence_sums[cls_name] / count,
                'frames_detected': min(count, num_frames),
            })

        return objects

    except Exception as e:
        logger.error(f"Object detection error: {e}")
        return []

    finally:
        # Clean up temp frames
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


def detect_objects_for_job(job_id: str):
    """Run object detection on all clips in a job. Called by the orchestrator."""
    from app.models.database import get_session_factory
    from app.models.clip import Clip
    from app.models.video import Video

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Running YOLOv8 on {len(clips)} clips for job {job_id}")

        for clip in clips:
            video = db.query(Video).filter(Video.id == clip.video_id).first()
            if not video:
                continue

            objects = detect_objects(
                video.filepath, clip.start_sec, clip.end_sec,
                num_frames=6,
            )

            clip.objects_detected = objects
            logger.debug(f"Clip {clip.id[:8]}: {len(objects)} object types detected")

        db.commit()
        logger.info(f"Object detection complete for job {job_id}")

    finally:
        _unload_model()
        db.close()
