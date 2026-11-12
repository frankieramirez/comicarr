/**
 * Wanted by series (v2 Wanted design): one row per series with how many
 * issues are missing, which ones and why; tabs filter by reason and keep
 * their counts; a row opens to its issues.
 */

import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor, within } from "../test-utils";
import WantedPage from "@/pages/WantedPage";
import { wantedSeriesWhy } from "@/lib/wantedAnnotation";

const counts = { all: 251, not_found: 2, searching: 0, queued: 249 };

function series(overrides: Record<string, unknown> = {}) {
  return {
    comicid: "4050-1",
    comic_name: "Absolute Superman",
    comic_year: "2024",
    publisher: "DC Comics",
    kind: "comic",
    missing: 2,
    which: "#23-24",
    why: "not_found",
    buckets: { not_found: 2, searching: 0, queued: 0 },
    max_attempts: 3,
    last_searched_at: null,
    ...overrides,
  };
}

describe("Wanted by series", () => {
  it("labels why a series is missing", () => {
    expect(wantedSeriesWhy({ why: "not_found", max_attempts: 3 })).toBe(
      "Not found 3×",
    );
    expect(wantedSeriesWhy({ why: "not_found", max_attempts: 1 })).toBe(
      "Not found",
    );
    expect(wantedSeriesWhy({ why: "queued", max_attempts: 0 })).toBe("Queued");
  });

  it("is the default view, with reason tabs and series totals", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/api/wanted/series", ({ request }) => {
        const state = new URL(request.url).searchParams.get("state") ?? "";
        seen.push(state);
        return HttpResponse.json({
          series:
            state === "not_found"
              ? [series()]
              : [
                  series(),
                  series({
                    comicid: "md-1",
                    comic_name: "20th Century Boys",
                    kind: "manga",
                    missing: 249,
                    which: "#1-249",
                    why: "queued",
                    max_attempts: 0,
                  }),
                ],
          counts,
          pagination: {
            total: state === "not_found" ? 1 : 2,
            limit: 50,
            offset: 0,
            has_more: false,
          },
        });
      }),
    );

    const user = userEvent.setup();
    render(<WantedPage />);

    expect(await screen.findByText("251 missing in 2 series")).toBeTruthy();
    const rows = screen.getAllByTestId("wanted-series-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("#23-24")).toBeTruthy();
    expect(within(rows[0]).getByText("Not found 3×")).toBeTruthy();
    expect(within(rows[1]).getByText("249")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /^Not found/ }));
    await waitFor(() => {
      expect(screen.getAllByTestId("wanted-series-row")).toHaveLength(1);
    });
    expect(seen).toContain("not_found");
    // Tab counts stay put while a tab is selected.
    expect(
      screen.getByRole("button", { name: /^Queued/ }).textContent,
    ).toContain("249");
  });

  it("opens a series to its issues", async () => {
    const asked: string[] = [];
    server.use(
      http.get("/api/wanted/series", () =>
        HttpResponse.json({
          series: [series()],
          counts,
          pagination: { total: 1, limit: 50, offset: 0, has_more: false },
        }),
      ),
      http.get("/api/wanted", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("comic_id") ?? "");
        return HttpResponse.json({
          issues: [
            {
              IssueID: "i-23",
              ComicID: "4050-1",
              ComicName: "Absolute Superman",
              Issue_Number: "23",
              IssueName: "Dawn",
              ReleaseDate: "2026-10-29",
              Status: "Wanted",
              acquisition: null,
            },
          ],
          pagination: { total: 1, limit: 200, offset: 0, has_more: false },
        });
      }),
    );

    const user = userEvent.setup();
    render(<WantedPage />);

    await user.click(
      await screen.findByRole("button", {
        name: "Show issues for Absolute Superman",
      }),
    );

    const issues = await screen.findByTestId("wanted-series-issues");
    expect(within(issues).getByText("Dawn")).toBeTruthy();
    expect(asked).toEqual(["4050-1"]);
  });
});
