#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
DomainError hierarchy + app-level exception handlers.

Register these on the FastAPI app via register_exception_handlers(app).
This keeps router code clean and centralizes error→HTTP mapping.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base for all domain-specific errors."""

    pass


class NotFoundError(DomainError):
    """Requested resource does not exist."""

    pass


class ProviderTimeoutError(DomainError):
    """External provider (ComicVine, Metron, etc.) timed out."""

    pass


class ConfigError(DomainError):
    """Configuration is invalid or missing required values."""

    pass


class AuthError(DomainError):
    """Authentication or authorization failure."""

    pass


class ValidationError(DomainError):
    """Input validation failed."""

    pass


def register_exception_handlers(app: FastAPI):
    """Register app-level exception handlers for domain errors."""

    @app.exception_handler(NotFoundError)
    async def handle_not_found(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ProviderTimeoutError)
    async def handle_provider_timeout(request: Request, exc: ProviderTimeoutError):
        return JSONResponse(status_code=504, content={"detail": str(exc)})

    @app.exception_handler(ConfigError)
    async def handle_config_error(request: Request, exc: ConfigError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(AuthError)
    async def handle_auth_error(request: Request, exc: AuthError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, exc: ValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
