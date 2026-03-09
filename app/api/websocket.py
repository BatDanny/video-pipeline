"""WebSocket endpoint for real-time job progress updates."""

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.security import require_websocket_token
from app.config import get_settings

router = APIRouter()


def _fetch_job_status_sync(job_id: str):
    from app.models.database import get_session_factory
    from app.models.job import Job, JobStatus
    
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"error": "Job not found"}

        status_data = {
            "job_id": job.id,
            "status": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
            "progress_pct": job.progress_pct or 0.0,
            "stage": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
            "message": f"Status: {job.status.value}" if isinstance(job.status, JobStatus) else "",
            "telemetry": job.telemetry or {},
        }

        if job.celery_task_id:
            try:
                from app.workers.celery_app import celery_app
                result = celery_app.AsyncResult(job.celery_task_id)
                if result.info and isinstance(result.info, dict):
                    status_data.update(result.info)
            except Exception:
                pass

        terminal_states = [
            JobStatus.COMPLETE, JobStatus.COMPLETE_WITH_ERRORS,
            JobStatus.FAILED, JobStatus.CANCELLED,
        ]
        is_terminal = job.status in terminal_states

        return {"status_data": status_data, "is_terminal": is_terminal}

    finally:
        db.close()

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
    await require_websocket_token(websocket)
    if websocket.client_state.name != "CONNECTING":
        return
    await websocket.accept()
    import anyio

    try:
        while not websocket.app.state.shutdown_event.is_set():
            # Poll job status from database in a background thread to prevent blocking
            try:
                result = await anyio.to_thread.run_sync(_fetch_job_status_sync, job_id)
                
                if "error" in result:
                    await websocket.send_json(result)
                    break
                    
                status_data = result["status_data"]
                is_terminal = result["is_terminal"]

                await websocket.send_json(status_data)

                if is_terminal:
                    await asyncio.sleep(1)  # Final update delay
                    await websocket.send_json({**status_data, "finished": True})
                    break

            except Exception as e:
                await websocket.send_json({"error": str(e)})

            # Poll delay, interruptible by shutdown
            try:
                await asyncio.wait_for(
                    websocket.app.state.shutdown_event.wait(), 
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                pass  # Timeout means we should poll again

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.websocket("/ws/logs/worker")
async def worker_logs_ws(websocket: WebSocket):
    """Real-time streaming of Celery worker container logs via docker."""
    await require_websocket_token(websocket)
    if websocket.client_state.name != "CONNECTING":
        return
    await websocket.accept()
    process = None
    try:
        settings = get_settings()
        log_path = settings.worker_log_path

        if not log_path.startswith("/app/data/logs/"):
            await websocket.send_text("[Log Stream Error] Worker log path is outside allowed log directory")
            return

        # Start tail process on the shared log file
        process = await asyncio.create_subprocess_exec(
            "tail", "-n", "100", "-f", log_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Read lines asynchronously and send to websocket
        while not websocket.app.state.shutdown_event.is_set():
            # Wait for either a new log line or a shutdown signal
            read_task = asyncio.create_task(process.stdout.readline())
            shutdown_task = asyncio.create_task(websocket.app.state.shutdown_event.wait())
            
            done, pending = await asyncio.wait(
                [read_task, shutdown_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if shutdown_task in done:
                for task in pending:
                    task.cancel()
                break
                
            # Must have been read_task
            line = read_task.result()

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
