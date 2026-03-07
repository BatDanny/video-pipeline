"""Whisper transcription module — extract speech and generate transcripts.

Optimized to extract full-video audio via a single ffmpeg call, load it
via soundfile, and pass numpy array slices directly to Whisper to dodge
the terrible per-clip I/O overhead.
"""

import os
import logging
import subprocess
import tempfile
from typing import Optional
from collections import defaultdict
import numpy as np
import soundfile as sf

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

        if model_size == "auto":
            from app.utils.hardware import get_vram_gb
            vram_gb = get_vram_gb()
            if vram_gb >= 22.0:
                model_size = "large-v3"
            elif vram_gb >= 14.0:
                model_size = "medium"
            else:
                model_size = "small"

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


def _extract_full_audio(video_path: str, output_path: str) -> bool:
    """Extract audio from the ENTIRE video into a 16kHz WAV."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # Whisper expects WAV 16-bit
            "-ar", "16000",  # 16kHz sample rate (Whisper native)
            "-ac", "1",  # Mono
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)  # Long timeout for full video
        return result.returncode == 0 and os.path.isfile(output_path)
    except Exception as e:
        logger.error(f"Audio extraction failed: {e}")
        return False


def _transcribe_audio_array(model, audio_data: np.ndarray, language: str = None) -> dict:
    """Transcribe a clip's audio directly from a memory numpy array."""
    # Ensure audio is float32 normalized to [-1.0, 1.0] for Whisper
    audio_data = audio_data.astype(np.float32)

    # Check for empty/silent sequences
    if len(audio_data) < 16000 or np.abs(audio_data).max() < 0.001:
        return {
            'transcript': None, 'has_speech': False,
            'language': None, 'confidence': 0.0,
            'word_count': 0, 'segments': [],
        }

    try:
        import torch
        options = {
            'fp16': True if torch.cuda.is_available() else False,
            'language': language,
            'task': 'transcribe',
            'no_speech_threshold': 0.6,
            'logprob_threshold': -1.0,
            'compression_ratio_threshold': 2.4,
        }

        # Passing native numpy array directly to whisper!
        result = model.transcribe(audio_data, **options)

        transcript_text = result.get('text', '').strip()
        segments = result.get('segments', [])
        detected_lang = result.get('language', 'unknown')

        # Calculate speech confidence
        if segments:
            avg_no_speech = sum(s.get('no_speech_prob', 1.0) for s in segments) / len(segments)
            has_speech = avg_no_speech < 0.5
            confidence = 1.0 - avg_no_speech
        else:
            has_speech = False
            confidence = 0.0

        word_count = len(transcript_text.split()) if transcript_text else 0
        if word_count < 2 or confidence < 0.3:
            transcript_text = None
            has_speech = False

        clean_segments = []
        for seg in segments[:50]:
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
        logger.error(f"Whisper inference error: {e}")
        return {
            'transcript': None, 'has_speech': False,
            'language': None, 'confidence': 0.0,
            'word_count': 0, 'segments': [],
        }


def transcribe_clips_for_job(job_id: str, progress_callback=None):
    """Run Whisper on all clips in a job natively from RAM via numpy array slicing."""
    from app.models.database import get_session_factory
    from app.models.clip import Clip
    from app.models.video import Video

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        model = _load_model()
        if model is None:
            logger.error("Whisper model unavailable; skipping transcription.")
            return

        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Running Whisper on {len(clips)} clips for job {job_id}")

        if not clips:
            return
            
        video_clips = defaultdict(list)
        for clip in clips:
            video_clips[clip.video_id].append(clip)
            
        total_clips = len(clips)
        processed_clips = 0

        for video_id, vclips in video_clips.items():
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video or not os.path.exists(video.filepath):
                continue
                
            tmp_full_audio = tempfile.mktemp(suffix=".wav", prefix=f"whisper_{video_id}_")
            
            try:
                # Extract full video audio ONCE
                logger.info(f"Extracting full audio for video {video.filename}")
                if not _extract_full_audio(video.filepath, tmp_full_audio):
                    logger.warning(f"Could not extract audio from {video.filepath}")
                    continue
                    
                # Read into memory float32 numpy array
                audio_array, samplerate = sf.read(tmp_full_audio, dtype='float32')
                if samplerate != 16000:
                    logger.warning(f"Unexpected samplerate {samplerate} from video {video.filepath}")

                vclips.sort(key=lambda c: c.start_sec)
                
                for clip in vclips:
                    # Slice the audio array natively!
                    start_sample = int(clip.start_sec * samplerate)
                    end_sample = int(clip.end_sec * samplerate)
                    
                    # Ensure boundaries are within array length
                    clip_audio = audio_array[start_sample:end_sample]
                    
                    result = _transcribe_audio_array(model, clip_audio)
                    clip.transcript = result.get('transcript')
                    clip.has_speech = result.get('has_speech', False)

                    db.commit()
                    processed_clips += 1

                    if progress_callback:
                        pct = 55.0 + (9.0 * processed_clips / total_clips)
                        progress_callback({
                            "stage": "analyzing",
                            "sub_stage": "transcription",
                            "message": f"Transcribing clip {processed_clips}/{total_clips}...",
                            "progress_pct": round(pct, 1),
                            "file_progress_pct": (processed_clips / total_clips) * 100,
                            "file_name": f"Clip {processed_clips}/{total_clips}"
                        })
            
            finally:
                if tmp_full_audio and os.path.isfile(tmp_full_audio):
                    os.unlink(tmp_full_audio)

        logger.info(f"Whisper transcription complete for job {job_id}")

    finally:
        _unload_model()
        db.close()
