"""Authentication boundaries for operators and signed Twilio callbacks."""

import secrets
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, Request, WebSocket
from starlette.requests import HTTPConnection
from twilio.request_validator import RequestValidator

from app.config import get_settings


def require_admin(request: Request) -> None:
    key = get_settings().admin_api_key
    if not key:
        raise HTTPException(status_code=503, detail="Operator API is not configured")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), key.encode()):
        raise HTTPException(
            status_code=401,
            detail="Operator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def public_url(connection: HTTPConnection, *, websocket: bool = False) -> str:
    """Use configured public origin, never attacker-controlled proxy/Host headers."""
    base = urlsplit(get_settings().base_url)
    if base.scheme != "https" or not base.netloc or base.query or base.fragment:
        raise ValueError("BASE_URL must be the HTTPS public URL, without query or fragment")
    scheme = "wss" if websocket else "https"
    path = base.path.rstrip("/") + connection.scope["path"]
    query = connection.scope.get("query_string", b"").decode("ascii")
    return urlunsplit((scheme, base.netloc, path, query, ""))


async def require_twilio(request: Request) -> None:
    token = get_settings().twilio_auth_token
    if not token:
        raise HTTPException(status_code=503, detail="Twilio validation is not configured")
    try:
        url = public_url(request)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Invalid public URL configuration") from exc
    params = await request.form() if request.method == "POST" else {}
    signature = request.headers.get("x-twilio-signature", "")
    if not signature or not RequestValidator(token).validate(url, params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


async def authenticate_twilio_websocket(websocket: WebSocket) -> bool:
    token = get_settings().twilio_auth_token
    signature = websocket.headers.get("x-twilio-signature", "")
    if not token or not signature:
        await websocket.close(code=1008)
        return False
    try:
        url = public_url(websocket, websocket=True)
    except ValueError:
        await websocket.close(code=1008)
        return False
    # Twilio documents a trailing-slash variation for WSS handshake signatures.
    parts = urlsplit(url)
    trailing = urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/"))
    validator = RequestValidator(token)
    if not any(validator.validate(candidate, {}, signature) for candidate in (url, trailing)):
        await websocket.close(code=1008)
        return False
    return True


def require_allowed_outbound(number: str) -> None:
    """Fail closed for operator calls and agent-triggered transfers/SMS alike."""
    settings = get_settings()
    if not settings.outbound_enabled or number not in settings.outbound_allowed_numbers:
        raise HTTPException(status_code=403, detail="Outbound destination is not enabled")
