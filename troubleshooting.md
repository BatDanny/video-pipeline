# VideoPipe Troubleshooting Guide

This guide contains known issues, their root causes, and resolutions. It is structured to facilitate automated failure handling in the future.

## Issue: GPU Underutilization (nvidia-smi shows GPU off / unused)

**Symptom:**
- The system indicates it is ingesting data or processing a job (via the web UI or logs).
- Running `nvidia-smi` on the host or `docker exec video-pipeline-worker-1 nvidia-smi` shows `0%` GPU utilization.
- `nvidia-smi` might show the GPU as "Off" (under processes) or "No running processes found".
- The worker `docker logs video-pipeline-worker-1` shows errors like:
  ```text
  Received unregistered task of type 'app.pipeline.orchestrator.run_pipeline'.
  The message has been ignored and discarded.
  ```

**Root Cause:**
Celery workers only execute tasks they are aware of. By default, `celery_app.autodiscover_tasks()` looks for a file named `tasks.py` inside the specified packages. If the task decorators (e.g., `@celery_app.task`) are located in other files like `orchestrator.py` and are not explicitly imported into the Celery app context, the worker will boot up successfully but will be unaware of those tasks. When the web app queues a job, the worker receives the message but silently discards it because the task name is unregistered. Consequently, the GPU-accelerated code is never invoked.

**Resolution / Automation Steps:**
1. **Check Task Registration:** Use `docker logs --tail 100 video-pipeline-worker-1` and look for the `[tasks]` section during worker boot. Ensure `app.pipeline.orchestrator.run_pipeline` (and any other required tasks) is listed.
2. **Fix Imports:** Ensure the internal module containing the task (e.g., `app.pipeline.orchestrator`) is explicitly registered in the `celery_app.py` configuration using `celery_app.conf.imports = ["app.pipeline.orchestrator"]`.
3. **Restart Worker:** Apply the fix by restarting the worker container: `docker compose restart worker`.
4. **Verify:** Check the worker logs again to ensure the tasks are now listed under `[tasks]` and monitor `nvidia-smi` for GPU activity once a new job starts.

## Issue: GPU Processes Missing in `nvidia-smi` (But Hardware is Active)

**Symptom:**
- The pipeline works perfectly and processes jobs fast.
- Running `nvidia-smi` shows the GPU is drawing high power (e.g., `170W / 370W`), temperatures are elevating, and `GPU-Util` jumps up (e.g., `22%`).
- However, the bottom section of `nvidia-smi` under "Processes:" shows `No running processes found` and Memory-Usage is consistently low (e.g., `2MiB / 24576MiB`).

**Root Cause:**
This is a known limitation caused by virtualization and Docker PID namespaces. The VM hypervisor and the NVIDIA Linux driver allocate the GPU physically via passthrough, but their driver memory maps (NVML) are not fully bridging the process IDs between the Docker container and the host kernel.
1. Docker's PID isolation hides the container's processes from the NVIDIA driver's local accounting on the host VM.
2. Setting `pid: "host"` in `docker-compose.yml` does not bridge the NVML subsystem through the VM hypervisor fully; thus `nvidia-smi` remains "blind" to the process IDs.

**Resolution / Automation Steps:**
This is **not a functional error** and does not impact pipeline performance. The GPU is successfully processing the data.
1. **Verify GPU Execution:** Do not rely on the `Processes` section. Instead, observe the **Power Usage** and **GPU-Util**. If power spikes from `~19W` up to `>150W` and the `GPU-Util` metric shows activity during pipeline jobs, the GPU computing is 100% active.
2. **Container Level Verification:** You can verify the container can access the CUDA runtime by running:
   ```bash
   docker exec video-pipeline-worker-1 python3 -c "import torch; print(torch.cuda.is_available())"
   ```
   If this returns `True`, the worker has full GPU access.
