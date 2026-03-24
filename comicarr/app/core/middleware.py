#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
FastAPI middleware — CSRF protection, security headers, setup gate.

CSRF is a global middleware (not per-route) so it's impossible to forget
when adding new routes. During transition, CherryPy's tools.csrf is
disabled under the WSGI bridge to avoid double-checking.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Single exemption list — shared concept with CherryPy during transition
CSRF_EXEMPT_PREFIXES = (
    "/api",
    "/auth/login",
    "/auth/setup",
    "/legacy",  # CherryPy WSGI bridge handles its own CSRF
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Require X-Requested-With header on state-changing requests.

    Combined with SameSite=Strict cookies, this provides CSRF protection.
    Cross-origin requests with custom headers trigger CORS preflight,
    which is rejected (no CORS policy configured).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            path = request.url.path
            exempt = any(
                path == prefix or path.startswith(prefix + "/")
                for prefix in CSRF_EXEMPT_PREFIXES
            )
            if not exempt:
                if request.headers.get("X-Requested-With") != "ComicarrFrontend":
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF validation failed"},
                    )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https://comicvine.gamespot.com https://static.metron.cloud https://uploads.mangadex.org",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ])

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Content-Security-Policy-Report-Only"] = self.CSP

        # HSTS when behind HTTPS
        ctx = getattr(request.app.state, "ctx", None)
        if ctx and ctx.config and getattr(ctx.config, "ENABLE_HTTPS", False):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class SetupGateMiddleware(BaseHTTPMiddleware):
    """Block all requests except setup-related paths when first-run setup is pending."""

    ALLOWED_PREFIXES = ("/", "/index.html", "/auth/setup", "/auth/check_setup", "/assets", "/favicon.ico", "/api/health")

    async def dispatch(self, request: Request, call_next):
        ctx = getattr(request.app.state, "ctx", None)
        if ctx and ctx.setup_token is not None:
            path = request.url.path
            allowed = any(
                path == prefix or path.startswith(prefix + "/")
                for prefix in self.ALLOWED_PREFIXES
            )
            # Allow exact root path
            if path == "/":
                allowed = True
            if not allowed:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Setup required. Please configure credentials via the setup page."},
                )
        return await call_next(request)
