import { plural, t } from "@lingui/core/macro";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";
import { useConfig } from "@/hooks/useConfig";
import { apiRequest } from "@/lib/api";
import { shelfErrorMessage } from "@/lib/shelf";
import type {
  SeriesShelf,
  ShelfCopy,
  ShelfCopyFields,
  ShelfCopyPage,
  ShelfItem,
} from "@/types";

const SHELF = ["shelf"] as const;

/** Whether the operator turned on "Track print copies" in Settings. */
export function useShelfEnabled(): boolean {
  return Boolean(useConfig().data?.shelf_enabled);
}

/** Copy counts for one series. Disabled while the shelf is switched off. */
export function useSeriesShelf(
  comicId: string | undefined,
): UseQueryResult<SeriesShelf> {
  const enabled = useShelfEnabled();
  return useQuery({
    queryKey: [...SHELF, "series", comicId],
    queryFn: () =>
      apiRequest<SeriesShelf>(
        "GET",
        `/api/shelf/series/${encodeURIComponent(comicId ?? "")}`,
      ),
    enabled: enabled && Boolean(comicId),
  });
}

export interface ShelfCopyFilters {
  comic_id?: string;
  item_id?: string;
  volume_number?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export function useShelfCopies(
  filters: ShelfCopyFilters,
  enabled = true,
): UseQueryResult<ShelfCopyPage> {
  return useQuery({
    queryKey: [...SHELF, "copies", filters],
    queryFn: () => {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(filters)) {
        if (value !== undefined && value !== "") params.set(key, String(value));
      }
      return apiRequest<ShelfCopyPage>("GET", `/api/shelf/copies?${params}`);
    },
    enabled,
  });
}

function useShelfMutation<TInput, TResult>(
  run: (input: TInput) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SHELF }),
    onError: (error: unknown) =>
      addToast({ type: "error", message: shelfErrorMessage(error) }),
  });
}

/** Add a copy of `item`, or change the copy `copyId` names. */
export function useSaveCopy() {
  return useShelfMutation(
    ({
      item,
      copyId,
      fields,
    }: {
      item: ShelfItem;
      copyId?: string;
      fields: ShelfCopyFields;
    }) =>
      copyId
        ? apiRequest<ShelfCopy>(
            "PATCH",
            `/api/shelf/copies/${encodeURIComponent(copyId)}`,
            fields,
          )
        : apiRequest<ShelfCopy>("POST", "/api/shelf/copies", {
            ...item,
            ...fields,
          }),
  );
}

export function useDeleteCopy() {
  return useShelfMutation((copyId: string) =>
    apiRequest<void>(
      "DELETE",
      `/api/shelf/copies/${encodeURIComponent(copyId)}`,
    ),
  );
}

/** Bulk "Mark on shelf": one plain copy for each item that has none. */
export function useMarkOnShelf() {
  const { addToast } = useToast();
  const mutation = useShelfMutation(
    ({
      comicId,
      ...body
    }: {
      comicId: string;
      ItemIDs?: string[];
      VolumeNumbers?: string[];
    }) =>
      apiRequest<{ created: number; skipped: number }>(
        "POST",
        `/api/shelf/series/${encodeURIComponent(comicId)}/mark`,
        body,
      ),
  );
  return {
    isPending: mutation.isPending,
    mark: async (
      comicId: string,
      items: { ItemIDs?: string[]; VolumeNumbers?: string[] },
    ) => {
      const { created } = await mutation.mutateAsync({ comicId, ...items });
      addToast({
        type: "success",
        message:
          created === 0
            ? t`Those are already on your shelf`
            : plural(created, {
                one: "# book marked on your shelf",
                other: "# books marked on your shelf",
              }),
      });
    },
  };
}
