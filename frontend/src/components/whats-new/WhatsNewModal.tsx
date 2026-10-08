/**
 * Post-upgrade What's New modal (#474 / #451).
 *
 * Opens on first authenticated layout paint when pending_whats_new is set.
 * Cap is by version (never mid-version). Overflow navigates to Settings →
 * About without dismissing. Only "Got it" writes LAST_SEEN_VERSION.
 */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { PanelUnavailable } from "@/components/dashboard/DashboardPanel";
import { useReleaseNotes } from "@/hooks/useReleaseNotes";
import { useDismissWhatsNew } from "@/hooks/useWhatsNew";
import { useVersionInfo } from "@/hooks/useVersion";
import { VersionSection } from "@/components/whats-new/ReleaseNotesList";
import { countBullets } from "@/lib/releaseNotes";
import { panelState } from "@/lib/panelState";

/** Max versions shown in the interrupt; never split a release's bullets. */
export const MODAL_VERSION_CAP = 3;

/** Deep-link target for overflow — About tab, no dismiss. */
export const WHATS_NEW_ARCHIVE_PATH = "/settings?section=about";

export default function WhatsNewModal() {
  const { status, data } = useVersionInfo();
  const pending =
    status === "success" ? (data?.pending_whats_new ?? null) : null;
  const from = pending?.from ?? null;
  const to = pending?.to ?? null;

  const notesQuery = useReleaseNotes(from, to, Boolean(pending));
  const dismiss = useDismissWhatsNew();

  const [open, setOpen] = useState(true);
  const navigate = useNavigate();

  if (!pending || !from || !to || !open) return null;

  const sections = notesQuery.data?.sections ?? [];
  const notesState = panelState(notesQuery, sections.length === 0);
  const single = sections.length === 1;
  const shown = sections.slice(0, MODAL_VERSION_CAP);
  const overflow = Math.max(0, sections.length - shown.length);
  const bullets = countBullets(sections);

  const notesSummary =
    notesState === "loading"
      ? "Loading release notes…"
      : notesState === "unavailable"
        ? "Release notes could not load."
        : notesState === "empty"
          ? "No release notes recorded for this upgrade."
          : sections.length === 1
            ? `${bullets} change${bullets === 1 ? "" : "s"} in this release.`
            : `${bullets} changes across ${sections.length} releases you skipped.`;

  const handleGotIt = async () => {
    try {
      await dismiss.mutateAsync();
      setOpen(false);
    } catch (ignored) {
      void ignored;
    }
  };

  const handleOverflow = () => {
    setOpen(false);
    navigate(WHATS_NEW_ARCHIVE_PATH);
  };

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) setOpen(false);
      }}
    >
      <DialogContent className="max-w-2xl p-0 overflow-hidden gap-0">
        <DialogHeader className="border-b border-border bg-primary/10 px-6 py-4 text-left">
          <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-wider text-primary">
            <Sparkles className="h-3.5 w-3.5" />
            Comicarr updated
          </div>
          <DialogTitle className="mt-1.5 font-mono text-lg">
            {from} → {to}
          </DialogTitle>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            {notesSummary}
          </p>
        </DialogHeader>

        <div className="max-h-[55vh] overflow-y-auto px-6 py-5 space-y-6">
          {notesState === "loading" ? (
            <p className="text-[12px] text-muted-foreground">Loading…</p>
          ) : notesState === "unavailable" ? (
            <div className="space-y-3">
              <PanelUnavailable
                label="Release notes"
                onRetry={() => void notesQuery.refetch()}
                isRetrying={notesQuery.isFetching}
              />
              <p className="text-[12px] text-muted-foreground">
                Notes could not load. You can still read them in{" "}
                <Link
                  to={WHATS_NEW_ARCHIVE_PATH}
                  onClick={() => setOpen(false)}
                  className="text-primary hover:underline"
                >
                  Settings → About
                </Link>
                .
              </p>
            </div>
          ) : (
            <>
              {shown.map((s) => (
                <VersionSection
                  key={s.version}
                  section={s}
                  hideHeading={single}
                />
              ))}
              {overflow > 0 && (
                <button
                  type="button"
                  onClick={handleOverflow}
                  className="flex items-center gap-1 text-[12px] text-primary hover:underline"
                >
                  …and {overflow} earlier release{overflow === 1 ? "" : "s"}
                  <ArrowRight className="h-3 w-3" />
                </button>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-3">
          <span className="text-[11px] text-muted-foreground">
            Dismissing marks {to} as seen for every user of this install.
          </span>
          <Button
            size="sm"
            onClick={() => void handleGotIt()}
            disabled={dismiss.isPending}
          >
            {dismiss.isPending ? "Saving…" : "Got it"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
