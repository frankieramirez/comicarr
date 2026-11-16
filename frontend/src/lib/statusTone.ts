import { t } from "@lingui/core/macro";
import type { IssueDisplayState, SeriesStatus } from "@/types/states.generated";

/**
 * Every issue and series state the backend registry declares
 * (comicarr/app/common/state_machines.py), lowercased. TONES must name each
 * one, so a state added there cannot reach a badge without a translated
 * label and a chosen tone: the build fails first.
 */
type RegisteredStatusKey = Lowercase<IssueDisplayState | SeriesStatus>;

export type StatusBadgeVariant =
  | "default"
  | "active"
  | "paused"
  | "ended"
  | "error"
  | "wanted"
  | "downloaded"
  | "skipped";

export type StatusTone = {
  key: string;
  token: string;
  label: string;
  badgeVariant: StatusBadgeVariant;
  glowColor: string;
};

const MUTED: Omit<StatusTone, "key" | "label"> = {
  token: "var(--muted-foreground)",
  badgeVariant: "default",
  glowColor: "var(--muted-foreground)",
};

const TONES = {
  active: {
    key: "active",
    get label() {
      return t`Active`;
    },
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  paused: {
    key: "paused",
    get label() {
      return t`Paused`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  ended: {
    key: "ended",
    get label() {
      return t`Ended`;
    },
    token: "var(--status-ended)",
    badgeVariant: "ended",
    glowColor: "var(--status-ended)",
  },
  loading: {
    key: "loading",
    get label() {
      return t`Loading`;
    },
    ...MUTED,
  },
  downloaded: {
    key: "downloaded",
    get label() {
      return t`Downloaded`;
    },
    token: "var(--status-downloaded)",
    badgeVariant: "downloaded",
    glowColor: "var(--status-downloaded)",
  },
  wanted: {
    key: "wanted",
    get label() {
      return t`Wanted`;
    },
    token: "var(--status-wanted)",
    badgeVariant: "wanted",
    glowColor: "var(--status-wanted)",
  },
  skipped: {
    key: "skipped",
    get label() {
      return t`Skipped`;
    },
    token: "var(--status-skipped)",
    badgeVariant: "skipped",
    glowColor: "var(--status-skipped)",
  },
  ignored: {
    key: "ignored",
    get label() {
      return t`Ignored`;
    },
    token: "var(--status-skipped)",
    badgeVariant: "skipped",
    glowColor: "var(--status-skipped)",
  },
  reserved: {
    key: "reserved",
    get label() {
      return t`Reserved`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  snatched: {
    key: "snatched",
    get label() {
      return t`Snatched`;
    },
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  archived: {
    key: "archived",
    get label() {
      return t`Archived`;
    },
    ...MUTED,
  },
  // A manga chapter inside an owned volume: not a file of its own, so it
  // stays as quiet as Archived.
  covered: {
    key: "covered",
    get label() {
      return t`Covered`;
    },
    ...MUTED,
  },
  failed: {
    key: "failed",
    get label() {
      return t`Failed`;
    },
    token: "var(--status-error)",
    badgeVariant: "error",
    glowColor: "var(--status-error)",
  },
  // A series its metadata provider returned nothing for.
  error: {
    key: "error",
    get label() {
      return t`Error`;
    },
    token: "var(--status-error)",
    badgeVariant: "error",
    glowColor: "var(--status-error)",
  },
  unknown: {
    key: "unknown",
    get label() {
      return t`Unknown`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  // The projection says "Missing" for a wanted issue with no explicit
  // intent; on screen it is Wanted, the word every count uses.
  missing: {
    key: "missing",
    get label() {
      return t`Wanted`;
    },
    token: "var(--status-wanted)",
    badgeVariant: "wanted",
    glowColor: "var(--status-wanted)",
  },
  queued: {
    key: "queued",
    get label() {
      return t`Queued`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  pending: {
    key: "pending",
    get label() {
      return t`Pending`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  completed: {
    key: "completed",
    get label() {
      return t`Completed`;
    },
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  done: {
    key: "done",
    get label() {
      return t`Done`;
    },
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  "manual review": {
    key: "manual review",
    get label() {
      return t`Manual review`;
    },
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
} satisfies Record<RegisteredStatusKey, StatusTone> &
  Record<string, StatusTone>;

/** TONES for lookup by a raw status string, which may be any word at all. */
const TONE_BY_KEY: Record<string, StatusTone> = TONES;

const MANUAL_REVIEW_KEY = "manual review";

export const STATUS_TONE_KEYS = Object.keys(TONES);

function resolveKey(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  if (normalized in TONE_BY_KEY) return normalized;
  if (normalized.includes("fail") || normalized.includes("error")) {
    return "failed";
  }
  if (normalized.includes("manual") || normalized.includes("review")) {
    return MANUAL_REVIEW_KEY;
  }
  if (normalized.includes("snatch")) return "snatched";
  if (normalized.includes("down")) return "active";
  if (normalized.includes("queue")) return "queued";
  if (normalized.includes("pend")) return "pending";
  return "";
}

/** Shared status → `--status-*` token, label, and Badge variant. */
export function statusTone(status?: string | null): StatusTone | null {
  if (!status) return null;
  const key = resolveKey(status);
  if (key && TONE_BY_KEY[key]) {
    const tone = TONE_BY_KEY[key];
    if (status.trim().toLowerCase() === key) return tone;
    return { ...tone, label: status };
  }
  return {
    key: "custom",
    label: status,
    ...MUTED,
  };
}

export function toneStatusForHealth(
  tone: "ready" | "warning" | "danger" | "neutral",
): string {
  switch (tone) {
    case "ready":
      return "active";
    case "warning":
      return "paused";
    case "danger":
      return "failed";
    default:
      return "unknown";
  }
}
