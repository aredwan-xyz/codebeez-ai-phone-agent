import structlog
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.config import get_settings
from app.db.base import init_db
from app.memory.session import init_redis
from app.api.calls import router as calls_router
from app.api.websocket import router as ws_router
from app.api.admin import router as admin_router

log = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", model=settings.claude_model, agent=settings.agent_name)
    await init_db()
    await init_redis()
    yield
    log.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(calls_router, prefix="/calls", tags=["calls"])
app.include_router(ws_router, prefix="/ws", tags=["websocket"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "agent": settings.agent_name}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
