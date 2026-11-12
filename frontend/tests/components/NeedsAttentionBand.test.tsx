/**
 * Dashboard needs-attention band (dashboard-spec.md §3.2, v2 dashboard).
 *
 * The band shows one row per *cause*: every series sharing a base reason and
 * stage, folded server-side. Covers nothing waiting, the cause copy, the fold
 * past the preview, a settings fix that leads the row, and an in-place action
 * that resolves every release key in the cause.
 */

import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import NeedsAttentionBand from "@/components/dashboard/NeedsAttentionBand";
import { causeSubline, seriesList } from "@/lib/attentionCause";
import type { AttentionCause } from "@/components/activity/timeline";

function series(label: string, count: number, comicid = label) {
  return {
    group_key: `${comicid}|r`,
    comicid,
    series_label: label,
    member_count: count,
    issue_labels: [`${label} #1`],
  };
}

function cause(overrides: Partial<AttentionCause> = {}): AttentionCause {
  const s = overrides.series ?? [series("Saga", 1, "42")];
  const members = s.reduce((n, x) => n + x.member_count, 0);
  return {
    cause_key: "postprocess_error|failed",
    base_reason: "postprocess_error",
    reason_phrase: "post-processing failed",
    headline: "Post-processing failed",
    hint: null,
    icon: "failed",
    fix: null,
    stage: "failed",
    available_actions: ["retry", "stop_wanting"],
    series_count: s.length,
    member_count: members,
    newest_updated_at: "2026-08-03 12:00:00",
    series: s,
    release_keys: Array.from({ length: members }, (_, i) => `rk-${i + 1}`),
    ...overrides,
  };
}

function bandHandler(causes: AttentionCause[]) {
  return http.get("/api/attention", () =>
    HttpResponse.json({
      results: [],
      causes,
      total: causes.reduce((n, c) => n + c.series_count, 0),
      member_total: causes.reduce((n, c) => n + c.member_count, 0),
      preview_cap: 5,
    }),
  );
}

describe("cause copy", () => {
  it("joins series names the way the design reads", () => {
    expect(seriesList(["A"])).toBe("A");
    expect(seriesList(["A", "B"])).toBe("A and B");
    expect(seriesList(["A", "B", "C"])).toBe("A, B and C");
    expect(seriesList(["A", "B", "C", "D", "E"])).toBe(
      "A, B and 3 more series",
    );
  });

  it("names the issue, the series, or the share each one has", () => {
    expect(causeSubline(cause())).toBe("Saga #1.");
    expect(
      causeSubline(
        cause({
          series: [series("Absolute Wonder Woman", 12), series("Batman", 11)],
          hint: "One settings fix clears them all.",
        }),
      ),
    ).toBe(
      "23 issues in Absolute Wonder Woman and Batman. One settings fix clears them all.",
    );
    expect(
      causeSubline(
        cause({ series: [series("Dandadan", 6), series("One Piece", 6)] }),
      ),
    ).toBe("Dandadan and One Piece, 6 issues each.");
  });
});

describe("NeedsAttentionBand", () => {
  it("renders one quiet line when nothing needs attention", async () => {
    server.use(bandHandler([]));

    render(<NeedsAttentionBand />);

    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Needs attention" }),
    ).toBeNull();
  });

  it("shows one row per cause with series and issue totals", async () => {
    server.use(
      bandHandler([
        cause({
          cause_key: "invalid_postprocess_command|failed",
          headline: "Post-processing is misconfigured",
          hint: "One settings fix clears them all.",
          icon: "settings",
          fix: {
            label: "Open post-processing",
            href: "/settings?section=media",
          },
          series: [series("Absolute Wonder Woman", 12), series("Batman", 11)],
        }),
        cause({
          cause_key: "submission_rejected|failed",
          headline: "The downloader rejected these submissions",
          series: [series("Dandadan", 6), series("One Piece", 6)],
        }),
      ]),
    );

    render(<NeedsAttentionBand />);

    expect(
      await screen.findByRole("region", { name: "Needs attention" }),
    ).toBeTruthy();
    expect(screen.getByText("4 series · 35 issues")).toBeTruthy();
    expect(screen.getAllByTestId("needs-attention-cause")).toHaveLength(2);
    expect(screen.getByText("Post-processing is misconfigured")).toBeTruthy();
    // A settings fix leads the row instead of a per-issue action.
    expect(
      screen
        .getByRole("link", { name: "Open post-processing" })
        .getAttribute("href"),
    ).toBe("/settings?section=media");
    expect(screen.getByRole("button", { name: "Retry all 12" })).toBeTruthy();
    expect(screen.queryByTestId("needs-attention-more")).toBeNull();
  });

  it("folds causes past the preview into one line", async () => {
    const causes = Array.from({ length: 5 }, (_, i) =>
      cause({
        cause_key: `r${i}|failed`,
        headline: `Cause ${i}`,
        series: [series(`Series ${i}`, i + 1)],
      }),
    );
    server.use(bandHandler(causes));

    render(<NeedsAttentionBand />);

    await screen.findByText("Cause 0");
    expect(screen.getAllByTestId("needs-attention-cause")).toHaveLength(3);
    const more = screen.getByTestId("needs-attention-more");
    // Causes 3 and 4 hold 4 + 5 issues in two series.
    expect(more.textContent).toBe(
      "2 more series with 9 issues, in other causes",
    );
    expect(more.getAttribute("href")).toBe("/activity/attention");
    expect(
      screen.getByRole("link", { name: "See all" }).getAttribute("href"),
    ).toBe("/activity/attention");
  });

  it("resolves every release key in the cause and refreshes the band", async () => {
    const requests: Array<{ action: string; release_keys: string[] }> = [];
    let hits = 0;
    const two = cause({
      series: [series("Saga", 1, "42"), series("Paper Girls", 1, "7")],
    });
    server.use(
      http.get("/api/attention", () => {
        hits += 1;
        if (hits > 1) {
          return HttpResponse.json({
            results: [],
            causes: [],
            total: 0,
            member_total: 0,
            preview_cap: 5,
          });
        }
        return HttpResponse.json({
          results: [],
          causes: [two],
          total: 2,
          member_total: 2,
          preview_cap: 5,
        });
      }),
      http.post("/api/attention/resolve", async ({ request }) => {
        const body = (await request.json()) as {
          action: string;
          release_keys: string[];
        };
        requests.push(body);
        return HttpResponse.json({
          success: true,
          partial: false,
          action: body.action,
          requested: 2,
          processed: 2,
          succeeded: 2,
          failed: 0,
          capped: false,
          skipped_for_cap: 0,
          cap: 25,
          results: body.release_keys.map((release_key) => ({
            release_key,
            ok: true,
            status: "retried",
          })),
        });
      }),
    );

    const user = userEvent.setup();
    render(<NeedsAttentionBand />);

    await user.click(
      await screen.findByRole("button", { name: "Retry all 2" }),
    );

    await waitFor(() => {
      expect(requests).toEqual([
        { action: "retry", release_keys: ["rk-1", "rk-2"] },
      ]);
    });
    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
  });

  it("says so when the band cannot be read", async () => {
    server.use(
      http.get("/api/attention", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 503 }),
      ),
    );

    render(<NeedsAttentionBand />);

    expect(await screen.findByText("Needs attention unavailable")).toBeTruthy();
    expect(screen.queryByText("Nothing needs you")).toBeNull();
  });
});
