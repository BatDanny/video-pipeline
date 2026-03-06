"""Pydantic schemas for Clip API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ClipTagSchema(BaseModel):
    """A single CLIP-generated tag with confidence score."""
    tag: str
    score: float


class ObjectDetectionSchema(BaseModel):
    """An aggregated object detection result."""
    class_name: str = Field(alias="class")
    count: int
    avg_confidence: float

    model_config = {"populate_by_name": True}


class ClipResponse(BaseModel):
    """Response schema for a single clip."""
    id: str
    video_id: str
    job_id: str
    start_sec: float
    end_sec: float
    duration_sec: float
    thumbnail_path: Optional[str]
    preview_path: Optional[str]
    tags: Optional[list[dict]]
    objects_detected: Optional[list[dict]]
    transcript: Optional[str]
    has_speech: bool
    motion_score: Optional[float]
    audio_energy: Optional[float]
    overall_score: float
    effective_score: float
    user_score_override: Optional[float]
    is_favorite: bool
    video_filename: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClipListResponse(BaseModel):
    """Response schema for clip listing."""
    clips: list[ClipResponse]
    total: int


class ClipUpdate(BaseModel):
    """Request body for updating a clip."""
    user_score_override: Optional[float] = None
    is_favorite: Optional[bool] = None
