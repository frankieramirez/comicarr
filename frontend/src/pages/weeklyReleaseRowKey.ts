import { encodeRowId } from "@/components/data-table/rowId";

export interface WeeklyIssue {
  COMIC: string;
  ISSUE: string;
  PUBLISHER: string;
  SHIPDATE: string;
  STATUS: string;
  ComicID: string | null;
  IssueID?: string | null;
  rowid?: number | null;
}

export function weeklyReleaseRowKey(issue: WeeklyIssue, index: number): string {
  return encodeRowId([
    issue.rowid ?? issue.IssueID,
    issue.ComicID,
    issue.COMIC,
    issue.ISSUE,
    issue.SHIPDATE,
    issue.ComicID ? null : index,
  ]);
}
