import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import { apiRequest } from "@/lib/api";
import type {
  InteractiveGrabResult,
  InteractiveSearchSession,
  ReleaseReviewIssue,
} from "@/types";

const INTERACTIVE_POLL_MS = 2_000;
const ACTIVE_STATES = new Set(["queued", "running"]);

export interface StartInteractiveSearchInput {
  entityType: "issue" | "annual" | "story_arc_issue";
  entityId: string;
}

interface GrabInteractiveCandidateInput {
  sessionId: string;
  candidateId: string;
  override: boolean;
}

export function useStartInteractiveSearch() {
  return useMutation({
    mutationFn: ({ entityType, entityId }: StartInteractiveSearchInput) =>
      apiRequest<InteractiveSearchSession>("POST", "/api/search/interactive", {
        entity_type: entityType,
        entity_id: entityId,
      }),
  });
}

export function useInteractiveSearch(sessionId: string | null) {
  return useQuery({
    queryKey: ["interactive-search", sessionId],
    queryFn: () =>
      apiRequest<InteractiveSearchSession>(
        "GET",
        `/api/search/interactive/${encodeURIComponent(sessionId ?? "")}`,
      ),
    enabled: Boolean(sessionId),
    staleTime: 0,
    gcTime: 15 * 60 * 1_000,
    refetchInterval: (query) =>
      ACTIVE_STATES.has(query.state.data?.state ?? "")
        ? INTERACTIVE_POLL_MS
        : false,
  });
}

export function useGrabInteractiveCandidate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      candidateId,
      override,
    }: GrabInteractiveCandidateInput) =>
      apiRequest<InteractiveGrabResult>(
        "POST",
        `/api/search/interactive/${encodeURIComponent(sessionId)}/candidates/${encodeURIComponent(candidateId)}/grab`,
        { override },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["upcoming"] }),
        queryClient.invalidateQueries({ queryKey: ["wanted"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
        queryClient.invalidateQueries({ queryKey: ["series"] }),
        queryClient.invalidateQueries({ queryKey: ["storyArcs"] }),
      ]);
    },
  });
}

export function useInteractiveReview() {
  const startInteractiveSearch = useStartInteractiveSearch();
  const { addToast } = useToast();
  const [reviewIssue, setReviewIssue] = useState<ReleaseReviewIssue | null>(
    null,
  );
  const [reviewSessionId, setReviewSessionId] = useState<string | null>(null);
  const [reviewTarget, setReviewTarget] =
    useState<StartInteractiveSearchInput | null>(null);

  const startReview = async (
    issue: ReleaseReviewIssue,
    target: StartInteractiveSearchInput,
  ) => {
    if (!target.entityId) return;
    setReviewIssue(issue);
    setReviewTarget(target);
    setReviewSessionId(null);
    startInteractiveSearch.reset();
    try {
      const session = await startInteractiveSearch.mutateAsync(target);
      setReviewSessionId(session.session_id);
    } catch {
      // The sheet owns the actionable error and retry affordance.
    }
  };

  const closeReview = () => {
    setReviewIssue(null);
    setReviewSessionId(null);
    setReviewTarget(null);
    startInteractiveSearch.reset();
  };

  return {
    startReview,
    reviewSheetProps: {
      issue: reviewIssue,
      sessionId: reviewSessionId,
      startPending: startInteractiveSearch.isPending,
      startError: startInteractiveSearch.error,
      onRetry: () =>
        reviewIssue && reviewTarget
          ? void startReview(reviewIssue, reviewTarget)
          : undefined,
      onClose: closeReview,
      onGrabbed: (result: InteractiveGrabResult) => {
        addToast({
          type: "success",
          title: result.idempotent ? "Grab already started" : "Grab started",
          message: result.idempotent
            ? "Comicarr returned the existing handoff outcome."
            : "The selected release was handed to the configured download route.",
        });
        closeReview();
      },
    },
  };
}
