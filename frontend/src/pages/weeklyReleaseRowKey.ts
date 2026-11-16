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
  /** Set on rows that are not pull-list comics (#1383). */
  kind?: "comic" | "manga";
  /** `mangaupdates` for manga rows, `library` for rows only the library knows. */
  source?: "pull" | "mangaupdates" | "library";
  /** Stable id for rows without a pull-list rowid. */
  key?: string;
  /** Manga: chapter range released this week, such as `411–412`. */
  chapters?: string;
  /** Manga: the volume released this week, when it was a volume. */
  volume?: string;
  /** Manga, Manhwa or Manhua; null until MangaUpdates says. */
  mangaType?: string | null;
  /** Rank in MangaUpdates' weekly popularity, when in the top list. */
  popular_rank?: number | null;
  cover?: string | null;
  url?: string | null;
}

/** One manga row as `/api/weekly` sends it. */
export interface MangaReleaseRow extends Omit<
  WeeklyIssue,
  "PUBLISHER" | "STATUS"
> {
  PUBLISHER: null;
  format: string | null;
  mu_series_id: string;
  year?: string | null;
}

export interface MangaWeek {
  /** `refreshing` while MangaUpdates is being read in the background. */
  status: "ok" | "refreshing" | "disabled" | "unavailable";
  rows: MangaReleaseRow[];
  error?: string | null;
  popular_rank: number;
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
  /** The week's manga, manhwa and manhua; older servers leave it out. */
  manga?: MangaWeek;
}

export function weeklyReleaseRowKey(issue: WeeklyIssue, index: number): string {
  if (issue.key) return encodeRowId([issue.key]);
  return encodeRowId([
    issue.rowid ?? issue.IssueID,
    issue.ComicID,
    issue.COMIC,
    issue.ISSUE,
    issue.SHIPDATE,
    issue.ComicID ? null : index,
  ]);
}
