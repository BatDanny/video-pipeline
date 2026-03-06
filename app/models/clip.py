"""Clip ORM model — represents a detected scene segment with AI analysis results."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.models.database import Base


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    # Scene boundaries
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    duration_sec = Column(Float, nullable=False)

    # Generated assets
    thumbnail_path = Column(String(1024), nullable=True)
    preview_path = Column(String(1024), nullable=True)

    # AI Analysis results
    tags = Column(JSON, nullable=True)  # CLIP tags: [{"tag": "snowboarding", "score": 0.92}]
    objects_detected = Column(JSON, nullable=True)  # YOLOv8: [{"class": "person", "count": 3, ...}]
    transcript = Column(Text, nullable=True)  # Whisper transcription
    has_speech = Column(Boolean, default=False)
    motion_score = Column(Float, nullable=True)  # 0.0–1.0
    audio_energy = Column(Float, nullable=True)  # RMS audio energy

    # Scoring
    overall_score = Column(Float, default=0.0)  # Weighted composite: 0.0–100.0
    user_score_override = Column(Float, nullable=True)  # Manual override
    is_favorite = Column(Boolean, default=False)

    # Metadata export
    metadata_sidecar_path = Column(String(1024), nullable=True)

    # Error tracking
    analysis_errors = Column(JSON, nullable=True)  # Per-module error messages

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    video = relationship("Video", back_populates="clips")
    job = relationship("Job", back_populates="clips")

    @property
    def effective_score(self) -> float:
        """Return user override if set, otherwise computed score."""
        if self.user_score_override is not None:
            return self.user_score_override
        return self.overall_score or 0.0

    def __repr__(self):
        return f"<Clip {self.id[:8]} {self.start_sec:.1f}s-{self.end_sec:.1f}s score={self.effective_score:.1f}>"
