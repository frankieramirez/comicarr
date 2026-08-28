import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import type { ActivityStatusResponse } from "@/hooks/useActivityStatus";
import {
  ACTIVITY_INVALIDATION_KEYS,
  ACTIVITY_STATUS_QUERY_KEY,
} from "@/lib/activityKeys";
import type { LiveConnectionState } from "@/lib/activityStatus";
import {
  ACTIVITY_COALESCE_MS,
  NO_TROUBLE,
  collateralKeys,
  comicAddedDetail,
  latchOnAttention,
  latchOnEvent,
  parseActivityEvent,
  type TroubleLatch,
} from "@/lib/activityLive";

export type { LiveConnectionState };

/** Reconnect backoff ceiling — a sleeping tab must not hammer the server. */
export const MAX_RECONNECT_DELAY_MS = 64_000;

/**
 * How long the socket must stay down before the status chrome calls it.
 * Below this a drop is silent: the 30s polls still carry every surface, so
 * a blip is not worth alarming the operator about (ADR §8, brief disconnect).
 */
export const PROLONGED_LOSS_MS = 60_000;

type UseServerEventsReturn = {
  isConnected: boolean;
  isReconnecting: boolean;
  /** Connection has been down long enough for the status chrome to say so. */
  connectionLost: boolean;
  live: LiveConnectionState;
};

/**
 * The app's one EventSource (ADR §8 — per-tab, never a second stream).
 *
 * `activity` is the only narrative channel. Its payload drives coalesced
 * invalidation and the enter-trouble toast latch; it is never accumulated
 * into a list, because every activity surface is query-backed. Auth rides
 * the JWT cookie, so no separate SSE key is needed.
 */
export function useServerEvents(enabled = true): UseServerEventsReturn {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const lossTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coalesceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(1000); // Start with 1 second
  const hasConnectedRef = useRef(false); // Track if we've connected before
  const latchRef = useRef<TroubleLatch>(NO_TROUBLE);

  useEffect(() => {
    if (!enabled) return;
    const syncLatch = () => {
      const state = queryClient.getQueryState<ActivityStatusResponse>(
        ACTIVITY_STATUS_QUERY_KEY,
      );
      latchRef.current = latchOnAttention(
        latchRef.current,
        state?.data?.attention,
        state?.dataUpdatedAt ?? 0,
      );
    };
    syncLatch();
    return queryClient.getQueryCache().subscribe(syncLatch);
  }, [enabled, queryClient]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let isMounted = true;

    const pendingCollateral = new Map<string, string[]>();

    /**
     * Refetch the narrative feed and every projection derived beside it, as
     * one batch. Also flushes whatever collateral caches the coalesced burst
     * touched (series/arc adds and refreshes).
     */
    const invalidateActivitySurfaces = () => {
      if (coalesceTimeoutRef.current) {
        clearTimeout(coalesceTimeoutRef.current);
        coalesceTimeoutRef.current = null;
      }
      for (const queryKey of ACTIVITY_INVALIDATION_KEYS) {
        queryClient.invalidateQueries({ queryKey });
      }
      for (const queryKey of pendingCollateral.values()) {
        queryClient.invalidateQueries({ queryKey });
      }
      pendingCollateral.clear();
    };

    /**
     * One invalidation pass per window, however many events land in it — a run
     * that grabs forty issues costs one refetch round, not forty.
     */
    const scheduleActivityInvalidation = () => {
      if (coalesceTimeoutRef.current) return;
      coalesceTimeoutRef.current = setTimeout(() => {
        coalesceTimeoutRef.current = null;
        invalidateActivitySurfaces();
      }, ACTIVITY_COALESCE_MS);
    };

    const markDisconnected = ({ retry }: { retry: boolean }) => {
      setIsConnected(false);
      setIsReconnecting(retry);

      if (!lossTimeoutRef.current) {
        lossTimeoutRef.current = setTimeout(() => {
          lossTimeoutRef.current = null;
          if (isMounted) setConnectionLost(true);
        }, PROLONGED_LOSS_MS);
      }
    };

    const setupEventSource = () => {
      if (!isMounted) return;

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const apiUrl = `/api/events/stream`;
      console.log("[SSE] Connecting to:", apiUrl);

      const evtSource = new EventSource(apiUrl);
      eventSourceRef.current = evtSource;

      evtSource.onopen = () => {
        console.log("[SSE] Connection established");
        setIsConnected(true);
        setIsReconnecting(false);
        setConnectionLost(false);
        if (lossTimeoutRef.current) {
          clearTimeout(lossTimeoutRef.current);
          lossTimeoutRef.current = null;
        }

        if (hasConnectedRef.current) {
          invalidateActivitySurfaces();

          fetch("/api/auth/check-session")
            .then((r) => r.json())
            .then((data) => {
              if (!data.authenticated) {
                evtSource.close();
                window.location.href = "/login";
              }
            })
            .catch(() => {});
        }

        hasConnectedRef.current = true;
        reconnectDelayRef.current = 1000;
      };

      evtSource.onerror = () => {
        console.error("[SSE] Connection error");
        evtSource.close();
        markDisconnected({ retry: isMounted });

        if (isMounted) {
          const delay = reconnectDelayRef.current;
          console.log(`[SSE] Reconnecting in ${delay}ms...`);
          reconnectTimeoutRef.current = setTimeout(() => {
            setupEventSource();
          }, delay);

          reconnectDelayRef.current = Math.min(
            delay * 2,
            MAX_RECONNECT_DELAY_MS,
          );
        }
      };

      evtSource.addEventListener("activity", (e: MessageEvent) => {
        const event = parseActivityEvent(e.data);
        if (!event) return;

        for (const queryKey of collateralKeys(event)) {
          pendingCollateral.set(queryKey.join("/"), queryKey);
        }
        scheduleActivityInvalidation();

        const detail = comicAddedDetail(event);
        if (detail) {
          window.dispatchEvent(new CustomEvent("comic-added", { detail }));
        }

        const { latch, toast } = latchOnEvent(
          latchRef.current,
          event,
          Date.now(),
        );
        latchRef.current = latch;
        if (toast) {
          addToast({
            type: "error",
            title: toast.title,
            description: toast.description,
          });
        }
      });

      evtSource.addEventListener("ai_activity", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          JSON.parse(e.data);
          queryClient.invalidateQueries({ queryKey: ["ai", "activity"] });
          queryClient.invalidateQueries({ queryKey: ["ai", "status"] });
          queryClient.invalidateQueries({ queryKey: ["dashboard"] });
        } catch (error) {
          console.error("[SSE] Error parsing ai_activity event:", error);
        }
      });

      evtSource.addEventListener("restart", () => {
        console.log("[SSE] Server restarting");

        addToast({
          type: "info",
          title: "Server Restarting",
          description: "Comicarr is restarting. Reconnecting automatically…",
        });
      });

      evtSource.addEventListener("shutdown", () => {
        console.log("[SSE] Server shutting down");

        addToast({
          type: "error",
          title: "Server Shutting Down",
          description: "The server is shutting down. Please wait...",
        });

        evtSource.close();
        markDisconnected({ retry: false });
      });
    };

    /**
     * A backgrounded tab can be parked on the 64s ceiling when the operator
     * comes back. Returning to the tab is a signal the server may be up, so
     * retry now and reset the ladder instead of serving stale data.
     */
    const retryIfDisconnected = () => {
      if (!isMounted || document.hidden) return;
      const current = eventSourceRef.current;
      if (current && current.readyState !== EventSource.CLOSED) return;
      reconnectDelayRef.current = 1000;
      setupEventSource();
    };

    document.addEventListener("visibilitychange", retryIfDisconnected);
    window.addEventListener("focus", retryIfDisconnected);

    setupEventSource();

    return () => {
      isMounted = false;

      document.removeEventListener("visibilitychange", retryIfDisconnected);
      window.removeEventListener("focus", retryIfDisconnected);

      for (const timer of [
        reconnectTimeoutRef,
        lossTimeoutRef,
        coalesceTimeoutRef,
      ]) {
        if (timer.current) {
          clearTimeout(timer.current);
          timer.current = null;
        }
      }
      pendingCollateral.clear();

      if (eventSourceRef.current) {
        console.log("[SSE] Closing connection");
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [enabled, queryClient, addToast]);

  const live: LiveConnectionState = connectionLost
    ? "lost"
    : !isConnected && isReconnecting
      ? "reconnecting"
      : "connected";

  return { isConnected, isReconnecting, connectionLost, live };
}
