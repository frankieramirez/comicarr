import { describe, it, expect } from "vitest";
import {
  applySequentially,
  describeBulkResult,
  type BulkIssueResult,
} from "@/hooks/useQueue";

/**
 * Bulk queue/unqueue applies one request per issue in sequence. A failure part
 * way through leaves the earlier issues already applied, so reporting the whole
 * batch as failed -- and keeping every id selected for the retry -- would tell
 * the user nothing happened and then repeat the requests that succeeded.
 */

function result(overrides: Partial<BulkIssueResult> = {}): BulkIssueResult {
  return { succeeded: [], failed: [], ...overrides };
}

describe("applySequentially", () => {
  it("applies every id in order and reports them all as succeeded", async () => {
    const applied: string[] = [];

    const outcome = await applySequentially(
      ["issue-1", "issue-2", "issue-3"],
      async (id) => {
        applied.push(id);
      },
    );

    expect(applied).toEqual(["issue-1", "issue-2", "issue-3"]);
    expect(outcome).toEqual({
      succeeded: ["issue-1", "issue-2", "issue-3"],
      failed: [],
    });
  });

  it("keeps going after a failure instead of abandoning the rest of the batch", async () => {
    const applied: string[] = [];

    const outcome = await applySequentially(
      ["issue-1", "issue-2", "issue-3"],
      async (id) => {
        applied.push(id);
        if (id === "issue-2") throw new Error("Issue not found");
      },
    );

    // The old loop threw on issue-2 and never attempted issue-3.
    expect(applied).toEqual(["issue-1", "issue-2", "issue-3"]);
    expect(outcome).toEqual({
      succeeded: ["issue-1", "issue-3"],
      failed: [{ id: "issue-2", error: "Issue not found" }],
    });
  });

  it("records a non-Error rejection without losing the batch", async () => {
    const outcome = await applySequentially(["issue-1"], () =>
      Promise.reject("boom"),
    );

    expect(outcome.failed).toEqual([{ id: "issue-1", error: "Unknown error" }]);
  });
});

describe("describeBulkResult", () => {
  it("reports a clean batch as a success and clears the selection", () => {
    expect(
      describeBulkResult(
        result({ succeeded: ["issue-1", "issue-2"] }),
        "skipped",
        "skip",
      ),
    ).toEqual({ type: "success", message: "2 issues skipped", keep: [] });
  });

  it("singularizes a one-issue batch", () => {
    expect(
      describeBulkResult(result({ succeeded: ["issue-1"] }), "queued", "queue")
        .message,
    ).toBe("1 issue queued");
  });

  it("reports partial progress and keeps only the failed ids selected", () => {
    const { type, message, keep } = describeBulkResult(
      result({
        succeeded: ["issue-1", "issue-2"],
        failed: [{ id: "issue-3", error: "Issue not found" }],
      }),
      "skipped",
      "skip",
    );

    expect(type).toBe("info");
    expect(message).toContain("2 of 3 issues skipped");
    expect(message).toContain("Issue not found");
    // A retry must not re-issue the two PUTs that already landed.
    expect(keep).toEqual(["issue-3"]);
  });

  it("reports a total failure as an error and keeps the whole selection", () => {
    const { type, message, keep } = describeBulkResult(
      result({
        failed: [
          { id: "issue-1", error: "Unauthorized" },
          { id: "issue-2", error: "Unauthorized" },
        ],
      }),
      "queued",
      "queue",
    );

    expect(type).toBe("error");
    expect(message).toBe("Failed to queue issues: Unauthorized");
    expect(keep).toEqual(["issue-1", "issue-2"]);
  });
});
