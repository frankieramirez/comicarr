import { t } from "@lingui/core/macro";

/**
 * Operator-facing copy for update diagnostics (Settings → About → Updates).
 * Codes match GET /api/system/version update_reason when update_state is unknown.
 */

export type UpdateState = "behind" | "current" | "unknown" | string;
export type UpdateReason =
  "never_checked" | "unreachable" | "rate_limited" | string | null | undefined;

export function formatUnknownUpdateReason(reason: UpdateReason): string {
  switch (reason || "never_checked") {
    case "never_checked":
      return t`Not checked yet`;
    case "unreachable":
      return t`Could not reach the release source`;
    case "rate_limited":
      return t`Rate limited — will retry on the normal schedule`;
    default:
      return t`Update status is unavailable`;
  }
}

/** Open-closed pending range ends for post-upgrade What's New (#474). */
export interface PendingWhatsNew {
  /** Exclusive lower bound (LAST_SEEN_VERSION). */
  from: string;
  /** Inclusive upper bound (current release). */
  to: string;
}

export interface VersionInfo {
  current_version?: string | null;
  latest_version?: string | null;
  release_version?: string | null;
  update_state?: UpdateState | null;
  update_reason?: UpdateReason;
  install_type?: string | null;
  message?: string | null;
  /** When set, show the post-upgrade modal / unread archive state. */
  pending_whats_new?: PendingWhatsNew | null;
}

/** One-line diagnostic for the Updates group (not a second badge). */
export function formatUpdateDiagnostic(info: VersionInfo | undefined): string {
  if (!info) return t`Loading update status…`;

  const state = info.update_state ?? "unknown";
  if (state === "behind") {
    const current = info.release_version || "—";
    const latest = info.latest_version || "—";
    return t`Update available: ${current} → ${latest}`;
  }
  if (state === "current") {
    return t`Up to date`;
  }
  return formatUnknownUpdateReason(info.update_reason);
}
