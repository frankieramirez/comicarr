/**
 * Server-Sent Events (SSE) type definitions
 *
 * The narrative channel is `activity` alone — its payload type is
 * `TimelineEvent` (see components/activity/timeline/types.ts), parsed through
 * `lib/activityLive.ts`. The per-feature channels that used to live here
 * (`addbyid`, `scheduler_message`, `config_check`, `search_progress`,
 * `search_complete`, generic `message`) have no producer and no listener.
 */

/**
 * Payload of the `comic-added` window event, derived from an `add` @ series
 * narration. Search cards settle their add button on it, so both the producer
 * (`lib/activityLive.ts`) and every consumer share this one shape.
 */
export interface ComicAddedDetail {
  comicid: string;
  comicname: string;
  status: "success" | "failure";
  message: string;
}
