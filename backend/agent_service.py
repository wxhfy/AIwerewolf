from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.errors import install_exception_handlers
from backend.core.middleware import install_middleware
from backend.interfaces.http.agent_api import router as agent_router

app = FastAPI(
    title="AI Werewolf Agent Service",
    version=settings.app_version,
    description="Deployable Agent Service contract. Remote decision execution is intentionally not enabled yet.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_middleware(app, settings)
install_exception_handlers(app)
app.include_router(agent_router)


@app.get("/api/v1/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok", "service": "agent-service", "version": settings.app_version}
