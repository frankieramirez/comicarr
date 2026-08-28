import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { getChatThread, getChatThreads } from "@/lib/chatApi";

export const chatQueryKeys = {
  all: ["ai", "chat"] as const,
  threads: () => [...chatQueryKeys.all, "threads"] as const,
  thread: (threadId: string) =>
    [...chatQueryKeys.all, "thread", threadId] as const,
};

export function useChatThreads() {
  return useInfiniteQuery({
    queryKey: chatQueryKeys.threads(),
    queryFn: ({ pageParam }) => getChatThreads(pageParam || undefined),
    initialPageParam: "",
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    staleTime: 30_000,
  });
}

export function useChatThread(threadId?: string) {
  return useQuery({
    queryKey: chatQueryKeys.thread(threadId || "draft"),
    queryFn: () => getChatThread(threadId as string),
    enabled: Boolean(threadId),
  });
}
