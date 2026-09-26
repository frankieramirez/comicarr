export interface ChatAttachment {
  id: string;
  filename: string;
  media_type: string;
  byte_size: number;
  width: number;
  height: number;
  url: string;
}

export interface ChatResult {
  ComicID?: string;
  ComicName?: string;
  ComicYear?: string;
  ComicPublisher?: string;
  ComicImage?: string;
  Have?: number;
  Total?: number;
  Status?: string;
  Issue_Number?: string;
  IssueDate?: string;
  DateAdded?: string;
  Provider?: string;
  StoryArc?: string;
  gaps?: number;
  pct?: number;
  total?: number;
  have?: number;
  [key: string]: unknown;
}

export interface ChatActionCandidate {
  comicid: string;
  name?: string | null;
  year?: string | null;
  publisher?: string | null;
  issues?: number | null;
  image?: string | null;
  in_library?: boolean;
}

export interface ChatActionIssue {
  issue_id: string;
  number?: string | null;
  kind: "issue" | "annual";
  current_status?: string | null;
}

export interface ChatActionPreview {
  query?: string;
  candidates?: ChatActionCandidate[];
  comic_id?: string;
  comic_name?: string;
  comic_year?: string;
  target_status?: "Wanted" | "Skipped";
  scope?: "all" | "issues" | "annuals";
  count?: number;
  issues?: ChatActionIssue[];
}

export interface ChatActionResult {
  message?: string;
  applied?: number;
  stale?: number;
  failed?: number;
  comicid?: string;
  name?: string;
}

export type ChatActionStatus = "pending" | "confirmed" | "dismissed" | "error";

/**
 * A write the model proposed. Nothing ran yet when status is "pending" —
 * the confirm endpoint re-checks the stored proposal before applying it.
 */
export interface ChatAction {
  action_id: "add_series" | "mark_issues" | string;
  status: ChatActionStatus | string;
  summary?: string;
  parameters?: Record<string, unknown>;
  preview?: ChatActionPreview;
  result?: ChatActionResult;
  error?: string;
}

export interface LibraryChatMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "complete" | "error" | "cancelled";
  results?: ChatResult[];
  action?: ChatAction | null;
  attachments: ChatAttachment[];
  created_at: string;
}

export interface ChatThreadSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatThread extends ChatThreadSummary {
  messages: LibraryChatMessage[];
}

export interface ChatThreadsResponse {
  threads: ChatThreadSummary[];
  next_cursor: string | null;
}

export type ChatStreamEvent =
  | { type: "thread"; thread: ChatThreadSummary }
  | { type: "user_message"; message: LibraryChatMessage }
  | { type: "text"; content: string; message_id?: string }
  | {
      type: "results";
      pattern_id?: string;
      data: ChatResult[];
      message_id?: string;
    }
  | { type: "action"; action: ChatAction; message_id?: string }
  | {
      type: "error";
      code?: string;
      content: string;
      retryable?: boolean;
    }
  | { type: "done"; message?: LibraryChatMessage };

export interface PendingChatImage {
  id: string;
  file: File;
  previewUrl: string;
}
