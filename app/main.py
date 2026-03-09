"""FastAPI application factory — main entry point."""

import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings
from app.models.database import init_db
from app.api.routes_jobs import router as jobs_router
from app.api.routes_clips import router as clips_router
from app.api.routes_highlights import router as highlights_router
from app.api.routes_config import router as config_router
from app.api.routes_browse import router as browse_router
from app.api.routes_gpu import router as gpu_router
from app.api.websocket import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()

    import asyncio
    import logging
    
    logger = logging.getLogger("uvicorn")
    logger.info("Initializing FastAPI lifespan...")
    
    app.state.shutdown_event = asyncio.Event()

    # Ensure directories exist
    for d in [settings.upload_dir, settings.output_dir, settings.model_cache_dir]:
        os.makedirs(d, exist_ok=True)

    # Initialize database tables (dev mode — production uses Alembic)
    init_db()

    try:
        yield  # App is running
    finally:
        # Shutdown cleanup (if needed)
        logger.info("FastAPI lifespan shutdown triggered. Setting WebSocket shutdown event.")
        app.state.shutdown_event.set()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Video Pipeline — AI Highlight Reel Generator",
        description="AI-powered video analysis pipeline for GoPro footage",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    # Mount static files
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    application.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Include API routers
    application.include_router(jobs_router, prefix="/api", tags=["Jobs"])
    application.include_router(clips_router, prefix="/api", tags=["Clips"])
    application.include_router(highlights_router, prefix="/api", tags=["Highlights"])
    application.include_router(config_router, prefix="/api", tags=["Config"])
    application.include_router(browse_router, tags=["Browse"])
    application.include_router(gpu_router, prefix="/api", tags=["GPU"])
    application.include_router(ws_router, tags=["WebSocket"])

    # Template engine
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(templates_dir, exist_ok=True)
    templates = Jinja2Templates(directory=templates_dir)

    # --- HTML Page Routes ---

    @application.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @application.get("/upload", response_class=HTMLResponse)
    async def upload_page(request: Request):
        settings = get_settings()
        return templates.TemplateResponse("upload.html", {
            "request": request,
            "tag_vocabulary": settings.default_tag_vocabulary,
            "settings": settings,
        })

    @application.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail_page(request: Request, job_id: str):
        settings = get_settings()
        return templates.TemplateResponse("job_detail.html", {
            "request": request,
            "job_id": job_id,
            "tag_vocabulary": settings.default_tag_vocabulary,
            "settings": settings,
        })

    @application.get("/jobs/{job_id}/clips", response_class=HTMLResponse)
    async def clip_browser_page(request: Request, job_id: str):
        return templates.TemplateResponse("clip_browser.html", {
            "request": request,
            "job_id": job_id,
        })

    @application.get("/jobs/{job_id}/highlights/{highlight_id}", response_class=HTMLResponse)
    async def highlight_editor_page(request: Request, job_id: str, highlight_id: str):
        return templates.TemplateResponse("highlight_editor.html", {
            "request": request,
            "job_id": job_id,
            "highlight_id": highlight_id,
        })

    return application


app = create_app()
