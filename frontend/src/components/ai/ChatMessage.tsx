import type { ChatMessage as ChatMessageType } from "@/hooks/useAiChat";
import { ChatResultCard } from "./ChatResultCard";
import { Loader2, User, Bot } from "lucide-react";

interface ChatMessageProps {
  message: ChatMessageType;
  onNavigate?: () => void;
}

export function ChatMessage({ message, onNavigate }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground"
        }`}
      >
        {isUser ? (
          <User className="h-3.5 w-3.5" />
        ) : (
          <Bot className="h-3.5 w-3.5" />
        )}
      </div>

      <div className={`flex-1 min-w-0 ${isUser ? "flex justify-end" : ""}`}>
        {isUser ? (
          <div className="inline-block max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
            {message.content}
          </div>
        ) : (
          <div className="max-w-[95%] space-y-2">
            {message.results && message.results.length > 0 && (
              <div className="space-y-1.5">
                {message.results.slice(0, 10).map((result, index) => (
                  <ChatResultCard
                    key={`${result.ComicID || result.StoryArc || index}-${index}`}
                    result={result}
                    onNavigate={onNavigate}
                  />
                ))}
                {message.results.length > 10 && (
                  <p className="text-xs text-muted-foreground pl-1">
                    ...and {message.results.length - 10} more results
                  </p>
                )}
              </div>
            )}

            {message.content && (
              <div
                className={`text-sm leading-relaxed ${
                  message.error ? "text-destructive" : "text-foreground"
                }`}
              >
                {message.content}
              </div>
            )}

            {message.isStreaming && !message.content && !message.results && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Thinking...</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
