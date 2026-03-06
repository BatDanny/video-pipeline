"""HighlightReel ORM model — represents an assembled highlight reel for export."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.models.database import Base


class HighlightReel(Base):
    __tablename__ = "highlight_reels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    clip_ids = Column(JSON, default=list)  # Ordered list of clip UUIDs
    target_duration_sec = Column(Float, nullable=True)
    actual_duration_sec = Column(Float, nullable=True)
    transition_type = Column(String(32), default="cut")  # cut, crossfade, dip_to_black
    transition_duration_sec = Column(Float, default=0.5)
    fcpxml_path = Column(String(1024), nullable=True)
    metadata_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    job = relationship("Job", back_populates="highlights")

    def __repr__(self):
        return f"<HighlightReel {self.id[:8]} '{self.name}' clips={len(self.clip_ids or [])}>"
