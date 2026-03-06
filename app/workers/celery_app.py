"""Celery application configuration and task registration."""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "video_pipeline",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Task behavior
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # One task at a time for GPU work

    # Result expiry
    result_expires=86400,  # 24 hours

    # Task routes — keep GPU tasks on GPU workers
    task_routes={
        "app.pipeline.*": {"queue": "pipeline"},
    },

    # Timezone
    timezone="UTC",
    enable_utc=True,
)

# Auto-discover tasks in pipeline modules
celery_app.autodiscover_tasks([
    "app.pipeline",
    "app.pipeline.analysis",
    "app.pipeline.enhancement",
])
