"""Shared API security and filesystem validation helpers."""

from pathlib import Path

from fastapi import Depends, Header, HTTPException, WebSocket

from app.config import Settings, get_settings


def _is_relative_to(path: Path, root: Path) -> bool:
    """Compatibility helper for Python versions without Path.is_relative_to."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_path_within_allowed_roots(path_str: str, settings: Settings | None = None) -> str:
    """Validate that a path resolves inside a configured allowed root."""
    cfg = settings or get_settings()
    candidate = Path(path_str).expanduser().resolve(strict=False)
    allowed_roots = [Path(root) for root in cfg.normalized_allowed_source_roots()]

    if not allowed_roots:
        raise HTTPException(status_code=500, detail="No allowed source roots configured")

    if not any(_is_relative_to(candidate, root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path not allowed")

    return str(candidate)


def require_api_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Require a static API token when auth is enabled."""
    if not settings.require_auth:
        return

    expected = settings.api_token
    if not expected:
        raise HTTPException(status_code=500, detail="Authentication is enabled but API token is not configured")

    bearer_token = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            bearer_token = token.strip() or None

    supplied = x_api_token or bearer_token
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_websocket_token(websocket: WebSocket) -> None:
    """Require a token before accepting a websocket connection when auth is enabled."""
    settings = get_settings()
    if not settings.require_auth:
        return

    expected = settings.api_token
    if not expected:
        await websocket.close(code=1011, reason="Authentication misconfigured")
        return

    supplied = websocket.headers.get("x-api-token") or websocket.query_params.get("token")
    auth_header = websocket.headers.get("authorization")
    if not supplied and auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            supplied = token.strip() or None

    if supplied != expected:
        await websocket.close(code=1008, reason="Unauthorized")
