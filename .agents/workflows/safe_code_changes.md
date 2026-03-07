---
description: How to safely apply Python code changes to the Video Pipeline
---
# Safe Code Changes

When developing or modifying the `video-pipeline` project, specifically the Python files in the `app/` directory, Uvicorn will attempt to hot-reload the `web` container. 

However, because the application uses long-running WebSockets and synchronous background thread offloading (`anyio.to_thread.run_sync`), a hot-reload during active communication can cause the FastAPI asyncio event loop to crash or deadlock, rendering the container unresponsive.

**MANDATORY STANDARD PROCESS FOR APPLYING PYTHON CODE CHANGES:**
1. Stop the affected containers before making edits using the `run_command` tool:
   ```bash
   // turbo
   docker compose stop web worker
   ```
2. Execute your `replace_file_content` or `multi_replace_file_content` tool calls to apply the required code edits safely.
3. Bring the containers back online using the `run_command` tool:
   ```bash
   // turbo
   docker compose start web worker
   ```

*Note: You do not need to do this for HTML/CSS/JS frontend changes, only for Python backend code.*
