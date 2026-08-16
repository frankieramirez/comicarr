import { describe, expect, it } from "vitest";
import {
  formatQuietStatus,
  liveAnnouncement,
  type ActivityStatusSnapshot,
} from "@/lib/activityStatus";

function snap(
  partial: Partial<ActivityStatusSnapshot> = {},
): ActivityStatusSnapshot {
  return {
    librarySeries: 412,
    api: "online",
    inFlight: 0,
    attention: 0,
    live: "connected",
    ...partial,
  };
}

describe("formatQuietStatus", () => {
  it("renders idle when open-work and attention are zero", () => {
    const meta = formatQuietStatus(snap({}));
    expect(meta.line).toBe("library: 412 series · api: online · idle");
    expect(meta.segments.find((s) => s.role === "idle")?.href).toBe(
      "/activity",
    );
    expect(meta.segments.some((s) => s.role === "attention")).toBe(false);
  });

  it("renders M in flight for non-zero open work", () => {
    const meta = formatQuietStatus(snap({ inFlight: 5 }));
    expect(meta.line).toBe("library: 412 series · api: online · 5 in flight");
    expect(meta.segments.find((s) => s.role === "activity")?.href).toBe(
      "/activity?state=in_flight",
    );
  });

  it("appends attention only when K > 0", () => {
    const withAttention = formatQuietStatus(
      snap({ inFlight: 3, attention: 2 }),
    );
    expect(withAttention.line).toBe(
      "library: 412 series · api: online · 3 in flight · ⚠ 2 need attention",
    );
    // Attention lands on the triage route — the only reason to click it is to
    // work through the problems, not to read the timeline.
    expect(
      withAttention.segments.find((s) => s.role === "attention")?.href,
    ).toBe("/activity/attention");

    const noAttention = formatQuietStatus(snap({ inFlight: 3, attention: 0 }));
    expect(noAttention.line).toBe(
      "library: 412 series · api: online · 3 in flight",
    );
    expect(noAttention.segments.some((s) => s.role === "attention")).toBe(
      false,
    );
  });

  it("keeps idle when only attention is non-zero", () => {
    const meta = formatQuietStatus(snap({ inFlight: 0, attention: 1 }));
    expect(meta.line).toBe(
      "library: 412 series · api: online · idle · ⚠ 1 need attention",
    );
  });

  it("renders unreachable when library and api are both down", () => {
    const meta = formatQuietStatus(
      snap({ librarySeries: null, api: "offline" }),
    );
    expect(meta.line).toBe("library: unavailable · api: offline · unreachable");
    expect(meta.segments.find((s) => s.role === "activity")?.href).toBe(
      "/activity",
    );
    expect(meta.segments.some((s) => s.role === "attention")).toBe(false);
  });

  it("renders unreachable on prolonged live-channel loss alone", () => {
    const meta = formatQuietStatus(snap({ live: "lost", inFlight: 4 }));
    expect(meta.line).toBe("library: 412 series · api: online · unreachable");
    expect(meta.segments.some((s) => s.role === "attention")).toBe(false);
  });

  it("stays quiet while the live channel is merely reconnecting", () => {
    const meta = formatQuietStatus(snap({ live: "reconnecting", inFlight: 4 }));
    expect(meta.line).toBe("library: 412 series · api: online · 4 in flight");
  });

  it("uses singular series label for one series", () => {
    const meta = formatQuietStatus(snap({ librarySeries: 1 }));
    expect(meta.line).toBe("library: 1 series · api: online · idle");
  });

  it("does not make library or api segments links", () => {
    const meta = formatQuietStatus(snap({ inFlight: 2, attention: 1 }));
    expect(
      meta.segments.find((s) => s.role === "library")?.href,
    ).toBeUndefined();
    expect(meta.segments.find((s) => s.role === "api")?.href).toBeUndefined();
  });
});

describe("liveAnnouncement", () => {
  it("is silent for mid-flight count ticks", () => {
    expect(liveAnnouncement(snap({ inFlight: 3 }), snap({ inFlight: 4 }))).toBe(
      "",
    );
  });

  it("announces idle↔busy edges", () => {
    expect(liveAnnouncement(snap({}), snap({ inFlight: 2 }))).toBe(
      "2 in flight",
    );
    expect(liveAnnouncement(snap({ inFlight: 2 }), snap({}))).toBe("Idle");
  });

  it("announces attention appear/change/clear", () => {
    expect(liveAnnouncement(snap({}), snap({ attention: 2 }))).toBe(
      "2 need attention",
    );
    expect(
      liveAnnouncement(snap({ attention: 2 }), snap({ attention: 3 })),
    ).toBe("3 need attention");
    expect(liveAnnouncement(snap({ attention: 2 }), snap({}))).toBe(
      "Attention cleared",
    );
  });

  it("announces offline and recovery", () => {
    expect(
      liveAnnouncement(snap({}), snap({ api: "offline", librarySeries: null })),
    ).toBe("API offline");
    expect(
      liveAnnouncement(snap({ api: "offline", librarySeries: null }), snap({})),
    ).toBe("API online");
  });

  it("announces prolonged live-channel loss and recovery ahead of counts", () => {
    expect(
      liveAnnouncement(snap({}), snap({ live: "lost", attention: 3 })),
    ).toBe("Server unreachable");
    expect(liveAnnouncement(snap({ live: "lost" }), snap({}))).toBe(
      "Reconnected",
    );
  });

  it("says nothing for a brief reconnect", () => {
    expect(liveAnnouncement(snap({}), snap({ live: "reconnecting" }))).toBe("");
    expect(liveAnnouncement(snap({ live: "reconnecting" }), snap({}))).toBe("");
  });
});
