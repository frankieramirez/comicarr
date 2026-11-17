import { afterEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import SearchPage from "@/pages/SearchPage";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";

const SEARCH_VIEW_KEY = "comicarr-search-view";

describe("SearchPage result views", () => {
  afterEach(() => {
    localStorage.removeItem(SEARCH_VIEW_KEY);
  });

  it.each(["4050-12345", "https://metron.cloud/series/99/"])(
    "shows accurate header and footer counts for exact lookup %s",
    async (query) => {
      server.use(
        http.post("/api/search/comics", async ({ request }) => {
          expect(await request.json()).toMatchObject({
            name: query,
            limit: 20,
            offset: 0,
          });
          return HttpResponse.json({
            results: [
              {
                comicid: query.startsWith("4050-") ? "12345" : "metron-99",
                name: "Exact lookup volume",
                comicyear: "2024",
                publisher: "Marvel",
                issues: "4",
              },
            ],
            pagination: { total: 1, limit: 20, offset: 0, returned: 1 },
          });
        }),
      );
      render(<SearchPage />, {
        useMemoryRouter: true,
        route: `/search?q=${encodeURIComponent(query)}&type=comic`,
      });

      expect(await screen.findByText("Exact lookup volume")).toBeTruthy();
      expect(screen.getByText(`1 result for "${query}"`)).toBeTruthy();
      expect(screen.getAllByText("1–1 of 1")).toHaveLength(2);
      expect(screen.queryByText("no rows")).toBeNull();
      expect(
        screen.queryByRole("navigation", { name: "Pagination" }),
      ).toBeNull();
    },
  );

  it("shows results as a list by default", async () => {
    render(<SearchPage />, {
      useMemoryRouter: true,
      route: "/search?q=spider&type=comic",
    });

    expect(await screen.findByText("Amazing Spider-Man")).toBeTruthy();
    expect(screen.queryAllByTestId("search-result-card")).toHaveLength(0);
    expect(
      screen
        .getByRole("button", { name: "List view" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("switches to cover cards and remembers the choice", async () => {
    const user = userEvent.setup();
    render(<SearchPage />, {
      useMemoryRouter: true,
      route: "/search?q=spider&type=comic",
    });

    await screen.findByText("Amazing Spider-Man");
    await user.click(screen.getByRole("button", { name: "Grid view" }));

    const cards = await screen.findAllByTestId("search-result-card");
    expect(cards).toHaveLength(2);
    expect(
      screen.getByRole("img", { name: "Amazing Spider-Man" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Add Amazing Spider-Man" }),
    ).toBeTruthy();
    // A series already in the library keeps its added state on the card.
    expect(
      screen.getByRole("button", { name: "Spider-Man: Miles Morales added" }),
    ).toBeTruthy();
    expect(localStorage.getItem(SEARCH_VIEW_KEY)).toBe("grid");
  });

  it("opens in grid view when the saved preference is grid", async () => {
    localStorage.setItem(SEARCH_VIEW_KEY, "grid");
    render(<SearchPage />, {
      useMemoryRouter: true,
      route: "/search?q=spider&type=comic",
    });

    expect(await screen.findAllByTestId("search-result-card")).toHaveLength(2);
  });

  it("lets the URL override the saved preference", async () => {
    localStorage.setItem(SEARCH_VIEW_KEY, "grid");
    render(<SearchPage />, {
      useMemoryRouter: true,
      route: "/search?q=spider&type=comic&view=list",
    });

    await screen.findByText("Amazing Spider-Man");
    expect(screen.queryAllByTestId("search-result-card")).toHaveLength(0);
  });

  it("sends a missing Comic Vine key to Sources and keys and claims no search", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          comicvine_enabled: true,
          comicvine_api_set: false,
        }),
      ),
      http.post("/api/search/comics", () =>
        HttpResponse.json(
          { detail: "Comic Vine API key is not set" },
          { status: 400 },
        ),
      ),
    );
    render(<SearchPage />, {
      useMemoryRouter: true,
      route: "/search?q=spider&type=comic",
    });

    expect(await screen.findByText("Comic Vine API key required")).toBeTruthy();
    expect(
      screen.getByText(
        "Add a Comic Vine API key in Settings → Sources and keys to search comics.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open Sources and keys" })
        .getAttribute("href"),
    ).toBe("/settings?section=api");
    expect(screen.queryByText("Searched ComicVine and Metron")).toBeNull();
  });
});
