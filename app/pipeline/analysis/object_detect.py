"""YOLOv8 object detection module — stub for Phase 9 implementation."""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def run_object_detection(job_id: str, progress_callback: Optional[Callable] = None):
    """Run YOLOv8 detection on all clips for a job.

    TODO: Phase 9 implementation
    - Load YOLOv8 model (yolov8m or yolov8l)
    - Sample frames from each clip
    - Run detection, aggregate results per clip
    - Track person counts for "group shot" scoring
    - Store results in Clip.objects_detected JSON field
    """
    logger.info(f"YOLOv8 object detection not yet implemented (Phase 9) for job {job_id}")
