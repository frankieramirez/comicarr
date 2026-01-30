import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import type {
  AddByIdEventData,
  SchedulerMessageEventData,
  ConfigCheckEventData,
  CheckUpdateEventData,
  SearchProgressEventData,
  SearchCompleteEventData,
  MessageEventData,
} from "@/types";

type UseServerEventsReturn = object;

/**
 * Hook to manage Server-Sent Events (SSE) connection for real-time updates
 */
export function useServerEvents(
  sseKey: string | null,
  enabled = true,
): UseServerEventsReturn {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const reconnectDelayRef = useRef(1000); // Start with 1 second

  useEffect(() => {
    if (!enabled || !sseKey) {
      return;
    }

    let isMounted = true;

    const setupEventSource = () => {
      if (!isMounted) return;

      // Clean up existing connection
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const apiUrl = `/api?cmd=checkGlobalMessages&apikey=${sseKey}`;
      console.log("[SSE] Connecting to:", apiUrl);

      const evtSource = new EventSource(apiUrl);
      eventSourceRef.current = evtSource;

      evtSource.onopen = () => {
        console.log("[SSE] Connection established");
        reconnectDelayRef.current = 1000; // Reset reconnect delay on successful connection
      };

      evtSource.onerror = () => {
        console.error("[SSE] Connection error");
        evtSource.close();

        // Attempt to reconnect with exponential backoff
        if (isMounted) {
          const delay = reconnectDelayRef.current;
          console.log(`[SSE] Reconnecting in ${delay}ms...`);
          reconnectTimeoutRef.current = setTimeout(() => {
            setupEventSource();
          }, delay);

          // Increase delay for next reconnect, max 64 seconds
          reconnectDelayRef.current = Math.min(delay * 2, 64000);
        }
      };

      // Event: addbyid - When a new series is added
      evtSource.addEventListener("addbyid", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: AddByIdEventData = JSON.parse(e.data);
          console.log("[SSE] addbyid event:", data);

          // Don't invalidate cache for mid-message events (progress updates)
          if (data.status === "mid-message-event") {
            return;
          }

          // Invalidate series cache if tables='both' or 'tables'
          if (data.tables === "both" || data.tables === "tables") {
            queryClient.invalidateQueries({ queryKey: ["series"] });
            // Also invalidate specific series detail if we have comicid
            if (data.comicid) {
              queryClient.invalidateQueries({
                queryKey: ["series", data.comicid],
              });
            }
          }

          // Dispatch custom event for ComicCard to handle navigation
          // Only dispatch when import is complete (tables is truthy and not 'None')
          if (
            data.comicid &&
            (data.status === "success" || data.status === "failure") &&
            data.tables &&
            data.tables !== "None"
          ) {
            window.dispatchEvent(
              new CustomEvent("comic-added", { detail: JSON.stringify(data) }),
            );
          }

          // Show success toast with series name (only for non-mid-message events)
          if (data.comicname && data.status === "success" && data.tables) {
            addToast({
              type: "success",
              title: "Series Added",
              description: `${data.comicname} (${data.seriesyear || "Unknown"}) has been added successfully.`,
            });
          }
        } catch (error) {
          console.error("[SSE] Error parsing addbyid event:", error);
        }
      });

      // Event: scheduler_message - Background task notifications
      evtSource.addEventListener("scheduler_message", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: SchedulerMessageEventData = JSON.parse(e.data);
          console.log("[SSE] scheduler_message event:", data);

          if (data.message) {
            addToast({
              type: data.status === "success" ? "success" : "error",
              title:
                data.status === "success" ? "Task Complete" : "Task Failed",
              description: data.message,
            });
          }
        } catch (error) {
          console.error("[SSE] Error parsing scheduler_message event:", error);
        }
      });

      // Event: config_check - Configuration validation messages
      evtSource.addEventListener("config_check", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: ConfigCheckEventData = JSON.parse(e.data);
          console.log("[SSE] config_check event:", data);

          // Invalidate config cache
          queryClient.invalidateQueries({ queryKey: ["config"] });

          // Note: Original implementation shows a modal dialog
          // For now, we'll just log it. Could add a modal later if needed.
        } catch (error) {
          console.error("[SSE] Error parsing config_check event:", error);
        }
      });

      // Event: check_update - Version update notifications
      evtSource.addEventListener("check_update", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: CheckUpdateEventData = JSON.parse(e.data);
          console.log("[SSE] check_update event:", data);

          const commitsBehind = parseInt(String(data.commits_behind), 10);
          if (
            commitsBehind > 0 &&
            data.current_version !== data.latest_version
          ) {
            addToast({
              type: "info",
              title: "Update Available",
              description: `A newer version is available. You are ${commitsBehind} commits behind.`,
            });
          } else if (commitsBehind === 0) {
            addToast({
              type: "success",
              title: "Up to Date",
              description: "Mylar is up to date.",
            });
          }
        } catch (error) {
          console.error("[SSE] Error parsing check_update event:", error);
        }
      });

      // Event: search_progress - Live search progress updates
      evtSource.addEventListener("search_progress", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: SearchProgressEventData = JSON.parse(e.data);
          console.log("[SSE] search_progress event:", data);

          // Don't show toast for progress events, just log them
          // Could be used to update a progress bar in the UI later
        } catch (error) {
          console.error("[SSE] Error parsing search_progress event:", error);
        }
      });

      // Event: search_complete - Search completion notification
      evtSource.addEventListener("search_complete", (e: MessageEvent) => {
        if (!e.data) return;

        try {
          const data: SearchCompleteEventData = JSON.parse(e.data);
          console.log("[SSE] search_complete event:", data);

          const resultCount = data.result_count || 0;
          addToast({
            type: "success",
            title: "Search Complete",
            description: `Found ${resultCount} result${resultCount !== 1 ? "s" : ""}.`,
          });
        } catch (error) {
          console.error("[SSE] Error parsing search_complete event:", error);
        }
      });

      // Event: shutdown - Server shutdown notification
      evtSource.addEventListener("shutdown", () => {
        console.log("[SSE] Server shutting down");

        addToast({
          type: "error",
          title: "Server Shutting Down",
          description: "The server is shutting down. Please wait...",
        });

        evtSource.close();
      });

      // Event: message - Default/generic message handler
      evtSource.addEventListener("message", (e: MessageEvent) => {
        if (!e.data) return;

        // Check for end-of-stream marker
        if (e.data === "END-OF-STREAM") {
          evtSource.close();
          return;
        }

        try {
          const data: MessageEventData = JSON.parse(e.data);
          console.log("[SSE] message event:", data);

          // Don't invalidate cache or show toast for mid-message events (progress updates)
          if (data.status === "mid-message-event") {
            return;
          }

          // Handle cache invalidation based on 'tables' field
          if (data.tables === "both") {
            queryClient.invalidateQueries({ queryKey: ["series"] });
            queryClient.invalidateQueries({ queryKey: ["wanted"] });
          } else if (data.tables === "tables") {
            queryClient.invalidateQueries({ queryKey: ["series"] });
          } else if (data.tables === "tabs") {
            // Invalidate current page queries
            // This is a generic invalidation - could be more specific based on current page
            queryClient.invalidateQueries();
          }

          // Show toast notification based on status
          if (data.message) {
            if (data.status === "success") {
              addToast({
                type: "success",
                title: "Success",
                description: data.message,
              });
            } else if (data.status === "failure") {
              addToast({
                type: "error",
                title: "Error",
                description: data.message,
              });
            }
          }
        } catch (error) {
          console.error("[SSE] Error parsing message event:", error);
        }
      });
    };

    setupEventSource();

    // Cleanup function
    return () => {
      isMounted = false;

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }

      if (eventSourceRef.current) {
        console.log("[SSE] Closing connection");
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [sseKey, enabled, queryClient, addToast]);

  return {};
}
