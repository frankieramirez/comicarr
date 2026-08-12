import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor, within } from "../test-utils";
import AttentionPage from "@/pages/AttentionPage";

interface BatchRequest {
  action: string;
  release_keys: string[];
}

function group(overrides = {}) {
  return {
    group_key: "42|postprocess_error",
    comicid: "42",
    series_label: "Saga",
    base_reason: "postprocess_error",
    reason_phrase: "post-processing failed",
    member_count: 2,
    newest_updated_at: "2026-08-03 12:00:00",
    oldest_updated_at: "2026-08-03 11:00:00",
    stage: "manual_review",
    available_actions: ["import", "search_again", "stop_wanting"],
    members: [
      {
        release_key: "rk-1",
        issue_label: "Saga #1",
        issueid: "iss-1",
        stage: "manual_review",
        available_actions: ["import", "search_again", "stop_wanting"],
        updated_date: "2026-08-03 12:00:00",
      },
      {
        release_key: "rk-2",
        issue_label: "Saga #2",
        issueid: "iss-2",
        stage: "manual_review",
        available_actions: ["import", "search_again", "stop_wanting"],
        updated_date: "2026-08-03 11:00:00",
      },
    ],
    ...overrides,
  };
}

/**
 * A group whose members really are at different stages — the shape an older
 * Comicarr could have left in `pipeline_journal`, since unresolved band rows
 * are never pruned.
 */
function mixedGroup() {
  return group({
    group_key: "mixed|r",
    series_label: "Mixed Series",
    stage: "mixed",
    available_actions: [],
    members: [
      {
        release_key: "rk-review",
        issue_label: "Mixed Series #1",
        issueid: "iss-1",
        stage: "manual_review",
        available_actions: ["import", "search_again", "stop_wanting"],
        updated_date: "2026-08-03 12:00:00",
      },
      {
        release_key: "rk-failed",
        issue_label: "Mixed Series #2",
        issueid: "iss-2",
        stage: "failed",
        available_actions: ["retry", "stop_wanting"],
        updated_date: "2026-08-03 11:00:00",
      },
    ],
  });
}

function bandHandler(groups: ReturnType<typeof group>[]) {
  return http.get("/api/attention", () =>
    HttpResponse.json({
      results: groups,
      total: groups.length,
      member_total: groups.reduce((n, g) => n + g.member_count, 0),
      preview_cap: 5,
    }),
  );
}

describe("AttentionPage", () => {
  it("shows every group — this surface is not bounded like the band", async () => {
    server.use(
      bandHandler(
        Array.from({ length: 9 }, (_, i) =>
          group({
            group_key: `${i}|r`,
            comicid: String(i),
            series_label: `S${i}`,
          }),
        ),
      ),
    );

    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    expect(await screen.findByText("S0")).toBeTruthy();
    expect(screen.getByText("S8")).toBeTruthy();
  });

  it("fans a group action out over every member and reports partials", async () => {
    const requests: BatchRequest[] = [];
    server.use(
      bandHandler([group()]),
      http.post("/api/attention/resolve", async ({ request }) => {
        const body = (await request.json()) as BatchRequest;
        requests.push(body);
        return HttpResponse.json({
          success: true,
          partial: true,
          action: body.action,
          requested: 2,
          processed: 2,
          succeeded: 1,
          failed: 1,
          capped: false,
          skipped_for_cap: 0,
          cap: 25,
          results: [],
        });
      }),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Saga");
    await user.click(screen.getByRole("button", { name: "Search again" }));

    await waitFor(() => {
      expect(requests).toEqual([
        { action: "search_again", release_keys: ["rk-1", "rk-2"] },
      ]);
    });
    // A partial result is a summary, never a blocking modal.
    expect(
      await screen.findByText("Search again 1 of 2 — 1 still needs attention."),
    ).toBeTruthy();
  });

  it("confirms before stop-wanting more than one issue", async () => {
    const requests: BatchRequest[] = [];
    server.use(
      bandHandler([group()]),
      http.post("/api/attention/resolve", async ({ request }) => {
        requests.push((await request.json()) as BatchRequest);
        return HttpResponse.json({
          success: true,
          partial: false,
          action: "stop_wanting",
          requested: 2,
          processed: 2,
          succeeded: 2,
          failed: 0,
          capped: false,
          skipped_for_cap: 0,
          cap: 25,
          results: [],
        });
      }),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Saga");
    await user.click(screen.getByRole("button", { name: "Stop wanting…" }));

    // Nothing has been sent yet — the consequence has to be read first.
    expect(requests).toEqual([]);
    expect(
      await screen.findByText(/will be marked ignored in your library/),
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Stop wanting" }));
    await waitFor(() => {
      expect(requests).toEqual([
        { action: "stop_wanting", release_keys: ["rk-1", "rk-2"] },
      ]);
    });
  });

  it("offers no group action when a group's members are at mixed stages", async () => {
    server.use(bandHandler([mixedGroup()]));

    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Mixed Series");
    expect(
      screen.getByText(
        "these issues stopped at different stages — pick the ones you mean",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    // Rows are shown without a click — otherwise the group reads as a dead end.
    expect(screen.getByText("Mixed Series #1")).toBeTruthy();
    expect(screen.getByText("Mixed Series #2")).toBeTruthy();
  });

  it("resolves an individual row inside a mixed-stage group", async () => {
    const requests: BatchRequest[] = [];
    server.use(
      bandHandler([mixedGroup()]),
      http.post("/api/attention/resolve", async ({ request }) => {
        const body = (await request.json()) as BatchRequest;
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
          results: [],
        });
      }),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Mixed Series");
    // Pick only the `failed` row — Retry is legal for it and for nothing else.
    await user.click(
      screen.getByRole("checkbox", { name: "Select Mixed Series #2" }),
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(requests).toEqual([
        { action: "retry", release_keys: ["rk-failed"] },
      ]);
    });
  });

  it("says so when a cross-stage selection shares no action", async () => {
    server.use(bandHandler([mixedGroup()]));

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Mixed Series");
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select all 2 in Mixed Series",
      }),
    );

    // One group, both its rows — the bar counts problems and issues separately.
    const bar = screen.getByRole("group", { name: "Selected issues" });
    expect(within(bar).getByText("1 problem · 2 issues")).toBeTruthy();
    // `stop_wanting` is the one action both stages admit, so it stays offered;
    // Retry and Import do not, because they'd be illegal for half the rows.
    expect(screen.getByRole("button", { name: "Stop wanting…" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Import" })).toBeNull();
  });

  it("surfaces the 25-row cap before the operator commits", async () => {
    server.use(
      bandHandler([
        group({
          group_key: "big|r",
          series_label: "Looney Tunes",
          member_count: 30,
          members: Array.from({ length: 30 }, (_, i) => ({
            release_key: `lt-${i}`,
            issue_label: `Looney Tunes #${i + 1}`,
            issueid: `lt-iss-${i}`,
            stage: "manual_review",
            available_actions: ["import", "search_again", "stop_wanting"],
            updated_date: "2026-08-03 12:00:00",
          })),
        }),
      ]),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Looney Tunes");
    await user.click(
      screen.getByRole("checkbox", { name: "Select all 30 in Looney Tunes" }),
    );

    const bar = screen.getByRole("group", { name: "Selected issues" });
    expect(within(bar).getByText("1 problem · 30 issues")).toBeTruthy();
    expect(
      within(bar).getByText("25 at a time — the rest stay here"),
    ).toBeTruthy();
  });

  it("filters by stage without hiding the rest of the queue permanently", async () => {
    server.use(
      bandHandler([
        group({ group_key: "a|r", series_label: "Review Series" }),
        group({
          group_key: "b|r",
          series_label: "Failed Series",
          stage: "failed",
          available_actions: ["retry", "stop_wanting"],
        }),
      ]),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    await screen.findByText("Review Series");
    await user.click(screen.getByRole("button", { name: "Failed" }));

    expect(screen.queryByText("Review Series")).toBeNull();
    expect(screen.getByText("Failed Series")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Review Series")).toBeTruthy();
  });

  it("opens the group a band card deep-linked to, and lets it be collapsed", async () => {
    server.use(
      bandHandler([
        group({ group_key: "a|r", series_label: "Quiet Series" }),
        group({ group_key: "b|r", series_label: "Linked Series" }),
      ]),
    );

    const user = userEvent.setup();
    render(<AttentionPage />, {
      route: "/activity/attention?group=b%7Cr",
      useMemoryRouter: true,
    });

    await screen.findByText("Linked Series");
    // The deep-linked group is open; its sibling is not.
    expect(screen.getByText("Saga #1")).toBeTruthy();
    expect(screen.getAllByText("Saga #1")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "hide issues" }));
    expect(screen.queryByText("Saga #1")).toBeNull();
  });

  it("says so plainly when nothing needs attention", async () => {
    server.use(bandHandler([]));

    render(<AttentionPage />, {
      route: "/activity/attention",
      useMemoryRouter: true,
    });

    expect(
      await screen.findByText("Nothing needs your attention"),
    ).toBeTruthy();
  });
});
