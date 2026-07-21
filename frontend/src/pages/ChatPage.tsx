import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ChatComposer } from "@/components/ai/ChatComposer";
import { ChatExamplePrompts } from "@/components/ai/ChatExamplePrompts";
import { ChatMessage } from "@/components/ai/ChatMessage";
import { ChatThreadList } from "@/components/ai/ChatThreadList";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { useToast } from "@/components/ui/toast";
import { useAiStatus } from "@/hooks/useAiStatus";
import {
  chatQueryKeys,
  useChatThread,
  useChatThreads,
} from "@/hooks/useLibraryChat";
import {
  deleteChatThread,
  renameChatThread,
  streamChatTurn,
} from "@/lib/chatApi";
import type {
  ChatStreamEvent,
  LibraryChatMessage,
  PendingChatImage,
} from "@/types/chat";
import {
  AlertTriangle,
  ArrowLeft,
  History,
  LoaderCircle,
  MessageSquareText,
  Settings,
} from "lucide-react";

function optimisticMessage(
  role: LibraryChatMessage["role"],
  content: string,
  threadId = "",
): LibraryChatMessage {
  return {
    id: `local-${crypto.randomUUID()}`,
    thread_id: threadId,
    role,
    content,
    status: role === "assistant" ? "streaming" : "complete",
    attachments: [],
    created_at: new Date().toISOString(),
  };
}

export default function ChatPage() {
  const { threadId } = useParams<{ threadId: string }>();
  const activeThreadKey = threadId || "draft";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const { data: aiStatus, isLoading: statusLoading } = useAiStatus();
  const threadsQuery = useChatThreads();
  const threadQuery = useChatThread(threadId);
  const [localMessages, setLocalMessages] = useState<{
    threadKey: string;
    messages: LibraryChatMessage[];
  }>({ threadKey: "draft", messages: [] });
  const [composer, setComposer] = useState<{
    input: string;
    images: PendingChatImage[];
    error: string | null;
    retryMessageId?: string;
  }>({ input: "", images: [], error: null });
  const [isSending, setIsSending] = useState(false);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const imagesRef = useRef<PendingChatImage[]>([]);
  const previousThreadKeyRef = useRef(activeThreadKey);
  const internalThreadRoutesRef = useRef(new Set<string>());
  const { input, images, error: composerError, retryMessageId } = composer;
  const setInput = (input: string) =>
    setComposer((current) => ({ ...current, input }));
  const setImages = (images: PendingChatImage[]) =>
    setComposer((current) => ({ ...current, images }));
  const setComposerError = (error: string | null) =>
    setComposer((current) => ({ ...current, error }));
  const setRetryMessageId = (retryMessageId?: string) =>
    setComposer((current) => ({ ...current, retryMessageId }));

  const threads = useMemo(
    () => threadsQuery.data?.pages.flatMap((page) => page.threads) || [],
    [threadsQuery.data],
  );
  const selectedThread = threads.find((thread) => thread.id === threadId);
  const messages =
    localMessages.threadKey === activeThreadKey
      ? localMessages.messages
      : threadQuery.data?.messages || [];

  useEffect(() => {
    imagesRef.current = images;
  }, [images]);

  useEffect(() => {
    if (previousThreadKeyRef.current === activeThreadKey) return;
    previousThreadKeyRef.current = activeThreadKey;
    if (internalThreadRoutesRef.current.delete(activeThreadKey)) return;
    for (const image of imagesRef.current) {
      URL.revokeObjectURL(image.previewUrl);
    }
    imagesRef.current = [];
    setComposer({ input: "", images: [], error: null });
    setLocalMessages({ threadKey: "selection", messages: [] });
  }, [activeThreadKey]);

  useEffect(() => {
    return () => {
      for (const image of imagesRef.current) {
        URL.revokeObjectURL(image.previewUrl);
      }
    };
  }, []);

  const clearDraftImages = () => {
    for (const image of images) URL.revokeObjectURL(image.previewUrl);
    setImages([]);
  };

  const refreshThreads = async (activeThreadId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: chatQueryKeys.threads() }),
      activeThreadId
        ? queryClient.invalidateQueries({
            queryKey: chatQueryKeys.thread(activeThreadId),
          })
        : Promise.resolve(),
    ]);
  };

  const sendMessage = async () => {
    const content = input.trim();
    if ((!content && images.length === 0) || isSending) return;

    setComposerError(null);
    setIsSending(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const optimisticUser = optimisticMessage("user", content, threadId);
    optimisticUser.attachments = images.map((image) => ({
      id: image.id,
      filename: image.file.name,
      media_type: image.file.type,
      byte_size: image.file.size,
      width: 0,
      height: 0,
      url: image.previewUrl,
    }));
    const optimisticAssistant = optimisticMessage("assistant", "", threadId);
    const retryingMessageId = retryMessageId;
    let activeThreadId = threadId;
    let failed = false;
    let savedUserMessageId = optimisticUser.id;
    const updateTurnMessages = (
      update: (current: LibraryChatMessage[]) => LibraryChatMessage[],
    ) => {
      setLocalMessages((current) => ({
        threadKey: activeThreadId || "draft",
        messages: update(current.messages),
      }));
    };
    setLocalMessages({
      threadKey: activeThreadId || "draft",
      messages: [
        ...messages,
        ...(retryingMessageId ? [] : [optimisticUser]),
        optimisticAssistant,
      ],
    });

    const handleEvent = (event: ChatStreamEvent) => {
      if (event.type === "thread") {
        activeThreadId = event.thread.id;
        setLocalMessages((current) => ({
          threadKey: event.thread.id,
          messages: current.messages.map((message) => ({
            ...message,
            thread_id: event.thread.id,
          })),
        }));
        if (!threadId) {
          internalThreadRoutesRef.current.add(event.thread.id);
          navigate(`/chat/${event.thread.id}`, { replace: true });
        }
      } else if (event.type === "user_message") {
        savedUserMessageId = event.message.id;
        if (!retryingMessageId) {
          updateTurnMessages((current) =>
            current.map((message) =>
              message.id === optimisticUser.id ? event.message : message,
            ),
          );
        }
      } else if (event.type === "text") {
        updateTurnMessages((current) =>
          current.map((message) =>
            message.id === optimisticAssistant.id
              ? { ...message, content: message.content + event.content }
              : message,
          ),
        );
      } else if (event.type === "results") {
        updateTurnMessages((current) =>
          current.map((message) =>
            message.id === optimisticAssistant.id
              ? { ...message, results: event.data }
              : message,
          ),
        );
      } else if (event.type === "error") {
        failed = true;
        setComposerError(event.content);
        if (event.code === "vision_unsupported") {
          updateTurnMessages((current) =>
            current.filter(
              (message) =>
                message.id !== optimisticUser.id &&
                message.id !== savedUserMessageId &&
                message.id !== optimisticAssistant.id,
            ),
          );
          if (!threadId) {
            internalThreadRoutesRef.current.add("draft");
            navigate("/chat", { replace: true });
          }
          setRetryMessageId(undefined);
          addToast({
            type: "error",
            title: "This model cannot read images",
            message:
              "Your draft is intact. Choose a vision-capable model in AI Settings.",
          });
        } else {
          if (savedUserMessageId !== optimisticUser.id) {
            setRetryMessageId(savedUserMessageId);
          }
          updateTurnMessages((current) =>
            current.map((message) =>
              message.id === optimisticAssistant.id
                ? {
                    ...message,
                    content: event.content,
                    status: "error",
                  }
                : message,
            ),
          );
        }
      } else if (event.type === "done") {
        if (event.message) {
          updateTurnMessages((current) =>
            current.map((message) =>
              message.id === optimisticAssistant.id ? event.message! : message,
            ),
          );
        } else {
          updateTurnMessages((current) =>
            current.map((message) =>
              message.id === optimisticAssistant.id
                ? { ...message, status: failed ? "error" : "complete" }
                : message,
            ),
          );
        }
      }
    };

    try {
      await streamChatTurn({
        threadId,
        retryMessageId: retryingMessageId,
        content,
        images: retryingMessageId ? [] : images.map((image) => image.file),
        signal: controller.signal,
        onEvent: handleEvent,
      });
      if (!failed) {
        setRetryMessageId(undefined);
        setInput("");
        clearDraftImages();
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setComposerError("Response stopped. Send again to retry this message.");
        if (savedUserMessageId !== optimisticUser.id) {
          setRetryMessageId(savedUserMessageId);
        }
        updateTurnMessages((current) =>
          current.map((message) =>
            message.id === optimisticAssistant.id
              ? { ...message, status: "cancelled" }
              : message,
          ),
        );
      } else {
        const message =
          error instanceof Error ? error.message : "Chat request failed.";
        setComposerError(message);
        if (savedUserMessageId !== optimisticUser.id) {
          setRetryMessageId(savedUserMessageId);
        }
        updateTurnMessages((current) =>
          current.map((item) =>
            item.id === optimisticAssistant.id
              ? { ...item, content: message, status: "error" }
              : item,
          ),
        );
      }
    } finally {
      abortRef.current = null;
      setIsSending(false);
      void refreshThreads(activeThreadId);
    }
  };

  const handleNew = () => {
    if (isSending) return;
    setThreadsOpen(false);
    setInput("");
    clearDraftImages();
    setComposerError(null);
    setRetryMessageId(undefined);
    setLocalMessages({ threadKey: "draft", messages: [] });
    navigate("/chat");
  };

  const handleRename = async (id: string, title: string) => {
    await renameChatThread(id, title);
    await refreshThreads(id);
  };

  const handleDelete = async (id: string) => {
    await deleteChatThread(id);
    if (id === threadId) navigate("/chat", { replace: true });
    await refreshThreads();
  };

  const threadList = (
    <ChatThreadList
      threads={threads}
      selectedId={threadId}
      hasMore={Boolean(threadsQuery.hasNextPage)}
      isLoading={threadsQuery.isLoading}
      isLoadingMore={threadsQuery.isFetchingNextPage}
      error={threadsQuery.isError ? "Could not load saved chats." : undefined}
      onBack={() => navigate("/")}
      onNew={handleNew}
      onSelect={(id) => {
        setThreadsOpen(false);
        clearDraftImages();
        setInput("");
        setComposerError(null);
        setRetryMessageId(undefined);
        setLocalMessages({ threadKey: "selection", messages: [] });
        navigate(`/chat/${id}`);
      }}
      onRename={handleRename}
      onDelete={handleDelete}
      onLoadMore={() => void threadsQuery.fetchNextPage()}
      onRetry={() => void threadsQuery.refetch()}
    />
  );

  if (statusLoading) {
    return (
      <div className="relative flex h-full items-center justify-center">
        <Button
          type="button"
          variant="ghost"
          className="absolute left-3 top-3"
          onClick={() => navigate("/")}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to Comicarr
        </Button>
        <LoaderCircle className="animate-spin text-muted-foreground" />
        <span className="sr-only">Loading Chat</span>
      </div>
    );
  }

  if (!aiStatus?.configured) {
    return (
      <div className="relative flex h-full items-center justify-center px-5">
        <Button
          type="button"
          variant="ghost"
          className="absolute left-3 top-3"
          onClick={() => navigate("/")}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to Comicarr
        </Button>
        <div className="max-w-md rounded-xl border bg-card p-6 text-center shadow-sm">
          <AlertTriangle className="mx-auto mb-4 text-primary" />
          <h1 className="text-xl font-semibold">Connect an AI provider</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Chat needs an OpenAI-compatible provider and model before it can
            read your collection.
          </p>
          <Button className="mt-5" onClick={() => navigate("/settings?tab=ai")}>
            <Settings data-icon="inline-start" />
            Open AI Settings
          </Button>
        </div>
      </div>
    );
  }

  return (
    <MessageScrollerProvider>
      <div className="flex h-full min-h-0 bg-background">
        <aside className="hidden w-72 shrink-0 border-r lg:flex">
          {threadList}
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/70 px-4 backdrop-blur-sm">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0 lg:hidden"
              onClick={() => navigate("/")}
              aria-label="Back to Comicarr"
            >
              <ArrowLeft />
            </Button>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <MessageSquareText className="shrink-0 text-primary" />
                <h1 className="truncate text-base font-semibold">
                  {selectedThread?.title || "New library chat"}
                </h1>
              </div>
              {selectedThread && (
                <p className="mono-meta mt-0.5">
                  {selectedThread.message_count} saved messages
                </p>
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto lg:hidden"
              onClick={() => setThreadsOpen(true)}
            >
              <History data-icon="inline-start" />
              History
            </Button>
          </header>

          <div className="min-h-0 flex-1">
            {threadQuery.isLoading && threadId ? (
              <div className="flex size-full items-center justify-center">
                <LoaderCircle className="animate-spin text-muted-foreground" />
                <span className="sr-only">Loading conversation</span>
              </div>
            ) : threadQuery.isError && threadId ? (
              <div className="flex size-full flex-col items-center justify-center gap-3 px-5 text-center text-sm text-muted-foreground">
                <p>Could not load this conversation.</p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void threadQuery.refetch()}
                >
                  Try again
                </Button>
              </div>
            ) : messages.length === 0 ? (
              <div className="flex size-full items-center overflow-y-auto">
                <ChatExamplePrompts
                  onSelectPrompt={(prompt) => {
                    setInput(prompt);
                    setComposerError(null);
                  }}
                />
              </div>
            ) : (
              <MessageScroller>
                <MessageScrollerViewport>
                  <MessageScrollerContent
                    aria-busy={isSending}
                    className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6"
                  >
                    {messages.map((message) => (
                      <MessageScrollerItem
                        key={message.id}
                        scrollAnchor={message.role === "user"}
                      >
                        <ChatMessage message={message} />
                      </MessageScrollerItem>
                    ))}
                  </MessageScrollerContent>
                </MessageScrollerViewport>
                <MessageScrollerButton />
              </MessageScroller>
            )}
          </div>

          <div className="shrink-0 border-t bg-background/95 px-4 pb-3 pt-3 backdrop-blur-sm sm:px-6">
            <ChatComposer
              value={input}
              images={images}
              isSending={isSending}
              error={composerError}
              onChange={(value) => {
                setInput(value);
                setComposerError(null);
                setRetryMessageId(undefined);
              }}
              onImagesChange={(nextImages) => {
                setImages(nextImages);
                setRetryMessageId(undefined);
              }}
              onSubmit={() => void sendMessage()}
              onStop={() => abortRef.current?.abort()}
              onValidationError={(message) => {
                setComposerError(message);
                addToast({ type: "error", message });
              }}
            />
          </div>
        </section>
      </div>

      <Drawer open={threadsOpen} onOpenChange={setThreadsOpen}>
        <DrawerContent className="h-[82dvh]">
          <DrawerHeader className="sr-only">
            <DrawerTitle>Chat history</DrawerTitle>
            <DrawerDescription>
              Open, rename, or delete a saved conversation.
            </DrawerDescription>
          </DrawerHeader>
          {threadList}
        </DrawerContent>
      </Drawer>
    </MessageScrollerProvider>
  );
}
