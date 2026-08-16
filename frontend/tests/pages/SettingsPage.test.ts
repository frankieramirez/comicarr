import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import { prepareConfigSaveData } from "@/lib/configSave";
import { formatAppVersion } from "@/lib/version";
import SettingsPage from "@/pages/SettingsPage";
import { settingsPanelClassName } from "@/lib/settingsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("settings configuration", () => {
  it("widens the Logs panel and keeps other tabs in a readable column", () => {
    expect(settingsPanelClassName("logs")).toContain("max-w-none");
    expect(settingsPanelClassName("logs")).not.toContain("max-w-4xl");
    expect(settingsPanelClassName("general")).toContain("max-w-4xl");
    expect(settingsPanelClassName("clients")).toContain("max-w-4xl");
  });

  it.each([
    ["disabled client with empty host", 3, ""],
    ["non-SAB client with legacy-invalid host", 1, "sab host without scheme"],
  ])(
    "saves unrelated settings for %s without validating SAB URL",
    async (_description, nzbDownloader, sabHost) => {
      let saved: unknown = null;
      server.use(
        http.get("/api/config", () =>
          HttpResponse.json({
            nzb_downloader: nzbDownloader,
            sab_host: sabHost,
            comicvine_enabled: true,
            mangadex_enabled: true,
          }),
        ),
        http.put("/api/config", async ({ request }) => {
          saved = await request.json();
          return HttpResponse.json({ success: true });
        }),
      );
      const user = userEvent.setup();

      render(createElement(SettingsPage));
      await screen.findByText("Settings");
      const comics = await screen.findByText("Comics (Comic Vine)");
      await user.click(comics);
      await user.click(screen.getByRole("button", { name: "Save Changes" }));

      await waitFor(() => expect(saved).not.toBeNull());
      expect(saved).toMatchObject({ comicvine_enabled: false });
    },
  );

  it("omits blank redacted secrets and raw API key values from saves", () => {
    const saveData = prepareConfigSaveData(
      {
        api_key: "do-not-send",
        ai_api_key: "",
        comicvine_api: "",
        mal_client_id: "",
        prowl_keys: "",
        slack_webhook_url: "",
        mattermost_webhook_url: "",
        discord_webhook_url: "",
        sab_apikey: "",
        comic_dir: "/comics",
      },
      {
        ai_api_key_set: true,
        comicvine_api_set: true,
        mal_client_id_set: true,
        prowl_keys_set: true,
        slack_webhook_url_set: true,
        mattermost_webhook_url_set: true,
        discord_webhook_url_set: true,
        sab_apikey_set: true,
      },
    );

    expect(saveData).toEqual({ comic_dir: "/comics" });
  });

  it("edits SABnzbd configuration from Download clients", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          nzb_downloader: 0,
          nzb_downloader_label: "SABnzbd",
          sab_host: "http://sabnzbd:8080",
          sab_category: "comics",
          sab_directory: "/downloads",
          sab_verify: false,
          sab_apikey_set: true,
        }),
      ),
      http.put("/api/config", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(
      screen.getAllByRole("button", { name: "Download clients" })[0],
    );

    const host = await screen.findByLabelText("SABnzbd URL");
    expect(
      screen.getByLabelText("SABnzbd API key").getAttribute("placeholder"),
    ).toBe("API key saved (enter a new value to change)");
    await user.clear(host);
    await user.type(host, "http://sab:8080");
    await user.type(
      screen.getByLabelText("SABnzbd API key"),
      "replacement-key",
    );
    await user.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({ sab_host: "http://sab:8080" });
    expect(saved).toMatchObject({ sab_apikey: "replacement-key" });
  });

  it("edits Newznab indexers without exposing stored API keys", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 101,
                name: "Indexer",
                host: "https://indexer.test",
                verify: true,
                categories: "5030",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
      http.put("/api/config/providers", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);

    const name = await screen.findByLabelText("Indexer name");
    expect(
      screen.getByLabelText("Indexer API key").getAttribute("placeholder"),
    ).toBe("API key saved (enter a new value to change)");
    await user.clear(name);
    await user.type(name, "My indexer");
    expect(screen.getByText("Unsaved indexer changes")).toBeTruthy();
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    await user.click(screen.getAllByRole("button", { name: "General" })[0]);
    expect(confirm).toHaveBeenCalledWith("Discard unsaved indexer changes?");
    expect(screen.getByLabelText("Indexer name")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save indexers" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({
      type: "newznab",
      enabled: true,
      providers: [
        expect.objectContaining({
          id: 101,
          name: "My indexer",
          api_key: "",
          api_key_set: true,
        }),
      ],
    });
  });

  it("keeps saved and newly added indexer field IDs unique", async () => {
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 1,
                name: "Saved indexer",
                host: "https://indexer.test",
                verify: true,
                categories: "5030",
                enabled: true,
                api_key_set: false,
              },
            ],
          },
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    await screen.findByLabelText("Indexer name");
    await user.click(screen.getByRole("button", { name: "Add indexer" }));

    const names = screen.getAllByLabelText("Indexer name");
    expect(names.map((input) => input.id)).toEqual([
      "indexer-name-saved-1",
      "indexer-name-new-1",
    ]);
    expect(names.map((input) => input.id)).toHaveLength(
      new Set(names.map((input) => input.id)).size,
    );
    expect(names.map((input) => input.id)).toEqual(
      names.map(
        (input) => input.closest("div")?.querySelector("label")?.htmlFor,
      ),
    );
  });

  it("edits Newznab categories and the RSS user ID as separate fields", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 101,
                name: "Indexer",
                host: "https://indexer.test",
                verify: true,
                // Server-side split of the stored `42#7030` field. The uid
                // used to be folded into the Categories box, where editing
                // categories quietly rewrote it.
                categories: "7030",
                rss_uid: "42",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
      http.put("/api/config/providers", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);

    const categories = await screen.findByLabelText("Categories");
    expect((categories as HTMLInputElement).value).toBe("7030");
    expect(
      (screen.getByLabelText("RSS user ID") as HTMLInputElement).value,
    ).toBe("42");

    await user.clear(categories);
    await user.type(categories, "7030,7020");
    await user.click(screen.getByRole("button", { name: "Save indexers" }));

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({
      type: "newznab",
      providers: [
        expect.objectContaining({ categories: "7030,7020", rss_uid: "42" }),
      ],
    });
  });

  it("requires a replacement indexer key when its server changes", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 101,
                name: "Indexer",
                host: "https://indexer.test/api",
                verify: true,
                categories: "5030",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
      http.put("/api/config/providers", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    const host = await screen.findByLabelText("Indexer URL");
    await user.clear(host);
    await user.type(host, "https://other.test/api");
    await user.click(screen.getByRole("button", { name: "Save indexers" }));

    expect(
      await screen.findByText(
        "Enter the API key again when changing an indexer server.",
      ),
    ).toBeTruthy();
    expect(saved).toBeNull();
  });

  it("adds a Torznab indexer when both provider lists start empty", async () => {
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: { enabled: false, providers: [] },
          torznab: { enabled: false, providers: [] },
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    await screen.findByRole("button", { name: "Add Torznab indexer" });
    await user.click(
      screen.getByRole("button", { name: "Add Torznab indexer" }),
    );

    expect(await screen.findByLabelText("Torznab indexer name")).toBeTruthy();
    expect(screen.queryByLabelText("RSS user ID")).toBeNull();
    expect(screen.getByText("Unsaved Torznab indexer changes")).toBeTruthy();
  });

  it("edits Torznab indexers without an RSS user ID field", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: { enabled: false, providers: [] },
          torznab: {
            enabled: true,
            providers: [
              {
                id: 202,
                name: "Prowlarr",
                host: "https://prowlarr.test/1/api",
                verify: true,
                categories: "7030",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
      http.put("/api/config/providers", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);

    const name = await screen.findByLabelText("Torznab indexer name");
    expect(screen.queryByLabelText("RSS user ID")).toBeNull();
    expect(
      screen
        .getByLabelText("Torznab indexer API key")
        .getAttribute("placeholder"),
    ).toBe("API key saved (enter a new value to change)");
    await user.clear(name);
    await user.type(name, "My tracker");
    expect(screen.getByText("Unsaved Torznab indexer changes")).toBeTruthy();
    await user.click(
      screen.getByRole("button", { name: "Save Torznab indexers" }),
    );

    await waitFor(() => expect(saved).not.toBeNull());
    expect(saved).toMatchObject({
      type: "torznab",
      enabled: true,
      providers: [
        expect.objectContaining({
          id: 202,
          name: "My tracker",
          api_key: "",
          api_key_set: true,
        }),
      ],
    });
    expect(
      (saved as { providers: Array<Record<string, unknown>> }).providers[0],
    ).not.toHaveProperty("rss_uid");
  });

  it("requires a replacement Torznab key when its server changes", async () => {
    let saved: unknown = null;
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: { enabled: false, providers: [] },
          torznab: {
            enabled: true,
            providers: [
              {
                id: 202,
                name: "Prowlarr",
                host: "https://prowlarr.test/1/api",
                verify: true,
                categories: "7030",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
      http.put("/api/config/providers", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    const host = await screen.findByLabelText("Torznab indexer URL");
    await user.clear(host);
    await user.type(host, "https://other.test/1/api");
    await user.click(
      screen.getByRole("button", { name: "Save Torznab indexers" }),
    );

    expect(
      await screen.findByText(
        "Enter the API key again when changing an indexer server.",
      ),
    ).toBeTruthy();
    expect(saved).toBeNull();
  });

  it("keeps Newznab and Torznab field IDs unique when both have the same saved id", async () => {
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 1,
                name: "Usenet",
                host: "https://usenet.test",
                verify: true,
                categories: "7030",
                enabled: true,
                api_key_set: false,
              },
            ],
          },
          torznab: {
            enabled: true,
            providers: [
              {
                id: 1,
                name: "Prowlarr",
                host: "https://prowlarr.test",
                verify: true,
                categories: "7030",
                enabled: true,
                api_key_set: false,
              },
            ],
          },
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    await screen.findByLabelText("Indexer name");

    const newznabName = screen.getByLabelText("Indexer name");
    const torznabName = screen.getByLabelText("Torznab indexer name");
    expect(newznabName.id).toBe("indexer-name-saved-1");
    expect(torznabName.id).toBe("torznab-indexer-name-saved-1");
    expect(newznabName.id).not.toBe(torznabName.id);
  });

  it("blocks dirty Torznab edits on section change when confirmation is declined", async () => {
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: { enabled: false, providers: [] },
          torznab: {
            enabled: true,
            providers: [
              {
                id: 202,
                name: "Prowlarr",
                host: "https://prowlarr.test/1/api",
                verify: true,
                categories: "7030",
                enabled: true,
                api_key_set: true,
              },
            ],
          },
        }),
      ),
    );
    const user = userEvent.setup();
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);

    render(createElement(SettingsPage));
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    const name = await screen.findByLabelText("Torznab indexer name");
    await user.type(name, " changed");
    await user.click(screen.getAllByRole("button", { name: "General" })[0]);

    expect(confirm).toHaveBeenCalledWith("Discard unsaved indexer changes?");
    expect(screen.getByLabelText("Torznab indexer name")).toBeTruthy();
  });

  it("keeps explicit replacement secret values", () => {
    const saveData = prepareConfigSaveData(
      {
        api_key: "do-not-send",
        comicvine_api: "x".repeat(40),
        discord_webhook_url: "https://discord.com/api/webhooks/new",
      },
      {
        comicvine_api_set: true,
        discord_webhook_url_set: true,
      },
    );

    expect(saveData).toEqual({
      comicvine_api: "x".repeat(40),
      discord_webhook_url: "https://discord.com/api/webhooks/new",
    });
  });

  it("sends only settings that changed", () => {
    expect(
      prepareConfigSaveData(
        { sab_host: "https://sab.test:8080", comic_dir: "/new-comics" },
        { sab_host: "https://sab.test:8080", comic_dir: "/comics" },
      ),
    ).toEqual({ comic_dir: "/new-comics" });
  });
});

describe("SettingsPage", () => {
  it("opens the acquisition operator surface from Settings", async () => {
    server.use(
      http.get("/api/search/health", () =>
        HttpResponse.json({
          viable_route: true,
          maintenance: { blocked: false, drained: true, active_leases: 0 },
          routes: {},
          workers: {},
          acquisition: {},
        }),
      ),
      http.get("/api/system/diagnostics", () =>
        HttpResponse.json({
          build: { id: "test-build", commit: "abc1234", verified: true },
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));

    expect(await screen.findByText("Settings")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "Acquisition" })[0]);

    expect(await screen.findByText("Acquisition health")).toBeTruthy();
    expect(screen.getByText("Evidence-driven repair")).toBeTruthy();
  });

  it("blocks dirty indexer edits on internal SPA links when confirmation is declined", async () => {
    server.use(
      http.get("/api/config/providers", () =>
        HttpResponse.json({
          newznab: {
            enabled: true,
            providers: [
              {
                id: 1,
                name: "Indexer",
                host: "https://indexer.test",
                verify: true,
                categories: "5030",
                enabled: true,
                api_key_set: false,
              },
            ],
          },
        }),
      ),
    );
    const user = userEvent.setup();
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);

    render(
      createElement(
        "div",
        null,
        createElement("a", { href: "/library" }, "Library preview link"),
        createElement(SettingsPage),
      ),
    );
    await screen.findByText("Settings");
    await user.click(screen.getAllByRole("button", { name: "Search" })[0]);
    const name = await screen.findByLabelText("Indexer name");
    await user.type(name, " changed");
    await user.click(
      screen.getByRole("link", { name: "Library preview link" }),
    );

    expect(confirm).toHaveBeenCalledWith("Discard unsaved indexer changes?");
    expect(screen.getByLabelText("Indexer name")).toBeTruthy();
  });
  it("shows the package release version even when the API reports a different one", async () => {
    // Regression for #412: Settings/About must not echo backend config.version
    // when that field is a git SHA or stale install metadata.
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          version: "0.19.13",
          config_path: "/config/config.ini",
          data_dir: "/data",
          python_version: "3.12.0",
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));

    expect(
      await screen.findByText(`comicarr ${formatAppVersion()}`, {
        exact: false,
      }),
    ).toBeTruthy();
    expect(screen.queryByText(/0\.19\.13/)).toBeNull();

    await user.click(screen.getAllByRole("button", { name: "About" })[0]);
    expect(await screen.findByText(formatAppVersion(false))).toBeTruthy();
    expect(screen.queryByText("0.19.13")).toBeNull();
  });

  it("shows the Updates group with toggles, diagnostics, and Check now", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          check_github: true,
          announce_releases: false,
          config_path: "/config/config.ini",
          data_dir: "/data",
          python_version: "3.12.0",
        }),
      ),
      http.get("/api/system/version", () =>
        HttpResponse.json({
          release_version: "0.21.0",
          latest_version: "0.22.0",
          update_state: "behind",
          update_reason: null,
          pending_whats_new: null,
        }),
      ),
      http.get("/api/system/whats-new/archive", () =>
        HttpResponse.json({
          sections: [{ version: "0.21.0", bullets: ["notes"] }],
          pending: null,
          current: "0.21.0",
          last_seen: "0.21.0",
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    expect(await screen.findByText("Settings")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "About" })[0]);

    expect(await screen.findByText("Updates")).toBeTruthy();
    expect(screen.getByText("Check for updates")).toBeTruthy();
    expect(screen.getByText("Announce releases to notifiers")).toBeTruthy();
    expect(
      await screen.findByText("Update available: 0.21.0 → 0.22.0"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check now" })).toBeTruthy();
    // Order: Updates → What's new → Support bundle → Build / environment.
    const updates = screen.getByText("Updates");
    // SettingGroup title (exact); archive no longer duplicates an h2.
    const whatsNew = screen.getByText("What's new");
    expect(await screen.findByTestId("whats-new-archive-summary")).toBeTruthy();
    const supportBundle = screen.getByText("Support bundle");
    const build = screen.getByText("Build / environment");
    expect(
      updates.compareDocumentPosition(whatsNew) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      whatsNew.compareDocumentPosition(supportBundle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      supportBundle.compareDocumentPosition(build) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Create support bundle" }),
    ).toBeTruthy();
    // AUTO_UPDATE must not appear.
    expect(screen.queryByText(/auto.?update/i)).toBeNull();
    // No GitHub/git wording in the operator-facing labels/help in this group.
    expect(screen.queryByText(/GitHub/i)).toBeNull();
  });

  it("shows unknown update reason in operator language", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          check_github: false,
          announce_releases: false,
        }),
      ),
      http.get("/api/system/version", () =>
        HttpResponse.json({
          update_state: "unknown",
          update_reason: "unreachable",
        }),
      ),
    );
    const user = userEvent.setup();

    render(createElement(SettingsPage));
    expect(await screen.findByText("Settings")).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "About" })[0]);

    expect(
      await screen.findByText("Could not reach the release source"),
    ).toBeTruthy();
  });
});
