"""Highlight assembly module — auto-select and arrange clips for a highlight reel."""

import logging
from sqlalchemy.orm import Session

from app.models.clip import Clip

logger = logging.getLogger(__name__)


def auto_assemble_highlight(
    db: Session,
    job_id: str,
    target_duration_sec: float = 120.0,
    min_score: float = 0.0,
    activity_focus: list[str] = None,
) -> tuple[list[str], float]:
    """Auto-select clips for a highlight reel based on scoring.

    Algorithm:
    1. Filter clips by minimum score threshold
    2. Sort by effective score descending
    3. Greedily select clips until target duration is met
    4. Respect variety: avoid back-to-back clips from same scene
    5. Force-include favorited clips
    6. Reorder final selection chronologically for narrative flow

    Returns: (ordered_clip_ids, actual_duration_sec)
    """
    # Get all clips for this job
    query = db.query(Clip).filter(Clip.job_id == job_id)

    if min_score > 0:
        query = query.filter(Clip.overall_score >= min_score)

    all_clips = query.all()

    if not all_clips:
        return [], 0.0

    # Separate favorites (always included) from regular clips
    favorites = [c for c in all_clips if c.is_favorite]
    regular = [c for c in all_clips if not c.is_favorite]

    # Sort regular clips by effective score descending
    regular.sort(key=lambda c: c.effective_score, reverse=True)

    # Start with favorites
    selected = list(favorites)
    selected_ids = {c.id for c in selected}
    selected_video_ids = set()  # Track to avoid too many clips from same video
    current_duration = sum(c.duration_sec for c in selected)

    # Track last selected video to avoid back-to-back from same source
    last_video_id = selected[-1].video_id if selected else None

    # Greedily add clips
    for clip in regular:
        if clip.id in selected_ids:
            continue

        if current_duration >= target_duration_sec:
            break

        # Variety check: skip if same video as last selected (unless no alternatives)
        if clip.video_id == last_video_id and len(regular) > len(selected):
            # Try to find a clip from a different video first
            continue

        # Check we haven't taken too many from one video
        video_count = sum(1 for c in selected if c.video_id == clip.video_id)
        if video_count > len(selected) * 0.5 and len(selected) > 4:
            # More than half from one video — skip unless high score
            if clip.effective_score < 70:
                continue

        selected.append(clip)
        selected_ids.add(clip.id)
        current_duration += clip.duration_sec
        last_video_id = clip.video_id

    # If we skipped clips due to variety rules but still under target, do another pass
    if current_duration < target_duration_sec:
        for clip in regular:
            if clip.id in selected_ids:
                continue
            if current_duration >= target_duration_sec:
                break
            selected.append(clip)
            selected_ids.add(clip.id)
            current_duration += clip.duration_sec

    # Reorder chronologically for narrative flow
    selected.sort(key=lambda c: (c.video_id, c.start_sec))

    clip_ids = [c.id for c in selected]
    actual_duration = round(sum(c.duration_sec for c in selected), 3)

    logger.info(f"Assembled highlight: {len(clip_ids)} clips, {actual_duration:.1f}s "
                f"(target: {target_duration_sec:.1f}s)")

    return clip_ids, actual_duration
