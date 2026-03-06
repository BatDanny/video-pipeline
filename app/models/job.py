"""Job ORM model — represents a video processing pipeline job."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Float, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
from app.models.database import Base


class JobStatus(str, enum.Enum):
    """Pipeline job status states."""
    PENDING = "pending"
    INGESTING = "ingesting"
    DETECTING_SCENES = "detecting_scenes"
    ANALYZING = "analyzing"
    SCORING = "scoring"
    ASSEMBLING = "assembling"
    ENHANCING = "enhancing"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    config = Column(JSON, default=dict)
    source_dir = Column(String(1024), nullable=True)
    output_dir = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    progress_pct = Column(Float, default=0.0)
    celery_task_id = Column(String(255), nullable=True)

    # Relationships
    videos = relationship("Video", back_populates="job", cascade="all, delete-orphan")
    clips = relationship("Clip", back_populates="job", cascade="all, delete-orphan")
    highlights = relationship("HighlightReel", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job {self.id[:8]} '{self.name}' [{self.status.value}]>"
