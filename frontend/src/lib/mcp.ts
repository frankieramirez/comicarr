/**
 * MCP endpoint helpers for the Settings "Agents (MCP)" group. Pure; no React.
 *
 * The server mounts the endpoint at `/mcp` (docs/architecture/mcp-server.md
 * section 2). A reverse proxy that serves Comicarr under `HTTP_ROOT` puts that
 * prefix in front of it, the same way OPDS links are built.
 */

/** The "Connect an agent (MCP)" page on comicarr.com. */
export const MCP_DOCS_URL: string | null = "https://comicarr.com/docs/api/mcp";

/** The URL an MCP client connects to: origin, then `HTTP_ROOT`, then `/mcp`. */
export function mcpEndpointUrl(
  origin: string,
  httpRoot?: string | null,
): string {
  const root = (httpRoot ?? "").trim().replace(/^\/+|\/+$/g, "");
  return `${origin.replace(/\/+$/, "")}${root ? `/${root}` : ""}/mcp`;
}
