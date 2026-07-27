import type { LibraryChatMessage } from "@/types/chat";
import {
  Attachment,
  AttachmentPreview,
  Attachments,
} from "@/components/ai-elements/attachments";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Message, MessageContent } from "@/components/ui/message";
import { AlertCircle, CircleStop } from "lucide-react";
import { ChatResultCard } from "./ChatResultCard";

interface ChatMessageProps {
  message: LibraryChatMessage;
}

/** The assistant's mark: an accent, not an avatar. */
function AssistantMark() {
  return (
    <span
      aria-hidden="true"
      className="flex size-4 shrink-0 items-center justify-center rounded-[5px] bg-primary/15"
    >
      <span className="size-[5px] rounded-[1px] bg-primary" />
    </span>
  );
}

function ThinkingDots() {
  return (
    <span aria-hidden="true" className="flex items-center gap-[3px]">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1 rounded-full bg-primary animate-pulse motion-reduce:animate-none"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <Message align={isUser ? "end" : "start"}>
      <MessageContent className="gap-3">
        {!isUser && (
          <div className="flex items-center gap-2">
            <AssistantMark />
            <span className="mono-label">Comicarr</span>
          </div>
        )}

        {message.attachments.length > 0 && (
          <Attachments variant="grid" className={isUser ? "ml-auto" : "ml-0"}>
            {message.attachments.map((attachment) => (
              <Attachment
                key={attachment.id}
                data={{
                  id: attachment.id,
                  type: "file",
                  filename: attachment.filename,
                  mediaType: attachment.media_type,
                  url: attachment.url,
                }}
              >
                <AttachmentPreview />
              </Attachment>
            ))}
          </Attachments>
        )}

        {message.content && message.status !== "error" && (
          <Bubble
            align={isUser ? "end" : "start"}
            variant={isUser ? "outline" : "ghost"}
          >
            <BubbleContent
              className={
                isUser
                  ? "rounded-[14px] rounded-br-[4px] bg-card px-3.5 py-2.5 whitespace-pre-wrap"
                  : "text-[15px] leading-[1.65] text-pretty whitespace-pre-wrap"
              }
            >
              {message.content}
            </BubbleContent>
          </Bubble>
        )}

        {message.results && message.results.length > 0 && (
          <div className="flex w-full max-w-2xl flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="mono-label shrink-0">In your library</span>
              <span className="h-px flex-1 bg-border" />
            </div>
            {message.results.slice(0, 10).map((result, index) => (
              <ChatResultCard
                key={`${result.ComicID || result.StoryArc || index}-${index}`}
                result={result}
              />
            ))}
            {message.results.length > 10 && (
              <p className="px-1 text-xs text-muted-foreground">
                {message.results.length - 10} more matches
              </p>
            )}
          </div>
        )}

        {message.status === "streaming" && !message.content && (
          <Marker aria-live="polite">
            <MarkerIcon className="flex items-center">
              <ThinkingDots />
            </MarkerIcon>
            <MarkerContent className="shimmer">
              Reading your library…
            </MarkerContent>
          </Marker>
        )}

        {message.status === "error" && (
          <Marker className="text-destructive" role="alert">
            <MarkerIcon>
              <AlertCircle />
            </MarkerIcon>
            <MarkerContent>
              {message.content || "The response could not be completed."}
            </MarkerContent>
          </Marker>
        )}

        {message.status === "cancelled" && (
          <Marker>
            <MarkerIcon>
              <CircleStop />
            </MarkerIcon>
            <MarkerContent>Response stopped</MarkerContent>
          </Marker>
        )}
      </MessageContent>
    </Message>
  );
}
