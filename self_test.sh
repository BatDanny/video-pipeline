#!/bin/bash
# self_test.sh - Checks the health and responsiveness of the Video Pipeline.

echo "======================================"
echo " Starting Video Pipeline Self-Test..."
echo "======================================"

# 1. Check Docker container status
echo ""
echo "[1/3] Checking Docker Containers..."
WEB_STATUS=$(docker ps -a --filter "name=video-pipeline-web-1" --format '{{.Status}}')
WORKER_STATUS=$(docker ps -a --filter "name=video-pipeline-worker-1" --format '{{.Status}}')

if [[ -z "$WEB_STATUS" || -z "$WORKER_STATUS" ]]; then
    echo "❌ ERROR: Containers not found. Is docker-compose up running?"
    exit 1
fi

echo "  - web:    $WEB_STATUS"
echo "  - worker: $WORKER_STATUS"

if [[ ! "$WEB_STATUS" == *"Up"* ]]; then
    echo "❌ ERROR: Web container is not Up."
    exit 1
fi

if [[ ! "$WORKER_STATUS" == *"Up"* ]]; then
    echo "❌ ERROR: Worker container is not Up."
    exit 1
fi
echo "✅ Docker containers are globally running."


# 2. Check web container internal healthcheck
echo ""
echo "[2/3] Checking Web Container Health Check..."
HEALTH=$(docker inspect --format='{{json .State.Health.Status}}' video-pipeline-web-1 | tr -d '"' 2>/dev/null)

if [[ "$HEALTH" == "healthy" || "$HEALTH" == "" ]]; then
     # Note: If no healthcheck defined, it prints nothing, which we treat as passing docker check
     echo "✅ Web container healthcheck: OK (${HEALTH:-no strict healthcheck defined})"
else
     echo "❌ ERROR: Web container reports as: $HEALTH"
     echo "This indicates Uvicorn or the event loop is hung!"
     exit 1
fi

# 3. Check API Responsiveness (Timeout = 3 seconds)
echo ""
echo "[3/3] Pinging API REST Endpoints..."
if curl -s -f -m 3 http://localhost:8000/api/jobs > /dev/null; then
    echo "✅ API responded successfully!"
else
    echo "❌ ERROR: API is unresponsive! The FastAPI event loop may be locked or Uvicorn crashed."
    exit 1
fi

echo ""
echo "🎉 SUCCESS: All systems are green and responsive! 🎉"
exit 0
