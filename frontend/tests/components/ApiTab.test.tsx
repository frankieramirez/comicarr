import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import { ApiTab } from "@/components/settings/ApiTab";

function ApiTabHarness({
  config = {},
  formData = {},
  onChange = vi.fn(),
}: {
  config?: Record<string, unknown>;
  formData?: Record<string, unknown>;
  onChange?: (key: string, value: string | boolean) => void;
}) {
  const [regeneratedApiKey, setRegeneratedApiKey] = useState<string | null>(
    null,
  );
  const [showApiTab, setShowApiTab] = useState(true);

  return (
    <div>
      <button type="button" onClick={() => setShowApiTab((shown) => !shown)}>
        Toggle API tab
      </button>
      {showApiTab ? (
        <ApiTab
          config={config}
          formData={formData}
          onChange={onChange}
          regeneratedApiKey={regeneratedApiKey}
          onRegeneratedApiKey={setRegeneratedApiKey}
        />
      ) : (
        <div>Other settings</div>
      )}
    </div>
  );
}

describe("ApiTab", () => {
  it("shows saved state for a redacted Metron password", () => {
    const onChange = vi.fn();

    render(
      <ApiTabHarness
        config={{
          comicvine_enabled: true,
          metron_password_set: true,
        }}
        formData={{
          comicvine_enabled: true,
          metron_password: "",
        }}
        onChange={onChange}
      />,
    );

    expect(
      screen.getByPlaceholderText("Password saved (enter new value to change)"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Metron password is configured. Enter a new value to change it.",
      ),
    ).toBeTruthy();
  });

  it("regenerates through the dedicated endpoint and copies the returned key", async () => {
    const returnedApiKey = "b".repeat(32);
    const onChange = vi.fn();
    const confirm = vi.fn(() => true);
    const writeText = vi.fn().mockResolvedValue(undefined);
    let regenerateCalls = 0;
    let genericConfigCalls = 0;

    vi.stubGlobal("confirm", confirm);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    server.use(
      http.post("/api/config/api-key/regenerate", () => {
        regenerateCalls += 1;
        return HttpResponse.json({ success: true, api_key: returnedApiKey });
      }),
      http.put("/api/config", () => {
        genericConfigCalls += 1;
        return HttpResponse.json({ success: true });
      }),
    );

    render(
      <ApiTabHarness
        config={{ api_key_set: true, comicvine_enabled: false }}
        formData={{ comicvine_enabled: false }}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByTitle("Regenerate API key"));

    await waitFor(() => {
      expect(regenerateCalls).toBe(1);
      expect(screen.getByDisplayValue(returnedApiKey)).toBeTruthy();
    });
    expect(confirm).toHaveBeenCalledOnce();
    expect(genericConfigCalls).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("API key regenerated.")).toBeTruthy();

    await userEvent.click(screen.getByTitle("Copy to clipboard"));

    expect(writeText).toHaveBeenCalledWith(returnedApiKey);
  });

  it("keeps a regenerated key when the API tab remounts", async () => {
    const returnedApiKey = "c".repeat(32);
    const confirm = vi.fn(() => true);
    let resolveRegeneration: (() => void) | null = null;

    vi.stubGlobal("confirm", confirm);

    server.use(
      http.post("/api/config/api-key/regenerate", async () => {
        await new Promise<void>((resolve) => {
          resolveRegeneration = resolve;
        });
        return HttpResponse.json({ success: true, api_key: returnedApiKey });
      }),
    );

    render(
      <ApiTabHarness
        config={{ api_key_set: true, comicvine_enabled: false }}
        formData={{ comicvine_enabled: false }}
      />,
    );

    await userEvent.click(screen.getByTitle("Regenerate API key"));
    await userEvent.click(
      screen.getByRole("button", { name: "Toggle API tab" }),
    );
    expect(screen.getByText("Other settings")).toBeTruthy();

    resolveRegeneration?.();

    await waitFor(() => {
      expect(screen.getByText("API key regenerated.")).toBeTruthy();
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Toggle API tab" }),
    );

    expect(screen.getByDisplayValue(returnedApiKey)).toBeTruthy();
  });
});
