/**
 * Regression tests for Story Arc search submission (issue #411).
 *
 * Enter and the Search button must POST /api/search/comics with type=story_arc
 * and render results from the backend { results: [...] } envelope.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ArcSearch from "@/components/storyarcs/ArcSearch";
import StoryArcsPage from "@/pages/StoryArcsPage";

const ARC_RESULT = {
  name: "Dark Phoenix Saga",
  comicid: "4045-12345",
  cvarcid: "4045-12345",
  publisher: "Marvel",
  issues: "?",
  comicimage: "https://example.com/dark-phoenix.jpg",
  description: "Story Arc - Click to load details",
  arclist: null,
  haveit: "No",
};

describe("ArcSearch", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("submits via Enter and renders results from the {results} envelope", async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post("/api/search/comics", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ results: [ARC_RESULT] });
      }),
    );

    render(<ArcSearch />);

    const input = screen.getByRole("textbox", { name: /search story arcs/i });
    await user.type(input, "Dark Phoenix");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(capturedBody).toEqual({
        name: "Dark Phoenix",
        type: "story_arc",
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Dark Phoenix Saga")).toBeTruthy();
    });

    // haveit "No" means not in the library: the card offers Add, not a disabled Added (#1514).
    const add = screen.getByRole("button", {
      name: /add arc/i,
    }) as HTMLButtonElement;
    expect(add.disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /^added$/i })).toBeNull();
    expect(screen.getByText("Marvel")).toBeTruthy();
  });

  it("submits via the Search button for the same non-empty query", async () => {
    const user = userEvent.setup();
    let requestCount = 0;

    server.use(
      http.post("/api/search/comics", async ({ request }) => {
        requestCount += 1;
        const body = (await request.json()) as { name?: string; type?: string };
        expect(body.name).toBe("House of M");
        expect(body.type).toBe("story_arc");
        return HttpResponse.json({
          results: [{ ...ARC_RESULT, name: "House of M" }],
        });
      }),
    );

    render(<ArcSearch />);

    await user.type(
      screen.getByRole("textbox", { name: /search story arcs/i }),
      "House of M",
    );
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      expect(requestCount).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("House of M")).toBeTruthy();
    });
  });

  it("shows an empty-result state when the provider returns no matches", async () => {
    const user = userEvent.setup();

    server.use(
      http.post("/api/search/comics", () => {
        return HttpResponse.json(
          { detail: "Search returned no results" },
          { status: 400 },
        );
      }),
    );

    render(<ArcSearch />);

    await user.type(
      screen.getByRole("textbox", { name: /search story arcs/i }),
      "zzzznotanarc",
    );
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(
        screen.getByText(/No story arcs found for .*zzzznotanarc/i),
      ).toBeTruthy();
    });
  });

  it("shows a request-failure state when search errors", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("/api/config", () => {
        return HttpResponse.json({
          comicvine_enabled: true,
          comicvine_api_set: true,
        });
      }),
      http.post("/api/search/comics", () => {
        return HttpResponse.json(
          { detail: "ComicVine is temporarily unavailable" },
          { status: 502 },
        );
      }),
    );

    render(<ArcSearch />);

    await user.type(
      screen.getByRole("textbox", { name: /search story arcs/i }),
      "Dark Phoenix",
    );
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(screen.getByText("Story arc search failed")).toBeTruthy();
      expect(
        screen.getByText(
          /ComicVine is temporarily unavailable|Unable to reach/i,
        ),
      ).toBeTruthy();
    });
  });
});

describe("StoryArcsPage empty-state search action", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("submits the typed query when the empty-state Search Story Arcs action is clicked", async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.get("/api/storyarcs", () => {
        return HttpResponse.json([]);
      }),
      http.get("/api/ai/status", () => {
        return HttpResponse.json({ configured: false, available: false });
      }),
      http.post("/api/search/comics", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ results: [ARC_RESULT] });
      }),
    );

    render(<StoryArcsPage />);

    await waitFor(() => {
      expect(screen.getByText("No story arcs tracked")).toBeTruthy();
    });

    const input = screen.getByRole("textbox", { name: /search story arcs/i });
    await user.type(input, "Dark Phoenix");
    await user.click(
      screen.getByRole("button", { name: /search story arcs/i }),
    );

    await waitFor(() => {
      expect(capturedBody).toEqual({
        name: "Dark Phoenix",
        type: "story_arc",
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Dark Phoenix Saga")).toBeTruthy();
    });
  });
});
