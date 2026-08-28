import { apiRequest } from "@/lib/api";
import type {
  ChatStreamEvent,
  ChatThread,
  ChatThreadSummary,
  ChatThreadsResponse,
} from "@/types/chat";

const CHAT_BASE = "/api/ai/chat";

export function getChatThreads(
  cursor?: string,
  limit = 30,
): Promise<ChatThreadsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return apiRequest("GET", `${CHAT_BASE}/threads?${params}`);
}

export function getChatThread(threadId: string): Promise<ChatThread> {
  return apiRequest("GET", `${CHAT_BASE}/threads/${threadId}`);
}

export function renameChatThread(
  threadId: string,
  title: string,
): Promise<ChatThreadSummary> {
  return apiRequest("PATCH", `${CHAT_BASE}/threads/${threadId}`, { title });
}

export async function deleteChatThread(threadId: string): Promise<void> {
  await apiRequest("DELETE", `${CHAT_BASE}/threads/${threadId}`);
}

interface StreamChatTurnOptions {
  threadId?: string;
  retryMessageId?: string;
  content: string;
  images: File[];
  signal: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
}

export async function streamChatTurn({
  threadId,
  retryMessageId,
  content,
  images,
  signal,
  onEvent,
}: StreamChatTurnOptions): Promise<void> {
  const form = new FormData();
  if (threadId) form.set("thread_id", threadId);
  if (retryMessageId) form.set("retry_message_id", retryMessageId);
  form.set("content", content);
  for (const image of images) form.append("images", image, image.name);

  const response = await fetch(`${CHAT_BASE}/turns/stream`, {
    method: "POST",
    headers: { "X-Requested-With": "ComicarrFrontend" },
    credentials: "include",
    body: form,
    signal,
  });

  if (!response.ok) {
    let message = `Chat request failed (${response.status}).`;
    try {
      const body = (await response.json()) as {
        detail?: string;
        error?: string;
      };
      message = body.detail || body.error || message;
    } catch (ignored) {
      void ignored;
    }
    throw new Error(message);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("Chat response did not include a stream.");

  const decoder = new TextDecoder();
  let buffer = "";
  let receivedDone = false;

  const parseLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith(":")) return;
    const value = trimmed.startsWith("data:")
      ? trimmed.slice(5).trim()
      : trimmed;
    if (!value) return;
    let event: ChatStreamEvent;
    try {
      event = JSON.parse(value) as ChatStreamEvent;
    } catch {
      return;
    }
    if (event.type === "done") receivedDone = true;
    onEvent(event);
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) parseLine(line);
    }
    buffer += decoder.decode();
    if (buffer.trim()) parseLine(buffer);
  } finally {
    reader.releaseLock();
  }
  if (!receivedDone) {
    throw new Error(
      "The chat response ended before it completed. Send again to retry.",
    );
  }
}
