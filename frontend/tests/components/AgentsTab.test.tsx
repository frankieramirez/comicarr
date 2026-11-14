import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import SettingsPage from "@/pages/SettingsPage";
import { mcpEndpointUrl } from "@/lib/mcp";

afterEach(() => {
  vi.unstubAllGlobals();
});

function serveConfig(config: Record<string, unknown>) {
  let saved: Record<string, unknown> | null = null;
  server.use(
    http.get("/api/config", () =>
      HttpResponse.json({ comicvine_enabled: true, ...config }),
    ),
    http.put("/api/config", async ({ request }) => {
      saved = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ success: true });
    }),
  );
  return () => saved;
}

describe("mcpEndpointUrl", () => {
  it.each([
    ["http://nas:8090", undefined, "http://nas:8090/mcp"],
    ["http://nas:8090", "/", "http://nas:8090/mcp"],
    ["https://home.example", "/comicarr", "https://home.example/comicarr/mcp"],
    ["https://home.example/", "comicarr/", "https://home.example/comicarr/mcp"],
  ])("%s with root %s is %s", (origin, root, expected) => {
    expect(mcpEndpointUrl(origin, root)).toBe(expected);
  });
});

describe("Agents (MCP) settings", () => {
  it("saves Enable MCP server and keeps writes disabled while MCP is off", async () => {
    const saved = serveConfig({ mcp_enabled: false, mcp_write_enabled: false });
    const user = userEvent.setup();

    render(<SettingsPage />, {
      useMemoryRouter: true,
      route: "/settings?section=agents",
    });

    const enable = (await screen.findByLabelText(
      /Enable MCP server/,
    )) as HTMLInputElement;
    const writes = screen.getByLabelText(
      /Allow write tools/,
    ) as HTMLInputElement;
    expect(enable.checked).toBe(false);
    expect(writes.disabled).toBe(true);

    await user.click(enable);
    expect(writes.disabled).toBe(false);
    await user.click(writes);

    await user.click(screen.getByRole("button", { name: "Save Changes" }));
    await waitFor(() => expect(saved()).not.toBeNull());
    expect(saved()).toMatchObject({
      mcp_enabled: true,
      mcp_write_enabled: true,
    });
    expect(screen.queryByRole("button", { name: /restart/i })).toBeNull();
  });

  it("shows the endpoint on this origin and copies it", async () => {
    serveConfig({ mcp_enabled: true });
    // userEvent.setup() installs its own clipboard, so stub after it.
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<SettingsPage />, {
      useMemoryRouter: true,
      route: "/settings?section=agents",
    });

    const expected = `${window.location.origin}/mcp`;
    expect(await screen.findByDisplayValue(expected)).toBeTruthy();
    expect(screen.getByText(/Authorization: Bearer/)).toBeTruthy();
    expect(screen.getByText(/X-Api-Key/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Copy MCP endpoint" }));
    expect(writeText).toHaveBeenCalledWith(expected);
    expect(await screen.findByText("MCP endpoint copied")).toBeTruthy();
  });

  it.each([
    [true, true],
    [false, false],
  ])(
    "with MCP enabled=%s, the rotation note beside regenerate shows=%s",
    async (mcpEnabled, noteShown) => {
      serveConfig({ mcp_enabled: mcpEnabled, api_key_set: true });

      render(<SettingsPage />, {
        useMemoryRouter: true,
        route: "/settings?section=api",
      });

      await screen.findByTitle("Regenerate API key");
      expect(Boolean(screen.queryByTestId("mcp-rotation-note"))).toBe(
        noteShown,
      );
    },
  );
});
