import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  InteractiveGrabResult,
  InteractiveSearchSession,
  ReleaseReviewIssue,
} from "@/types";

const INTERACTIVE_POLL_MS = 2_000;
const ACTIVE_STATES = new Set(["queued", "running"]);

// Expiry never appears as a session `state` — the server signals it as a
// 410 on poll and grab (router returns {"status": "expired"}), so it must
// be recognized from the error, not the payload.
export function isInteractiveSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 410;
}

export interface StartInteractiveSearchInput {
  entityType: "issue" | "annual" | "story_arc_issue" | "series";
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
    retry: (failureCount, error) =>
      !isInteractiveSessionExpired(error) && failureCount < 1,
    refetchInterval: (query) => {
      // After an error the query keeps its last payload, so a session that
      // expired mid-run still reads as "running" — without this branch the
      // client polls the dead session (and its 410) forever.
      if (isInteractiveSessionExpired(query.state.error)) return false;
      return ACTIVE_STATES.has(query.state.data?.state ?? "")
        ? INTERACTIVE_POLL_MS
        : false;
    },
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
  // Guards overlapping starts. `isPending` from the closure is stale for two
  // clicks in the same tick, so the in-flight flag lives in a ref instead.
  const startInFlight = useRef(false);

  const startReview = async (
    issue: ReleaseReviewIssue,
    target: StartInteractiveSearchInput,
  ) => {
    if (!target.entityId) return;
    if (startInFlight.current) return;
    startInFlight.current = true;
    setReviewIssue(issue);
    setReviewTarget(target);
    setReviewSessionId(null);
    startInteractiveSearch.reset();
    try {
      const session = await startInteractiveSearch.mutateAsync(target);
      setReviewSessionId(session.session_id);
    } catch {
      // The sheet owns the actionable error and retry affordance.
    } finally {
      // Always clears, so a failed start still allows retry and closing the
      // sheet mid-flight cannot strand the flag.
      startInFlight.current = false;
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
