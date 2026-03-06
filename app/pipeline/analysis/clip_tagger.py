"""CLIP activity tagging module — zero-shot classification of video clips."""

import os
import subprocess
import tempfile
import logging
from typing import Callable, Optional

from app.models.database import get_session_factory
from app.models.clip import Clip
from app.models.video import Video
from app.config import get_settings

logger = logging.getLogger(__name__)

# Global model cache (loaded once per worker process)
_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None


def _load_clip_model():
    """Load CLIP model (cached globally per process)."""
    global _clip_model, _clip_preprocess, _clip_tokenizer

    if _clip_model is not None:
        return _clip_model, _clip_preprocess, _clip_tokenizer

    settings = get_settings()

    try:
        import torch
        import open_clip

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading CLIP model {settings.clip_model} on {device}")

        model, _, preprocess = open_clip.create_model_and_transforms(
            settings.clip_model,
            pretrained=settings.clip_pretrained,
            cache_dir=settings.model_cache_dir,
        )
        model = model.to(device)
        model.eval()

        tokenizer = open_clip.get_tokenizer(settings.clip_model)

        _clip_model = model
        _clip_preprocess = preprocess
        _clip_tokenizer = tokenizer

        logger.info(f"CLIP model loaded on {device}")
        return model, preprocess, tokenizer

    except ImportError:
        logger.warning("open_clip not available — CLIP tagging will use placeholder results")
        return None, None, None
    except Exception as e:
        logger.error(f"Failed to load CLIP model: {e}")
        return None, None, None


def _extract_frames(video_path: str, start_sec: float, end_sec: float,
                     num_frames: int = 8) -> list[str]:
    """Extract evenly-spaced frames from a clip using ffmpeg.

    Returns list of paths to extracted frame images.
    """
    duration = end_sec - start_sec
    if duration <= 0:
        return []

    frame_paths = []
    tmpdir = tempfile.mkdtemp(prefix="clip_frames_")

    for i in range(num_frames):
        t = start_sec + (duration * i / max(num_frames - 1, 1))
        out_path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                out_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=15)
            if os.path.isfile(out_path):
                frame_paths.append(out_path)
        except Exception as e:
            logger.debug(f"Frame extraction failed at t={t}: {e}")

    return frame_paths


def _tag_frames_with_clip(frame_paths: list[str], tag_vocabulary: list[str],
                           top_k: int = 5, threshold: float = 0.15) -> list[dict]:
    """Run CLIP zero-shot classification on extracted frames.

    Returns list of {"tag": str, "score": float} dictionaries.
    """
    model, preprocess, tokenizer = _load_clip_model()

    if model is None:
        # Placeholder when CLIP is unavailable
        return [{"tag": "unanalyzed", "score": 0.0}]

    try:
        import torch
        from PIL import Image

        device = next(model.parameters()).device

        # Tokenize text prompts
        text_prompts = [f"a photo of {tag}" for tag in tag_vocabulary]
        text_tokens = tokenizer(text_prompts).to(device)

        with torch.no_grad():
            text_features = model.encode_text(text_tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

        # Process each frame
        all_scores = []
        for frame_path in frame_paths:
            try:
                image = Image.open(frame_path).convert("RGB")
                image_tensor = preprocess(image).unsqueeze(0).to(device)

                with torch.no_grad():
                    image_features = model.encode_image(image_tensor)
                    image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                    similarity = (image_features @ text_features.T).squeeze(0)

                all_scores.append(similarity.cpu().numpy())
            except Exception as e:
                logger.debug(f"Failed to process frame {frame_path}: {e}")

        if not all_scores:
            return [{"tag": "unanalyzed", "score": 0.0}]

        # Average scores across frames
        import numpy as np
        avg_scores = np.mean(all_scores, axis=0)

        # Build results: top-K tags above threshold
        results = []
        indices = np.argsort(avg_scores)[::-1]
        for idx in indices[:top_k]:
            score = float(avg_scores[idx])
            if score >= threshold:
                results.append({
                    "tag": tag_vocabulary[idx],
                    "score": round(score, 4),
                })

        return results if results else [{"tag": tag_vocabulary[indices[0]], "score": round(float(avg_scores[indices[0]]), 4)}]

    except Exception as e:
        logger.error(f"CLIP inference error: {e}")
        return [{"tag": "error", "score": 0.0}]

    finally:
        # Clean up extracted frames
        import shutil
        for frame_path in frame_paths:
            tmpdir = os.path.dirname(frame_path)
            if tmpdir and os.path.isdir(tmpdir) and "clip_frames_" in tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
                break


def run_clip_tagging(job_id: str, progress_callback: Optional[Callable] = None):
    """Run CLIP tagging on all clips for a job.

    Updates each Clip record with tags.
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        total = len(clips)

        if total == 0:
            logger.info(f"No clips to tag for job {job_id}")
            return

        # Get tag vocabulary from job config or defaults
        from app.models.job import Job
        job = db.query(Job).filter(Job.id == job_id).first()
        config = job.config or {}
        tag_vocab = config.get("tag_vocabulary", settings.default_tag_vocabulary)

        logger.info(f"Tagging {total} clips for job {job_id}")

        for i, clip in enumerate(clips):
            try:
                # Get source video path
                video = db.query(Video).filter(Video.id == clip.video_id).first()
                if not video:
                    continue

                # Extract frames
                frame_paths = _extract_frames(
                    video_path=video.filepath,
                    start_sec=clip.start_sec,
                    end_sec=clip.end_sec,
                    num_frames=settings.clip_sample_frames,
                )

                # Run CLIP
                tags = _tag_frames_with_clip(
                    frame_paths=frame_paths,
                    tag_vocabulary=tag_vocab,
                    top_k=settings.clip_top_k_tags,
                    threshold=settings.clip_confidence_threshold,
                )

                clip.tags = tags
                db.commit()

                # Report progress
                if progress_callback:
                    pct = 30.0 + (45.0 * (i + 1) / total)  # 30% to 75%
                    progress_callback({
                        "stage": "analyzing",
                        "sub_stage": "clip_tagging",
                        "current_clip": i + 1,
                        "total_clips": total,
                        "message": f"Tagging clip {i + 1}/{total}...",
                        "progress_pct": round(pct, 1),
                    })

            except Exception as e:
                logger.error(f"Failed to tag clip {clip.id}: {e}")
                clip.analysis_errors = clip.analysis_errors or {}
                if isinstance(clip.analysis_errors, dict):
                    clip.analysis_errors["clip_tagger"] = str(e)
                elif isinstance(clip.analysis_errors, list):
                    clip.analysis_errors.append({"module": "clip_tagger", "error": str(e)})
                db.commit()

        # Free GPU memory after batch
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.info(f"Completed CLIP tagging for job {job_id}")

    finally:
        db.close()
