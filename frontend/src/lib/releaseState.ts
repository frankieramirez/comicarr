import type { UpcomingIssue } from "@/types";
import { parseDay } from "@/lib/releaseWeek";

/**
 * Where one of this week's releases stands, in the words Releases > Mine
 * uses for its tabs and status column. Needs you wins over everything: an
 * issue with an open Needs attention item is the operator's to fix.
 */
export type ReleaseBucket =
  "needs_you" | "in_progress" | "downloaded" | "coming_up" | "other";

export interface ReleaseState {
  bucket: ReleaseBucket;
  label: string;
  detail?: string;
  tone: string;
  /** Download percent, when the client reports one. */
  progress?: number | null;
}

const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "long" });
const DAY_AND_TIME = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "12m ago", "2h ago", "yesterday", "Tue 21:40" for when a download landed. */
export function landedLabel(
  iso: string | null | undefined,
  now: Date = new Date(),
): string | undefined {
  if (!iso) return undefined;
  const at = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  if (Number.isNaN(at.getTime())) return undefined;
  const minutes = Math.max(
    0,
    Math.round((now.getTime() - at.getTime()) / 60_000),
  );
  if (minutes < 60) return minutes < 1 ? "just now" : `${minutes}m ago`;
  if (minutes < 12 * 60) return `${Math.round(minutes / 60)}h ago`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (at.toDateString() === yesterday.toDateString()) return "yesterday";
  return DAY_AND_TIME.format(at).replace(",", "");
}

export function releaseDay(issue: UpcomingIssue): string {
  return String(issue.IssueDate || issue.ReleaseDate || "").slice(0, 10);
}

export function releaseState(
  issue: UpcomingIssue,
  today: string,
  now: Date = new Date(),
): ReleaseState {
  const status = (issue.Status || "").toLowerCase();
  const day = releaseDay(issue);
  if (issue.attention) {
    return {
      bucket: "needs_you",
      label: issue.attention,
      tone: "var(--status-error)",
    };
  }
  if (status === "downloaded" || status === "archived") {
    return {
      bucket: "downloaded",
      label: "Downloaded",
      detail: landedLabel(issue.downloaded_at, now),
      tone: "var(--status-downloaded)",
    };
  }
  if (status === "snatched") {
    if (issue.download?.phase === "importing") {
      return {
        bucket: "in_progress",
        label: "Importing",
        tone: "var(--in-flight)",
      };
    }
    return {
      bucket: "in_progress",
      label: "Downloading",
      tone: "var(--in-flight)",
      progress: issue.download?.percent ?? null,
    };
  }
  if (status === "wanted") {
    if (day && day > today) {
      return {
        bucket: "coming_up",
        label: `Out ${WEEKDAY.format(parseDay(day))}`,
        detail: "wanted",
        tone: "var(--text-muted)",
      };
    }
    return {
      bucket: "in_progress",
      label: "Searching",
      detail: "wanted",
      tone: "var(--status-wanted)",
    };
  }
  return {
    bucket: day && day > today ? "coming_up" : "other",
    label: issue.Status || "Unknown",
    tone: "var(--text-muted)",
  };
}

/** Wednesday is new comic day in the US direct market. */
export function isNewComicDay(iso: string): boolean {
  return parseDay(iso).getDay() === 3;
}

/** "#23" for comics, "Ch. 213" for manga chapters. */
export function releaseNumber(issue: UpcomingIssue): string {
  const number = issue.IssueNumber || issue.Issue_Number || "";
  if (!number) return "—";
  return issue.ContentType === "manga" ? `Ch. ${number}` : `#${number}`;
}
