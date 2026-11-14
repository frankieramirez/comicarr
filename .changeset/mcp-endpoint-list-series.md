---
"comicarr": minor
---

Comicarr can now serve AI agents over MCP at `/mcp`. It is off by default: set `mcp_enabled = True` in the `[MCP]` section of `config.ini` to turn it on. Agents sign in with your existing API key, sent as `Authorization: Bearer <key>` or `X-Api-Key`, and five wrong keys lock that address out for five minutes, as on the login page. This first version has one read-only tool, `list_series`, which lists your library by name, kind and status.
