from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass
class ServiceError(Exception):
    status_code: int
    code: str
    detail: str
    title: str = "Request failed"
    extra: dict[str, Any] | None = None


class NotImplementedServiceError(ServiceError):
    def __init__(self, detail: str, *, code: str = "not_implemented") -> None:
        super().__init__(501, code, detail, "Capability not implemented")


def _problem(
    request: Request,
    *,
    status: int,
    title: str,
    detail: Any,
    code: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": f"urn:aiwerewolf:error:{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if extra:
        payload.update(extra)
    return payload


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_problem(
                request,
                status=exc.status_code,
                title=exc.title,
                detail=exc.detail,
                code=exc.code,
                extra=exc.extra,
            ),
            media_type="application/problem+json",
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_problem(
                request,
                status=exc.status_code,
                title="HTTP error",
                detail=exc.detail,
                code=f"http_{exc.status_code}",
            ),
            headers=exc.headers,
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_problem(
                request,
                status=422,
                title="Validation failed",
                detail="Request data did not match the API contract.",
                code="validation_error",
                extra={"errors": exc.errors()},
            ),
            media_type="application/problem+json",
        )
