import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { StoryArc, StoryArcDetail, ArcIssueStatus } from "@/types";

/**
 * Fetch all tracked story arcs
 */
export function useStoryArcs(): UseQueryResult<StoryArc[]> {
  return useQuery({
    queryKey: ["storyArcs"],
    queryFn: () => apiRequest<StoryArc[]>("GET", "/api/storyarcs"),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Fetch a single story arc with all its issues
 */
export function useStoryArcDetail(
  storyArcId: string | undefined,
): UseQueryResult<StoryArcDetail> {
  return useQuery({
    queryKey: ["storyArcs", storyArcId],
    queryFn: () =>
      apiRequest<StoryArcDetail>("GET", `/api/storyarcs/${storyArcId}`),
    enabled: !!storyArcId,
  });
}

/**
 * Delete an entire story arc
 */
export function useDelStoryArc(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (storyArcId: string) =>
      apiRequest("DELETE", `/api/storyarcs/${storyArcId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
    },
  });
}

/**
 * Remove a single issue from a story arc
 */
export function useDelArcIssue(): UseMutationResult<
  unknown,
  Error,
  { issueArcId: string; storyArcId: string }
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      issueArcId,
      storyArcId,
    }: {
      issueArcId: string;
      storyArcId: string;
    }) =>
      apiRequest("DELETE", `/api/storyarcs/${storyArcId}/issues/${issueArcId}`),
    onSuccess: (_, { storyArcId }) => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      queryClient.invalidateQueries({ queryKey: ["storyArcs", storyArcId] });
    },
  });
}

/**
 * Set the status of an individual arc issue with optimistic update
 */
export function useSetArcIssueStatus(
  storyArcId: string,
): UseMutationResult<
  unknown,
  Error,
  { issueArcId: string; status: ArcIssueStatus },
  { previousStatus: ArcIssueStatus | undefined }
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      issueArcId,
      status,
    }: {
      issueArcId: string;
      status: ArcIssueStatus;
    }) =>
      apiRequest(
        "PUT",
        `/api/storyarcs/${storyArcId}/issues/${issueArcId}/status`,
        {
          status,
        },
      ),
    onMutate: async ({ issueArcId, status }) => {
      await queryClient.cancelQueries({
        queryKey: ["storyArcs", storyArcId],
      });
      const previous = queryClient.getQueryData<StoryArcDetail>([
        "storyArcs",
        storyArcId,
      ]);
      const previousStatus = previous?.issues.find(
        (i) => i.IssueArcID === issueArcId,
      )?.Status;

      if (previous) {
        queryClient.setQueryData<StoryArcDetail>(["storyArcs", storyArcId], {
          ...previous,
          issues: previous.issues.map((i) =>
            i.IssueArcID === issueArcId ? { ...i, Status: status } : i,
          ),
        });
      }
      return { previousStatus };
    },
    onError: (_err, { issueArcId }, context) => {
      if (context?.previousStatus) {
        queryClient.setQueryData<StoryArcDetail>(
          ["storyArcs", storyArcId],
          (old) =>
            old
              ? {
                  ...old,
                  issues: old.issues.map((i) =>
                    i.IssueArcID === issueArcId
                      ? { ...i, Status: context.previousStatus! }
                      : i,
                  ),
                }
              : undefined,
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      queryClient.invalidateQueries({ queryKey: ["storyArcs", storyArcId] });
    },
  });
}

/**
 * Mark all non-downloaded issues as Wanted
 */
interface WantAllResponse {
  success: boolean;
  data: { queued: number; skipped: number };
}

export function useWantAllArcIssues(): UseMutationResult<
  WantAllResponse,
  Error,
  string
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (storyArcId: string) =>
      apiRequest<WantAllResponse>(
        "POST",
        `/api/storyarcs/${storyArcId}/want-all`,
      ),
    onSuccess: (_, storyArcId) => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      queryClient.invalidateQueries({ queryKey: ["storyArcs", storyArcId] });
    },
  });
}

/**
 * Refresh a story arc from ComicVine
 */
export function useRefreshStoryArc(): UseMutationResult<
  unknown,
  Error,
  string
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (storyArcId: string) =>
      apiRequest("POST", `/api/storyarcs/${storyArcId}/refresh`),
    onSuccess: (_, storyArcId) => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      queryClient.invalidateQueries({ queryKey: ["storyArcs", storyArcId] });
    },
  });
}
