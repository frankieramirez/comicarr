# What does Comicarr need to serve MCP at `/mcp` from its FastAPI process, authenticated with its static API key?

## Findings

Comicarr can do this with the official `mcp` Python SDK 2.3.0 and no new web stack. The SDK builds a Starlette sub-app that runs inside the existing uvicorn process. It resolves cleanly against Comicarr's locked FastAPI, Starlette, pydantic, uvicorn and sse-starlette. The spec makes authorization optional, so a static key is allowed. The SDK's bearer hook takes a static key in about ten lines. Local clients (Claude Code, Cursor, VS Code, Codex CLI) all accept a static header without OAuth. Claude on the web and in Claude Desktop is the exception. Its connectors call the server from Anthropic's cloud. Static request headers there are a beta for a limited set of organizations. So a LAN-only Comicarr will not reach those connectors without public HTTPS exposure.

Four things in Comicarr's own code need changes. Mount the SDK's route at `/mcp` with a plain `Route`, not `Mount`. Run the session manager from Comicarr's lifespan. Set the SDK's Host/Origin allowlist, which by default rejects every non-localhost host. Exempt `/mcp` from Comicarr's CSRF middleware.

### 1. Spec revisions and the Streamable HTTP transport

**Revisions.** The spec site lists 2026-07-28 as "(latest)", followed by 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05, plus a Draft. The SDK's version registry has the same five released revisions.

**2026-07-28 is a large break.** The spec now calls it the "modern" era and calls 2025-11-25 and earlier "legacy". The 2026-07-28 changelog:

- Removes protocol-level sessions and the `Mcp-Session-Id` header.
- Removes the `initialize` handshake. Every request carries its protocol version and client capabilities in `_meta`.
- Adds a mandatory `server/discover` RPC.
- Replaces the HTTP GET stream and resource subscribe with a `subscriptions/listen` POST stream.
- Removes SSE resumability (`Last-Event-ID`). A broken stream loses the in-flight request, and the client must re-issue it.
- Replaces server-initiated requests (elicitation, sampling, roots) with the Multi Round-Trip Request pattern. The server returns `resultType: "input_required"` and the client retries with the answers.
- Requires `Mcp-Method` and `Mcp-Name` request headers on POST.
- Deprecates Roots, Sampling and Logging.

**Stateful and stateless.** In the legacy era (2025-03-26 through 2025-11-25), the server MAY assign an `MCP-Session-Id` on the `InitializeResult` response. Clients then send it on every request, MAY open a standalone SSE stream with GET, and end the session with DELETE. In the modern era, every request is a self-contained POST.

**SSE streaming.** In both eras, a POST response is either `application/json` or a `text/event-stream` stream. The stream carries request-scoped notifications such as `notifications/progress` before the final result. In 2026-07-28, those notifications still travel on the stream of the request they belong to.

**Deprecated HTTP+SSE transport.** This is the 2024-11-05 transport. It used two endpoints: a GET SSE stream, plus a separate POST endpoint for client messages. Streamable HTTP replaced it starting with 2025-03-26. Claude Code calls SSE deprecated, and VS Code calls it "a legacy SSE endpoint".

**Origin and DNS rebinding.** Servers MUST validate `Origin` on all incoming connections. If `Origin` is present and invalid, the server MUST answer 403. When running locally, servers SHOULD bind to 127.0.0.1, and they SHOULD authenticate all connections. 2025-11-25 says the same.

**Protocol version header.**

- Every POST MUST carry `MCP-Protocol-Version`.
- In 2026-07-28 the header MUST match the version in `_meta`. A mismatch gets 400 `HeaderMismatch`. An unsupported version gets 400 `UnsupportedProtocolVersionError`. An unknown method gets 404 with JSON-RPC `-32601`.
- A server MAY treat a request with no header as 2025-03-26.
- A client that speaks both eras tries a modern request first. It falls back to `initialize` only if a 400 body is not a recognized modern error.

### 2. The official Python SDK (`mcp` on PyPI)

**Version and license.** The latest release is 2.3.0, uploaded 2026-10-02. It is MIT licensed and requires Python >=3.10. Comicarr requires >=3.11, so this fits. The 1.x line is still maintained: 1.30.0 shipped 2026-09-07, the same day as 2.2.0. 2.x renames `FastMCP` to `mcp.server.mcpserver.MCPServer`. Importing `mcp.server.fastmcp` in 2.x raises an error that points at the migration guide. Tutorials written for 1.x will not run unchanged.

**Dependencies of 2.3.0.** `anyio>=4.9`, `httpx2>=2.10.0` (a new package from pydantic, not `httpx`), `jsonschema>=4.20`, `mcp-types==2.3.0`, `opentelemetry-api>=1.28`, `pydantic>=2.12`, `pyjwt[crypto]>=2.10.1`, `python-multipart>=0.0.9`, `sse-starlette>=3.0`, `starlette>=0.27` (>=0.48 on Python 3.14), `typing-extensions`, `typing-inspection`, and `uvicorn>=0.31.1`. The 1.30.0 release used `httpx<1.0,>=0.27.1`, `httpx-sse` and `pydantic-settings` instead.

**No conflict with Comicarr.** Comicarr's `pyproject.toml` declares `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0`, `sse-starlette>=3.0.0` and `httpx>=0.27.0`. Its `uv.lock` pins fastapi 0.135.2, starlette 1.3.1, pydantic 2.12.5, anyio 4.14.2, uvicorn 0.42.0, sse-starlette 3.3.3 and httpx 0.28.1. Running `uv pip compile` with those exact pins plus `mcp==2.3.0` on Python 3.11 resolves without changing any of them. It adds `mcp-types`, `httpx2`, `httpcore2`, `truststore`, `opentelemetry-api`, `jsonschema` and its dependencies, and `pyjwt`/`cryptography`. Upgrading `uv.lock` to `mcp==2.3.0` would reuse every pinned package already there and add those new ones. `httpx2` installs next to `httpx` and does not replace it.

**Mounting inside FastAPI.**

- `MCPServer.streamable_http_app(streamable_http_path="/mcp", json_response=False, stateless_http=False, event_store=None, max_request_body_size=..., session_idle_timeout=..., max_sessions=..., transport_security=None, host="127.0.0.1")` returns a Starlette app with one route at `streamable_http_path`. Its lifespan runs `session_manager.run()`.
- The SDK's ASGI guide warns that "a mounted sub-application's lifespan never runs". The host app must enter `mcp.session_manager.run()` in its own lifespan. If it does not, the first request fails with `RuntimeError: Task group is not initialized`. `session_manager` exists only after `streamable_http_app()` has been called. `session_manager.run()` can be entered only once per instance.
- The guide's own patterns are `Mount("/", app)`, or `Mount("/prefix", app)` with `streamable_http_path="/"`. Comicarr already mounts its SPA at `/`, so `Mount("/")` cannot coexist with it. A probe showed that `app.mount("/mcp", sub)` with `streamable_http_path="/"` answers `POST /mcp` with `307` to `/mcp/`. A probe also showed what does work. Append `starlette.routing.Route("/mcp", endpoint=sub)` to the FastAPI router, keep the default `streamable_http_path="/mcp"`, and place the route before the SPA mount. Then `POST /mcp` returns 200 directly, the SDK's auth middleware still runs, and the SPA still serves `/`.
- `stateless_http=True` affects only legacy clients. The SDK routes on `MCP-Protocol-Version`, and a 2026-07-28 request is handled before that flag is read. The deploy guide says the modern path is "sessionless by construction". With the flag set, a legacy client gets no session. It loses the server-to-client back-channel (push elicitation, sampling, roots) and resumability. In exchange, no per-session state lives in memory. `json_response=True` returns plain JSON instead of SSE. On the modern path in SSE mode, the SDK starts SSE only once a handler emits a notification or a ping interval passes.

**DNS rebinding defaults.** When `transport_security` is None and `host` is a loopback name, the SDK enables Host and Origin checks with only `127.0.0.1:*`, `localhost:*` and `[::1]:*` allowed. A probe confirmed that a request with `Host: comicarr.lan:8090` gets `421 Invalid Host header`. A probe also confirmed that `Origin: http://evil.example` on localhost gets 403. Comicarr is reached by LAN hostnames and through reverse proxies, so it must pass `TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` built from its own config. It can also turn the check off, but only if it does its own Origin validation, because the spec makes that validation a MUST.

**Tool features.**

- `@mcp.tool(name, title, description, annotations, icons, meta, structured_output)` is the registration decorator.
- `ToolAnnotations` has `title`, `read_only_hint`, `destructive_hint`, `idempotent_hint` and `open_world_hint`. They serialize as `readOnlyHint` and so on. The spec says clients MUST treat annotations as untrusted unless they come from trusted servers.
- Structured output: a return type annotation, such as a pydantic model, produces an `outputSchema` in `tools/list` and `structuredContent` in results. A plain `str` return is wrapped as `{"result": ...}`. A probe confirmed both on the wire.
- Progress: `await ctx.report_progress(progress, total, message)`. A probe on a 2026-07-28 request saw `notifications/progress` streamed before the result.
- Elicitation: use a resolver, `Annotated[T, Resolve(fn)]` returning `Elicit(...)`. It works in both eras, and on 2026-07-28 the SDK uses Multi Round-Trip Requests. Direct `await ctx.elicit()` and `ctx.elicit_url()` work only for legacy-era clients, because they are server-to-client requests.

### 3. Authorization

- The 2026-07-28 authorization page says: "Authorization is **OPTIONAL** for MCP implementations. When supported: Implementations using an HTTP-based transport **SHOULD** conform to this specification." It is a SHOULD, not a MUST. STDIO servers SHOULD NOT follow it and should take credentials from the environment.
- When a server does follow it, the server is an OAuth 2.1 resource server. It MUST validate tokens, MUST accept only tokens issued for itself, and must not pass tokens through.
- The transport page says servers SHOULD authenticate all connections. Nothing in the spec forbids a static bearer token or a custom header. A static key is a non-OAuth choice that the spec allows but does not describe.
- **What the SDK offers.** `TokenVerifier` is a protocol with one method, `async verify_token(token) -> AccessToken | None`. Pass it as `MCPServer(token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=...))`. The two arguments must be given together. `resource_server_url` is a required field, but it may be None. When it is None, the SDK serves no protected-resource metadata route.
- A probe confirmed a constant-time comparison against Comicarr's key works. Without the key, the SDK answers 401 with `WWW-Authenticate: Bearer error="invalid_token"`.
- The SDK's `BearerAuthBackend` reads only `Authorization: Bearer <token>`. A probe sent `X-Api-Key` with the correct value and still got 401. To accept `X-Api-Key`, the same header Comicarr's REST API reads through `APIKeyHeader(name="X-Api-Key")`, Comicarr needs a small ASGI shim before the route. The shim either maps `X-Api-Key` to `Authorization: Bearer` or checks the key itself.
- `issuer_url` must be a valid URL even when no OAuth server exists. A placeholder works, and it is only advertised when `resource_server_url` is set.
- Custom routes added with `@mcp.custom_route()` are never authenticated.

### 4. Client support for a remote server with a static header and no OAuth

| Client | Remote Streamable HTTP | Static header without OAuth | Notes |
|---|---|---|---|
| Claude Code | Yes, `claude mcp add --transport http <name> <url>` | Yes, `--header "Authorization: Bearer ..."` (or `-H`, any header such as `X-API-Key`). `.mcp.json` takes `"type": "http"` with `headers`, and `${VAR}` / `${VAR:-default}` expansion. `headersHelper` runs a command for dynamic headers. | OAuth is optional. If `headers.Authorization` is set and rejected, Claude Code reports a failure and does not fall back to OAuth. SSE is deprecated. |
| Claude (web, Desktop, mobile) custom connectors | Yes, added by URL under Customize > Connectors. A URL ending in `/sse` selects SSE. | Only through "Request headers", which is in beta for a limited set of organizations. Allowed names include `authorization`, `x-api-key` and `x-auth-token`, up to four headers. The value is sent exactly as entered, so a bearer token needs the `Bearer ` prefix typed in. Without that beta, the choices are OAuth (DCR, CIMD or a pre-registered client) or "No sign-in". | Requests come from Anthropic's cloud (egress `160.79.104.0/21`), so the server must be reachable from the internet over HTTPS. MCP tunnels for private networks are a research preview for the Enterprise plan only, and Anthropic tells tunneled servers to require OAuth. Claude Desktop also runs local servers: the first-party guide shows `claude_desktop_config.json` entries that start a command, and `.mcpb` desktop extensions. The pages reviewed do not mention `mcp-remote`, which is a community bridge and not first-party. |
| Cursor | Yes. Supports stdio, SSE and Streamable HTTP. | Yes. `mcp.json` entry with `url` and `headers`. `${env:NAME}` interpolation works in `headers`. Remote servers do not support `envFile`. | OAuth is supported when a server requires it (PKCE, RFC 9728 discovery, DCR or a static `auth` client). It is not required. |
| VS Code / GitHub Copilot | Yes. The client tries Streamable HTTP, then falls back to SSE. | Yes. `.vscode/mcp.json` `servers` entry with `url` and `headers`, for example `"Authorization": "Bearer ${input:api-token}"`, with a `promptString` input and `password: true`. The portable Copilot `mcpServers` format also takes `headers`, but only `${NAME}` environment references, not inputs. | An `oauth` object (or `oauthClientId` in the portable format) is optional. |
| OpenAI Codex CLI | Yes. Supports stdio and Streamable HTTP. | Yes. `config.toml` keys `url`, `bearer_token_env_var`, `http_headers` (static) and `env_http_headers`. | OAuth (CIMD, DCR) is optional, through `codex mcp login`. |

None of these clients requires OAuth. The only client in the table limited to stdio for local config is Claude Desktop's `claude_desktop_config.json`, and the Desktop app reaches remote servers through connectors instead.

### 5. Conventions among *arr apps

None found. Shallow checkouts of the `Sonarr/Sonarr`, `Radarr/Radarr`, `Lidarr/Lidarr` and `Prowlarr/Prowlarr` default branches (latest commits 2026-11-02 to 2026-11-11) contain no file or path named with `mcp`. Search results show only third-party wrapper projects listed on aggregator sites. These are separate processes that call the *arr REST APIs, and none is published by the *arr projects.

### Comicarr-side facts for the design

- `comicarr/app/core/middleware.py` `CSRFMiddleware` returns 403 for any POST, PUT, DELETE or PATCH without `X-Requested-With: ComicarrFrontend`, unless the path is in `CSRF_EXEMPT_PREFIXES`, which today is `/opds` and `/api/health`. MCP clients will not send that header, so `/mcp` must be added to that list. `SetupGateMiddleware` will return 503 for `/mcp` until first-run setup is done, which seems right.
- A probe stacked three pass-through `BaseHTTPMiddleware` layers, the type Comicarr uses, in front of the SDK route. Both the modern SSE stream (progress followed by the result) and the legacy SSE stream still arrived intact. This used httpx's in-process ASGI transport, not a live uvicorn socket, so long-lived streams and client disconnects behind real uvicorn still need testing.
- `comicarr/app/main.py` already has an `asynccontextmanager` lifespan and mounts the SPA at `/` last. The MCP route must be added before that mount, and the lifespan must enter `mcp.session_manager.run()`.
- `require_api_key("full")` in `comicarr/app/core/security.py` compares `X-Api-Key` with `hmac.compare_digest` against `config.API_KEY`. A `TokenVerifier` can reuse that comparison for the bearer path.

## Sources

- https://github.com/modelcontextprotocol/modelcontextprotocol (shallow clone at commit `06e9234`, 2026-11-12), `docs/docs.json`: the version list, with 2026-07-28 marked "(latest)".
- Same repo, `docs/specification/2026-07-28/changelog.mdx`: removal of sessions, handshake and resumability; `server/discover`; `subscriptions/listen`; MRTR; `Mcp-Method` and `Mcp-Name` headers; deprecation of Roots, Sampling and Logging.
- Same repo, `docs/specification/2026-07-28/basic/transports/streamable-http.mdx`: single POST endpoint, Origin MUST and 403, localhost SHOULD, auth SHOULD, `MCP-Protocol-Version` rules and error codes, backward-compatibility probing, summary of the earlier session shape.
- Same repo, `docs/specification/2026-07-28/basic/versioning.mdx`: the modern, legacy and dual-era terms, per-request version negotiation.
- Same repo, `docs/specification/2025-11-25/basic/transports.mdx`: Streamable HTTP replacing 2024-11-05 HTTP+SSE, `MCP-Session-Id` MAY, GET stream, `Last-Event-ID`, DELETE, Origin MUST.
- Same repo, `docs/specification/2026-07-28/basic/authorization/index.mdx` and `security-considerations.mdx`: "Authorization is OPTIONAL", HTTP SHOULD conform, STDIO SHOULD NOT, OAuth 2.1 resource server, audience validation, no token passthrough.
- Same repo, `docs/specification/2026-07-28/server/tools.mdx`: `outputSchema`, `annotations`, and annotations untrusted unless from trusted servers.
- Same repo, `docs/docs/2026-07-28/develop/connect-local-servers.mdx` and `connect-remote-servers.mdx`: Claude Desktop local servers run as commands from `claude_desktop_config.json`, and remote servers are added as Custom Connectors.
- https://pypi.org/pypi/mcp/json and `https://pypi.org/pypi/mcp/<version>/json` for 2.3.0, 2.0.0 and 1.30.0: latest version 2.3.0 (2026-10-02), MIT license, Python >=3.10, dependency lists for each line, release dates.
- https://pypi.org/pypi/httpx2/json: `httpx2` is "The next generation HTTP client" from github.com/pydantic/httpx2, a separate package from `httpx`.
- `mcp-2.3.0-py3-none-any.whl` and `mcp_types-2.3.0-py3-none-any.whl` (downloaded with `pip download`):
  - `mcp_types/version.py`: the known, handshake and modern protocol versions.
  - `mcp/server/fastmcp.py`: `FastMCP` renamed to `MCPServer`.
  - `mcp/server/mcpserver/server.py`: `streamable_http_app` signature, `tool()` signature, `session_manager`.
  - `mcp/server/lowlevel/server.py`: loopback DNS-rebinding default, auth wrapping, lifespan.
  - `mcp/server/streamable_http_manager.py`: modern routing before the `stateless` check, `run()` callable only once.
  - `mcp/server/transport_security.py`: `TransportSecuritySettings`.
  - `mcp/server/auth/provider.py`: `TokenVerifier` and `AccessToken`.
  - `mcp/server/auth/settings.py`: `AuthSettings` fields.
  - `mcp/server/auth/middleware/bearer_auth.py`: reads only the `Authorization: Bearer` header.
  - `mcp/server/mcpserver/context.py`: `report_progress`, `elicit`.
  - `mcp_types/_types.py`: `ToolAnnotations` hints, `output_schema`, `structured_content`.
- https://github.com/modelcontextprotocol/python-sdk (shallow clone at commit `77001c9`, 2026-11-05, which is the main branch and may be ahead of 2.3.0):
  - `docs/run/asgi.md`: mounting, "a mounted sub-application's lifespan never runs", the `RuntimeError`, the 421 behind a real hostname, CORS, unauthenticated custom routes.
  - `docs/run/deploy.md`: `stateless_http` affects only legacy clients, the modern path is sessionless.
  - `docs/run/authorization.md`: `TokenVerifier` is the whole integration surface, RFC 9728 metadata, 401 behavior.
  - `docs/handlers/elicitation.md`: resolvers work in both eras, `ctx.elicit` only in the legacy era.
  - `docs/servers/structured-output.md`: `output_schema` and `structured_content`.
- Local probes (scratch scripts, not committed), run with `fastapi==0.135.2`, `starlette==1.3.1`, `mcp==2.3.0` and `httpx==0.28.1` on Python 3.11 through `httpx.ASGITransport`. They established: `uv pip compile` of Comicarr's locked pins plus `mcp==2.3.0` resolves with no conflicts; `Route("/mcp", endpoint=sub)` returns 200 and `Mount("/mcp")` returns 307; the default transport security returns 421 for a LAN Host and 403 for a bad Origin; a static-key `TokenVerifier` works and `X-Api-Key` alone gets 401; a 2026-07-28 `tools/call` returns no session ID and streams progress before the result; `outputSchema` and `readOnlyHint` appear in `tools/list`; SSE passes through `BaseHTTPMiddleware`.
- https://code.claude.com/docs/en/mcp.md: `claude mcp add --transport http ... --header`, `.mcp.json` `type: http` with `headers` and variable expansion, `headersHelper`, OAuth optional with no OAuth fallback when `Authorization` is set, SSE deprecated.
- https://claude.com/docs/connectors/building/authentication.md: Claude's auth types (`oauth_dcr`, `oauth_cimd`, `static_headers` beta for limited organizations, `none`), allowed header names, one infrastructure across claude.ai, Desktop, mobile, Claude Code and Cowork, egress `160.79.104.0/21`.
- https://claude.com/docs/connectors/custom/add-unlisted.md: custom connector by URL on all plans, "No sign-in" plus Request headers for API keys (beta), the value sent exactly as typed, up to four headers, `/sse` URL selects SSE, `.mcpb` desktop extensions.
- https://claude.com/docs/connectors/mcp-tunnels/overview: tunnels are a research preview for the Enterprise plan only, servers must speak Streamable HTTP, and Anthropic says to require OAuth on tunneled servers.
- https://cursor.com/docs/mcp.md: stdio, SSE and Streamable HTTP; `url` and `headers`; `${env:...}` interpolation; no `envFile` for remote servers; OAuth supported but not required.
- https://code.visualstudio.com/docs/agents/reference/mcp-configuration.md: `headers` with `${input:...}`, `promptString` with `password`, the portable format's `${NAME}`-only rule, Streamable HTTP with SSE fallback, optional `oauth`.
- https://learn.chatgpt.com/docs/extend/mcp.md?surface=cli (redirected from developers.openai.com/codex/mcp.md): Codex stdio and Streamable HTTP, `bearer_token_env_var`, `http_headers`, `env_http_headers`, `codex mcp login`.
- https://github.com/Sonarr/Sonarr, https://github.com/Radarr/Radarr, https://github.com/Lidarr/Lidarr, https://github.com/Prowlarr/Prowlarr (shallow `--no-checkout` clones, `git ls-tree`): no MCP files in any first-party *arr repo.
- `/home/user/comicarr/pyproject.toml` and `/home/user/comicarr/uv.lock`: Comicarr's declared ranges and locked versions.
- `/home/user/comicarr/comicarr/app/core/middleware.py`: `CSRF_EXEMPT_PREFIXES`, the `X-Requested-With` rule, the setup gate.
- `/home/user/comicarr/comicarr/app/core/security.py`: `APIKeyHeader(name="X-Api-Key")`, `require_api_key` using `hmac.compare_digest`.
- `/home/user/comicarr/comicarr/app/main.py`: the lifespan, middleware order, SPA mounted at `/` last.
