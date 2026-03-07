"""CLIP activity tagging module — zero-shot classification of video clips.

Optimized to extract frames entirely in-memory using cv2,
eliminating ffmpeg subprocess overhead and keeping the GPU fed.
"""

import os
import logging
from typing import Callable, Optional
from collections import defaultdict
import numpy as np
import cv2
from PIL import Image
import torch

from app.models.database import get_session_factory
from app.models.clip import Clip
from app.models.video import Video
from app.models.job import Job
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
        import open_clip
        from app.utils.hardware import get_vram_gb

        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        model_name = settings.clip_model
        pretrained = settings.clip_pretrained
        
        if model_name == "auto":
            vram_gb = get_vram_gb()
            if vram_gb >= 22.0:
                model_name = "ViT-H-14"
                pretrained = "laion2b_s32b_b79k"
            elif vram_gb >= 14.0:
                model_name = "ViT-L-14"
                pretrained = "laion2b_s32b_b82k"
            else:
                model_name = "ViT-B-16"
                pretrained = "laion2b_s34b_b88k"
                
        logger.info(f"Loading CLIP model {model_name} on {device}")

        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained=pretrained,
            cache_dir=settings.model_cache_dir,
        )
        model = model.to(device)
        model.eval()

        tokenizer = open_clip.get_tokenizer(model_name)

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


def _unload_clip_model():
    """Free GPU memory by unloading the CLIP model."""
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is not None:
        del _clip_model
        del _clip_preprocess
        del _clip_tokenizer
        _clip_model = None
        _clip_preprocess = None
        _clip_tokenizer = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("CLIP model unloaded, VRAM freed")


def _get_video_props(video_path: str):
    """Get video fps and frame count using cv2."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 30.0, 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, total_frames


def _tag_frames_with_clip(image_tensors: list[torch.Tensor], tag_vocabulary: list[str],
                          text_features: torch.Tensor,
                          top_k: int = 5, threshold: float = 0.15) -> tuple[list[dict], Optional[torch.Tensor]]:
    """Run CLIP zero-shot classification on extracted frame tensors.

    Returns a tuple of (list of {"tag": str, "score": float} dictionaries, semantic fingerprint tensor).
    """
    model, _, _ = _load_clip_model()

    if model is None or not image_tensors:
        return [{"tag": "unanalyzed", "score": 0.0}], None

    try:
        device = next(model.parameters()).device

        # Stack into a single batch tensor and process in one GPU pass
        batch = torch.stack(image_tensors).to(device)

        with torch.no_grad():
            image_features = model.encode_image(batch)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            
            # Create Semantic Fingerprint to find Visual Duplicates
            clip_fingerprint = image_features.mean(dim=0)
            clip_fingerprint = clip_fingerprint / clip_fingerprint.norm(dim=-1, keepdim=True)
            
            # Similarity matrix: (batch_size, num_tags)
            similarities = (image_features @ text_features.T)

        # Average scores across all frames
        avg_scores = similarities.mean(dim=0).cpu().numpy()

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
                
        final_tags = results if results else [{"tag": tag_vocabulary[indices[0]], "score": round(float(avg_scores[indices[0]]), 4)}]
        return final_tags, clip_fingerprint

    except Exception as e:
        logger.error(f"CLIP inference error: {e}")
        return [{"tag": "error", "score": 0.0}], None


def run_clip_tagging(job_id: str, progress_callback: Optional[Callable] = None):
    """Run CLIP tagging on all clips for a job, processing by video to avoid subprocess overhead."""
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        # Load model first
        model, preprocess, tokenizer = _load_clip_model()
        if model is None:
            logger.error("CLIP model unavailable; skipping tagging.")
            return

        device = next(model.parameters()).device

        # Setup text prompts (do this once)
        job = db.query(Job).filter(Job.id == job_id).first()
        config = job.config or {}
        tag_vocab = config.get("tag_vocabulary", settings.default_tag_vocabulary)

        text_prompts = [f"a photo of {tag}" for tag in tag_vocab]
        text_tokens = tokenizer(text_prompts).to(device)

        with torch.no_grad():
            text_features = model.encode_text(text_tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        total_clips = len(clips)

        if total_clips == 0:
            logger.info(f"No clips to tag for job {job_id}")
            return

        logger.info(f"Tagging {total_clips} clips for job {job_id}")

        # Group clips by video
        video_clips = defaultdict(list)
        for clip in clips:
            video_clips[clip.video_id].append(clip)

        processed_clips = 0
        seen_fingerprints: list[torch.Tensor] = []
        similarity_threshold = getattr(settings, 'clip_similarity_threshold', 0.97)

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
                duration = clip.end_sec - clip.start_sec
                num_frames = settings.clip_sample_frames
                
                image_tensors = []
                # Calculate required frame indices
                for i in range(num_frames):
                    t = clip.start_sec + (duration * i / max(num_frames - 1, 1))
                    frame_idx = int(t * fps)
                    
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    ret, frame = cap.read()
                    
                    if ret and frame is not None:
                        # OpenCV returns BGR, convert to RGB
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        image = Image.fromarray(frame_rgb)
                        image_tensors.append(preprocess(image))
                
                if image_tensors:
                    tags, fingerprint = _tag_frames_with_clip(
                        image_tensors=image_tensors,
                        tag_vocabulary=tag_vocab,
                        text_features=text_features,
                        top_k=settings.clip_top_k_tags,
                        threshold=settings.clip_confidence_threshold,
                    )
                    
                    # Deduplication check
                    if fingerprint is not None and seen_fingerprints:
                        seen_stack = torch.stack(seen_fingerprints)
                        sims = (seen_stack @ fingerprint).cpu().numpy()
                        max_sim = float(sims.max())
                        
                        if max_sim > similarity_threshold:
                            logger.info(f"Clip visually identical to prior clip (sim: {max_sim:.3f}). Dropping.")
                            db.delete(clip)
                            db.commit()
                            processed_clips += 1
                            continue
                            
                    if fingerprint is not None:
                        seen_fingerprints.append(fingerprint)
                        
                    clip.tags = tags
                    db.commit()
                else:
                    clip.tags = [{"tag": "unanalyzed", "score": 0.0}]
                    db.commit()

                processed_clips += 1
                
                if progress_callback:
                    pct = 25.0 + (14.0 * processed_clips / total_clips)
                    progress_callback({
                        "stage": "analyzing",
                        "sub_stage": "clip_tagging",
                        "current_clip": processed_clips,
                        "total_clips": total_clips,
                        "message": f"Tagging clip {processed_clips}/{total_clips}...",
                        "progress_pct": round(pct, 1),
                        "file_progress_pct": (processed_clips / total_clips) * 100,
                        "file_name": f"Clip {processed_clips}/{total_clips}"
                    })

            cap.release()

        # Free GPU memory after batch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info(f"Completed CLIP tagging for job {job_id}")

    finally:
        _unload_clip_model()
        db.close()
