import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ChatThreadSummary } from "@/types/chat";
import {
  ArrowLeft,
  LoaderCircle,
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";

interface ChatThreadListProps {
  threads: ChatThreadSummary[];
  selectedId?: string;
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  error?: string;
  onBack: () => void;
  onNew: () => void;
  onSelect: (threadId: string) => void;
  onRename: (threadId: string, title: string) => Promise<void>;
  onDelete: (threadId: string) => Promise<void>;
  onLoadMore: () => void;
  onRetry: () => void;
}

function formatThreadTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function ChatThreadList({
  threads,
  selectedId,
  hasMore,
  isLoading,
  isLoadingMore,
  error,
  onBack,
  onNew,
  onSelect,
  onRename,
  onDelete,
  onLoadMore,
  onRetry,
}: ChatThreadListProps) {
  const [busyId, setBusyId] = useState<string>();

  return (
    <div className="flex size-full min-h-0 flex-col bg-card/40">
      <div className="border-b px-3 py-2">
        <Button
          type="button"
          variant="ghost"
          className="w-full justify-start text-muted-foreground hover:text-foreground"
          onClick={onBack}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to Comicarr
        </Button>
      </div>
      <div className="border-b p-3">
        <Button type="button" className="w-full justify-start" onClick={onNew}>
          <Plus data-icon="inline-start" />
          New chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <LoaderCircle className="animate-spin" />
            <span className="sr-only">Loading saved chats</span>
          </div>
        ) : error ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-sm text-muted-foreground">
            <p>{error}</p>
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              Try again
            </Button>
          </div>
        ) : threads.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center px-5 text-center text-sm text-muted-foreground">
            <MessageSquareText className="mb-3" />
            Saved conversations appear here.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {threads.map((thread) => {
              const active = thread.id === selectedId;
              return (
                <div
                  key={thread.id}
                  className="group flex items-center rounded-lg data-[active=true]:bg-accent"
                  data-active={active}
                >
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-auto min-w-0 flex-1 justify-start rounded-lg px-3 py-2.5 text-left whitespace-normal"
                    onClick={() => onSelect(thread.id)}
                  >
                    <span className="block truncate text-sm font-medium">
                      {thread.title}
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{thread.message_count} messages</span>
                      <span aria-hidden="true">·</span>
                      <span>{formatThreadTime(thread.updated_at)}</span>
                    </span>
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Actions for ${thread.title}`}
                          className="mr-1 shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                        />
                      }
                    >
                      {busyId === thread.id ? (
                        <LoaderCircle className="animate-spin" />
                      ) : (
                        <MoreHorizontal />
                      )}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuGroup>
                        <DropdownMenuItem
                          onClick={() => {
                            const title = window
                              .prompt("Rename chat", thread.title)
                              ?.trim();
                            if (!title || title === thread.title) return;
                            setBusyId(thread.id);
                            void onRename(thread.id, title).finally(() =>
                              setBusyId(undefined),
                            );
                          }}
                        >
                          <Pencil />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => {
                            if (
                              !window.confirm(
                                `Delete “${thread.title}”? This also removes its images.`,
                              )
                            )
                              return;
                            setBusyId(thread.id);
                            void onDelete(thread.id).finally(() =>
                              setBusyId(undefined),
                            );
                          }}
                        >
                          <Trash2 />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuGroup>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })}
            {hasMore && (
              <Button
                type="button"
                variant="ghost"
                disabled={isLoadingMore}
                onClick={onLoadMore}
              >
                {isLoadingMore && (
                  <LoaderCircle
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                )}
                Load older chats
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
