import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { Comic, Issue } from "@/types";

/** Raw issue row from the authenticated metadata API. */
export type IssueMetadata = Issue & {
  AcquisitionIntent?: string | null;
  ArtworkURL?: string | null;
  ComicSize?: string | null;
  DigitalDate?: string | null;
  Type?: string | null;
  Deleted?: number | null;
};

export interface IssueDetailData {
  issue: IssueMetadata;
  series: Comic | null;
}

/**
 * Load a single issue via the authenticated metadata API, optionally with its
 * parent series for breadcrumb context. Rejects when the issue does not belong
 * to the series id in the route.
 */
export function useIssueDetail(
  comicId: string | undefined,
  issueId: string | undefined,
): UseQueryResult<IssueDetailData> {
  return useQuery({
    queryKey: ["issue-detail", comicId, issueId],
    enabled: Boolean(comicId && issueId),
    queryFn: async () => {
      const issue = await apiRequest<IssueMetadata>(
        "GET",
        `/api/metadata/issue/${issueId}`,
      );

      const issueComicId = String(issue.ComicID ?? issue.comicId ?? "");
      if (!issueComicId || issueComicId !== String(comicId)) {
        throw new Error("Issue not found for this series");
      }

      try {
        const detail = await apiRequest<{ comic: Comic }>(
          "GET",
          `/api/series/${comicId}`,
        );
        return { issue, series: detail.comic ?? null };
      } catch {
        return { issue, series: null };
      }
    },
  });
}
