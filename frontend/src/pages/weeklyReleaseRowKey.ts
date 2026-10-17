import { encodeRowId } from "@/components/data-table/rowId";

/** How a pull-list row relates to the library, worked out by the backend. */
export type WeeklyLibraryState =
  "wanted" | "downloaded" | "in_library" | "not_in_library";

export interface WeeklyIssue {
  COMIC: string;
  ISSUE: string;
  PUBLISHER: string;
  SHIPDATE: string;
  STATUS: string;
  ComicID: string | null;
  IssueID?: string | null;
  format?: string | null;
  rowid?: number | null;
  in_library?: boolean;
  library_issue_id?: string | null;
  issue_status?: string | null;
  state?: WeeklyLibraryState;
}

export interface WeekRef {
  week: string;
  year: string;
}

export interface WeeklyPullWeek extends WeekRef {
  /** Sunday that opens the week, ISO date. */
  start: string;
  /** Saturday that closes the week, ISO date. */
  end: string;
  /** Weeks from the current week; 0 is this week. */
  offset: number;
  prev: WeekRef | null;
  next: WeekRef | null;
  /** `unavailable` means no source could fill the week yet. */
  source: "stored" | "fetched" | "unavailable";
  rows: WeeklyIssue[];
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
