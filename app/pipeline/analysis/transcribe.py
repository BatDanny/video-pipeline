"""Whisper transcription module — extract speech and generate transcripts.

Uses OpenAI Whisper for automatic speech recognition on clip audio.
Designed for GoPro footage where speech may be intermittent with wind/action noise.
"""

import os
import logging
import subprocess
import tempfile
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global model cache
_whisper_model = None


def _load_model():
    """Load Whisper model with GPU support."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        import whisper
        import torch

        settings = get_settings()
        model_size = getattr(settings, 'whisper_model', 'medium')
        cache_dir = settings.model_cache_dir

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"Loading Whisper '{model_size}' model on {device}")

        _whisper_model = whisper.load_model(
            model_size,
            device=device,
            download_root=cache_dir if cache_dir else None,
        )

        logger.info(f"Whisper model loaded on {device}")
        return _whisper_model

    except Exception as e:
        logger.warning(f"Failed to load Whisper: {e}")
        return None


def _unload_model():
    """Free GPU memory by unloading the Whisper model."""
    global _whisper_model
    if _whisper_model is not None:
        del _whisper_model
        _whisper_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("Whisper model unloaded")


def _extract_audio(video_path: str, start_sec: float, duration_sec: float,
                    output_path: str) -> bool:
    """Extract audio segment from video using ffmpeg."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", video_path,
            "-t", str(duration_sec),
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # Whisper expects WAV
            "-ar", "16000",  # 16kHz sample rate (Whisper's native)
            "-ac", "1",  # Mono
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.returncode == 0 and os.path.isfile(output_path)
    except Exception as e:
        logger.error(f"Audio extraction failed: {e}")
        return False


def transcribe_clip(video_path: str, start_sec: float, end_sec: float,
                     language: str = None) -> dict:
    """Transcribe speech in a clip segment.

    Args:
        video_path: Path to source video
        start_sec, end_sec: Clip boundaries
        language: Optional language code (e.g., 'en'). Auto-detect if None.

    Returns:
        Dict with 'transcript', 'has_speech', 'language', 'confidence',
        'word_count', 'segments'
    """
    model = _load_model()
    if model is None:
        return {
            'transcript': None,
            'has_speech': False,
            'language': None,
            'confidence': 0.0,
            'word_count': 0,
            'segments': [],
        }

    duration = end_sec - start_sec
    tmp_audio = None

    try:
        # Extract audio segment
        tmp_audio = tempfile.mktemp(suffix=".wav", prefix="whisper_")
        if not _extract_audio(video_path, start_sec, duration, tmp_audio):
            logger.warning(f"Could not extract audio from {video_path}")
            return {
                'transcript': None, 'has_speech': False,
                'language': None, 'confidence': 0.0,
                'word_count': 0, 'segments': [],
            }

        # Check audio file size (skip very small/empty audio)
        if os.path.getsize(tmp_audio) < 1000:
            return {
                'transcript': None, 'has_speech': False,
                'language': None, 'confidence': 0.0,
                'word_count': 0, 'segments': [],
            }

        # Run transcription
        options = {
            'fp16': True,  # Use half precision on GPU
            'language': language,
            'task': 'transcribe',
            'no_speech_threshold': 0.6,  # Higher threshold = more strict
            'logprob_threshold': -1.0,
            'compression_ratio_threshold': 2.4,
        }

        import torch
        if not torch.cuda.is_available():
            options['fp16'] = False

        result = model.transcribe(tmp_audio, **options)

        transcript_text = result.get('text', '').strip()
        segments = result.get('segments', [])
        detected_lang = result.get('language', 'unknown')

        # Calculate speech confidence from segment probabilities
        if segments:
            avg_no_speech = sum(
                s.get('no_speech_prob', 1.0) for s in segments
            ) / len(segments)
            has_speech = avg_no_speech < 0.5
            confidence = 1.0 - avg_no_speech
        else:
            has_speech = False
            confidence = 0.0

        # Filter out hallucinated/low-quality transcripts
        word_count = len(transcript_text.split()) if transcript_text else 0
        if word_count < 2 or confidence < 0.3:
            transcript_text = None
            has_speech = False

        # Clean up segment data for storage
        clean_segments = []
        for seg in segments[:50]:  # Cap at 50 segments
            clean_segments.append({
                'start': round(seg.get('start', 0), 2),
                'end': round(seg.get('end', 0), 2),
                'text': seg.get('text', '').strip(),
            })

        return {
            'transcript': transcript_text,
            'has_speech': has_speech,
            'language': detected_lang,
            'confidence': round(confidence, 3),
            'word_count': word_count,
            'segments': clean_segments,
        }

    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return {
            'transcript': None, 'has_speech': False,
            'language': None, 'confidence': 0.0,
            'word_count': 0, 'segments': [],
        }

    finally:
        if tmp_audio and os.path.isfile(tmp_audio):
            os.unlink(tmp_audio)


def transcribe_clips_for_job(job_id: str):
    """Run Whisper on all clips in a job. Called by the orchestrator."""
    from app.models.database import get_session_factory
    from app.models.clip import Clip
    from app.models.video import Video

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Running Whisper on {len(clips)} clips for job {job_id}")

        for clip in clips:
            video = db.query(Video).filter(Video.id == clip.video_id).first()
            if not video:
                continue

            result = transcribe_clip(video.filepath, clip.start_sec, clip.end_sec)

            clip.transcript = result['transcript']
            clip.has_speech = result['has_speech']

        db.commit()
        logger.info(f"Whisper transcription complete for job {job_id}")

    finally:
        _unload_model()
        db.close()
