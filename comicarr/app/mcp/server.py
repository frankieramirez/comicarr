#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Build the MCP server and the ASGI endpoint mounted at ``/mcp``.

Request path, outermost first (after Comicarr's setup gate and CSRF exemption):

1. ``MCP_ENABLED`` false: 404, before authentication.
2. An ``Origin`` header naming another host: 403.
3. An IP locked out by the login limiter: 429.
4. ``X-Api-Key`` is rewritten to ``Authorization: Bearer``.
5. The SDK's bearer middleware checks the key against the live ``API_KEY``;
   a 401 counts as a failure against the login limiter.
6. The SDK's stateless Streamable HTTP transport.

Both settings are read on every request, so changes apply without a restart.
"""

import hmac
import json
import logging
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.authentication import AuthenticationMiddleware

from comicarr.app.mcp.tools import series as series_tools
from comicarr.app.system.service import login_rate_limiter

INSTRUCTIONS = "Comicarr manages a comic and manga library. Use list_series to see what the library holds."


class ApiKeyVerifier:
    """The SDK's TokenVerifier: the bearer token must equal the live API key."""

    def __init__(self, get_ctx):
        self._get_ctx = get_ctx

    async def verify_token(self, token):
        config = self._get_ctx().config
        expected = getattr(config, "API_KEY", None) if config else None
        if not expected or not hmac.compare_digest(token.encode(), str(expected).encode()):
            return None
        return AccessToken(token=token, client_id="api-key", scopes=[])


def _build_server():
    # MCPServer calls logging.basicConfig(), which would give the root logger a
    # stderr handler Comicarr never asked for. Put the root logger back.
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    server = MCPServer(name="comicarr", title="Comicarr", instructions=INSTRUCTIONS)
    root.handlers[:] = handlers
    root.setLevel(level)
    return server


async def _send_json(send, status, detail):
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope, name):
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1")
    return None


def _foreign_origin(scope):
    origin = _header(scope, b"origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc.lower() != (_header(scope, b"host") or "").lower()


def _with_bearer_from_api_key(scope):
    api_key = _header(scope, b"x-api-key")
    if api_key is None or _header(scope, b"authorization") is not None:
        return scope
    headers = [(k, v) for k, v in scope["headers"] if k != b"x-api-key"]
    headers.append((b"authorization", ("Bearer %s" % api_key).encode("latin-1")))
    return {**scope, "headers": headers}


class McpEndpoint:
    """The ``/mcp`` ASGI endpoint. ``session_manager.run()`` must be entered once at startup."""

    def __init__(self, get_ctx):
        self._get_ctx = get_ctx
        self.server = _build_server()
        series_tools.register(self.server, get_ctx)
        # Builds the session manager. Host checking is off: the Origin check below replaces it.
        self.server.streamable_http_app(
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        self.session_manager = self.server.session_manager
        transport = RequireAuthMiddleware(
            StreamableHTTPASGIApp(self.session_manager), required_scopes=[], resource_metadata_url=None
        )
        self._authenticated = AuthenticationMiddleware(
            AuthContextMiddleware(transport), backend=BearerAuthBackend(ApiKeyVerifier(get_ctx))
        )

    def _enabled(self):
        config = self._get_ctx().config
        return bool(getattr(config, "MCP_ENABLED", False)) if config else False

    async def __call__(self, scope, receive, send):
        if not self._enabled():
            return await _send_json(send, 404, "Not Found")
        if _foreign_origin(scope):
            return await _send_json(send, 403, "Origin not allowed")

        limiter = login_rate_limiter()
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if limiter.is_locked_out(ip):
            return await _send_json(send, 429, "Too many failed API key attempts")

        async def counting_send(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                limiter.record_failure(ip)
            await send(message)

        await self._authenticated(_with_bearer_from_api_key(scope), receive, counting_send)
