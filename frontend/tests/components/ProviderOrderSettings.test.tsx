import { createElement } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, within } from "../test-utils";
import { ProviderOrderSettings } from "@/components/settings/ProviderOrderSettings";

const PROVIDERS = [
  { name: "NZBgeek", kind: "newznab", route: "nzb" },
  { name: "DrunkenSlug", kind: "newznab", route: "nzb" },
  { name: "Prowlarr", kind: "torznab", route: "torrent" },
];

function rowNames() {
  const list = screen.getByRole("list", { name: "Search order" });
  return within(list)
    .getAllByRole("listitem")
    .map((item) => item.textContent ?? "");
}

describe("Search order settings", () => {
  it("shows the enabled providers in the order search uses them", async () => {
    server.use(
      http.get("/api/config/provider-order", () =>
        HttpResponse.json({ providers: PROVIDERS }),
      ),
    );

    render(createElement(ProviderOrderSettings));

    await screen.findByRole("list", { name: "Search order" });
    expect(rowNames()).toEqual([
      "1NZBgeekUsenet",
      "2DrunkenSlugUsenet",
      "3ProwlarrTorrent",
    ]);
    expect(
      (
        screen.getByRole("button", {
          name: "Move NZBgeek up",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Save order" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("reorders and saves the full list of names", async () => {
    let body: unknown;
    server.use(
      http.get("/api/config/provider-order", () =>
        HttpResponse.json({ providers: PROVIDERS }),
      ),
      http.put("/api/config/provider-order", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          success: true,
          providers: [PROVIDERS[1], PROVIDERS[0], PROVIDERS[2]],
        });
      }),
    );
    const user = userEvent.setup();
    render(createElement(ProviderOrderSettings));

    await user.click(
      await screen.findByRole("button", { name: "Move DrunkenSlug up" }),
    );
    expect(rowNames()[0]).toBe("1DrunkenSlugUsenet");
    expect(screen.getByText("Unsaved order changes")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Save order" }));

    expect(await screen.findByText("Search order saved")).toBeTruthy();
    expect(body).toEqual({ order: ["DrunkenSlug", "NZBgeek", "Prowlarr"] });
    expect(screen.queryByText("Unsaved order changes")).toBeNull();
  });

  it("puts the saved order back on reset", async () => {
    server.use(
      http.get("/api/config/provider-order", () =>
        HttpResponse.json({ providers: PROVIDERS }),
      ),
    );
    const user = userEvent.setup();
    render(createElement(ProviderOrderSettings));

    await user.click(
      await screen.findByRole("button", { name: "Move NZBgeek down" }),
    );
    await user.click(screen.getByRole("button", { name: "Reset order" }));

    expect(rowNames()[0]).toBe("1NZBgeekUsenet");
  });

  it("explains an empty order", async () => {
    render(createElement(ProviderOrderSettings));

    expect(
      await screen.findByText(/No Search providers are enabled yet/),
    ).toBeTruthy();
  });
});
