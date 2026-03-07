"""YOLOv8 object detection module — detect people, animals, vehicles, sports equipment.

Uses Ultralytics YOLOv8 for frame-level object detection, aggregated per-clip.
Optimized to extract frames entirely in-memory using cv2.
"""

import os
import logging
from collections import Counter, defaultdict
import cv2

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

        if model_name == "auto":
            from app.utils.hardware import get_vram_gb
            vram_gb = get_vram_gb()
            if vram_gb >= 22.0:
                model_name = "yolov8x.pt"
            elif vram_gb >= 14.0:
                model_name = "yolov8l.pt"
            else:
                model_name = "yolov8m.pt"

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


def detect_objects_for_job(job_id: str, progress_callback=None):
    """Run object detection on all clips in a job natively from RAM via OpenCV."""
    from app.models.database import get_session_factory
    from app.models.clip import Clip
    from app.models.video import Video
    import torch

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        model = _load_model()
        if model is None:
            logger.error("YOLOv8 model unavailable; skipping detection.")
            return

        settings = get_settings()
        confidence_threshold = getattr(settings, 'yolo_confidence_threshold', 0.35)
        num_frames = getattr(settings, 'yolo_sample_frames', 6)
        imgsz = getattr(settings, 'yolo_imgsz', 1280)
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Running YOLOv8 on {len(clips)} clips for job {job_id}")

        if not clips:
            return

        # Group by video
        video_clips = defaultdict(list)
        for clip in clips:
            video_clips[clip.video_id].append(clip)

        total_clips = len(clips)
        processed_clips = 0

        for video_id, vclips in video_clips.items():
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video or not os.path.exists(video.filepath):
                continue

            cap = cv2.VideoCapture(video.filepath)
            if not cap.isOpened():
                logger.error(f"Cannot open video {video.filepath}")
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            # Sort clips by start time
            vclips.sort(key=lambda c: c.start_sec)

            for clip in vclips:
                duration_sec = clip.end_sec - clip.start_sec
                interval = max(duration_sec / (num_frames + 1), 0.1)
                
                frame_images = []
                for i in range(num_frames):
                    t = clip.start_sec + interval * (i + 1)
                    frame_idx = int(t * fps)
                    
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    ret, frame = cap.read()
                    
                    if ret and frame is not None:
                        frame_images.append(frame) # YOLO works with BGR numpy matrices directly
                
                if frame_images:
                    results = model.predict(
                        source=frame_images,
                        device=device,
                        conf=confidence_threshold,
                        verbose=False,
                        imgsz=imgsz,
                    )

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

                    objects = []
                    for cls_name, count in all_detections.most_common():
                        objects.append({
                            'class_name': cls_name,
                            'category': RELEVANT_CATEGORIES.get(cls_name, cls_name),
                            'count': count,
                            'avg_confidence': confidence_sums[cls_name] / count,
                            'frames_detected': min(count, num_frames),
                        })
                    clip.objects_detected = objects
                else:
                    clip.objects_detected = []

                db.commit()
                processed_clips += 1
                
                logger.debug(f"Clip {clip.id[:8]}: {len(clip.objects_detected)} object types detected")

                if progress_callback:
                    pct = 40.0 + (14.0 * processed_clips / total_clips)
                    progress_callback({
                        "stage": "analyzing",
                        "sub_stage": "object_detection",
                        "message": f"Detecting objects in clip {processed_clips}/{total_clips}...",
                        "progress_pct": round(pct, 1),
                        "file_progress_pct": (processed_clips / total_clips) * 100,
                        "file_name": f"Clip {processed_clips}/{total_clips}"
                    })

            cap.release()

        logger.info(f"Object detection complete for job {job_id}")

    finally:
        _unload_model()
        db.close()
