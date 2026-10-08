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

const TONES: Record<string, StatusTone> = {
  active: {
    key: "active",
    label: "Active",
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  paused: {
    key: "paused",
    label: "Paused",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  ended: {
    key: "ended",
    label: "Ended",
    token: "var(--status-ended)",
    badgeVariant: "ended",
    glowColor: "var(--status-ended)",
  },
  loading: {
    key: "loading",
    label: "Loading",
    ...MUTED,
  },
  downloaded: {
    key: "downloaded",
    label: "Downloaded",
    token: "var(--status-downloaded)",
    badgeVariant: "downloaded",
    glowColor: "var(--status-downloaded)",
  },
  wanted: {
    key: "wanted",
    label: "Wanted",
    token: "var(--status-wanted)",
    badgeVariant: "wanted",
    glowColor: "var(--status-wanted)",
  },
  skipped: {
    key: "skipped",
    label: "Skipped",
    token: "var(--status-skipped)",
    badgeVariant: "skipped",
    glowColor: "var(--status-skipped)",
  },
  ignored: {
    key: "ignored",
    label: "Ignored",
    token: "var(--status-skipped)",
    badgeVariant: "skipped",
    glowColor: "var(--status-skipped)",
  },
  reserved: {
    key: "reserved",
    label: "Reserved",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  snatched: {
    key: "snatched",
    label: "Snatched",
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  archived: {
    key: "archived",
    label: "Archived",
    ...MUTED,
  },
  failed: {
    key: "failed",
    label: "Failed",
    token: "var(--status-error)",
    badgeVariant: "error",
    glowColor: "var(--status-error)",
  },
  unknown: {
    key: "unknown",
    label: "Unknown",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  missing: {
    key: "missing",
    label: "Missing",
    token: "var(--status-wanted)",
    badgeVariant: "wanted",
    glowColor: "var(--status-wanted)",
  },
  queued: {
    key: "queued",
    label: "Queued",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  pending: {
    key: "pending",
    label: "Pending",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
  completed: {
    key: "completed",
    label: "Completed",
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  done: {
    key: "done",
    label: "Done",
    token: "var(--status-active)",
    badgeVariant: "active",
    glowColor: "var(--status-active)",
  },
  "manual review": {
    key: "manual review",
    label: "Manual review",
    token: "var(--status-paused)",
    badgeVariant: "paused",
    glowColor: "var(--status-paused)",
  },
};

export const STATUS_TONE_KEYS = Object.keys(TONES);

function resolveKey(raw: string): string {
  const normalized = raw.trim().toLowerCase();
  if (normalized in TONES) return normalized;
  if (normalized.includes("fail") || normalized.includes("error")) {
    return "failed";
  }
  if (normalized.includes("manual") || normalized.includes("review")) {
    return "manual review";
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
  if (key && TONES[key]) {
    const tone = TONES[key];
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
