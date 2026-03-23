import { useEffect, useRef, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSeriesImage } from "@/lib/api";
import type { SearchResult } from "@/types";

const MAX_CONCURRENT = 4;

interface SearchResponse {
  results?: Record<string, unknown>[];
  pagination?: unknown;
}

/**
 * Lazy-loads cover images for Metron search results via throttled
 * getSeriesImage calls, patching the React Query cache as each resolves.
 */
export function useMetronImages(results: SearchResult[], queryKey: unknown[]) {
  const queryClient = useQueryClient();
  const activeRef = useRef(0);
  const fetchedRef = useRef(new Set<string>());
  const lastKeyRef = useRef("");

  const keyStr = JSON.stringify(queryKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableKey = useMemo(() => queryKey, [keyStr]);

  useEffect(() => {
    if (lastKeyRef.current !== keyStr) {
      fetchedRef.current = new Set();
      lastKeyRef.current = keyStr;
    }

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

    let cancelled = false;
    const queue = needsImage.flatMap((r) => (r.comicid ? [r.comicid] : []));

    // Mark as fetched immediately to prevent duplicate queuing
    for (const id of queue) {
      fetchedRef.current.add(id);
    }

    function processQueue() {
      while (activeRef.current < MAX_CONCURRENT && queue.length > 0) {
        const seriesId = queue.shift()!;
        activeRef.current++;

        getSeriesImage(seriesId)
          .then((imageUrl) => {
            if (cancelled || !imageUrl) return;
            queryClient.setQueryData(stableKey, (old: unknown) => {
              if (!old) return old;
              return patchResults(old as SearchResponse, seriesId, imageUrl);
            });
          })
          .finally(() => {
            activeRef.current--;
            if (!cancelled) processQueue();
          });
      }
    }

    processQueue();

    return () => {
      cancelled = true;
    };
  }, [results, stableKey, keyStr, queryClient]);
}

function patchResults(
  data: SearchResponse,
  seriesId: string,
  imageUrl: string,
): SearchResponse {
  if (!data.results || !Array.isArray(data.results)) return data;

  return {
    ...data,
    results: data.results.map((item) => {
      if (item.comicid === seriesId) {
        return {
          ...item,
          comicimage: imageUrl,
          comicthumb: imageUrl,
          image: imageUrl,
        };
      }
      return item;
    }),
  };
}
