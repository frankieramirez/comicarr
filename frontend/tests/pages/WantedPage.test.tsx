import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import WantedPage from "@/pages/WantedPage";

const wantedResponse = {
  issues: [],
  pagination: { total: 0, limit: 50, offset: 0, has_more: false },
};

function renderWantedWithForceResult(result: Record<string, unknown>) {
  server.use(
    http.get("/api/wanted", () => HttpResponse.json(wantedResponse)),
    http.post("/api/search/force", () => HttpResponse.json(result)),
  );
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
  return render(<WantedPage />);
}

function sagaIssue(
  id: string,
  number: string,
  acquisition?: {
    state: string | null;
    attempt_count: number;
    reason?: string | null;
    run_id?: string | null;
  } | null,
) {
  return {
    IssueID: id,
    ComicID: "comic-saga",
    ComicName: "Saga",
    Issue_Number: number,
    IssueDate: "2020-01-01",
    Status: "Wanted",
    DateAdded: "2026-01-01",
    acquisition: acquisition === undefined ? null : acquisition,
  };
}

describe("WantedPage", () => {
  it("reports an accepted force search with its accepted issue count", async () => {
    const user = userEvent.setup();
    renderWantedWithForceResult({
      success: true,
      status: "accepted",
      run_id: "run-123",
      accepted: 3,
      message: "Search initiated for wanted issues",
    });

    await user.click(
      await screen.findByRole("button", { name: /force search/i }),
    );

    expect(
      await screen.findByText(
        "Search accepted — 3 wanted issues queued. Run run-123.",
      ),
    ).toBeTruthy();
  });

  it("reports a completed no-match search without presenting it as a failure", async () => {
    const user = userEvent.setup();
    renderWantedWithForceResult({
      success: true,
      status: "no_match",
      run_id: "run-no-match",
      accepted: 0,
      message: "No eligible wanted issues found",
    });

    await user.click(
      await screen.findByRole("button", { name: /force search/i }),
    );

    expect(
      await screen.findByText(
        "No eligible wanted issues found. Run run-no-match.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Nothing to search")).toBeTruthy();
    expect(
      screen.queryByText(
        "Search accepted — 0 wanted issues queued. Run run-no-match.",
      ),
    ).toBeNull();
  });

  it("reports a blocked force search without a success toast", async () => {
    const user = userEvent.setup();
    renderWantedWithForceResult({
      success: false,
      status: "blocked",
      message: "Search blocked: no complete acquisition route is ready",
    });

    await user.click(
      await screen.findByRole("button", { name: /force search/i }),
    );

    expect(
      await screen.findByText(
        "Search blocked: no complete acquisition route is ready",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "Search accepted — 3 wanted issues queued. Run run-123.",
      ),
    ).toBeNull();
  });

  it("reports a partially accepted force search without claiming full success", async () => {
    const user = userEvent.setup();
    renderWantedWithForceResult({
      success: true,
      status: "partial",
      run_id: "run-partial",
      accepted: 2,
      message: "Search queued 2 Wanted issues; 1 could not be queued",
    });

    await user.click(
      await screen.findByRole("button", { name: /force search/i }),
    );

    expect(await screen.findByText("Search partially accepted")).toBeTruthy();
    expect(
      screen.getByText(
        "Search queued 2 Wanted issues; 1 could not be queued. Run run-partial.",
      ),
    ).toBeTruthy();
  });

  it("reports a failed force search distinctly", async () => {
    const user = userEvent.setup();
    renderWantedWithForceResult({
      success: false,
      status: "failed",
      message: "Search failed to start",
    });

    await user.click(
      await screen.findByRole("button", { name: /force search/i }),
    );

    expect(await screen.findByText("Search failed to start")).toBeTruthy();
    expect(
      screen.queryByText(
        "Search accepted — 3 wanted issues queued. Run run-123.",
      ),
    ).toBeNull();
  });

  /**
   * #490: Wanted rows show live-sticky acquisition copy from the latest run
   * item — never searched / searching… / no match · N tries — without a
   * countdown or progress percent.
   */
  it("renders live-sticky acquisition annotations from the API payload", async () => {
    server.use(
      http.get("/api/wanted", () =>
        HttpResponse.json({
          issues: [
            sagaIssue("saga-never", "1", null),
            sagaIssue("saga-live", "2", {
              state: "running",
              attempt_count: 1,
              run_id: "run-live",
            }),
            sagaIssue("saga-sticky", "3", {
              state: "no_match",
              attempt_count: 3,
              run_id: "run-old",
              reason: "providers empty",
            }),
          ],
          pagination: {
            total: 3,
            limit: 50,
            offset: 0,
            has_more: false,
          },
        }),
      ),
    );

    render(<WantedPage />);

    expect(await screen.findByText("never searched")).toBeTruthy();
    expect(screen.getByText("searching…")).toBeTruthy();
    expect(screen.getByText("no match · 3 tries")).toBeTruthy();
    expect(screen.queryByText(/retry/i)).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  /**
   * #408: filtering was applied only to the currently loaded page while the
   * footer still described the unfiltered queue. The filter term must ride
   * the server query, and match count / pagination total must agree on the
   * filtered set — including matches that would have lived past offset 50.
   */
  it("filters the full Wanted queue through the API and reports matching totals", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/wanted", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const q = (url.searchParams.get("q") || "").toLowerCase();
        const offset = Number(url.searchParams.get("offset") || 0);
        if (q === "saga") {
          return HttpResponse.json({
            issues: [
              sagaIssue("saga-1", "1"),
              sagaIssue("saga-2", "2"),
              sagaIssue("saga-10", "10"),
              sagaIssue("saga-11", "11"),
              sagaIssue("saga-12", "12"),
            ],
            pagination: {
              total: 12,
              limit: 50,
              offset: 0,
              has_more: false,
            },
          });
        }
        return HttpResponse.json({
          issues:
            offset === 0
              ? [sagaIssue("saga-page1", "1")]
              : [sagaIssue("saga-page2", "10")],
          pagination: {
            total: 53,
            limit: 50,
            offset,
            has_more: offset === 0,
          },
        });
      }),
    );

    const user = userEvent.setup();
    render(<WantedPage />);

    expect(await screen.findByText("53 issues in queue")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("50");
    });

    await user.type(
      screen.getByRole("textbox", { name: "Filter wanted issues" }),
      "saga",
    );

    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("q")).toBe("saga");
      expect(last?.searchParams.get("offset")).toBe("0");
    });

    expect(await screen.findByText("12 matches")).toBeTruthy();
    expect(screen.getByText("12 issues in queue")).toBeTruthy();
    expect(await screen.findByText("1–12 of 12")).toBeTruthy();
    // One page of matches: the footer keeps the range and drops the pager
    // rather than showing two dead buttons.
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
    // Matches that lived past the first unfiltered page are still listed.
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
  });

  it("returns to the first page when the filter changes", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/wanted", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const offset = Number(url.searchParams.get("offset") || 0);
        return HttpResponse.json({
          issues: [sagaIssue(`row-${offset}`, "1")],
          pagination: {
            total: 90,
            limit: 50,
            offset,
            has_more: true,
          },
        });
      }),
    );

    const user = userEvent.setup();
    render(<WantedPage />);
    await screen.findByText("90 issues in queue");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("50");
    });

    await user.type(
      screen.getByRole("textbox", { name: "Filter wanted issues" }),
      "flash",
    );
    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("q")).toBe("flash");
      expect(last?.searchParams.get("offset")).toBe("0");
    });
  });

  it("toasts when Skip fails", async () => {
    server.use(
      http.get("/api/wanted", () =>
        HttpResponse.json({
          issues: [sagaIssue("saga-1", "1")],
          pagination: { total: 1, limit: 50, offset: 0, has_more: false },
        }),
      ),
      http.put("/api/series/issues/:issueId/unqueue", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    render(<WantedPage />);
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
