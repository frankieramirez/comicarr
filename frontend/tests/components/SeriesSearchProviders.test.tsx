import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { SeriesSearchProviders } from "@/components/series/SeriesSearchProviders";

const AVAILABLE = ["DDL(GetComics)", "NZBGeek", "MagIndex"];

function renderProviders(
  props: Partial<Parameters<typeof SeriesSearchProviders>[0]> = {},
) {
  return render(
    <SeriesSearchProviders
      comicId="18692"
      available={AVAILABLE}
      override={null}
      {...props}
    />,
  );
}

function capturePatch() {
  const sent: { body?: unknown } = {};
  server.use(
    http.patch("/api/series/18692/search-providers", async ({ request }) => {
      sent.body = await request.json();
      return HttpResponse.json({
        success: true,
        provider_override: { order: ["MagIndex"], exclude: [] },
      });
    }),
  );
  return sent;
}

describe("SeriesSearchProviders", () => {
  it("shows the global order when the series has no override", () => {
    renderProviders();

    expect(screen.getByText("global order")).toBeTruthy();
    expect(screen.getByTestId("series-providers").textContent).toBe(
      "DDL(GetComics) → NZBGeek → MagIndex",
    );
  });

  it("shows the override order and skipped providers", () => {
    renderProviders({
      override: { order: ["MagIndex", "Gone"], exclude: ["DDL(GetComics)"] },
    });

    expect(screen.getByText("custom")).toBeTruthy();
    expect(screen.getByTestId("series-providers").textContent).toBe(
      "MagIndex → NZBGeek",
    );
    expect(
      screen.getByText("Skips DDL(GetComics) for this series."),
    ).toBeTruthy();
  });

  it("moves a provider to the top and saves only the names that differ from global order", async () => {
    const sent = capturePatch();
    const user = userEvent.setup();
    renderProviders();

    await user.click(screen.getByRole("button", { name: "Change providers" }));
    await user.click(
      await screen.findByRole("button", { name: "Move MagIndex up" }),
    );
    await user.click(screen.getByRole("button", { name: "Move MagIndex up" }));
    await user.click(screen.getByRole("button", { name: "Save providers" }));

    await waitFor(() =>
      expect(sent.body).toEqual({ order: ["MagIndex"], exclude: [] }),
    );
  });

  it("skips an unticked provider", async () => {
    const sent = capturePatch();
    const user = userEvent.setup();
    renderProviders();

    await user.click(screen.getByRole("button", { name: "Change providers" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "DDL(GetComics)" }),
    );
    await user.click(screen.getByRole("button", { name: "Save providers" }));

    await waitFor(() =>
      expect(sent.body).toEqual({ order: [], exclude: ["DDL(GetComics)"] }),
    );
  });

  it("clears the override back to the global order", async () => {
    const sent = capturePatch();
    const user = userEvent.setup();
    renderProviders({ override: { order: ["MagIndex"], exclude: [] } });

    await user.click(screen.getByRole("button", { name: "Change providers" }));
    await user.click(
      await screen.findByRole("button", { name: "Use global order" }),
    );

    await waitFor(() => expect(sent.body).toEqual({ order: [], exclude: [] }));
  });
});
