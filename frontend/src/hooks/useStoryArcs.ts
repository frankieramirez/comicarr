import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiCall } from "@/lib/api";
import type { StoryArc, StoryArcDetail, ArcIssueStatus } from "@/types";

/**
 * Fetch all tracked story arcs
 */
export function useStoryArcs(): UseQueryResult<StoryArc[]> {
  return useQuery({
    queryKey: ["storyArcs"],
    queryFn: () => apiCall<StoryArc[]>("getStoryArc"),
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
    queryFn: () => apiCall<StoryArcDetail>("getStoryArc", { id: storyArcId }),
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
      apiCall("delStoryArc", { StoryArcID: storyArcId }),
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
    mutationFn: ({ issueArcId }: { issueArcId: string; storyArcId: string }) =>
      apiCall("delArcIssue", { IssueArcID: issueArcId }),
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
    }) => apiCall("setArcIssueStatus", { IssueArcID: issueArcId, status }),
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
      apiCall<WantAllResponse>("wantAllArcIssues", {
        StoryArcID: storyArcId,
      }),
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
      apiCall("refreshStoryArc", { StoryArcID: storyArcId }),
    onSuccess: (_, storyArcId) => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      queryClient.invalidateQueries({ queryKey: ["storyArcs", storyArcId] });
    },
  });
}
