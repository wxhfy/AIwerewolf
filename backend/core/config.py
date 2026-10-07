from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    environment: str
    cors_origins: tuple[str, ...]
    cors_allow_credentials: bool
    max_request_body_bytes: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    redis_url: str
    auth_mode: str
    auth_tokens: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_name=os.getenv("APP_NAME", "AI Werewolf API"),
            app_version=os.getenv("APP_VERSION", "0.3.0"),
            environment=os.getenv("APP_ENV", "development"),
            cors_origins=_csv_env("CORS_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001"),
            cors_allow_credentials=_bool_env("CORS_ALLOW_CREDENTIALS", True),
            max_request_body_bytes=max(1024, int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))),
            rate_limit_requests=max(0, int(os.getenv("RATE_LIMIT_REQUESTS", "0"))),
            rate_limit_window_seconds=max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))),
            redis_url=os.getenv("REDIS_URL", "").strip(),
            auth_mode=os.getenv("AUTH_MODE", "disabled").strip().lower(),
            auth_tokens=os.getenv("AUTH_TOKENS", "").strip(),
        )


settings = Settings.from_env()


def validate_production_configuration() -> None:
    """Reject unsafe deployment settings before serving traffic or claiming jobs."""
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        return
    errors: list[str] = []
    if not os.getenv("DATABASE_URL", "").startswith(("postgresql://", "postgresql+")):
        errors.append("DATABASE_URL must point to PostgreSQL")
    if os.getenv("LLM_PROVIDER", "").strip().lower() in {"", "fake"}:
        errors.append("LLM_PROVIDER must be a real provider")
    if _bool_env("ALLOW_FALLBACK", False) or _bool_env("_TEST_ALLOW_FAKE_LLM", False):
        errors.append("model fallback and fake-model test mode must be disabled")
    if not _bool_env("AIWEREWOLF_STRICT_MODE", False):
        errors.append("AIWEREWOLF_STRICT_MODE must be true")
    auth_mode = os.getenv("AUTH_MODE", settings.auth_mode).strip().lower()
    auth_tokens = os.getenv("AUTH_TOKENS", settings.auth_tokens).strip()
    if auth_mode != "static_token":
        errors.append("production AUTH_MODE must be static_token until OIDC is configured")
    if not auth_tokens:
        errors.append("AUTH_TOKENS must contain at least one token")
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))
