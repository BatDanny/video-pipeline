# Debug Journal
Welcome to the VideoPipe debugging journal. Log complex bugs, root causes, and resolutions here to preserve system knowledge.

## 2026-03-05: Docker Worker Healthcheck Issue
**Symptom:** Docker showed the `worker` container as `unhealthy`, even though the Celery worker process was running fine and connected to Redis.
**Root Cause:** The `worker` service inherited the base `Dockerfile` which included a `HEALTHCHECK` defined as `curl -f http://localhost:8000/`. Because the worker container didn't expose a web service on port 8000, `curl` was failing and Docker marked it as unhealthy.
**Resolution:** Modified `docker-compose.yml` to explicitly disable healthchecks in the `worker` service:
```yaml
healthcheck:
  disable: true
```
**Artifacts Created:** Added `debug/capture_stack.sh` script to capture full system states to `debug/dumps/` for easier troubleshooting in the future.
