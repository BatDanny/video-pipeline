"""Pydantic schemas for Job API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class JobCreate(BaseModel):
    """Request body for creating a new job."""
    name: str = Field(..., min_length=1, max_length=255)
    source_path: Optional[str] = Field(None, description="Path to video files on server/NAS")
    activity_focus: list[str] = Field(default_factory=list, description="Activity tags to prioritize")
    config: dict = Field(default_factory=dict, description="Pipeline config overrides")


class JobUpdate(BaseModel):
    """Request body for updating a job."""
    name: Optional[str] = None
    config: Optional[dict] = None


class JobResponse(BaseModel):
    """Response schema for a single job."""
    id: str
    name: str
    status: str
    config: dict
    source_dir: Optional[str]
    output_dir: Optional[str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    progress_pct: float
    video_count: int = 0
    clip_count: int = 0
    top_score: Optional[float] = None
    telemetry: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """Response schema for job listing."""
    jobs: list[JobResponse]
    total: int


class JobStartRequest(BaseModel):
    """Optional overrides when starting a job."""
    config_overrides: dict = Field(default_factory=dict)
