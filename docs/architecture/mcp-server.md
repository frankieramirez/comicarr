# MCP server design

The settled design for the MCP server in the Feature-complete milestone of the
[1.0 roadmap](https://github.com/frankieramirez/comicarr/issues/1184). Each
section records a decision made on the
[MCP server design map](https://github.com/frankieramirez/comicarr/issues/1242)
and links the ticket that holds the reasoning. The build runs under
[Build: MCP server](https://github.com/frankieramirez/comicarr/issues/1301).
Sections 1 to 3 are live, with `list_series` as the only tool
([#1302](https://github.com/frankieramirez/comicarr/issues/1302)), and so is
the section 6 contract
([#1303](https://github.com/frankieramirez/comicarr/issues/1303)). In section
5, the write switch and the status writes `set_issue_status`, `pause_series`
and `resume_series` are live
([#1307](https://github.com/frankieramirez/comicarr/issues/1307)), and so are
the search writes `search_issue`, `search_missing` and `retry_search_run`
([#1308](https://github.com/frankieramirez/comicarr/issues/1308)), and
`add_series` and `refresh_series`
([#1309](https://github.com/frankieramirez/comicarr/issues/1309)).

Research: [MCP transport, auth and clients](../research/2026-11-13-mcp-transport-auth-clients.md)
([ticket](https://github.com/frankieramirez/comicarr/issues/1243)).

## 1. Tool layer

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1244).

- Package: `comicarr/app/mcp/`. `server.py` builds the server and its ASGI
  app, `tools/<domain>.py` holds the tools for one domain, and `contracts.py`
  holds the Pydantic input and output models. Only `app/main.py` imports it.
- Import rule: the router rule from
  [ADR-0005](../adr/0005-legacy-module-boundary.md). A tool calls a domain
  service, a seam module, or a published seam such as `attention.read`. It
  imports no root module outside Infrastructure, runs no SQL of its own, and
  reaches no private module. `scripts/check_legacy_seams.py` treats
  `comicarr/app/mcp/**` like a `router.py`, with an empty allowlist. A tool
  that needs data no service exposes adds the service function first.
- Built-in chat is not rewired. It is frozen, and its query patterns and
  confirmed actions keep working unchanged. The MCP tools are the only tool
  layer Comicarr grows from here; if chat is rebuilt after 1.0, it calls them.
- Read tools wait on no Foundations seam. `add_series` waits on the Series add
  seam (#1209) and `refresh_series` on the Series refresh seam (#1207). All
  tools wait on the seam guard (#1200).

## 2. Transport

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1245).

- Streamable HTTP in the existing uvicorn process. No stdio, no legacy
  HTTP+SSE endpoint.
- Stateless (`stateless_http=True`). Protocol revisions 2025-11-25 and
  2026-07-28 are both supported, as the SDK negotiates them.
- SDK: `mcp>=2.3,<3`, using `MCPServer`. MIT licensed.
- Mounting: `Route("/mcp", endpoint=<sdk app>)` is added before the SPA mount
  in `app/main.py`. The lifespan enters `session_manager.run()` once at
  startup, whether or not MCP is enabled.
- Middleware: `/mcp` joins `CSRF_EXEMPT_PREFIXES`. The setup gate stays in
  front, so `/mcp` answers 503 until first-run setup completes.
- Origin: the SDK's Host check is off. Comicarr answers 403 to any request
  whose `Origin` header is present and is not Comicarr's own origin.
- Off by default: with `MCP_ENABLED` false, `/mcp` answers 404 before
  authentication. The SPA must not turn that into `index.html`.
- Settings, section `MCP`, read on every request so changes apply live:

  | Key | Type | Default |
  |---|---|---|
  | `MCP_ENABLED` | bool | false |
  | `MCP_WRITE_ENABLED` | bool | false |

  Both appear in Settings under "Agents (MCP)", with the endpoint URL to copy.
- Owed by the build: one test that streams through real uvicorn and the three
  `BaseHTTPMiddleware` layers.

## 3. Authentication

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1246).

- The existing `API_KEY`. No second key, no OAuth.
- Accepted headers: `Authorization: Bearer <key>` and `X-Api-Key: <key>`. A
  small ASGI shim turns the second into the first; the SDK's `TokenVerifier`
  compares with `hmac.compare_digest` against the live key.
- Writes: with `MCP_WRITE_ENABLED` false, write tools are left out of
  `tools/list`, and calling one returns `writes_disabled`.
- Lockout: failed keys count against the login page's per-IP limiter (5
  failures, 300 seconds). A locked-out IP gets 429.
- Rotation: regenerating the API key cuts off every MCP client at once.
  Settings says so beside the regenerate button when MCP is on.
- No MCP-specific rate limit for 1.0. Outbound calls already pass the provider
  rate limiters and the search queue.

## 4. Read tools

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1247).

| Tool | Answers | Calls |
|---|---|---|
| `list_series` | What is in my library, by name, kind and status | `series.service.list_comics` |
| `get_series` | One series: status, location, counts, providers, next and last issue | `series.service.get_comic_detail` |
| `list_issues` | Issues of one series, by status | `series.service.project_issue_collection` |
| `list_wanted` | What is missing, by issue or by series | `series.service.get_wanted`, `get_wanted_by_series` |
| `get_issue_story` | Why an issue is not here yet | `series.issue_story.story_details` |
| `list_activity` | What happened, overall or for one series or issue | `activity.service.get_timeline` |
| `list_in_flight` | What is downloading or processing, and what is stuck | `activity.service.get_in_flight` |
| `list_attention` | What needs the operator | `attention.read` |
| `list_download_history` | What finished or failed | `downloads.service.get_history` |
| `list_download_queue` | The direct-download queue | `downloads.service.get_ddl_queue` |
| `get_weekly_releases` | This week's releases and which are followed | `weekly.service.get_week` |
| `get_system_health` | Indexers, download clients and background jobs | `search.service.get_health`, `system.connections`, the jobs list |
| `find_series` | A series on the metadata providers, before adding it | `search.service.find_comic`, `find_manga` |
| `get_search_run` | Progress and outcome of a search | the search runs service |

- Tools only. No resources or prompts in 1.0.
- Paging: `limit` (default 25, maximum 100) and `offset`. Every list result
  carries `total` and `next_offset`.
- Left out: settings and config, logs and the support bundle, auth, OPDS,
  story arcs and reading lists, built-in AI, import inbox internals.

## 5. Write tools

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1248).

| Tool | Does | Annotations |
|---|---|---|
| `add_series` | Adds a series by provider id and kind, optionally Wanted | open-world |
| `set_issue_status` | Marks one issue Wanted or Skipped | idempotent |
| `search_issue` | Searches for one Wanted issue | open-world |
| `search_missing` | Searches for every Wanted issue of one series | open-world |
| `refresh_series` | Refreshes a series' metadata | idempotent |
| `pause_series` | Stops automatic searching for a series | idempotent |
| `resume_series` | Restarts automatic searching for a series | idempotent |
| `retry_search_run` | Retries a failed search run | open-world |
| `retry_post_processing` | Retries post-processing of one download by `release_key` | |
| `resolve_attention` | Resolves a needs-attention item | destructive |
| `cancel_in_flight` | Cancels a queued or running download or search | destructive |

- Never exposed: deleting a series or files, clearing history, settings and
  provider writes, API key regeneration, shutdown and restart, migration,
  acquisition repair and canaries, post-processing an arbitrary folder,
  metadata tagging, import confirmation, story arcs, built-in AI.
- Confirmation is the MCP client's own approval prompt. Inside the tool,
  searches use the existing preview and confirm ledger in one call, and
  status changes re-read live state.
- Attribution: every write passes `audit_identity="mcp"`, and its Activity
  rows show "via MCP" through the existing `activity` event.
- Long-running work returns at once with `run_id` or the series id. No
  progress notifications in 1.0.
- In code: `ComicarrMCPServer.write_tool` in `comicarr/app/mcp/server.py`
  registers a write. While `MCP_WRITE_ENABLED` is off, write tools are left
  out of `tools/list` and a direct call returns `writes_disabled`; the switch
  is read on every request. Attribution is the `actor` column on
  `activity_events` (migration `0017_activity_actor`), which the timeline
  shows as "via MCP". Status writes record a `status_change` row only when
  the status actually changed. Search writes call
  `series.service.search_wanted_issue_now` and `search_all_missing_now`, which
  run the browser's preview and confirm ledger in one call with a session id
  minted per call. A search an agent starts writes a `search.started` run row
  with `actor`; Comicarr's own sweeps still narrate only the closing row.
  `acquisition.maintenance.acquisition_paused` is the maintenance check.
  `add_series` takes `provider` (`comicvine`, `metron`, `mangadex`,
  `myanimelist`), `provider_id` and `kind`, the shape `find_series` returns,
  and calls `search.service.add_series_from_provider`. Its `want` flag rides on
  the queued add, and the mass-add worker marks the series' issues and annuals
  Wanted right after the add (`importer.markSeriesWanted`). A row left by a
  failed metadata fetch does not count as already in the library, so a later
  `add_series` retries it. `add_series` and `refresh_series` write `add.started` and
  `refresh.started` series rows with `actor`.
- Writes that would start acquisition during maintenance return
  `maintenance`; `retry_post_processing` returns `busy` when the processing
  lock is held.

## 6. Tool contract

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1249).

- Names: `verb_noun`, snake_case, no prefix. Verbs: `list`, `get`, `find`,
  `add`, `set`, `search`, `refresh`, `retry`, `resolve`, `cancel`, `pause`,
  `resume`. A new verb changes this list first.
- Shape: Pydantic input and output models, a published `outputSchema`,
  `structuredContent` plus a one-line text summary, a `title`, and truthful
  annotations.
- Identifiers: strings, Comicarr's own (`series_id`, `issue_id`, `run_id`,
  `release_key`). Write tools never accept names in place of ids.
- Errors: malformed calls are protocol errors. Everything else is
  `isError: true` with `{code, message, retryable}`, where `code` is one of
  `not_found`, `invalid_argument`, `writes_disabled`, `stale_preview`, `busy`,
  `provider_unavailable`, `maintenance`, `internal`.
- Breaking changes go through [ADR-0006](../adr/0006-deprecation-policy.md):
  the old name stays as an alias marked deprecated, a registry entry is added,
  and `in_use()` is true when the name was called in the last 30 days. A small
  table records the last call per tool name, written at most hourly per name.
  Additive changes are free.
- Check: `tests/contract/mcp_tools.json` snapshots `tools/list`. Any diff
  fails until the snapshot is updated in the same pull request, and a name
  that disappears without a registry entry fails outright. The snapshot is the
  MCP part of the milestone 5 contract.
- In code: `comicarr/app/mcp/contracts.py` holds `VERBS`, the error codes,
  `Limit`/`Offset`, the `Paged` output base, `tool_result()`, `tool_error()`
  and `ContractError`. `ComicarrMCPServer` turns rejected arguments into
  `invalid_argument` and any unexpected exception into `internal`.
  `tests/unit/test_mcp_contract.py` holds the snapshot and name checks;
  regenerate the snapshot with
  `UPDATE_MCP_SNAPSHOT=1 pytest tests/unit/test_mcp_contract.py`.
  `tests/integration/test_mcp_eras.py` drives every tool once per protocol
  era, and a new tool adds its sample call to `CALLS` there.

## 7. Clients

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1250).

| Client | Status |
|---|---|
| Claude Code | tested |
| VS Code (GitHub Copilot) | tested |
| Cursor | documented, best-effort |
| Codex CLI | documented, best-effort |
| Claude web and Desktop connectors | documented note: needs public HTTPS |

- Every pull request: an integration test boots the app and drives `/mcp`
  with the SDK's client, once per protocol era. It covers each read tool,
  writes off and on, 404 when disabled, 401 on a bad key and 403 on a foreign
  Origin.
- Each release candidate: a manual check with Claude Code and VS Code on the
  RC image, recorded like the Clean slate integration check.
- Operator docs: a "Connect an agent (MCP)" page on comicarr.com with one
  snippet per client, a short section in `docs/operator-guide.md`, and a link
  from the Settings group.
