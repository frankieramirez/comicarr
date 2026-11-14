import { describe, expect, it } from "vitest";
import {
  buildFeed,
  isOpen,
  subjectHref,
  storyHasTrouble,
} from "@/components/activity/timeline/stories";
import type { TimelineEvent } from "@/components/activity/timeline/types";

function event(
  overrides: Partial<TimelineEvent> &
    Pick<TimelineEvent, "event_id" | "created_at" | "activity" | "status">,
): TimelineEvent {
  return {
    subject_type: "issue",
    subject_id: "iss-1",
    subject_label: "Saga #1",
    parent_series_id: "ser-1",
    ...overrides,
  };
}

describe("buildFeed", () => {
  it("renders a group-of-one as a plain closed row", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 12:00:00",
        activity: "add",
        status: "succeeded",
        subject_type: "series",
        subject_id: "ser-1",
        subject_label: "Saga",
      }),
    ]);

    expect(nodes).toHaveLength(1);
    expect(nodes[0].events).toHaveLength(1);
    expect(nodes[0].closer?.activity).toBe("add");
    expect(isOpen(nodes[0])).toBe(false);
  });

  it("groups advances into one story and closes on a terminal pair", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 10:00:00",
        activity: "grab",
        status: "succeeded",
        provider: "DDL",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 10:05:00",
        activity: "download",
        status: "succeeded",
      }),
      event({
        event_id: 3,
        created_at: "2026-07-10 10:10:00",
        activity: "import",
        status: "succeeded",
      }),
    ]);

    expect(nodes).toHaveLength(1);
    expect(nodes[0].events).toHaveLength(3);
    expect(nodes[0].opened_at).toBe("2026-07-10 10:00:00");
    expect(nodes[0].closer?.activity).toBe("import");
    expect(nodes[0].closer?.status).toBe("succeeded");
    expect(isOpen(nodes[0])).toBe(false);
  });

  it("opens a second story after a terminal close (retry never reopens)", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 10:00:00",
        activity: "grab",
        status: "succeeded",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 10:05:00",
        activity: "download",
        status: "failed",
        reason_code: "download_failed",
      }),
      event({
        event_id: 3,
        created_at: "2026-07-10 11:00:00",
        activity: "grab",
        status: "succeeded",
      }),
    ]);

    expect(nodes).toHaveLength(2);
    // Newest-first feed order.
    expect(nodes[0].opened_at).toBe("2026-07-10 11:00:00");
    expect(isOpen(nodes[0])).toBe(true);
    expect(nodes[1].opened_at).toBe("2026-07-10 10:00:00");
    expect(storyHasTrouble(nodes[1])).toBe(true);
  });

  it("keeps position by opening time (nothing re-sorts on closer)", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 09:00:00",
        activity: "grab",
        status: "succeeded",
        subject_id: "iss-a",
        subject_label: "A",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 10:00:00",
        activity: "add",
        status: "succeeded",
        subject_type: "series",
        subject_id: "ser-x",
        subject_label: "X",
      }),
      event({
        event_id: 3,
        created_at: "2026-07-10 11:00:00",
        activity: "import",
        status: "succeeded",
        subject_id: "iss-a",
        subject_label: "A",
      }),
    ]);

    // Opening times: A@09, X@10. Closer for A is 11 — A still sorts by open.
    expect(nodes.map((n) => n.subject_label)).toEqual(["X", "A"]);
    expect(nodes[1].opened_at).toBe("2026-07-10 09:00:00");
    expect(nodes[1].closer?.created_at).toBe("2026-07-10 11:00:00");
  });

  it("groups run search.started with its terminal closer", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 08:00:00",
        activity: "search",
        status: "started",
        subject_type: "run",
        subject_id: "run-1",
        subject_label: "Wanted backlog",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 08:30:00",
        activity: "search",
        status: "succeeded",
        subject_type: "run",
        subject_id: "run-1",
        subject_label: "Wanted backlog",
      }),
    ]);

    expect(nodes).toHaveLength(1);
    expect(nodes[0].events).toHaveLength(2);
    expect(nodes[0].closer?.status).toBe("succeeded");
  });

  it("accepts newest-first API order without mis-grouping", () => {
    const nodes = buildFeed([
      event({
        event_id: 3,
        created_at: "2026-07-10 10:10:00",
        activity: "import",
        status: "succeeded",
      }),
      event({
        event_id: 1,
        created_at: "2026-07-10 10:00:00",
        activity: "grab",
        status: "succeeded",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 10:05:00",
        activity: "download",
        status: "succeeded",
      }),
    ]);

    expect(nodes).toHaveLength(1);
    expect(nodes[0].events.map((e) => e.event_id)).toEqual([1, 2, 3]);
  });
});

describe("subjectHref", () => {
  it("builds series and issue deep links when identity is complete", () => {
    expect(
      subjectHref({
        subject_type: "series",
        subject_id: "ser-1",
      }),
    ).toBe("/library/ser-1");
    expect(
      subjectHref({
        subject_type: "issue",
        subject_id: "iss-1",
        parent_series_id: "ser-1",
      }),
    ).toBe("/library/ser-1/issue/iss-1");
    expect(
      subjectHref({
        subject_type: "issue",
        subject_id: "iss-1",
        parent_series_id: null,
      }),
    ).toBeNull();
    expect(
      subjectHref({
        subject_type: "run",
        subject_id: "run-1",
      }),
    ).toBeNull();
  });

  it("keeps a status change out of an open download story", () => {
    const nodes = buildFeed([
      event({
        event_id: 1,
        created_at: "2026-07-10 12:00:00",
        activity: "grab",
        status: "succeeded",
      }),
      event({
        event_id: 2,
        created_at: "2026-07-10 12:01:00",
        activity: "status_change",
        status: "succeeded",
        reason_detail: "Skipped",
        actor: "mcp",
      }),
    ]);
    expect(nodes).toHaveLength(2);
    const [change, grab] = nodes;
    expect(change.events.map((e) => e.event_id)).toEqual([2]);
    expect(isOpen(change)).toBe(false);
    expect(grab.events.map((e) => e.event_id)).toEqual([1]);
    expect(isOpen(grab)).toBe(true);
  });
});
