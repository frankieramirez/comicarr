import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "../test-utils";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MockEventSource } from "../mocks/eventSource";
import { ACTIVITY_STATUS_QUERY_KEY } from "@/lib/activityKeys";
import { ACTIVITY_COALESCE_MS } from "@/lib/activityLive";
import type { TimelineEvent } from "@/components/activity/timeline/types";

const { addToast } = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ addToast }),
}));

const {
  MAX_RECONNECT_DELAY_MS,
  PROLONGED_LOSS_MS,
  useServerEvents,
} = await import("@/hooks/useServerEvents");

function narrative(partial: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    event_id: 1,
    created_at: "2026-08-01T12:00:00+00:00",
    activity: "import",
    status: "succeeded",
    subject_type: "issue",
    subject_id: "9001",
    subject_label: "Saga #12",
    ...partial,
  };
}

/**
 * Like the shared test client, but queries survive without observers — these
 * tests seed the status cache directly, and `gcTime: 0` would collect it
 * before the hook ever reads it back.
 */
function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
        staleTime: 0,
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
      },
    },
  });
}

let queryClient: QueryClient;
let invalidateSpy: ReturnType<typeof vi.spyOn>;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function mount() {
  return renderHook(() => useServerEvents(true), { wrapper });
}

/** Keys passed to invalidateQueries, as "a/b" strings. */
function invalidatedKeys(): string[] {
  return invalidateSpy.mock.calls.map((call) => {
    const filters = call[0] as { queryKey?: readonly unknown[] };
    return (filters.queryKey ?? []).join("/");
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  addToast.mockClear();
  queryClient = createClient();
  invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
});

afterEach(() => {
  // Unmount while the clock is still fake so the hook's cleanup can clear its
  // own reconnect and coalesce timers.
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("listener surface", () => {
  it("listens for activity plus the three surviving system channels", () => {
    mount();
    expect(MockEventSource.latest.registeredTypes.sort()).toEqual([
      "activity",
      "ai_activity",
      "restart",
      "shutdown",
    ]);
  });

  it("registers none of the retired per-feature channels", () => {
    mount();
    const registered = MockEventSource.latest.registeredTypes;
    for (const retired of [
      "addbyid",
      "storyarc_added",
      "search_progress",
      "search_complete",
      "scheduler_message",
      "config_check",
      "check_update",
      "message",
    ]) {
      expect(registered).not.toContain(retired);
    }
  });

  it("opens exactly one stream per tab", () => {
    mount();
    act(() => MockEventSource.latest.open());
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.latest.url).toBe("/api/events/stream");
  });
});

describe("coalesced invalidation", () => {
  it("collapses an event burst into one pass over every activity surface", () => {
    mount();
    act(() => MockEventSource.latest.open());
    invalidateSpy.mockClear();

    act(() => {
      for (let i = 0; i < 40; i += 1) {
        MockEventSource.latest.emit("activity", narrative({ event_id: i }));
      }
    });
    expect(invalidatedKeys()).toEqual([]);

    act(() => vi.advanceTimersByTime(ACTIVITY_COALESCE_MS));
    expect(invalidatedKeys()).toEqual([
      "activity/timeline",
      "activity/band",
      "activity/status",
      "activity/in-flight",
      "wanted",
    ]);
  });

  it("folds collateral into the same pass, deduplicated", () => {
    mount();
    act(() => MockEventSource.latest.open());
    invalidateSpy.mockClear();

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ activity: "add", subject_type: "series", subject_id: "42" }),
      );
      MockEventSource.latest.emit(
        "activity",
        narrative({
          activity: "refresh",
          subject_type: "series",
          subject_id: "42",
        }),
      );
      vi.advanceTimersByTime(ACTIVITY_COALESCE_MS);
    });

    expect(invalidatedKeys()).toEqual([
      "activity/timeline",
      "activity/band",
      "activity/status",
      "activity/in-flight",
      "series",
      "series/42",
      "wanted",
    ]);
  });

  it("keeps the Wanted annotation fresh from issue narration", () => {
    mount();
    act(() => MockEventSource.latest.open());
    invalidateSpy.mockClear();

    act(() => {
      MockEventSource.latest.emit("activity", narrative());
      vi.advanceTimersByTime(ACTIVITY_COALESCE_MS);
    });

    expect(invalidatedKeys()).toContain("wanted");
  });

  it("ignores a malformed frame entirely", () => {
    mount();
    act(() => MockEventSource.latest.open());
    invalidateSpy.mockClear();

    act(() => {
      MockEventSource.latest.emit("activity", "not json");
      MockEventSource.latest.emit("activity", { event_id: 7 });
      vi.advanceTimersByTime(ACTIVITY_COALESCE_MS * 4);
    });

    expect(invalidatedKeys()).toEqual([]);
  });

  it("refetches the same set immediately on reconnect, without replay", () => {
    mount();
    act(() => MockEventSource.latest.open());

    act(() => MockEventSource.latest.fail());
    invalidateSpy.mockClear();
    act(() => vi.advanceTimersByTime(1000));
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => MockEventSource.latest.open());
    expect(invalidatedKeys()).toEqual([
      "activity/timeline",
      "activity/band",
      "activity/status",
      "activity/in-flight",
    ]);
  });

  it("does not refetch on the first connection of the session", () => {
    mount();
    invalidateSpy.mockClear();
    act(() => MockEventSource.latest.open());
    expect(invalidatedKeys()).toEqual([]);
  });
});

describe("enter-trouble toast latch", () => {
  it("interrupts once on the way into trouble, then stays quiet", () => {
    mount();
    act(() => MockEventSource.latest.open());

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ status: "failed", reason_code: "download_failed" }),
      );
    });
    expect(addToast).toHaveBeenCalledTimes(1);
    expect(addToast).toHaveBeenCalledWith({
      type: "error",
      title: "Needs attention",
      description: "Couldn't import Saga #12",
    });

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ event_id: 2, status: "needs_attention" }),
      );
    });
    expect(addToast).toHaveBeenCalledTimes(1);
  });

  it("never toasts normal severity", () => {
    mount();
    act(() => MockEventSource.latest.open());

    act(() => {
      for (const status of ["started", "succeeded", "no_match", "cancelled"]) {
        MockEventSource.latest.emit("activity", narrative({ status }));
      }
    });
    expect(addToast).not.toHaveBeenCalled();
  });

  it("re-arms when the visible attention count clears", () => {
    mount();
    act(() => MockEventSource.latest.open());

    act(() => {
      MockEventSource.latest.emit("activity", narrative({ status: "failed" }));
    });
    expect(addToast).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1);
      queryClient.setQueryData(ACTIVITY_STATUS_QUERY_KEY, {
        in_flight: 0,
        attention: 0,
      });
    });

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ event_id: 3, status: "blocked" }),
      );
    });
    expect(addToast).toHaveBeenCalledTimes(2);
  });

  it("survives its own invalidation reading a stale zero", () => {
    // The status count cached before the burst is still 0 while the refetch
    // it just triggered is in flight. That stale zero must not re-arm.
    queryClient.setQueryData(ACTIVITY_STATUS_QUERY_KEY, {
      in_flight: 0,
      attention: 0,
    });
    mount();
    act(() => MockEventSource.latest.open());

    act(() => {
      MockEventSource.latest.emit("activity", narrative({ status: "failed" }));
      vi.advanceTimersByTime(ACTIVITY_COALESCE_MS);
    });
    expect(addToast).toHaveBeenCalledTimes(1);

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ event_id: 5, status: "needs_attention" }),
      );
      vi.advanceTimersByTime(ACTIVITY_COALESCE_MS);
    });
    expect(addToast).toHaveBeenCalledTimes(1);
  });

  it("stays latched while attention is still visible", () => {
    mount();
    act(() => MockEventSource.latest.open());

    act(() => {
      MockEventSource.latest.emit("activity", narrative({ status: "failed" }));
      vi.advanceTimersByTime(1);
      queryClient.setQueryData(ACTIVITY_STATUS_QUERY_KEY, {
        in_flight: 1,
        attention: 2,
      });
    });

    act(() => {
      MockEventSource.latest.emit(
        "activity",
        narrative({ event_id: 4, status: "blocked" }),
      );
    });
    expect(addToast).toHaveBeenCalledTimes(1);
  });
});

describe("reconnect", () => {
  it("backs off exponentially up to the 64s ceiling", () => {
    mount();
    act(() => MockEventSource.latest.open());

    for (const delay of [1000, 2000, 4000, 8000, 16000, 32000]) {
      const before = MockEventSource.instances.length;
      act(() => MockEventSource.latest.fail());
      act(() => vi.advanceTimersByTime(delay - 1));
      expect(MockEventSource.instances).toHaveLength(before);
      act(() => vi.advanceTimersByTime(1));
      expect(MockEventSource.instances).toHaveLength(before + 1);
    }

    // Ladder has reached the ceiling and stays there.
    for (let round = 0; round < 3; round += 1) {
      const before = MockEventSource.instances.length;
      act(() => MockEventSource.latest.fail());
      act(() => vi.advanceTimersByTime(MAX_RECONNECT_DELAY_MS - 1));
      expect(MockEventSource.instances).toHaveLength(before);
      act(() => vi.advanceTimersByTime(1));
      expect(MockEventSource.instances).toHaveLength(before + 1);
    }
  });

  it("retries immediately on focus instead of waiting out the ceiling", () => {
    mount();
    act(() => MockEventSource.latest.open());
    act(() => MockEventSource.latest.fail());
    const parked = MockEventSource.instances.length;

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(MockEventSource.instances).toHaveLength(parked + 1);
  });

  it("leaves a healthy stream alone on focus", () => {
    mount();
    act(() => MockEventSource.latest.open());
    const before = MockEventSource.instances.length;

    act(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(MockEventSource.instances).toHaveLength(before);
  });
});

describe("connection health", () => {
  it("stays quiet through a brief drop and reports a prolonged one", () => {
    const { result } = mount();
    act(() => MockEventSource.latest.open());
    expect(result.current.live).toBe("connected");

    act(() => MockEventSource.latest.fail());
    expect(result.current.isReconnecting).toBe(true);
    expect(result.current.live).toBe("reconnecting");

    act(() => vi.advanceTimersByTime(PROLONGED_LOSS_MS));
    expect(result.current.connectionLost).toBe(true);
    expect(result.current.live).toBe("lost");

    act(() => MockEventSource.latest.open());
    expect(result.current.live).toBe("connected");
    expect(result.current.connectionLost).toBe(false);
  });
});
