/**
 * Server-Sent Events (SSE) type definitions
 */

/** Base SSE event data */
export interface SSEEventData {
  status?: 'success' | 'failure' | 'mid-message-event';
  message?: string;
  tables?: 'both' | 'tables' | 'tabs';
}

/** addbyid event data */
export interface AddByIdEventData extends SSEEventData {
  comicid?: string;
  comicname?: string;
  seriesyear?: string;
}

/** scheduler_message event data */
export interface SchedulerMessageEventData extends SSEEventData {
  message: string;
}

/** config_check event data */
export interface ConfigCheckEventData extends SSEEventData {
  config_errors?: string[];
}

/** check_update event data */
export interface CheckUpdateEventData extends SSEEventData {
  commits_behind: string | number;
  current_version?: string;
  latest_version?: string;
}

/** search_progress event data */
export interface SearchProgressEventData extends SSEEventData {
  current?: number;
  total?: number;
  query?: string;
}

/** search_complete event data */
export interface SearchCompleteEventData extends SSEEventData {
  result_count?: number;
}

/** Generic message event data */
export interface MessageEventData extends SSEEventData {
  type?: string;
}

/** Custom window event for comic-added */
export interface ComicAddedEvent extends CustomEvent<string> {
  detail: string;
}
