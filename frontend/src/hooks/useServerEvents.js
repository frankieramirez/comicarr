import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/toast';

/**
 * Hook to manage Server-Sent Events (SSE) connection for real-time updates
 * @param {string} sseKey - The SSE API key from authentication
 * @param {boolean} enabled - Whether to establish the SSE connection
 */
export function useServerEvents(sseKey, enabled = true) {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const eventSourceRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
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
      console.log('[SSE] Connecting to:', apiUrl);

      const evtSource = new EventSource(apiUrl);
      eventSourceRef.current = evtSource;

      evtSource.onopen = () => {
        console.log('[SSE] Connection established');
        reconnectDelayRef.current = 1000; // Reset reconnect delay on successful connection
      };

      evtSource.onerror = (error) => {
        console.error('[SSE] Connection error:', error);
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
      evtSource.addEventListener('addbyid', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] addbyid event:', data);

          // Don't invalidate cache for mid-message events (progress updates)
          if (data.status === 'mid-message-event') {
            return;
          }

          // Invalidate series cache if tables='both' or 'tables'
          if (data.tables === 'both' || data.tables === 'tables') {
            queryClient.invalidateQueries({ queryKey: ['series'] });
          }

          // Show success toast with series name
          if (data.comicname && data.status === 'success') {
            addToast({
              type: 'success',
              title: 'Series Added',
              description: `${data.comicname} (${data.seriesyear || 'Unknown'}) has been added successfully.`,
            });
          }
        } catch (error) {
          console.error('[SSE] Error parsing addbyid event:', error);
        }
      });

      // Event: scheduler_message - Background task notifications
      evtSource.addEventListener('scheduler_message', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] scheduler_message event:', data);

          if (data.message) {
            addToast({
              type: data.status === 'success' ? 'success' : 'error',
              title: data.status === 'success' ? 'Task Complete' : 'Task Failed',
              description: data.message,
            });
          }
        } catch (error) {
          console.error('[SSE] Error parsing scheduler_message event:', error);
        }
      });

      // Event: config_check - Configuration validation messages
      evtSource.addEventListener('config_check', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] config_check event:', data);

          // Invalidate config cache
          queryClient.invalidateQueries({ queryKey: ['config'] });

          // Note: Original implementation shows a modal dialog
          // For now, we'll just log it. Could add a modal later if needed.
        } catch (error) {
          console.error('[SSE] Error parsing config_check event:', error);
        }
      });

      // Event: check_update - Version update notifications
      evtSource.addEventListener('check_update', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] check_update event:', data);

          const commitsBehind = parseInt(data.commits_behind);
          if (commitsBehind > 0 && data.current_version !== data.latest_version) {
            addToast({
              type: 'info',
              title: 'Update Available',
              description: `A newer version is available. You are ${commitsBehind} commits behind.`,
            });
          } else if (commitsBehind === 0) {
            addToast({
              type: 'success',
              title: 'Up to Date',
              description: 'Mylar is up to date.',
            });
          }
        } catch (error) {
          console.error('[SSE] Error parsing check_update event:', error);
        }
      });

      // Event: search_progress - Live search progress updates
      evtSource.addEventListener('search_progress', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] search_progress event:', data);

          // Don't show toast for progress events, just log them
          // Could be used to update a progress bar in the UI later
        } catch (error) {
          console.error('[SSE] Error parsing search_progress event:', error);
        }
      });

      // Event: search_complete - Search completion notification
      evtSource.addEventListener('search_complete', (e) => {
        if (!e.data) return;

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] search_complete event:', data);

          const resultCount = data.result_count || 0;
          addToast({
            type: 'success',
            title: 'Search Complete',
            description: `Found ${resultCount} result${resultCount !== 1 ? 's' : ''}.`,
          });
        } catch (error) {
          console.error('[SSE] Error parsing search_complete event:', error);
        }
      });

      // Event: shutdown - Server shutdown notification
      evtSource.addEventListener('shutdown', (e) => {
        console.log('[SSE] Server shutting down');

        addToast({
          type: 'error',
          title: 'Server Shutting Down',
          description: 'The server is shutting down. Please wait...',
        });

        evtSource.close();
      });

      // Event: message - Default/generic message handler
      evtSource.addEventListener('message', (e) => {
        if (!e.data) return;

        // Check for end-of-stream marker
        if (e.data === 'END-OF-STREAM') {
          evtSource.close();
          return;
        }

        try {
          const data = JSON.parse(e.data);
          console.log('[SSE] message event:', data);

          // Don't invalidate cache or show toast for mid-message events (progress updates)
          if (data.status === 'mid-message-event') {
            return;
          }

          // Handle cache invalidation based on 'tables' field
          if (data.tables === 'both') {
            queryClient.invalidateQueries({ queryKey: ['series'] });
            queryClient.invalidateQueries({ queryKey: ['wanted'] });
          } else if (data.tables === 'tables') {
            queryClient.invalidateQueries({ queryKey: ['series'] });
          } else if (data.tables === 'tabs') {
            // Invalidate current page queries
            // This is a generic invalidation - could be more specific based on current page
            queryClient.invalidateQueries();
          }

          // Show toast notification based on status
          if (data.message) {
            if (data.status === 'success') {
              addToast({
                type: 'success',
                title: 'Success',
                description: data.message,
              });
            } else if (data.status === 'failure') {
              addToast({
                type: 'error',
                title: 'Error',
                description: data.message,
              });
            }
          }
        } catch (error) {
          console.error('[SSE] Error parsing message event:', error);
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
        console.log('[SSE] Closing connection');
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [sseKey, enabled, queryClient, addToast]);

  return {
    // Could expose connection state here if needed
    // isConnected: eventSourceRef.current?.readyState === EventSource.OPEN
  };
}
