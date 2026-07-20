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

export interface LibraryChatMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "complete" | "error" | "cancelled";
  results?: ChatResult[];
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
