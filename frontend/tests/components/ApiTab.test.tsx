import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import { ApiTab } from "@/components/settings/ApiTab";
import { useConfig } from "@/hooks/useConfig";

/**
 * Mirrors how SettingsPage wires ApiTab: `config` comes from the useConfig
 * query, `formData` is separate local form state. ApiTab is rendered in
 * isolation elsewhere, but the API key specifically flows through the query
 * cache, so it can only be exercised through this wiring.
 */
function ApiTabHarness({
  formData = {},
  onChange = vi.fn(),
}: {
  formData?: Record<string, unknown>;
  onChange?: (key: string, value: string | boolean) => void;
}) {
  const { data: config } = useConfig();
  return (
    <ApiTab
      config={(config ?? {}) as Record<string, unknown>}
      formData={formData}
      onChange={onChange}
    />
  );
}

describe("ApiTab", () => {
  it("regenerates through the dedicated endpoint and copies the returned key", async () => {
    const oldApiKey = "a".repeat(32);
    const newApiKey = "b".repeat(32);
    const onChange = vi.fn();
    const confirm = vi.fn(() => true);
    const writeText = vi.fn().mockResolvedValue(undefined);
    let regenerateCalls = 0;
    let genericConfigCalls = 0;

    // Stateful so the refetch triggered by invalidation returns the rotated key,
    // as the real server would — otherwise a reverting cache would go unnoticed.
    let currentApiKey = oldApiKey;

    vi.stubGlobal("confirm", confirm);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({ api_key: currentApiKey, comicvine_enabled: false }),
      ),
      http.post("/api/config/api-key/regenerate", () => {
        regenerateCalls += 1;
        currentApiKey = newApiKey;
        return HttpResponse.json({ success: true, api_key: newApiKey });
      }),
      http.put("/api/config", () => {
        genericConfigCalls += 1;
        return HttpResponse.json({ success: true });
      }),
    );

    render(<ApiTabHarness onChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue(oldApiKey)).toBeTruthy();
    });

    await userEvent.click(screen.getByTitle("Regenerate API key"));

    await waitFor(() => {
      expect(regenerateCalls).toBe(1);
      expect(screen.getByDisplayValue(newApiKey)).toBeTruthy();
    });

    expect(confirm).toHaveBeenCalledOnce();
    // Rotation must not round-trip through the generic config write, which
    // rejects API_KEY as non-writable.
    expect(genericConfigCalls).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("API key regenerated.")).toBeTruthy();

    await userEvent.click(screen.getByTitle("Copy to clipboard"));

    expect(writeText).toHaveBeenCalledWith(newApiKey);
  });

  it("shows the server key and ignores any api_key in form state", async () => {
    const serverApiKey = "c".repeat(32);

    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({ api_key: serverApiKey, comicvine_enabled: false }),
      ),
    );

    render(<ApiTabHarness formData={{ api_key: "stale-form-value" }} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue(serverApiKey)).toBeTruthy();
    });
    expect(screen.queryByDisplayValue("stale-form-value")).toBeNull();
  });

  it("surfaces an error and keeps the existing key when regeneration fails", async () => {
    const oldApiKey = "d".repeat(32);
    const confirm = vi.fn(() => true);

    vi.stubGlobal("confirm", confirm);

    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({ api_key: oldApiKey, comicvine_enabled: false }),
      ),
      http.post("/api/config/api-key/regenerate", () =>
        HttpResponse.json(
          { success: false, error: "Failed to persist new API key" },
          { status: 500 },
        ),
      ),
    );

    render(<ApiTabHarness />);

    await waitFor(() => {
      expect(screen.getByDisplayValue(oldApiKey)).toBeTruthy();
    });

    await userEvent.click(screen.getByTitle("Regenerate API key"));

    await waitFor(() => {
      expect(screen.getByText("Failed to regenerate API key")).toBeTruthy();
    });
    expect(screen.getByDisplayValue(oldApiKey)).toBeTruthy();
  });
});
