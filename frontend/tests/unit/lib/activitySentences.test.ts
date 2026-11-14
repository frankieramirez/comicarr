import { describe, expect, it } from "vitest";
import {
  actorLabel,
  reasonDetailLine,
  reasonPhrase,
  sentenceFor,
  storyHeadline,
} from "@/components/activity/timeline/sentences";
import type { Story, TimelineEvent } from "@/components/activity/timeline/types";

function event(partial: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    event_id: 1,
    created_at: "2026-07-10 12:00:00",
    activity: "import",
    status: "succeeded",
    subject_type: "issue",
    subject_id: "iss-1",
    subject_label: "Saga #1",
    ...partial,
  };
}

describe("sentenceFor", () => {
  it("uses couldn't-voice for failures", () => {
    expect(
      sentenceFor(event({ activity: "download", status: "failed" })),
    ).toBe("Couldn't download Saga #1");
  });

  it("includes provider on grab.succeeded", () => {
    expect(
      sentenceFor(
        event({
          activity: "grab",
          status: "succeeded",
          provider: "GetComics",
        }),
      ),
    ).toBe("Grabbed Saga #1 from GetComics");
  });
});

describe("reasonPhrase", () => {
  it("maps known codes and degrades unmapped codes without snake_case primary", () => {
    expect(reasonPhrase("disk_full")).toBe(
      "not enough space on the destination volume",
    );
    expect(reasonPhrase("totally_unknown_code_xyz")).toBe(
      "something went wrong",
    );
    expect(reasonPhrase(null)).toBeNull();
  });

  it("exposes the raw token only as expand detail for unmapped codes", () => {
    const line = reasonDetailLine("weird_token", "extra");
    expect(line.phrase).toBe("something went wrong");
    expect(line.rawCode).toBe("weird_token");
    expect(line.detail).toBe("extra");

    const mapped = reasonDetailLine("disk_full", null);
    expect(mapped.phrase).toContain("not enough space");
    expect(mapped.rawCode).toBeNull();
  });
});

describe("storyHeadline", () => {
  it("uses the closer sentence when closed and the last event when open", () => {
    const closed: Story = {
      key: "k",
      subject_type: "issue",
      subject_id: "iss-1",
      subject_label: "Saga #1",
      opened_at: "2026-07-10 10:00:00",
      events: [
        event({ activity: "grab", status: "succeeded", event_id: 1 }),
        event({
          activity: "import",
          status: "failed",
          event_id: 2,
          created_at: "2026-07-10 10:10:00",
        }),
      ],
      closer: event({
        activity: "import",
        status: "failed",
        event_id: 2,
        created_at: "2026-07-10 10:10:00",
      }),
    };
    expect(storyHeadline(closed)).toBe("Couldn't import Saga #1");

    const open: Story = {
      ...closed,
      closer: null,
      events: [event({ activity: "grab", status: "succeeded" })],
    };
    expect(storyHeadline(open)).toBe("Grabbed Saga #1");
  });
});

describe("status changes", () => {
  const change = (partial: Partial<TimelineEvent>) =>
    event({ activity: "status_change", status: "succeeded", ...partial });

  it("reads an issue marked wanted or skipped", () => {
    expect(sentenceFor(change({ reason_detail: "Wanted" }))).toBe(
      "Marked Saga #1 wanted",
    );
    expect(
      sentenceFor(change({ subject_type: "annual", reason_detail: "Skipped" })),
    ).toBe("Marked Saga #1 skipped");
  });

  it("reads a series paused or resumed", () => {
    const series = { subject_type: "series", subject_label: "Saga" };
    expect(sentenceFor(change({ ...series, reason_detail: "Paused" }))).toBe(
      "Paused Saga",
    );
    expect(sentenceFor(change({ ...series, reason_detail: "Active" }))).toBe(
      "Resumed Saga",
    );
  });

  it("names the agent that asked, and nobody for Comicarr's own work", () => {
    expect(actorLabel(change({ actor: "mcp" }))).toBe("via MCP");
    expect(actorLabel(change({ actor: null }))).toBeNull();
    expect(actorLabel(event())).toBeNull();
  });
});
