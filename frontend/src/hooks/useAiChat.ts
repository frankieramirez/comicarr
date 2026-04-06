import { useCallback, useRef, useState } from "react";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  results?: ChatResult[];
  isStreaming?: boolean;
  error?: boolean;
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

interface SSEEvent {
  type: "text" | "results" | "error" | "done";
  content?: string;
  pattern_id?: string;
  data?: ChatResult[];
}

let messageCounter = 0;

function generateId(): string {
  messageCounter += 1;
  return `msg-${Date.now()}-${messageCounter}`;
}

export function useAiChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || isStreaming) return;

      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content: content.trim(),
      };

      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

      // Build conversation history for context
      const conversationMessages = [
        ...messages
          .filter((m) => !m.error)
          .map((m) => ({
            role: m.role,
            content: m.content,
          })),
        { role: "user" as const, content: content.trim() },
      ];

      const abortController = new AbortController();
      abortRef.current = abortController;

      try {
        const response = await fetch("/api/ai/chat/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "ComicarrFrontend",
          },
          credentials: "include",
          body: JSON.stringify({ messages: conversationMessages }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("No response body");
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let accumulatedText = "";
        let accumulatedResults: ChatResult[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse SSE events from the buffer
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith(":")) continue;

            let eventData = trimmed;
            if (eventData.startsWith("data:")) {
              eventData = eventData.slice(5).trim();
            }

            if (!eventData) continue;

            try {
              const event: SSEEvent = JSON.parse(eventData);

              if (event.type === "text" && event.content) {
                accumulatedText += event.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? {
                          ...m,
                          content: accumulatedText,
                          results:
                            accumulatedResults.length > 0
                              ? accumulatedResults
                              : undefined,
                        }
                      : m,
                  ),
                );
              } else if (event.type === "results" && event.data) {
                accumulatedResults = [...accumulatedResults, ...event.data];
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? {
                          ...m,
                          content: accumulatedText,
                          results: accumulatedResults,
                        }
                      : m,
                  ),
                );
              } else if (event.type === "error" && event.content) {
                accumulatedText += event.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? {
                          ...m,
                          content: accumulatedText,
                          isStreaming: false,
                          error: true,
                        }
                      : m,
                  ),
                );
              } else if (event.type === "done") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessage.id
                      ? {
                          ...m,
                          content:
                            accumulatedText ||
                            "I couldn't generate a response. Please try again.",
                          results:
                            accumulatedResults.length > 0
                              ? accumulatedResults
                              : undefined,
                          isStreaming: false,
                        }
                      : m,
                  ),
                );
              }
            } catch {
              // Skip unparseable lines
            }
          }
        }

        // Finalize if no done event was received
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessage.id && m.isStreaming
              ? {
                  ...m,
                  content: accumulatedText || "Response completed.",
                  results:
                    accumulatedResults.length > 0
                      ? accumulatedResults
                      : undefined,
                  isStreaming: false,
                }
              : m,
          ),
        );
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id
                ? { ...m, content: "Request cancelled.", isStreaming: false }
                : m,
            ),
          );
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id
                ? {
                    ...m,
                    content:
                      "Failed to connect to AI. Please check your settings.",
                    isStreaming: false,
                    error: true,
                  }
                : m,
            ),
          );
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [isStreaming, messages],
  );

  const cancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, sendMessage, isStreaming, cancelStream, clearMessages };
}
