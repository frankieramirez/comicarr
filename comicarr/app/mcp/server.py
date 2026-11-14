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
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from starlette.middleware.authentication import AuthenticationMiddleware

from comicarr import logger
from comicarr.app.mcp.contracts import ContractError, tool_error
from comicarr.app.mcp.tools import recovery as recovery_tools
from comicarr.app.mcp.tools import search as search_tools
from comicarr.app.mcp.tools import series as series_tools
from comicarr.app.mcp.usage import ToolCallRecorder
from comicarr.app.system.deprecations import REGISTRY as DEPRECATIONS
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


def _argument_problem(error):
    """Name the rejected fields, never their values: those are the caller's data."""
    fields = sorted({".".join(str(part) for part in err["loc"]) or "arguments" for err in error.errors()})
    return "Invalid value for %s." % ", ".join(fields)


class ComicarrMCPServer(MCPServer):
    """MCPServer whose tool failures all carry the contract's ``{code, message, retryable}``.

    An unknown tool stays the SDK's own error result. Rejected arguments become
    ``invalid_argument``; a :class:`ContractError` becomes its own code; any
    other exception becomes ``internal`` and its text stays in the log.

    Write tools register through :meth:`write_tool`. While ``MCP_WRITE_ENABLED``
    is false (read on every request) they are left out of ``tools/list`` and
    calling one returns ``writes_disabled``.

    A renamed tool keeps its old name through :meth:`alias` (ADR-0006). Every
    call to a known name, old or new, goes through :class:`ToolCallRecorder`.
    """

    def __init__(self, get_ctx, **kwargs):
        super().__init__(**kwargs)
        self._get_ctx = get_ctx
        self.write_tools = set()
        self.aliases = {}
        self.calls = ToolCallRecorder()

    def write_tool(self, *, name, **kwargs):
        """Register a write tool; same arguments as :meth:`tool`."""
        self.write_tools.add(name)
        return self.tool(name=name, **kwargs)

    def alias(self, old_name, new_name):
        """Keep ``old_name`` callable as a deprecated alias of the tool ``new_name``.

        The alias is listed with the new tool's schemas, a title and description
        marked deprecated and naming the replacement, and it dispatches to the
        new tool. It is a write tool when the new one is. Each alias needs an
        MCP tool entry in the deprecation registry, which
        ``tests/unit/test_mcp_contract.py`` checks.
        """
        if self._tool_manager.get_tool(new_name) is None:
            raise ValueError("Cannot alias %s to unknown tool %s" % (old_name, new_name))
        if old_name == new_name or self._tool_manager.get_tool(old_name) is not None or old_name in self.aliases:
            raise ValueError("%s is already a tool name" % old_name)
        self.aliases[old_name] = new_name
        if new_name in self.write_tools:
            self.write_tools.add(old_name)

    def writes_enabled(self):
        config = self._get_ctx().config
        return bool(getattr(config, "MCP_WRITE_ENABLED", False)) if config else False

    async def list_tools(self):
        tools = await super().list_tools()
        by_name = {tool.name: tool for tool in tools}
        for old_name, new_name in self.aliases.items():
            target = by_name[new_name]
            tools.append(
                target.model_copy(
                    update={
                        "name": old_name,
                        "title": "%s (deprecated)" % (target.title or new_name),
                        "description": "Deprecated: renamed to %s, use that instead. %s"
                        % (new_name, target.description or ""),
                    }
                )
            )
        if self.writes_enabled():
            return tools
        return [tool for tool in tools if tool.name not in self.write_tools]

    async def call_tool(self, name, arguments, context=None):
        if name in self.aliases or self._tool_manager.get_tool(name) is not None:
            self.calls.record(name)
        if name in self.write_tools and not self.writes_enabled():
            return tool_error("writes_disabled", "MCP writes are off. Turn on MCP_WRITE_ENABLED to allow them.")
        try:
            return await super().call_tool(self.aliases.get(name, name), arguments, context)
        except UnexpectedToolError as e:
            if isinstance(e.__cause__, ContractError):
                body = e.__cause__.body
                return tool_error(body.code, body.message, body.retryable)
            logger.error("[MCP] Tool %s failed: %r" % (name, e.__cause__))
            return tool_error("internal", "The tool failed. Details are in the Comicarr log.", retryable=True)
        except ToolError as e:
            if isinstance(e.__cause__, ValidationError):
                return tool_error("invalid_argument", _argument_problem(e.__cause__))
            raise


def _build_server(get_ctx):
    # MCPServer calls logging.basicConfig(), which would give the root logger a
    # stderr handler Comicarr never asked for. Put the root logger back.
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    server = ComicarrMCPServer(get_ctx, name="comicarr", title="Comicarr", instructions=INSTRUCTIONS)
    root.handlers[:] = handlers
    root.setLevel(level)
    return server


def register_aliases(server, registry=DEPRECATIONS):
    """Declare an alias for every renamed MCP tool in the deprecation registry."""
    for entry in registry:
        if entry.mcp_tool:
            server.alias(entry.mcp_tool, entry.mcp_replacement)


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
    """The ``/mcp`` ASGI endpoint. Serve it inside ``async with endpoint.run():``."""

    def __init__(self, get_ctx):
        self._get_ctx = get_ctx
        self.server = _build_server(get_ctx)
        series_tools.register(self.server, get_ctx)
        search_tools.register(self.server, get_ctx)
        recovery_tools.register(self.server, get_ctx)
        register_aliases(self.server)
        self._authenticated = None

    @asynccontextmanager
    async def run(self):
        """Run a fresh session manager for one app lifespan.

        The SDK's session manager runs only once, and tests start the same app's
        lifespan more than once, so each run builds its own.
        """
        # Host checking is off: the Origin check in __call__ replaces it.
        self.server.streamable_http_app(
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        session_manager = self.server.session_manager
        transport = RequireAuthMiddleware(
            StreamableHTTPASGIApp(session_manager), required_scopes=[], resource_metadata_url=None
        )
        async with session_manager.run():
            self._authenticated = AuthenticationMiddleware(
                AuthContextMiddleware(transport), backend=BearerAuthBackend(ApiKeyVerifier(self._get_ctx))
            )
            try:
                yield
            finally:
                self._authenticated = None

    def _enabled(self):
        config = self._get_ctx().config
        return bool(getattr(config, "MCP_ENABLED", False)) if config else False

    async def __call__(self, scope, receive, send):
        if not self._enabled():
            return await _send_json(send, 404, "Not Found")
        if self._authenticated is None:
            return await _send_json(send, 503, "MCP is starting up")
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
