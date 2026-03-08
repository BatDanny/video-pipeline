---
description: Verify the Video Pipeline stack health using a browser subagent
---

# Verify Video Pipeline Stack

This workflow checks if the Video Pipeline Docker stack is running and healthy without needing a full browser.

1.  Run `docker ps` to ensure the `web`, `worker`, and `redis` containers are Up and healthy.
2.  Run `curl -I http://localhost:8000` to verify the frontend web server is responding with a 200 OK status.
3.  Run `curl http://localhost:8000/api/gpu/status` to verify the backend API connects to the database and Redis successfully (it should return a JSON response).
