import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSeriesImage } from "@/lib/api";
import type { SearchResult } from "@/types";

const MAX_CONCURRENT = 4;

/**
 * Lazy-loads cover images for Metron search results via throttled
 * getSeriesImage calls, patching the React Query cache as each resolves.
 */
export function useMetronImages(results: SearchResult[], queryKey: unknown[]) {
  const queryClient = useQueryClient();
  const activeRef = useRef(0);
  const queueRef = useRef<string[]>([]);
  const fetchedRef = useRef(new Set<string>());

  useEffect(() => {
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
