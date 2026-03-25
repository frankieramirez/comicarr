import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

interface BulkMetatagParams {
  comicId: string;
  issueIds: string[];
}

export function useBulkMetatag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ comicId, issueIds }: BulkMetatagParams) => {
      return apiRequest("POST", "/api/metadata/metatag/bulk", {
        id: comicId,
        issue_ids: issueIds,
      });
    },
    onSuccess: (_, { comicId }) => {
      // Invalidate series data to reflect any changes after tagging completes
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}
