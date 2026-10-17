import { createElement } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { ProwlarrSettings } from "@/components/settings/ProwlarrSettings";
import type {
  ReadableConfig,
  SettingsFormData,
} from "@/types/config.generated";

function renderSettings(
  formData: SettingsFormData,
  config: ReadableConfig = {},
) {
  return render(
    createElement(ProwlarrSettings, {
      config,
      formData,
      onChange: () => {},
    }),
  );
}

describe("Prowlarr settings", () => {
  it("tests the saved key and reports how many torrent indexers answer", async () => {
    let body: unknown;
    server.use(
      http.post("/api/config/prowlarr/test", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          success: true,
          torrent_indexers: 4,
          indexers: 6,
        });
      }),
    );
    const user = userEvent.setup();
    renderSettings(
      { enable_prowlarr: true, prowlarr_host: "http://prowlarr:9696" },
      { prowlarr_apikey_set: true },
    );

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect(
      await screen.findByText(
        "Connected. Prowlarr has 4 enabled torrent indexers.",
      ),
    ).toBeTruthy();
    expect(body).toEqual({
      host: "http://prowlarr:9696",
      api_key: "",
      verify: true,
    });
  });

  it("shows why a test failed", async () => {
    server.use(
      http.post("/api/config/prowlarr/test", () =>
        HttpResponse.json({
          success: false,
          error: "Prowlarr rejected the API key",
        }),
      ),
    );
    const user = userEvent.setup();
    renderSettings({
      prowlarr_host: "http://prowlarr:9696",
      prowlarr_apikey: "wrong",
    });

    await user.click(screen.getByRole("button", { name: /test connection/i }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Prowlarr rejected the API key",
    );
  });

  it("cannot test without a URL and a key", () => {
    renderSettings({ prowlarr_host: "http://prowlarr:9696" });

    expect(
      (
        screen.getByRole("button", {
          name: /test connection/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("warns when torrent search is off", () => {
    renderSettings({ enable_prowlarr: true }, { enable_torrent_search: false });

    expect(screen.getByRole("alert").textContent).toContain(
      "Torrent search is off",
    );
  });
});
