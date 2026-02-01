import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiCall } from "@/lib/api";

interface BulkMetatagParams {
  comicId: string;
  issueIds: string[];
}

export function useBulkMetatag() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ comicId, issueIds }: BulkMetatagParams) => {
      return apiCall("bulkMetatag", {
        id: comicId,
        issue_ids: issueIds.join(","),
      });
    },
    onSuccess: (_, { comicId }) => {
      // Invalidate series data to reflect any changes after tagging completes
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}
