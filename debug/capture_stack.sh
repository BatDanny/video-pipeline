#!/bin/bash
# ============================================
# VideoPipe - Debug Stack Capture Script
# ============================================
# Run this script when the application is misbehaving to dump
# system state into the debug/dumps folder for later review.

set -e

# Get script directory to work relatively
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DUMP_DIR="$SCRIPT_DIR/dumps"

# Ensure dumps directory exists
mkdir -p "$DUMP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_FILE="$DUMP_DIR/stack_dump_$TIMESTAMP.txt"

echo "Capturing system state to: $DUMP_FILE"

{
    echo "=============================================="
    echo "VIDEO PIPELINE DEBUG DUMP"
    echo "Date: $(date)"
    echo "=============================================="
    echo ""
    
    echo "--- DISK SPACE ---"
    df -h
    echo ""
    
    echo "--- MEMORY USAGE ---"
    free -h
    echo ""
    
    echo "--- SYSTEM LOAD ---"
    uptime
    echo ""
    
    echo "--- DOCKER CONTAINERS ---"
    sudo docker ps -a
    echo ""
    
    echo "--- DOCKER STATS ---"
    sudo docker stats --no-stream
    echo ""
    
    if command -v nvidia-smi &> /dev/null; then
        echo "--- GPU STATUS ---"
        nvidia-smi
        echo ""
    fi
    
    echo "--- DOCKER COMPOSE LOGS (Last 200 lines) ---"
    cd "$PROJECT_ROOT" && sudo docker compose logs --tail 200
    echo ""
    
} > "$DUMP_FILE" 2>&1

echo "Done. Dump saved to $DUMP_FILE"
