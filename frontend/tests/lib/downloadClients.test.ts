import { describe, expect, it } from "vitest";
import {
  clientCards,
  formatRootRoutes,
  hostKey,
  parseRootRoutes,
} from "@/lib/downloadClients";
import type { SettingsFormData } from "@/types/config.generated";

const values = (v: Record<string, unknown>) => v as unknown as SettingsFormData;

describe("downloadClients", () => {
  it("round-trips qBittorrent root routes", () => {
    const text = "/data/comics | comics | /dl/comics\n/data/manga | manga";
    const routes = parseRootRoutes(text);
    expect(routes).toEqual([
      { root: "/data/comics", category: "comics", savePath: "/dl/comics" },
      { root: "/data/manga", category: "manga", savePath: "" },
    ]);
    expect(formatRootRoutes(routes)).toBe(text);
    expect(formatRootRoutes([{ root: "", category: "", savePath: "" }])).toBe(
      "",
    );
  });

  it("keeps a switched-off usenet client whose server is still set", () => {
    const cards = clientCards(
      values({ nzb_downloader: 3, sab_host: "http://sab:8080" }),
    );
    expect(cards).toEqual([
      { client: expect.objectContaining({ id: "sabnzbd" }), enabled: false },
    ]);
  });

  it("orders usenet, torrent, then direct downloads", () => {
    const cards = clientCards(
      values({
        nzb_downloader: 1,
        enable_torrents: true,
        torrent_downloader: 5,
        enable_ddl: true,
      }),
    );
    expect(cards.map((card) => card.client.id)).toEqual([
      "nzbget",
      "qbittorrent",
      "ddl",
    ]);
    expect(cards.every((card) => card.enabled)).toBe(true);
  });

  it("shows an added kind before it is switched on", () => {
    const cards = clientCards(values({}), new Set(["ddl"]));
    expect(cards).toEqual([
      { client: expect.objectContaining({ id: "ddl" }), enabled: false },
    ]);
  });

  it("compares servers by scheme, host and port", () => {
    expect(hostKey("qbit:8080")).toBe(hostKey("http://QBIT:8080/"));
    expect(hostKey("http://qbit")).toBe(hostKey("http://qbit:80"));
    expect(hostKey("https://qbit")).not.toBe(hostKey("http://qbit"));
    expect(hostKey("  ")).toBeNull();
  });
});
