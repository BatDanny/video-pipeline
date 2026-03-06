"""Scoring module — weighted composite scoring algorithm."""

import logging

from app.models.database import get_session_factory
from app.models.job import Job
from app.models.clip import Clip
from app.config import get_settings

logger = logging.getLogger(__name__)


def _compute_activity_relevance(tags: list[dict], activity_focus: list[str]) -> float:
    """Score how well clip tags match the user's activity focus.

    Returns 0.0–1.0.
    """
    if not tags or not activity_focus:
        # If no activity focus specified, give moderate base score
        if tags:
            # Use the highest tag confidence as a proxy
            return max(t.get("score", 0.0) for t in tags)
        return 0.3

    focus_set = {a.lower() for a in activity_focus}
    max_relevance = 0.0

    for tag_entry in tags:
        tag = tag_entry.get("tag", "").lower()
        score = tag_entry.get("score", 0.0)
        if tag in focus_set:
            max_relevance = max(max_relevance, score)
        # Partial matching: check if focus keyword is contained in tag
        for focus in focus_set:
            if focus in tag or tag in focus:
                max_relevance = max(max_relevance, score * 0.8)

    return min(max_relevance, 1.0)


def _compute_duration_penalty(duration_sec: float) -> float:
    """Penalize very short (<1s) or very long (>60s) clips.

    Returns 0.0–1.0 (1.0 = no penalty, 0.0 = heavy penalty).
    """
    if duration_sec < 0.5:
        return 0.1
    elif duration_sec < 1.0:
        return 0.5
    elif duration_sec < 2.0:
        return 0.8
    elif duration_sec <= 30.0:
        return 1.0  # Sweet spot
    elif duration_sec <= 60.0:
        return 0.9
    elif duration_sec <= 120.0:
        return 0.7
    else:
        return 0.5


def _compute_visual_quality_estimate(tags: list[dict]) -> float:
    """Rough visual quality estimate based on content tags.

    Returns 0.0–1.0.
    """
    # Quality-positive tags
    quality_tags = {"scenic landscape", "sunset", "sunrise", "beach", "ocean", "mountain"}
    # Quality-negative tags (often lower quality footage)
    action_tags = {"crash", "wipeout"}

    if not tags:
        return 0.5  # Unknown

    score = 0.5
    for tag_entry in tags:
        tag = tag_entry.get("tag", "").lower()
        confidence = tag_entry.get("score", 0.0)
        if tag in quality_tags:
            score = max(score, 0.5 + confidence * 0.5)
        if tag in action_tags:
            score = min(score, 0.7)  # Action clips can still be interesting

    return min(score, 1.0)


def score_clips(job_id: str):
    """Compute weighted composite scores for all clips in a job.

    Uses available analysis data. Missing signals get neutral (0.5) values.
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        config = job.config or {}
        activity_focus = config.get("activity_focus", [])

        # Get weights from settings (could also be in job config)
        weights = {
            "activity_relevance": settings.weight_activity_relevance,
            "motion_intensity": settings.weight_motion_intensity,
            "people_presence": settings.weight_people_presence,
            "audio_interest": settings.weight_audio_interest,
            "visual_quality": settings.weight_visual_quality,
            "duration_penalty": settings.weight_duration_penalty,
            "uniqueness": settings.weight_uniqueness,
        }

        clips = db.query(Clip).filter(Clip.job_id == job_id).all()
        logger.info(f"Scoring {len(clips)} clips for job {job_id}")

        for clip in clips:
            tags = clip.tags or []

            # Compute each signal
            activity_score = _compute_activity_relevance(tags, activity_focus)
            motion_score = clip.motion_score if clip.motion_score is not None else 0.5
            people_score = _compute_people_score(clip.objects_detected)
            audio_score = _compute_audio_score(clip.has_speech, clip.audio_energy)
            quality_score = _compute_visual_quality_estimate(tags)
            duration_score = _compute_duration_penalty(clip.duration_sec)
            uniqueness_score = 0.7  # Placeholder — full implementation uses CLIP embeddings

            # Weighted sum
            composite = (
                weights["activity_relevance"] * activity_score +
                weights["motion_intensity"] * motion_score +
                weights["people_presence"] * people_score +
                weights["audio_interest"] * audio_score +
                weights["visual_quality"] * quality_score +
                weights["duration_penalty"] * duration_score +
                weights["uniqueness"] * uniqueness_score
            )

            # Normalize to 0–100
            clip.overall_score = round(min(composite * 100, 100.0), 2)

        db.commit()
        logger.info(f"Scoring complete for job {job_id}")

    finally:
        db.close()


def _compute_people_score(objects_detected: list) -> float:
    """Score based on person detection. Returns 0.0–1.0."""
    if not objects_detected:
        return 0.5  # Unknown

    for obj in objects_detected:
        if obj.get("class") == "person":
            count = obj.get("count", 0)
            confidence = obj.get("avg_confidence", 0.0)
            if count >= 3:
                return min(0.9, 0.5 + confidence * 0.4)  # Group shot
            elif count >= 1:
                return min(0.8, 0.4 + confidence * 0.4)
    return 0.3  # No people


def _compute_audio_score(has_speech: bool, audio_energy: float = None) -> float:
    """Score based on audio interest. Returns 0.0–1.0."""
    score = 0.3
    if has_speech:
        score = 0.7
    if audio_energy is not None:
        # Higher energy = more interesting audio
        score = max(score, min(audio_energy, 1.0))
    return score
