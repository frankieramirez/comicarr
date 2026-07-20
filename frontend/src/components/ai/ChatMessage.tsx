import type { LibraryChatMessage } from "@/types/chat";
import {
  Attachment,
  AttachmentInfo,
  AttachmentPreview,
  Attachments,
} from "@/components/ai-elements/attachments";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import {
  Message,
  MessageAvatar,
  MessageContent,
} from "@/components/ui/message";
import { AlertCircle, Bot, CircleStop, LoaderCircle } from "lucide-react";
import { ChatResultCard } from "./ChatResultCard";

interface ChatMessageProps {
  message: LibraryChatMessage;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <Message align={isUser ? "end" : "start"}>
      {!isUser && (
        <MessageAvatar aria-hidden="true" className="size-8 bg-primary/10">
          <Bot className="text-primary" />
        </MessageAvatar>
      )}
      <MessageContent>
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
                <AttachmentInfo />
              </Attachment>
            ))}
          </Attachments>
        )}

        {message.content && message.status !== "error" && (
          <Bubble
            align={isUser ? "end" : "start"}
            variant={isUser ? "default" : "ghost"}
          >
            <BubbleContent className="whitespace-pre-wrap">
              {message.content}
            </BubbleContent>
          </Bubble>
        )}

        {message.results && message.results.length > 0 && (
          <div className="flex w-full max-w-2xl flex-col gap-2">
            <div className="mono-label px-1">Library matches</div>
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
            <MarkerIcon>
              <LoaderCircle className="animate-spin motion-reduce:animate-none" />
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
