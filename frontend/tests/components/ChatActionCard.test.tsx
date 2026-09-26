import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderMinimal, screen } from "../test-utils";
import { ChatActionCard } from "@/components/ai/ChatActionCard";
import { confirmChatAction } from "@/lib/chatApi";
import type { ChatAction } from "@/types/chat";

vi.mock("@/lib/chatApi", () => ({
  confirmChatAction: vi.fn(),
  dismissChatAction: vi.fn(),
}));
const pending: ChatAction = {
  action_id: "mark_issues",
  status: "pending",
  summary: "Mark two issues Wanted",
};
const partial: ChatAction = {
  ...pending,
  status: "partial",
  preview: {
    issues: [
      { issue_id: "1", kind: "issue", number: "1" },
      { issue_id: "2", kind: "issue", number: "2" },
    ],
  },
  result: {
    success: false,
    message: "Marked 1 issue Wanted. 1 search could not be queued.",
    applied: 1,
    search_failed: 1,
    retryable: true,
    items: [
      {
        issue_id: "1",
        kind: "issue",
        outcome: "applied",
        search_handoff: "failed",
      },
      { issue_id: "2", kind: "issue", outcome: "failed", search_handoff: null },
    ],
  },
};
function Card({ initial = pending }: { initial?: ChatAction }) {
  const [action, setAction] = useState(initial);
  return (
    <ChatActionCard
      action={action}
      threadId="thread-1"
      messageId="message-1"
      onActionChange={setAction}
    />
  );
}
describe("ChatActionCard", () => {
  beforeEach(() => vi.resetAllMocks());
  it("shows partial confirmation and retries unfinished work to completion", async () => {
    const user = userEvent.setup();
    vi.mocked(confirmChatAction)
      .mockResolvedValueOnce({ action: partial })
      .mockResolvedValueOnce({
        action: {
          ...pending,
          status: "confirmed",
          result: { success: true, message: "Marked 2 issues Wanted." },
        },
      });
    renderMinimal(<Card />);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      partial.result!.message!,
    );
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Retry unfinished" }));
    expect(await screen.findByText("Marked 2 issues Wanted.")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Retry unfinished" }),
    ).toBeNull();
    expect(confirmChatAction).toHaveBeenCalledTimes(2);
    expect(confirmChatAction).toHaveBeenLastCalledWith(
      "thread-1",
      "message-1",
      { comicid: undefined },
    );
  });
  it("restores partial outcomes and retry controls from persisted state", () => {
    renderMinimal(<Card initial={partial} />);
    expect(screen.getByRole("alert").textContent).toContain(
      partial.result!.message!,
    );
    expect(
      screen
        .getByRole("button", { name: "Retry unfinished" })
        .hasAttribute("disabled"),
    ).toBe(false);
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });
  it("shows a failed retry's error alongside its partial result message", async () => {
    vi.mocked(confirmChatAction).mockResolvedValue({
      action: {
        ...partial,
        result: {
          ...partial.result,
          message: "One issue still needs a search.",
          error: "Search provider is unavailable.",
        },
      },
    });
    renderMinimal(<Card initial={partial} />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Retry unfinished" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("One issue still needs a search.");
    expect(alert.textContent).toContain("Search provider is unavailable.");
  });
  it("shows which issues still need a status update or search handoff", () => {
    renderMinimal(<Card initial={partial} />);
    expect(screen.getByText("#1 · Search not queued")).toBeTruthy();
    expect(screen.getByText("#2 · Update failed")).toBeTruthy();
  });
  it("prioritizes unfinished issues and bounds large partial previews", () => {
    const issues = Array.from({ length: 50 }, (_, index) => ({
      issue_id: String(index),
      kind: "issue" as const,
      number: String(index),
    }));
    renderMinimal(
      <Card
        initial={{
          ...partial,
          preview: { issues },
          result: {
            ...partial.result,
            items: [
              {
                issue_id: "49",
                kind: "issue",
                outcome: "failed",
                search_handoff: null,
              },
            ],
          },
        }}
      />,
    );
    expect(screen.getByText("#49 · Update failed")).toBeTruthy();
    expect(screen.getByText("+10 more")).toBeTruthy();
    expect(screen.queryByText("#48")).toBeNull();
  });
  it("does not offer retries unless a partial result permits them", () => {
    renderMinimal(
      <Card
        initial={{
          ...partial,
          result: { ...partial.result, retryable: false },
        }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      partial.result!.message!,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("shows a pending selection error and clears it after successful confirmation", async () => {
    const proposal: ChatAction = {
      action_id: "add_series",
      status: "pending",
      preview: { candidates: [{ comicid: "123", name: "Batman" }] },
    };
    vi.mocked(confirmChatAction)
      .mockResolvedValueOnce({
        action: {
          ...proposal,
          result: { error: "Choose a current candidate." },
        },
      })
      .mockResolvedValueOnce({
        action: {
          ...proposal,
          status: "confirmed",
          result: { message: "Added Batman." },
        },
      });
    renderMinimal(<Card initial={proposal} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Batman/ }));
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Choose a current candidate.",
    );
    expect(
      screen.getByRole("button", { name: "Confirm" }).hasAttribute("disabled"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Added Batman.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("renders the stored terminal error message", () => {
    renderMinimal(
      <Card
        initial={{
          ...pending,
          status: "error",
          result: {
            success: false,
            message: "The provider rejected this series.",
          },
        }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "The provider rejected this series.",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("prevents replay while the server is processing", () => {
    renderMinimal(<Card initial={{ ...pending, status: "processing" }} />);
    expect(screen.getByRole("status").textContent).toContain(
      "Confirmation is in progress.",
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(confirmChatAction).not.toHaveBeenCalled();
  });
  it("disables retries while the confirmation request is in flight", async () => {
    vi.mocked(confirmChatAction).mockReturnValue(new Promise(() => {}));
    renderMinimal(<Card initial={partial} />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Retry unfinished" }));
    expect(
      screen
        .getByRole("button", { name: "Retry unfinished" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});
