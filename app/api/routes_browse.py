"""File browser API — browse NAS directories from the web UI."""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browse", tags=["browse"])

# Allowed base paths (security: prevent browsing outside these)
ALLOWED_ROOTS = [
    "/mnt/nas",
    "/app/data/uploads",
]


def _is_path_allowed(path: str) -> bool:
    """Check if path is under an allowed root directory."""
    real_path = os.path.realpath(path)
    return any(real_path.startswith(os.path.realpath(root)) for root in ALLOWED_ROOTS)


# Video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mts", ".m2ts"}


@router.get("")
async def browse_directory(
    path: str = Query("/mnt/nas/gopro", description="Directory to browse"),
):
    """Browse a directory and return its contents.

    Returns folders and video files, sorted with folders first.
    Only paths under allowed roots can be browsed (security).
    """
    if not _is_path_allowed(path):
        raise HTTPException(status_code=403, detail="Path not allowed")

    if not os.path.isdir(path):
        raise HTTPException(status_code=404, detail="Directory not found")

    items = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    folders = []
    files = []

    for entry in entries:
        # Skip hidden files
        if entry.startswith("."):
            continue

        full_path = os.path.join(path, entry)
        try:
            stat = os.stat(full_path)
        except (OSError, PermissionError):
            continue

        if os.path.isdir(full_path):
            # Count video files inside this folder (one level deep for speed)
            video_count = 0
            try:
                for sub in os.listdir(full_path):
                    if os.path.splitext(sub)[1].lower() in VIDEO_EXTENSIONS:
                        video_count += 1
            except (OSError, PermissionError):
                pass

            folders.append({
                "name": entry,
                "path": full_path,
                "type": "folder",
                "video_count": video_count,
                "modified": stat.st_mtime,
            })

        elif os.path.isfile(full_path):
            ext = os.path.splitext(entry)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                size_mb = stat.st_size / (1024 * 1024)
                files.append({
                    "name": entry,
                    "path": full_path,
                    "type": "file",
                    "size_mb": round(size_mb, 1),
                    "extension": ext,
                    "modified": stat.st_mtime,
                })

    # Folders first, then video files
    items = folders + files

    # Parent path for navigation
    parent = os.path.dirname(path) if path != "/" else None
    if parent and not _is_path_allowed(parent):
        parent = None

    return {
        "path": path,
        "parent": parent,
        "items": items,
        "folder_count": len(folders),
        "file_count": len(files),
    }


@router.get("/roots")
async def get_browse_roots():
    """Return available root directories for browsing."""
    roots = []
    for root in ALLOWED_ROOTS:
        if os.path.isdir(root):
            roots.append({
                "name": os.path.basename(root) or root,
                "path": root,
            })
    return {"roots": roots}
