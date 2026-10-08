import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ArcIssueTable from "@/components/storyarcs/ArcIssueTable";
import type { ArcIssue } from "@/types";

const arcIssue: ArcIssue = {
  IssueArcID: "arc-issue-9",
  ReadingOrder: 1,
  ComicID: "comic-1",
  ComicName: "Absolute Batman",
  IssueNumber: "9",
  IssueID: "issue-9",
  Status: "Wanted",
  IssueDate: "2026-08-12",
  IssueName: "Ready to search",
  IssuePublisher: "DC Comics",
  Location: null,
};

describe("ArcIssueTable", () => {
  it("starts Interactive Search for a story-arc issue in place", async () => {
    let searchBody: unknown;
    server.use(
      http.post("/api/search/interactive", async ({ request }) => {
        searchBody = await request.json();
        return HttpResponse.json({
          session_id: "session-arc",
          entity_type: "story_arc_issue",
          entity_id: "arc-issue-9",
          series_id: "comic-1",
          state: "complete",
          candidate_count: 0,
          progress: {
            provider_total: 0,
            provider_completed: 0,
            current_provider: null,
          },
          provider_failures: [],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [],
        });
      }),
    );
    const user = userEvent.setup();
    render(<ArcIssueTable issues={[arcIssue]} storyArcId="arc-1" />);

    await user.click(
      screen.getByRole("button", {
        name: "Actions for Absolute Batman #9",
      }),
    );
    await user.click(
      screen.getByRole("menuitem", { name: "Interactive Search" }),
    );

    await waitFor(() => {
      expect(searchBody).toEqual({
        entity_type: "story_arc_issue",
        entity_id: "arc-issue-9",
      });
    });
    expect(
      await screen.findByRole("heading", { name: "Review releases" }),
    ).toBeTruthy();
  });

  it("moves keyboard focus through menu items and returns it to the trigger on Escape", async () => {
    const user = userEvent.setup();
    render(<ArcIssueTable issues={[arcIssue]} storyArcId="arc-1" />);

    const trigger = screen.getByRole("button", {
      name: "Actions for Absolute Batman #9",
    });
    trigger.focus();
    await user.keyboard("{Enter}");

    const firstItem = await screen.findByRole("menuitem", {
      name: "Interactive Search",
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(firstItem);
    });

    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(
      screen.getByRole("menuitem", { name: "Mark as Read" }),
    );

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("menu")).toBeNull();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });

  it("reaches Confirm with the keyboard after Remove from Arc", async () => {
    let deleted: { storyArcId?: string; issueArcId?: string } | undefined;
    server.use(
      http.delete(
        "/api/storyarcs/:storyArcId/issues/:issueArcId",
        ({ params }) => {
          deleted = params;
          return HttpResponse.json({ success: true });
        },
      ),
    );
    const user = userEvent.setup();
    render(<ArcIssueTable issues={[arcIssue]} storyArcId="arc-1" />);

    const trigger = screen.getByRole("button", {
      name: "Actions for Absolute Batman #9",
    });
    trigger.focus();
    await user.keyboard("{Enter}");

    const remove = await screen.findByRole("menuitem", {
      name: "Remove from Arc",
    });
    remove.focus();
    await user.keyboard("{Enter}");

    const confirm = await screen.findByRole("menuitem", { name: "Confirm" });
    if (document.activeElement !== confirm) {
      await user.keyboard("{ArrowDown}");
    }
    expect(document.activeElement).toBe(confirm);

    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(deleted).toEqual({
        storyArcId: "arc-1",
        issueArcId: "arc-issue-9",
      });
    });
  });
});
