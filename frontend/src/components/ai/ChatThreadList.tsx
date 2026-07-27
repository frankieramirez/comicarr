import { useMemo, useState } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { useAuth } from "@/contexts/AuthContext";
import { confirmChatDelete, promptChatTitle } from "@/lib/chatDialogs";
import type { ChatThreadSummary } from "@/types/chat";
import {
  ArrowLeft,
  LoaderCircle,
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";

interface ChatThreadListProps {
  threads: ChatThreadSummary[];
  selectedId?: string;
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  error?: string;
  /** Active series the assistant can read, shown under the workspace name. */
  seriesIndexed?: number;
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

/** Bucket a thread by how recently it was touched, newest bucket first. */
function threadBucket(value: string): "Today" | "Yesterday" | "Earlier" {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Earlier";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return "Earlier";
}

const BUCKET_ORDER = ["Today", "Yesterday", "Earlier"] as const;

export function ChatThreadList({
  threads,
  selectedId,
  hasMore,
  isLoading,
  isLoadingMore,
  error,
  seriesIndexed,
  onBack,
  onNew,
  onSelect,
  onRename,
  onDelete,
  onLoadMore,
  onRetry,
}: ChatThreadListProps) {
  const { user } = useAuth();
  const [busyId, setBusyId] = useState<string>();
  const [filter, setFilter] = useState("");

  const username = user?.username || "admin";
  const query = filter.trim().toLowerCase();
  const matches = useMemo(
    () =>
      query
        ? threads.filter((thread) => thread.title.toLowerCase().includes(query))
        : threads,
    [threads, query],
  );
  const groups = useMemo(
    () =>
      BUCKET_ORDER.map((label) => ({
        label,
        threads: matches.filter(
          (thread) => threadBucket(thread.updated_at) === label,
        ),
      })).filter((group) => group.threads.length > 0),
    [matches],
  );

  return (
    <div className="flex size-full min-h-0 flex-col bg-card/40">
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b px-3">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Back to Comicarr"
          onClick={onBack}
        >
          <ArrowLeft />
        </Button>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold tracking-tight">
            Ask Comicarr
          </div>
          <div className="mono-meta">
            {seriesIndexed === undefined
              ? "library assistant"
              : `${seriesIndexed} series indexed`}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2 px-3 pt-3 pb-2">
        <Button
          type="button"
          variant="outline"
          className="w-full justify-start"
          onClick={onNew}
        >
          <Plus data-icon="inline-start" className="text-primary" />
          <span className="flex-1 text-left">New chat</span>
          <Kbd>⌘⇧K</Kbd>
        </Button>
        <div className="flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 focus-within:border-primary">
          <Search className="size-3.5 shrink-0 text-muted-foreground" />
          <input
            type="search"
            value={filter}
            aria-label="Search chats"
            placeholder="Search chats"
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2">
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
        ) : matches.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            No chats match “{filter.trim()}”.
          </div>
        ) : (
          <div className="flex flex-col gap-3.5">
            {groups.map((group) => (
              <div key={group.label} className="flex flex-col gap-0.5">
                <div className="mono-label px-2 pt-1.5 pb-1">{group.label}</div>
                {group.threads.map((thread) => {
                  const active = thread.id === selectedId;
                  return (
                    <div
                      key={thread.id}
                      className="group flex items-center rounded-lg border border-transparent data-[active=true]:border-border data-[active=true]:bg-accent"
                      data-active={active}
                    >
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-auto min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg px-2.5 py-2 text-left whitespace-normal"
                        onClick={() => onSelect(thread.id)}
                      >
                        <span className="block w-full truncate text-[13px] font-medium">
                          {thread.title}
                        </span>
                        <span className="mono-meta block w-full truncate">
                          {thread.message_count} msgs ·{" "}
                          {formatThreadTime(thread.updated_at)}
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
                              className="mr-1 shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 data-popup-open:opacity-100"
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
                                const title = promptChatTitle(thread.title);
                                if (!title) return;
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
                                if (!confirmChatDelete(thread.title)) return;
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
              </div>
            ))}
            {hasMore && !query && (
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

      <div className="flex shrink-0 items-center gap-2.5 border-t px-3 py-2.5">
        <Avatar className="size-6.5">
          <AvatarFallback className="bg-linear-to-br from-primary to-chart-2 text-[10px] font-semibold text-primary-foreground">
            {username.slice(0, 2).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <span className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground">
          {username}
        </span>
      </div>
    </div>
  );
}
