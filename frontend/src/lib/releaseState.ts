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
}

const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "long" });

export function releaseDay(issue: UpcomingIssue): string {
  return String(issue.IssueDate || issue.ReleaseDate || "").slice(0, 10);
}

export function releaseState(
  issue: UpcomingIssue,
  today: string,
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
      tone: "var(--status-downloaded)",
    };
  }
  if (status === "snatched") {
    return {
      bucket: "in_progress",
      label: "Downloading",
      tone: "var(--in-flight)",
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
