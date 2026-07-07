import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import { ApiTab } from "@/components/settings/ApiTab";

describe("ApiTab", () => {
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
      <ApiTab
        config={{ api_key: "old-api-key", comicvine_enabled: false }}
        formData={{ api_key: "old-api-key", comicvine_enabled: false }}
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
});
