"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Pipeline configuration loaded from environment variables and .env file."""

    # Database
    database_url: str = "sqlite:///data/db/pipeline.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Paths
    upload_dir: str = "/app/data/uploads"
    output_dir: str = "/app/data/outputs"
    model_cache_dir: str = "/app/data/models"

    # Scene Detection — TransNetV2 (GPU)
    scene_detect_threshold: float = 0.5  # probability threshold (0-1) for shot boundary
    scene_detect_method: str = "transnetv2"  # "transnetv2" (GPU) — fallback: uniform segments
    min_scene_duration_sec: float = 1.0

    # CLIP — Default to "auto" to scale based on VRAM
    clip_model: str = "auto"
    clip_pretrained: str = "auto"
    clip_similarity_threshold: float = 0.97  # Threshold for visual deduplication
    clip_sample_frames: int = 16
    clip_confidence_threshold: float = 0.12
    clip_top_k_tags: int = 8

    # YOLOv8 — Default to "auto" to scale based on VRAM
    yolo_model: str = "auto"
    yolo_confidence_threshold: float = 0.35
    yolo_sample_frames: int = 12
    yolo_imgsz: int = 1280  # Full HD inference — catches small/distant objects

    # Whisper — Default to "auto" to scale based on VRAM
    whisper_model: str = "auto"
    whisper_language: Optional[str] = None  # Auto-detect

    # Motion Analysis — more sample pairs = smoother motion profile
    motion_sample_pairs: int = 20

    # Scoring Weights
    weight_activity_relevance: float = 0.30
    weight_motion_intensity: float = 0.20
    weight_people_presence: float = 0.15
    weight_audio_interest: float = 0.10
    weight_visual_quality: float = 0.10
    weight_duration_penalty: float = 0.05
    weight_uniqueness: float = 0.10

    # Highlight Defaults
    default_target_duration_sec: float = 120.0
    default_transition_type: str = "cut"
    default_transition_duration_sec: float = 0.5

    # Enhancement
    gyroflow_enabled: bool = False
    rife_enabled: bool = False
    rife_interpolation_factor: int = 2
    realesrgan_enabled: bool = False
    realesrgan_scale: int = 2
    demucs_enabled: bool = False
    demucs_model: str = "htdemucs"

    # Default tag vocabulary for CLIP zero-shot classification
    default_tag_vocabulary: list[str] = [
        "snowboarding", "skiing", "surfing", "biking", "mountain biking",
        "skateboarding", "hiking", "running", "swimming", "jumping",
        "trick", "crash", "wipeout", "scenic landscape", "sunset",
        "sunrise", "beach", "ocean", "mountain", "forest", "city",
        "family", "group of people", "child playing", "dog",
        "celebration", "campfire", "food", "driving", "boat", "underwater",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
