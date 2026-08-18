import { describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import { ReleaseReviewSheet } from "@/components/releases/ReleaseReviewSheet";

describe("ReleaseReviewSheet", () => {
  const issue = {
    IssueID: "issue-1",
    ComicID: "comic-1",
    ComicName: "Example",
    Issue_Number: "1",
    IssueNumber: "1",
    Status: "Wanted",
  };

  function sessionCandidate(accepted: boolean, overrideable: boolean) {
    return {
      candidate_id: "candidate-1",
      state: "available",
      candidate: {
        title: "Example 001 (2026) (Digital)",
        provider: "Indexer",
        source_kind: "usenet",
        published_at: "2026-08-12T04:00:00Z",
        size_bytes: 98_000_000,
        pack: false,
        metrics: { grabs: 8 },
      },
      verdict: {
        status: accepted ? "accepted" : "rejected",
        accepted,
        overrideable,
        reason_code: accepted ? "accepted.issue" : "ignored.search_word",
        reasons: [
          {
            code: accepted ? "accepted.issue" : "ignored.search_word",
            message: accepted
              ? "Issue, year, and volume match"
              : "Contains a configured ignored word",
          },
        ],
        match_kind: accepted ? "standard" : "none",
      },
    };
  }

  function handleSession(accepted: boolean, overrideable: boolean) {
    server.use(
      http.get("/api/search/interactive/session-1", () =>
        HttpResponse.json({
          session_id: "session-1",
          entity_type: "issue",
          entity_id: "issue-1",
          state: "complete",
          candidate_count: 1,
          progress: {
            provider_total: 2,
            provider_completed: 2,
            current_provider: null,
          },
          provider_failures: [
            {
              provider: "Slow indexer",
              code: "timeout",
              detail: "Provider timed out",
            },
          ],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [sessionCandidate(accepted, overrideable)],
        }),
      ),
    );
  }

  it("opens for a selected issue while its search is starting", async () => {
    render(
      <ReleaseReviewSheet
        issue={issue}
        sessionId={null}
        startPending
        startError={null}
        onRetry={vi.fn()}
        onClose={vi.fn()}
        onGrabbed={vi.fn()}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Review releases" }),
    ).toBeTruthy();
    expect(screen.getByText("Starting provider search…")).toBeTruthy();
  });

  it("explains candidates and submits an accepted grab", async () => {
    handleSession(true, false);
    let grabBody: unknown;
    server.use(
      http.post(
        "/api/search/interactive/session-1/candidates/candidate-1/grab",
        async ({ request }) => {
          grabBody = await request.json();
          return HttpResponse.json({
            success: true,
            status: "submitted",
            candidate_id: "candidate-1",
          });
        },
      ),
    );
    const onGrabbed = vi.fn();
    const user = userEvent.setup();
    render(
      <ReleaseReviewSheet
        issue={issue}
        sessionId="session-1"
        startPending={false}
        startError={null}
        onRetry={vi.fn()}
        onClose={vi.fn()}
        onGrabbed={onGrabbed}
      />,
    );

    expect(
      await screen.findByText("Example 001 (2026) (Digital)"),
    ).toBeTruthy();
    expect(screen.getByText("Issue, year, and volume match")).toBeTruthy();
    expect(screen.getByText("Slow indexer")).toBeTruthy();
    expect(screen.getByText("Provider timed out")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Review grab" }));
    await user.click(screen.getByRole("button", { name: "Confirm grab" }));

    await waitFor(() => expect(grabBody).toEqual({ override: false }));
    expect(onGrabbed).toHaveBeenCalledOnce();
  });

  it("shows which missing issues a pack would satisfy", async () => {
    server.use(
      http.get("/api/search/interactive/session-series", () =>
        HttpResponse.json({
          session_id: "session-series",
          entity_type: "series",
          entity_id: "comic-1",
          state: "complete",
          candidate_count: 1,
          progress: {
            provider_total: 1,
            provider_completed: 1,
            current_provider: null,
          },
          provider_failures: [],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [
            {
              ...sessionCandidate(true, false),
              candidate: {
                ...sessionCandidate(true, false).candidate,
                title: "Example 001-003 (2026)",
                pack: true,
              },
              verdict: {
                ...sessionCandidate(true, false).verdict,
                reason_code: "accepted.pack",
                match_kind: "pack",
              },
              satisfies: [
                {
                  entity_type: "issue",
                  entity_id: "i1",
                  issue_number: "1",
                },
                {
                  entity_type: "issue",
                  entity_id: "i2",
                  issue_number: "2",
                },
                {
                  entity_type: "issue",
                  entity_id: "i3",
                  issue_number: "3",
                },
              ],
            },
          ],
        }),
      ),
    );

    render(
      <ReleaseReviewSheet
        issue={{
          ComicName: "Example",
          Status: "Wanted",
          scope: "series",
          missingCount: 4,
        }}
        sessionId="session-series"
        startPending={false}
        startError={null}
        onRetry={vi.fn()}
        onClose={vi.fn()}
        onGrabbed={vi.fn()}
      />,
    );

    expect(await screen.findByText("Example 001-003 (2026)")).toBeTruthy();
    expect(screen.getByText("covers #1–#3")).toBeTruthy();
    expect(screen.getByText(/4 missing issues/i)).toBeTruthy();
  });

  it("requires acknowledgement before submitting an override", async () => {
    handleSession(false, true);
    let grabBody: unknown;
    server.use(
      http.post(
        "/api/search/interactive/session-1/candidates/candidate-1/grab",
        async ({ request }) => {
          grabBody = await request.json();
          return HttpResponse.json({
            success: true,
            status: "submitted",
            candidate_id: "candidate-1",
          });
        },
      ),
    );
    const user = userEvent.setup();
    render(
      <ReleaseReviewSheet
        issue={issue}
        sessionId="session-1"
        startPending={false}
        startError={null}
        onRetry={vi.fn()}
        onClose={vi.fn()}
        onGrabbed={vi.fn()}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: "Review override" }),
    );
    const confirm = screen.getByRole("button", { name: "Confirm grab" });
    expect(confirm).toHaveProperty("disabled", true);
    await user.click(screen.getByRole("checkbox"));
    expect(confirm).toHaveProperty("disabled", false);
    await user.click(confirm);

    await waitFor(() => expect(grabBody).toEqual({ override: true }));
  });
});
