"""Whisper transcription module — stub for Phase 9 implementation."""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def run_transcription(job_id: str, progress_callback: Optional[Callable] = None):
    """Run Whisper transcription on all clips for a job.

    TODO: Phase 9 implementation
    - Extract audio from clip time range via ffmpeg (to temp WAV)
    - Run Whisper (medium or large-v3 model)
    - Store transcript text + word-level timestamps
    - Compute has_speech boolean and speech duration ratio
    """
    logger.info(f"Whisper transcription not yet implemented (Phase 9) for job {job_id}")
