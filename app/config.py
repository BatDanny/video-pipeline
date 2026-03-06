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

    # Scene Detection
    scene_detect_threshold: float = 27.0
    scene_detect_method: str = "content"  # "content" or "adaptive"
    min_scene_duration_sec: float = 1.0

    # CLIP
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "openai"
    clip_sample_frames: int = 8
    clip_confidence_threshold: float = 0.15
    clip_top_k_tags: int = 5

    # YOLOv8
    yolo_model: str = "yolov8m.pt"
    yolo_confidence_threshold: float = 0.5
    yolo_sample_frames: int = 8

    # Whisper
    whisper_model: str = "medium"
    whisper_language: Optional[str] = None  # Auto-detect

    # Motion Analysis
    motion_sample_pairs: int = 10

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
