"""WebSocket endpoint for real-time job progress updates."""

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/progress/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    """Real-time progress updates for a pipeline job.

    Sends JSON messages with structure:
    {
        "stage": "analyzing",
        "sub_stage": "clip_tagging",
        "progress_pct": 45.2,
        "current_clip": 23,
        "total_clips": 50,
        "current_file": "GX010042.MP4",
        "eta_sec": 120,
        "message": "Tagging clip 23/50..."
    }
    """
    await websocket.accept()

    try:
        while True:
            # Poll job status from database
            try:
                from app.models.database import get_session_factory
                from app.models.job import Job, JobStatus

                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    job = db.query(Job).filter(Job.id == job_id).first()
                    if not job:
                        await websocket.send_json({"error": "Job not found"})
                        break

                    status_data = {
                        "job_id": job.id,
                        "status": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
                        "progress_pct": job.progress_pct or 0.0,
                        "stage": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
                        "message": f"Status: {job.status.value}" if isinstance(job.status, JobStatus) else "",
                    }

                    # Try to get detailed progress from Celery task state
                    if job.celery_task_id:
                        try:
                            from app.workers.celery_app import celery_app
                            result = celery_app.AsyncResult(job.celery_task_id)
                            if result.info and isinstance(result.info, dict):
                                status_data.update(result.info)
                        except Exception:
                            pass

                    await websocket.send_json(status_data)

                    # Stop polling if job is in a terminal state
                    terminal_states = [
                        JobStatus.COMPLETE, JobStatus.COMPLETE_WITH_ERRORS,
                        JobStatus.FAILED, JobStatus.CANCELLED,
                    ]
                    if job.status in terminal_states:
                        await asyncio.sleep(1)  # Final update delay
                        await websocket.send_json({**status_data, "finished": True})
                        break

                finally:
                    db.close()

            except Exception as e:
                await websocket.send_json({"error": str(e)})

            await asyncio.sleep(2)  # Poll every 2 seconds

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.websocket("/ws/logs/worker")
async def worker_logs_ws(websocket: WebSocket):
    """Real-time streaming of Celery worker container logs via docker."""
    await websocket.accept()
    process = None
    try:
        # Start tail process on the shared log file
        process = await asyncio.create_subprocess_exec(
            "tail", "-n", "100", "-f", "/app/data/logs/worker.log",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Read lines asynchronously and send to websocket
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            try:
                msg = line.decode("utf-8").rstrip("\r\n")
                if msg:
                    await websocket.send_text(msg)
            except Exception:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(f"[Log Stream Error] {str(e)}")
        except Exception:
            pass
    finally:
        if process and process.returncode is None:
            try:
                process.kill()
            except Exception:
                pass

