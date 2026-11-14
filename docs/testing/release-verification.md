# Release verification

Checks to run by hand on each release candidate, on top of CI. Record the
result of each check in the release candidate's PR or tracking issue, with the
RC image tag, the client versions and pass or fail, the same way the Clean
slate integration check records each download client.

## MCP clients

Section 7 of [the MCP server design](../architecture/mcp-server.md) commits to
Claude Code and VS Code (GitHub Copilot) being tested with every release.
Cursor and Codex CLI are best effort and need no check.

1. Start the RC image with a seeded library and finish first-run setup.
2. In **Settings → System → Agents (MCP)**, turn on **Enable MCP server** and
   **Allow write tools**, and copy the endpoint and the API key.
3. For each of Claude Code and VS Code, connect with the snippet from
   [Connect an agent (MCP)](https://comicarr.com/docs/api/mcp), then:
   - list the tools, and check that the write tools appear;
   - call one read tool, such as `list_series`, and check its answer matches
     the library;
   - call one write tool, such as `pause_series` then `resume_series` on one
     series, approve it in the client, and check that **Activity** shows the
     change with **via MCP**.
4. Turn **Allow write tools** off and check that the client no longer lists
   the write tools after refreshing them.

Record, for example:

```text
MCP client check, comicarr:0.53.0-rc.1
- Claude Code 2.x: tools listed, list_series ok, pause/resume ok, via MCP shown: pass
- VS Code 1.x + Copilot: tools listed, list_series ok, pause/resume ok, via MCP shown: pass
```

A client the check records as broken gets a regression test in
`tests/integration/test_mcp_eras.py` before it is fixed.
