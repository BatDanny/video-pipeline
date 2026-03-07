"""API route for system status — GPU, CPU, RAM, and active pipeline info."""

import subprocess
import os
import logging

from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_nvidia_smi() -> dict:
    """Run nvidia-smi and parse the output into structured data."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed,persistence_mode",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        line = result.stdout.strip()
        if not line:
            return None

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            return None

        return {
            "name": parts[0],
            "temperature_c": _safe_int(parts[1]),
            "utilization_pct": _safe_int(parts[2]),
            "memory_used_mib": _safe_int(parts[3]),
            "memory_total_mib": _safe_int(parts[4]),
            "power_draw_w": _safe_float(parts[5]),
            "power_limit_w": _safe_float(parts[6]),
            "fan_speed_pct": _safe_int(parts[7]),
            "persistence_mode": parts[8].strip().lower() in ("enabled", "on"),
        }
    except Exception:
        return None


def _get_cpu_ram() -> dict:
    """Get CPU and RAM usage from /proc (works in any Linux container)."""
    cpu_pct = 0.0
    ram_used_gb = 0.0
    ram_total_gb = 0.0
    ram_pct = 0.0
    cpu_count = os.cpu_count() or 1

    # RAM from /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        total_kb = meminfo.get("MemTotal", 0)
        available_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        ram_total_gb = round(total_kb / 1048576, 1)
        ram_used_gb = round((total_kb - available_kb) / 1048576, 1)
        ram_pct = round((ram_used_gb / max(ram_total_gb, 0.1)) * 100, 1)
    except Exception:
        pass

    # CPU from /proc/loadavg (1-minute load average)
    try:
        with open("/proc/loadavg") as f:
            load_1m = float(f.read().split()[0])
        cpu_pct = round(min(100.0, (load_1m / cpu_count) * 100), 1)
    except Exception:
        pass

    return {
        "cpu_pct": cpu_pct,
        "cpu_cores": cpu_count,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "ram_pct": ram_pct,
    }


def _get_pipeline_info() -> dict:
    """Get active pipeline stage and model info from a known Redis key."""
    default = {"active": False, "stage": "", "sub_stage": "", "message": "Idle",
               "progress_pct": 0, "active_model": "", "file_name": ""}
    try:
        import redis as redis_lib
        import json
        from app.config import get_settings
        settings = get_settings()
        r = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

        raw = r.get("videopipe:active_pipeline")
        if not raw:
            return default

        result = json.loads(raw)
        stage = result.get("stage", "")
        sub_stage = result.get("sub_stage", "")
        message = result.get("message", "")
        progress = result.get("progress_pct", 0)
        file_name = result.get("file_name", "")

        # Determine what model is active based on stage
        model_name = ""
        if sub_stage == "clip_tagging" or (stage == "analyzing" and "CLIP" in message):
            model_name = f"CLIP {settings.clip_model}"
        elif sub_stage == "object_detection" or "YOLO" in message:
            model_name = f"YOLO {settings.yolo_model}"
        elif sub_stage == "transcription" or "Whisper" in message:
            model_name = f"Whisper {settings.whisper_model}"
        elif stage == "detecting_scenes":
            model_name = "TransNetV2 (GPU)"
        elif stage == "ingesting":
            model_name = "ffprobe (CPU)"
        elif stage == "scoring":
            model_name = "Scoring (CPU)"
        elif sub_stage == "motion":
            model_name = "OpenCV Motion (CPU)"

        return {
            "active": stage not in ("", "complete", "failed"),
            "stage": stage,
            "sub_stage": sub_stage,
            "message": message,
            "progress_pct": progress,
            "active_model": model_name,
            "file_name": file_name,
        }

    except Exception as e:
        logger.debug(f"Could not fetch pipeline info: {e}")
        return default


def _safe_int(val: str) -> int:
    try:
        return int(val.strip())
    except (ValueError, AttributeError):
        return 0


def _safe_float(val: str) -> float:
    try:
        return round(float(val.strip()), 1)
    except (ValueError, AttributeError):
        return 0.0


@router.get("/gpu/status")
async def system_status():
    """Return real-time system metrics: GPU, CPU, RAM, and active pipeline info."""
    gpu_data = _parse_nvidia_smi()
    cpu_ram = _get_cpu_ram()
    pipeline = _get_pipeline_info()

    gpu_offline = {
        "available": False, "name": "No GPU detected",
        "temperature_c": 0, "utilization_pct": 0,
        "memory_used_mib": 0, "memory_total_mib": 0, "memory_pct": 0.0,
        "power_draw_w": 0.0, "power_limit_w": 0.0, "power_pct": 0.0,
        "fan_speed_pct": 0, "status": "offline",
    }

    if gpu_data is None:
        gpu = gpu_offline
    else:
        memory_pct = (gpu_data["memory_used_mib"] / max(gpu_data["memory_total_mib"], 1)) * 100
        power_pct = (gpu_data["power_draw_w"] / max(gpu_data["power_limit_w"], 1)) * 100

        if pipeline.get("active", False):
            status = "active"
        elif gpu_data["power_draw_w"] > 100:
            status = "heavy"
        elif gpu_data["power_draw_w"] > 40:
            status = "active"
        else:
            status = "idle"

        gpu = {
            "available": True,
            "name": gpu_data["name"],
            "temperature_c": gpu_data["temperature_c"],
            "utilization_pct": gpu_data["utilization_pct"],
            "memory_used_mib": gpu_data["memory_used_mib"],
            "memory_total_mib": gpu_data["memory_total_mib"],
            "memory_pct": round(memory_pct, 1),
            "power_draw_w": gpu_data["power_draw_w"],
            "power_limit_w": gpu_data["power_limit_w"],
            "power_pct": round(power_pct, 1),
            "fan_speed_pct": gpu_data["fan_speed_pct"],
            "status": status,
        }

    return {**gpu, **cpu_ram, "pipeline": pipeline}

