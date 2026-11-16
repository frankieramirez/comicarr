import { ph, t } from "@lingui/core/macro";
import type { UpcomingIssue } from "@/types";
import type {
  MangaReleaseRow,
  WeeklyIssue,
  WeeklyLibraryState,
  WeeklyPullWeek,
} from "@/pages/weeklyReleaseRowKey";
import { releaseDay } from "@/lib/releaseState";
import type { ReleaseFormat } from "@/components/releases/releaseFormat";

/**
 * One list for Releases (#1383): the pull list's comics, MangaUpdates'
 * manga, and any library release neither of them lists, so turning off
 * "Only my library" never hides the library's own week.
 */

function numberKey(value: string | null | undefined): string {
  const text = String(value ?? "").trim();
  const parsed = Number.parseFloat(text);
  return Number.isFinite(parsed) && /^\d/.test(text) ? String(parsed) : text;
}

function libraryState(status: string | null | undefined): WeeklyLibraryState {
  const value = (status || "").toLowerCase();
  if (value === "downloaded" || value === "archived") return "downloaded";
  if (value === "wanted" || value === "snatched" || value === "failed")
    return "wanted";
  return "in_library";
}

export function mangaRow(row: MangaReleaseRow): WeeklyIssue {
  return {
    ...row,
    PUBLISHER: "",
    STATUS: "",
    kind: "manga",
    source: "mangaupdates",
    mangaType: row.format,
    format: null,
  };
}

export function libraryRow(issue: UpcomingIssue): WeeklyIssue {
  const manga = issue.ContentType === "manga";
  return {
    key: `library-${issue.IssueID}`,
    source: "library",
    kind: manga ? "manga" : "comic",
    COMIC: issue.ComicName || "",
    ISSUE: issue.IssueNumber || issue.Issue_Number || "",
    PUBLISHER: manga ? "" : issue.Publisher || "",
    SHIPDATE: releaseDay(issue),
    STATUS: issue.Status || "",
    ComicID: issue.ComicID,
    IssueID: issue.IssueID,
    in_library: true,
    library_issue_id: issue.IssueID,
    issue_status: issue.Status || null,
    state: libraryState(issue.Status),
    mangaType: null,
  };
}

/** Pull-list comics, then manga, then library releases neither one listed. */
export function mergeReleases(
  week: WeeklyPullWeek | undefined,
  libraryIssues: UpcomingIssue[],
): WeeklyIssue[] {
  const comics = (week?.rows ?? []).map((row): WeeklyIssue => ({
    ...row,
    kind: "comic",
    source: "pull",
  }));
  const manga = (week?.manga?.rows ?? []).map(mangaRow);
  const seenIssues = new Set<string>();
  const seenNumbers = new Set<string>();
  for (const row of [...comics, ...manga]) {
    const issueId = row.library_issue_id || row.IssueID;
    if (issueId) seenIssues.add(issueId);
    if (row.ComicID) seenNumbers.add(`${row.ComicID}|${numberKey(row.ISSUE)}`);
  }
  const extra = libraryIssues
    .filter(
      (issue) =>
        !seenIssues.has(issue.IssueID) &&
        !seenNumbers.has(
          `${issue.ComicID}|${numberKey(issue.IssueNumber || issue.Issue_Number)}`,
        ),
    )
    .map(libraryRow);
  return [...comics, ...manga, ...extra];
}

const MINE_STATUSES = new Set(["wanted", "snatched", "downloaded"]);

/**
 * Only my library: the library's week from the pull list and store dates,
 * plus chapters MangaUpdates lists for library manga, so a chapter that
 * came out this week shows even when its MangaDex date falls elsewhere.
 */
export function withLibraryManga(
  week: WeeklyPullWeek | undefined,
  issues: UpcomingIssue[],
): UpcomingIssue[] {
  const seen = new Set(issues.map((issue) => issue.IssueID));
  const extra: UpcomingIssue[] = [];
  for (const row of week?.manga?.rows ?? []) {
    const issueId = row.library_issue_id;
    const status = (row.issue_status || "").toLowerCase();
    if (!issueId || seen.has(issueId) || !MINE_STATUSES.has(status)) continue;
    seen.add(issueId);
    extra.push({
      IssueID: issueId,
      ComicID: row.ComicID || "",
      ComicName: row.COMIC,
      IssueNumber: row.ISSUE,
      IssueDate: row.SHIPDATE,
      Status: row.issue_status as UpcomingIssue["Status"],
      Publisher: null,
      ContentType: "manga",
    } as UpcomingIssue);
  }
  return [...issues, ...extra];
}

export function matchesFormat(row: WeeklyIssue, format: ReleaseFormat) {
  if (format === "all") return true;
  if (format === "comics") return row.kind !== "manga";
  return (
    row.kind === "manga" &&
    (row.mangaType ?? "").toLowerCase() === format.toLowerCase()
  );
}

/**
 * Popular only trims MangaUpdates' long tail; comics, library series and
 * library releases always stay.
 */
export function passesPopular(row: WeeklyIssue, popularOnly: boolean) {
  return (
    !popularOnly ||
    row.source !== "mangaupdates" ||
    row.popular_rank != null ||
    row.state !== "not_in_library"
  );
}

const UNTYPED_MANGA = "Manga, manhwa or manhua";

/** The heading a row groups under: publisher for comics, type for manga. */
export function groupKey(row: WeeklyIssue): string {
  if (row.kind === "manga") return row.mangaType || UNTYPED_MANGA;
  return row.PUBLISHER || t`Unknown publisher`;
}

/** How a row reads in the number column: `#23`, `Ch. 411–412`, `Vol. 14`. */
export function releaseLabel(row: WeeklyIssue): string {
  if (row.kind !== "manga") return row.ISSUE ? `#${row.ISSUE}` : "";
  if (row.chapters || (row.source !== "mangaupdates" && row.ISSUE))
    return t`Ch. ${ph({ chapter: row.chapters || row.ISSUE })}`;
  if (row.volume) return t`Vol. ${ph({ volume: row.volume })}`;
  return "";
}
