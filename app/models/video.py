"""Video ORM model — represents a source video file within a job."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, BigInteger, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.models.database import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(512), nullable=False)
    filepath = Column(String(1024), nullable=False)
    duration_sec = Column(Float, nullable=True)
    resolution = Column(String(32), nullable=True)  # e.g. "5312x2988"
    fps = Column(Float, nullable=True)
    codec = Column(String(32), nullable=True)  # e.g. "hevc"
    file_size_bytes = Column(BigInteger, nullable=True)
    gopro_metadata = Column(JSON, nullable=True)  # Parsed GoPro telemetry
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    job = relationship("Job", back_populates="videos")
    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Video {self.id[:8]} '{self.filename}'>"
