"""JSON metadata sidecar writer for clips and highlight reels."""

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _safe_name(value: str, default: str) -> str:
    """Return a filesystem-safe filename stem."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (value or ""))
    cleaned = cleaned.strip("_")
    return cleaned or default


def write_clip_sidecar(clip, video, output_dir: str) -> str:
    """Write a JSON metadata sidecar for a single clip.

    Returns the path to the written file.
    """
    sidecar = {
        "clip_id": clip.id,
        "video_filename": video.filename if video else None,
        "video_filepath": video.filepath if video else None,
        "start_sec": clip.start_sec,
        "end_sec": clip.end_sec,
        "duration_sec": clip.duration_sec,
        "analysis": {
            "tags": clip.tags or [],
            "objects_detected": clip.objects_detected or [],
            "transcript": clip.transcript,
            "has_speech": clip.has_speech,
            "motion_score": clip.motion_score,
            "audio_energy": clip.audio_energy,
        },
        "scoring": {
            "overall_score": clip.overall_score,
            "user_score_override": clip.user_score_override,
            "effective_score": clip.effective_score,
            "is_favorite": clip.is_favorite,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(output_dir, exist_ok=True)
    filename = f"clip_{clip.id[:8]}_metadata.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, default=str)

    return filepath


def write_metadata_bundle(highlight_reel, clips: list, output_dir: str) -> str:
    """Write a JSON metadata bundle for a highlight reel.

    Includes reel info plus metadata for all included clips.
    Returns the path to the written file.
    """
    bundle = {
        "highlight_reel": {
            "id": highlight_reel.id,
            "name": highlight_reel.name,
            "target_duration_sec": highlight_reel.target_duration_sec,
            "actual_duration_sec": highlight_reel.actual_duration_sec,
            "transition_type": highlight_reel.transition_type,
            "transition_duration_sec": highlight_reel.transition_duration_sec,
            "clip_count": len(clips),
            "created_at": highlight_reel.created_at.isoformat() if highlight_reel.created_at else None,
        },
        "clips": [],
    }

    for clip in clips:
        clip_data = {
            "clip_id": clip.id,
            "start_sec": clip.start_sec,
            "end_sec": clip.end_sec,
            "duration_sec": clip.duration_sec,
            "tags": clip.tags or [],
            "overall_score": clip.overall_score,
            "effective_score": clip.effective_score,
            "is_favorite": clip.is_favorite,
            "transcript": clip.transcript,
        }
        bundle["clips"].append(clip_data)

    bundle["generated_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(output_dir, exist_ok=True)
    filename = f"{_safe_name(highlight_reel.name, 'highlight_reel')}_metadata.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, default=str)

    return filepath
