/**
 * Permanent Settings → About "What's new" archive (#474 / #451).
 *
 * Server floors depth at the pending range and pads toward ~10 when quiet.
 * Always shows version headings. "Mark as read" writes LAST_SEEN_VERSION.
 */
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDismissWhatsNew, useWhatsNewArchive } from "@/hooks/useWhatsNew";
import { VersionSection } from "@/components/whats-new/ReleaseNotesList";
import { countBullets } from "@/lib/releaseNotes";
import { cn } from "@/lib/utils";
import type { ReleaseNotesSection } from "@/types/version";

function isUnread(
  version: string,
  pending: { from: string; to: string } | null | undefined,
): boolean {
  if (!pending) return false;
  return (
    versionCompare(version, pending.from) > 0 &&
    versionCompare(version, pending.to) <= 0
  );
}

/** Lightweight semver compare for UI badges (x.y.z only). */
function versionCompare(a: string, b: string): number {
  const pa = a
    .replace(/^v/i, "")
    .split(".")
    .map((n) => parseInt(n, 10) || 0);
  const pb = b
    .replace(/^v/i, "")
    .split(".")
    .map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d > 0 ? 1 : -1;
  }
  return 0;
}

export default function WhatsNewArchive() {
  const archiveQuery = useWhatsNewArchive();
  const dismiss = useDismissWhatsNew();
  const sections = archiveQuery.data?.sections ?? [];
  const pending = archiveQuery.data?.pending ?? null;
  const current = archiveQuery.data?.current;

  const [expanded, setExpanded] = useState<string | null>(null);

  const defaultExpanded = expanded ?? sections[0]?.version ?? null;

  if (archiveQuery.isLoading) {
    return (
      <div
        className="rounded-lg border px-3 py-3 text-[12.5px] text-muted-foreground"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
      >
        Loading release history…
      </div>
    );
  }

  if (archiveQuery.isError) {
    return (
      <div
        className="rounded-lg border px-3 py-3 text-[12.5px] text-muted-foreground"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
      >
        Could not load release history.
      </div>
    );
  }

  const pendingCount = pending
    ? sections.filter((s) => isUnread(s.version, pending)).length
    : 0;
  const pendingBullets = pending
    ? countBullets(sections.filter((s) => isUnread(s.version, pending)))
    : 0;

  return (
    <div className="rounded-md border border-border">
      <div
        className={cn(
          "flex items-start justify-between gap-4 border-b border-border px-4 py-3",
          pending && "bg-primary/5",
        )}
      >
        <div>
          <div className="flex items-center gap-2">
            {pending && pendingCount > 0 && (
              <span
                data-testid="whats-new-unread"
                className="rounded-sm bg-primary/15 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-primary"
              >
                {pendingCount} unread
              </span>
            )}
          </div>
          <p
            className="text-[11.5px] text-muted-foreground"
            data-testid="whats-new-archive-summary"
          >
            {pending
              ? `You upgraded from ${pending.from}. ${pendingCount} release${pendingCount === 1 ? "" : "s"} · ${pendingBullets} change${pendingBullets === 1 ? "" : "s"}.`
              : current
                ? `Running ${current}. Nothing unread — recent history below.`
                : "Release notes for this install."}
          </p>
        </div>
        {pending && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => void dismiss.mutateAsync()}
            disabled={dismiss.isPending}
          >
            {dismiss.isPending ? "Saving…" : "Mark as read"}
          </Button>
        )}
      </div>

      {sections.length === 0 ? (
        <p className="px-4 py-6 text-center text-[12px] text-muted-foreground">
          No release notes to show.
        </p>
      ) : (
        <div className="divide-y divide-border">
          {sections.map((s) => (
            <ArchiveRow
              key={s.version}
              section={s}
              unread={isUnread(s.version, pending)}
              open={(expanded ?? defaultExpanded) === s.version}
              onToggle={() =>
                setExpanded((cur) => {
                  const openId = cur ?? defaultExpanded;
                  return openId === s.version ? "" : s.version;
                })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ArchiveRow({
  section,
  unread,
  open,
  onToggle,
}: {
  section: ReleaseNotesSection;
  unread: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-secondary/50"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="font-mono text-[12px] font-medium">
          {section.version}
        </span>
        {unread && (
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />
        )}
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {section.bullets.length} change
          {section.bullets.length === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 pl-9">
          <VersionSection section={section} density="compact" hideHeading />
        </div>
      )}
    </div>
  );
}
