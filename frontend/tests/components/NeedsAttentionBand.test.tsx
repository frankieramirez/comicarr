/**
 * Dashboard needs-attention band (dashboard-spec.md §3.2).
 *
 * Covers the three band shapes the ticket names — nothing waiting, a short
 * list under the cap, and a list that folds the rest into triage — plus an
 * in-place action so the count updates without a manual refresh.
 */

import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import NeedsAttentionBand from "@/components/dashboard/NeedsAttentionBand";

function group(overrides: Record<string, unknown> = {}) {
  return {
    group_key: "42|postprocess_error",
    comicid: "42",
    series_label: "Saga",
    base_reason: "postprocess_error",
    reason_phrase: "post-processing failed",
    member_count: 1,
    newest_updated_at: "2026-08-03 12:00:00",
    oldest_updated_at: "2026-08-03 12:00:00",
    stage: "failed",
    available_actions: ["retry", "stop_wanting"],
    members: [
      {
        release_key: "rk-1",
        issue_label: "Saga #12",
        issueid: "iss-1",
        stage: "failed",
        available_actions: ["retry", "stop_wanting"],
        updated_date: "2026-08-03 12:00:00",
      },
    ],
    ...overrides,
  };
}

function bandHandler(
  groups: ReturnType<typeof group>[],
  opts: { total?: number; preview_cap?: number } = {},
) {
  const preview_cap = opts.preview_cap ?? 5;
  const total = opts.total ?? groups.length;
  return http.get("/api/activity/band", () =>
    HttpResponse.json({
      results: groups,
      total,
      member_total: groups.reduce((n, g) => n + g.member_count, 0),
      preview_cap,
    }),
  );
}

describe("NeedsAttentionBand", () => {
  it("renders one quiet line when nothing needs attention", async () => {
    server.use(bandHandler([]));

    render(<NeedsAttentionBand />);

    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull();
    expect(screen.queryByText(/need attention/i)).toBeNull();
  });

  it("shows the group count and each group's phrase under the cap", async () => {
    server.use(
      bandHandler([
        group(),
        group({
          group_key: "7|search_error",
          comicid: "7",
          series_label: "Invincible",
          reason_phrase: "search failed",
          members: [
            {
              release_key: "rk-2",
              issue_label: "Invincible #1",
              issueid: "iss-2",
              stage: "failed",
              available_actions: ["retry", "stop_wanting"],
              updated_date: "2026-08-03 11:00:00",
            },
          ],
        }),
      ]),
    );

    render(<NeedsAttentionBand />);

    expect(
      await screen.findByRole("region", { name: "Needs attention" }),
    ).toBeTruthy();
    expect(screen.getByText("2 need attention")).toBeTruthy();
    expect(screen.getByText("Saga")).toBeTruthy();
    expect(screen.getByText(/post-processing failed/)).toBeTruthy();
    expect(screen.getByText("Invincible")).toBeTruthy();
    expect(screen.getByText(/search failed/)).toBeTruthy();
    expect(screen.getAllByTestId("needs-attention-group")).toHaveLength(2);
    expect(screen.queryByTestId("needs-attention-more")).toBeNull();
    // Group-level actions match the triage route's exits.
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(2);
  });

  it("folds groups past the preview cap into a triage link", async () => {
    const groups = Array.from({ length: 5 }, (_, i) =>
      group({
        group_key: `${i}|r`,
        comicid: String(i),
        series_label: `Series ${i}`,
        members: [
          {
            release_key: `rk-${i}`,
            issue_label: `Series ${i} #1`,
            issueid: `iss-${i}`,
            stage: "failed",
            available_actions: ["retry", "stop_wanting"],
            updated_date: "2026-08-03 12:00:00",
          },
        ],
      }),
    );
    // Server can report a total larger than the rows it returned (band envelope).
    server.use(bandHandler(groups, { total: 8, preview_cap: 5 }));

    render(<NeedsAttentionBand />);

    expect(await screen.findByText("8 need attention")).toBeTruthy();
    expect(screen.getAllByTestId("needs-attention-group")).toHaveLength(5);
    const more = await screen.findByTestId("needs-attention-more");
    expect(more.textContent).toContain("+3 more");
    expect(more.getAttribute("href")).toBe("/activity/attention");
    expect(
      screen.getByRole("link", { name: "See all 8 →" }).getAttribute("href"),
    ).toBe("/activity/attention");
  });

  it("runs a group action through the same batch endpoint and refreshes the band", async () => {
    const requests: Array<{ action: string; release_keys: string[] }> = [];
    let hits = 0;
    server.use(
      http.get("/api/activity/band", () => {
        hits += 1;
        // After a successful action the band is empty — the count moves without
        // the operator refreshing.
        if (hits > 1) {
          return HttpResponse.json({
            results: [],
            total: 0,
            member_total: 0,
            preview_cap: 5,
          });
        }
        return HttpResponse.json({
          results: [group()],
          total: 1,
          member_total: 1,
          preview_cap: 5,
        });
      }),
      http.post("/api/downloads/needs-attention/batch", async ({ request }) => {
        const body = (await request.json()) as {
          action: string;
          release_keys: string[];
        };
        requests.push(body);
        return HttpResponse.json({
          success: true,
          partial: false,
          action: body.action,
          requested: 1,
          processed: 1,
          succeeded: 1,
          failed: 0,
          capped: false,
          skipped_for_cap: 0,
          cap: 25,
          results: [{ release_key: "rk-1", ok: true, status: "retried" }],
        });
      }),
    );

    const user = userEvent.setup();
    render(<NeedsAttentionBand />);

    expect(await screen.findByText("1 needs attention")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(requests).toEqual([
        { action: "retry", release_keys: ["rk-1"] },
      ]);
    });
    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
    expect(screen.queryByText("1 needs attention")).toBeNull();
  });

  it("says so when the band cannot be read", async () => {
    server.use(
      http.get("/api/activity/band", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 503 }),
      ),
    );

    render(<NeedsAttentionBand />);

    expect(await screen.findByText("Needs attention unavailable")).toBeTruthy();
    expect(screen.queryByText("Nothing needs you")).toBeNull();
  });
});
