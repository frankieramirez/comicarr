import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { InteractiveGrabResult, InteractiveSearchSession } from "@/types";

const INTERACTIVE_POLL_MS = 2_000;
const ACTIVE_STATES = new Set(["queued", "running"]);

interface StartInteractiveSearchInput {
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
      ]);
    },
  });
}
