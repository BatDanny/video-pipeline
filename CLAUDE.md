# CLAUDE.md — Video Pipeline Agent Instructions

## Stack Verification — REQUIRED After Every Edit

After **every** file change, verify the stack is up and healthy before responding to the user:

```bash
docker compose ps --format "table {{.Name}}\t{{.Status}}"
```

All three services (`web`, `worker`, `redis`) must show `Up` or `healthy`.
If any container is not running, investigate logs and fix before proceeding:

```bash
docker compose logs --tail=30 web
docker compose logs --tail=30 worker
```

The web container uses `--reload`, so Python changes to `app/` are applied automatically.
The worker does NOT hot-reload — restart it after changes to pipeline/worker code:

```bash
docker compose restart worker
```

**Never report a fix as complete until `docker compose ps` confirms all containers are healthy.**

---

## Project Overview

AI-powered GoPro highlight reel generator.
Stack: FastAPI + Celery + Redis + SQLAlchemy (SQLite) + Jinja2 templates.
GPU pipeline: CLIP, YOLOv8, Whisper, TransNetV2. Exports FCPXML for FCP / DaVinci Resolve.

## Container Layout

| Container | Role | Hot-reload? |
|-----------|------|-------------|
| `web` | FastAPI/uvicorn on :8000 | Yes (`--reload`) |
| `worker` | Celery GPU worker, concurrency=2 | No (restart required) |
| `redis` | Message broker + result backend | N/A |

## Key Paths

- App root: `/home/dannydebian/dev/video-pipeline/app/`
- API routes: `app/api/routes_*.py`
- Pipeline: `app/pipeline/orchestrator.py`, `ingest.py`, `scene_detect.py`, `scoring.py`
- Analysis: `app/pipeline/analysis/{clip_tagger,object_detect,transcribe,motion}.py`
- Enhancement: `app/pipeline/enhancement/` — **ALL STUBS** (Phase 12 TODO)
- Export: `app/export/fcpxml.py`
- Templates: `app/templates/`
- Shared JS globals: `app/static/js/app.js` — `escapeHtml()`, `formatDuration()`, `showToast()`

## Safe Code Change Workflow

1. Edit file(s)
2. `docker compose ps` — verify stack still up
3. If worker code changed: `docker compose restart worker`
4. Check logs for import errors: `docker compose logs --tail=20 web`
5. Confirm fix works end-to-end before marking task done

## Migrations

Run inside the web container (has alembic + correct env):

```bash
docker compose exec web alembic upgrade head
```

## Common Gotchas

- `app/config.py` uses `extra="ignore"` — unknown env vars are silently dropped, not errors
- Worker requires explicit restart after any Python change (no `--reload`)
- Redis requires password auth: `redis://:${REDIS_PASSWORD}@redis:6379/0`
- FCPXML format resource IDs must be simple `r{n}` — FCP rejects resolution-encoded IDs
- `_seconds_to_rational(1/fps, fps)` for 119.88fps correctly yields `1001/120000s`
