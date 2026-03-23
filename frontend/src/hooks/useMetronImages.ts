import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSeriesImage } from "@/lib/api";
import type { SearchResult } from "@/types";

const MAX_CONCURRENT = 4;

/**
 * Lazy-loads cover images for Metron search results.
 *
 * Metron's series_list API doesn't include images, so we fire
 * throttled getSeriesImage calls and patch the React Query cache
 * as each resolves.
 */
export function useMetronImages(results: SearchResult[], queryKey: unknown[]) {
  const queryClient = useQueryClient();
  const activeRef = useRef(0);
  const queueRef = useRef<string[]>([]);
  const fetchedRef = useRef(new Set<string>());

  useEffect(() => {
    // Find Metron results that need images
    const needsImage = results.filter(
      (r) =>
        r.metadata_source === "metron" &&
        !r.image &&
        !r.comicimage &&
        !r.comicthumb &&
        r.comicid &&
        !fetchedRef.current.has(r.comicid),
    );

    if (needsImage.length === 0) return;

    // Build queue of series IDs to fetch
    const ids = needsImage.map((r) => r.comicid!);
    queueRef.current = [...ids];

    function processQueue() {
      while (
        activeRef.current < MAX_CONCURRENT &&
        queueRef.current.length > 0
      ) {
        const seriesId = queueRef.current.shift()!;
        fetchedRef.current.add(seriesId);
        activeRef.current++;

        getSeriesImage(seriesId)
          .then((imageUrl) => {
            if (imageUrl) {
              // Update the React Query cache in-place
              queryClient.setQueryData(queryKey, (old: unknown) => {
                if (!old) return old;
                return patchResults(old, seriesId, imageUrl);
              });
            }
          })
          .finally(() => {
            activeRef.current--;
            processQueue();
          });
      }
    }

    processQueue();
  }, [results, queryKey, queryClient]);
}

/**
 * Patch a search response to update the image for a given series ID.
 * Handles both array and object response formats.
 */
function patchResults(
  data: unknown,
  seriesId: string,
  imageUrl: string,
): unknown {
  const patchItem = (item: Record<string, unknown>) => {
    if (item.comicid === seriesId) {
      return {
        ...item,
        comicimage: imageUrl,
        comicthumb: imageUrl,
        image: imageUrl,
      };
    }
    return item;
  };

  if (Array.isArray(data)) {
    return data.map(patchItem);
  }

  const obj = data as Record<string, unknown>;
  if (obj.results && Array.isArray(obj.results)) {
    return {
      ...obj,
      results: (obj.results as Record<string, unknown>[]).map(patchItem),
    };
  }

  return data;
}
