"""
Redis-backed session store.

One entry per active call. Expires automatically when the call ends.
"""

import redis.asyncio as redis
import structlog

from app.config import get_settings
from app.models.call import CallSession

log = structlog.get_logger()
settings = get_settings()

_redis: redis.Redis | None = None
SESSION_TTL = 3600  # seconds


async def init_redis():
    global _redis
    _redis = redis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()
    log.info("redis.connected")


def get_redis() -> redis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis


class SessionStore:
    def __init__(self):
        self._r = get_redis()

    def _key(self, call_sid: str) -> str:
        return f"call_session:{call_sid}"

    async def save_session(self, session: CallSession):
        await self._r.setex(
            self._key(session.call_sid),
            SESSION_TTL,
            session.model_dump_json(),
        )

    async def update_session(self, session: CallSession):
        await self.save_session(session)

    async def get_session(self, call_sid: str) -> CallSession | None:
        raw = await self._r.get(self._key(call_sid))
        if raw:
            return CallSession.model_validate_json(raw)
        return None

    async def delete_session(self, call_sid: str):
        await self._r.delete(self._key(call_sid))
