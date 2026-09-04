"""Domain errors mapped to the HTTP status codes required by TDD §9.3."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class UnauthorizedError(Exception):
    """Missing or unrecognized bearer token."""


class ForbiddenError(Exception):
    """Authenticated, but the claimed identity does not match the token binding."""


class ConflictError(Exception):
    """Unknown job, stale/invalid receipt token, or gateway/job binding mismatch."""


class BadRequestError(Exception):
    """Client contract defect distinct from pydantic validation, e.g. a missing
    required field that isn't part of the declared request model."""


class NotFoundError(Exception):
    """Referenced resource does not exist."""


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # TDD §9.3 has no 422 entry; a malformed request is a "client contract defect" -> 400.
        return JSONResponse(status_code=400, content={"error": "MALFORMED_REQUEST", "detail": exc.errors()})

    @app.exception_handler(BadRequestError)
    async def _on_bad_request(_: Request, exc: BadRequestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "MALFORMED_REQUEST", "detail": str(exc)})

    @app.exception_handler(UnauthorizedError)
    async def _on_unauthorized(_: Request, __: UnauthorizedError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED"})

    @app.exception_handler(ForbiddenError)
    async def _on_forbidden(_: Request, __: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": "FORBIDDEN"})

    @app.exception_handler(ConflictError)
    async def _on_conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": "CONFLICT", "detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _on_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND", "detail": str(exc)})

    @app.exception_handler(Exception)
    async def _on_unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "detail": str(exc)})
