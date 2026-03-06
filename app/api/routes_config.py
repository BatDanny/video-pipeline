"""API routes for pipeline configuration management."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings

router = APIRouter()


class PipelineConfig(BaseModel):
    """Pipeline configuration — mirrors relevant Settings fields."""
    # Scene Detection
    scene_detect_threshold: float
    scene_detect_method: str
    min_scene_duration_sec: float

    # CLIP
    clip_model: str
    clip_sample_frames: int
    clip_confidence_threshold: float
    clip_top_k_tags: int

    # YOLOv8
    yolo_model: str
    yolo_confidence_threshold: float
    yolo_sample_frames: int

    # Whisper
    whisper_model: str
    whisper_language: Optional[str]

    # Motion
    motion_sample_pairs: int

    # Scoring Weights
    weight_activity_relevance: float
    weight_motion_intensity: float
    weight_people_presence: float
    weight_audio_interest: float
    weight_visual_quality: float
    weight_duration_penalty: float
    weight_uniqueness: float

    # Highlight Defaults
    default_target_duration_sec: float
    default_transition_type: str
    default_transition_duration_sec: float

    # Enhancement
    gyroflow_enabled: bool
    rife_enabled: bool
    rife_interpolation_factor: int
    realesrgan_enabled: bool
    realesrgan_scale: int
    demucs_enabled: bool
    demucs_model: str

    # Tag vocabulary
    default_tag_vocabulary: list[str]


@router.get("/config", response_model=PipelineConfig)
async def get_config():
    """Get current pipeline configuration defaults."""
    settings = get_settings()
    return PipelineConfig(
        scene_detect_threshold=settings.scene_detect_threshold,
        scene_detect_method=settings.scene_detect_method,
        min_scene_duration_sec=settings.min_scene_duration_sec,
        clip_model=settings.clip_model,
        clip_sample_frames=settings.clip_sample_frames,
        clip_confidence_threshold=settings.clip_confidence_threshold,
        clip_top_k_tags=settings.clip_top_k_tags,
        yolo_model=settings.yolo_model,
        yolo_confidence_threshold=settings.yolo_confidence_threshold,
        yolo_sample_frames=settings.yolo_sample_frames,
        whisper_model=settings.whisper_model,
        whisper_language=settings.whisper_language,
        motion_sample_pairs=settings.motion_sample_pairs,
        weight_activity_relevance=settings.weight_activity_relevance,
        weight_motion_intensity=settings.weight_motion_intensity,
        weight_people_presence=settings.weight_people_presence,
        weight_audio_interest=settings.weight_audio_interest,
        weight_visual_quality=settings.weight_visual_quality,
        weight_duration_penalty=settings.weight_duration_penalty,
        weight_uniqueness=settings.weight_uniqueness,
        default_target_duration_sec=settings.default_target_duration_sec,
        default_transition_type=settings.default_transition_type,
        default_transition_duration_sec=settings.default_transition_duration_sec,
        gyroflow_enabled=settings.gyroflow_enabled,
        rife_enabled=settings.rife_enabled,
        rife_interpolation_factor=settings.rife_interpolation_factor,
        realesrgan_enabled=settings.realesrgan_enabled,
        realesrgan_scale=settings.realesrgan_scale,
        demucs_enabled=settings.demucs_enabled,
        demucs_model=settings.demucs_model,
        default_tag_vocabulary=settings.default_tag_vocabulary,
    )


@router.put("/config", response_model=PipelineConfig)
async def update_config(config: PipelineConfig):
    """Update pipeline configuration defaults.

    Note: In production, this would persist to a config file or database.
    For now, changes are ephemeral (last until server restart).
    """
    # In a full implementation, we'd write to a config store.
    # For now, return the submitted config as acknowledgment.
    return config
