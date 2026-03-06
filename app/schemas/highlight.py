"""Pydantic schemas for Highlight Reel API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class HighlightCreate(BaseModel):
    """Request body for creating a highlight reel."""
    name: str = Field(default="Highlight Reel")
    target_duration_sec: float = Field(default=120.0, ge=5.0)
    min_score: float = Field(default=0.0, ge=0.0, le=100.0)
    activity_focus: list[str] = Field(default_factory=list)
    transition_type: str = Field(default="cut")
    transition_duration_sec: float = Field(default=0.5, ge=0.0, le=5.0)
    auto_assemble: bool = Field(default=True, description="Auto-select clips by score")


class HighlightUpdate(BaseModel):
    """Request body for updating a highlight reel."""
    name: Optional[str] = None
    clip_ids: Optional[list[str]] = None  # Reorder or change clips
    transition_type: Optional[str] = None
    transition_duration_sec: Optional[float] = None


class HighlightResponse(BaseModel):
    """Response schema for a single highlight reel."""
    id: str
    job_id: str
    name: str
    clip_ids: list[str]
    target_duration_sec: Optional[float]
    actual_duration_sec: Optional[float]
    transition_type: str
    transition_duration_sec: float
    fcpxml_path: Optional[str]
    metadata_path: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class HighlightListResponse(BaseModel):
    """Response schema for highlight listing."""
    highlights: list[HighlightResponse]
    total: int
