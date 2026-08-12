import { useState } from "react";
import {
  Ban,
  CheckCircle2,
  Download,
  LoaderCircle,
  RefreshCw,
  SearchX,
  ShieldAlert,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  useGrabInteractiveCandidate,
  useInteractiveSearch,
} from "@/hooks/useInteractiveSearch";
import { getErrorMessage } from "@/lib/api";
import type {
  InteractiveGrabResult,
  InteractiveReleaseCandidate,
  UpcomingIssue,
} from "@/types";

interface ReleaseReviewSheetProps {
  issue: UpcomingIssue | null;
  sessionId: string | null;
  startPending: boolean;
  startError: unknown;
  onRetry: () => void;
  onClose: () => void;
  onGrabbed: (result: InteractiveGrabResult) => void;
}

function verdictLabel(candidate: InteractiveReleaseCandidate) {
  if (candidate.verdict.accepted) return "Ready";
  if (candidate.verdict.overrideable) return "Review needed";
  if (candidate.verdict.status === "blocked") return "Blocked";
  if (candidate.verdict.status === "error") return "Match failed";
  return "Not a match";
}

function verdictColor(candidate: InteractiveReleaseCandidate) {
  if (candidate.verdict.accepted) return "var(--status-active)";
  if (candidate.verdict.overrideable) return "var(--status-paused)";
  if (candidate.verdict.status === "blocked") return "var(--status-error)";
  return "var(--muted-foreground)";
}

function VerdictIcon({
  candidate,
}: {
  candidate: InteractiveReleaseCandidate;
}) {
  if (candidate.verdict.accepted)
    return <CheckCircle2 className="size-3" aria-hidden="true" />;
  if (candidate.verdict.overrideable)
    return <ShieldAlert className="size-3" aria-hidden="true" />;
  if (candidate.verdict.status === "blocked")
    return <Ban className="size-3" aria-hidden="true" />;
  return <XCircle className="size-3" aria-hidden="true" />;
}

function VerdictPill({
  candidate,
}: {
  candidate: InteractiveReleaseCandidate;
}) {
  const color = verdictColor(candidate);
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.06em]"
      style={{
        borderColor: `color-mix(in oklab, ${color} 45%, var(--border))`,
        color,
        background: `color-mix(in oklab, ${color} 9%, transparent)`,
      }}
    >
      <VerdictIcon candidate={candidate} />
      {verdictLabel(candidate)}
    </span>
  );
}

function formatBytes(value: number | null) {
  if (!value || value < 1) return "size unknown";
  const units = ["B", "KB", "MB", "GB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 3);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value / 1024 ** unit)} ${units[unit]}`;
}

function formatPublished(value: string | null) {
  if (!value) return "date unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "date unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function CandidateFacts({
  candidate,
}: {
  candidate: InteractiveReleaseCandidate;
}) {
  const metrics = Object.entries(candidate.candidate.metrics ?? {});
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tabular-nums text-muted-foreground">
      <span>{candidate.candidate.provider}</span>
      <span>{candidate.candidate.source_kind.toUpperCase()}</span>
      <span>{formatBytes(candidate.candidate.size_bytes)}</span>
      <span>{formatPublished(candidate.candidate.published_at)}</span>
      {candidate.candidate.pack ? <span>pack</span> : null}
      {metrics.slice(0, 3).map(([key, value]) => (
        <span key={key}>
          {value} {key}
        </span>
      ))}
    </div>
  );
}

function CandidateReason({
  candidate,
}: {
  candidate: InteractiveReleaseCandidate;
}) {
  const reasons = candidate.verdict.reasons ?? [];
  return (
    <div className="mt-3 space-y-2 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
      {reasons.length > 0 ? (
        reasons.map((reason) => (
          <div key={reason.code}>
            <div className="text-foreground">{reason.message}</div>
            <div className="mt-0.5 font-mono text-[10px]">{reason.code}</div>
          </div>
        ))
      ) : (
        <div>No matcher explanation was returned.</div>
      )}
    </div>
  );
}

function IssueContext({
  issue,
  expiresAt,
}: {
  issue: UpcomingIssue;
  expiresAt?: string;
}) {
  const number = issue.IssueNumber ?? issue.Issue_Number ?? "—";
  const name = issue.ComicName ?? issue.ReleaseComicName ?? "Tracked issue";
  return (
    <div className="flex min-w-0 items-center gap-3">
      <div
        className="grid size-12 shrink-0 place-items-center rounded-[5px] border font-mono text-sm font-semibold"
        style={{
          borderColor: "var(--border)",
          background: "color-mix(in oklab, var(--primary) 9%, var(--card))",
          color: "var(--primary)",
        }}
        aria-hidden="true"
      >
        #{number}
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{name}</div>
        <div className="mt-1 truncate font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {issue.annual ? "Annual" : "Issue"} · {issue.Status ?? "Tracked"}
          {expiresAt ? ` · available until ${formatPublished(expiresAt)}` : ""}
        </div>
      </div>
    </div>
  );
}

function ConfirmationDialog({
  candidate,
  sessionId,
  onClose,
  onGrabbed,
}: {
  candidate: InteractiveReleaseCandidate;
  sessionId: string;
  onClose: () => void;
  onGrabbed: (result: InteractiveGrabResult) => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const grab = useGrabInteractiveCandidate();
  const needsOverride =
    candidate.verdict.overrideable && !candidate.verdict.accepted;
  const submit = async () => {
    const result = await grab.mutateAsync({
      sessionId,
      candidateId: candidate.candidate_id,
      override: needsOverride,
    });
    onGrabbed(result);
  };
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent className="max-h-[90svh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {needsOverride
              ? "Override and grab this release?"
              : "Grab this release?"}
          </DialogTitle>
          <DialogDescription>
            Comicarr will re-check the item, provider, duplicate state, and
            download route before handoff.
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-md border border-border bg-secondary/30 p-3">
          <VerdictPill candidate={candidate} />
          <div className="mt-3 break-words text-sm font-semibold leading-snug">
            {candidate.candidate.title}
          </div>
          <div className="mt-2">
            <CandidateFacts candidate={candidate} />
          </div>
          <CandidateReason candidate={candidate} />
        </div>
        {needsOverride ? (
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-[color-mix(in_oklab,var(--status-paused)_45%,var(--border))] p-3 text-sm">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              className="mt-0.5 accent-[var(--primary)]"
            />
            <span>
              <strong>Override this match-policy rejection</strong>
              <span className="mt-1 block text-xs text-muted-foreground">
                I reviewed the matcher explanation. Safety blocks still cannot
                be overridden.
              </span>
            </span>
          </label>
        ) : null}
        {grab.error ? (
          <div role="alert" className="text-sm text-[var(--status-error)]">
            {getErrorMessage(grab.error)}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={grab.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={grab.isPending || (needsOverride && !acknowledged)}
          >
            {grab.isPending ? (
              <LoaderCircle className="animate-spin motion-reduce:animate-none" />
            ) : (
              <Download />
            )}
            {grab.isPending ? "Checking and handing off…" : "Confirm grab"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReleaseReviewSheet({
  issue,
  sessionId,
  startPending,
  startError,
  onRetry,
  onClose,
  onGrabbed,
}: ReleaseReviewSheetProps) {
  const session = useInteractiveSearch(sessionId);
  const data = session.data;
  const candidates = data?.candidates ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmation, setConfirmation] =
    useState<InteractiveReleaseCandidate | null>(null);

  const selected =
    candidates.find((candidate) => candidate.candidate_id === selectedId) ??
    candidates.find((candidate) => candidate.state === "available") ??
    candidates[0] ??
    null;
  const active =
    startPending || data?.state === "queued" || data?.state === "running";
  const displayError = startError ?? session.error;
  const canGrab = Boolean(
    selected &&
    selected.state === "available" &&
    (selected.verdict.accepted || selected.verdict.overrideable),
  );

  return (
    <>
      <Sheet
        open={Boolean(issue)}
        onOpenChange={(open, details) =>
          !open && issue && details.reason !== "none" ? onClose() : undefined
        }
      >
        <SheetContent className="flex h-full w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-xl">
          <SheetHeader className="shrink-0 border-b border-border p-5 pr-12 text-left">
            <SheetTitle>Review releases</SheetTitle>
            <SheetDescription>
              Choose one result for this issue. Nothing downloads until you
              confirm.
            </SheetDescription>
            {issue ? (
              <div className="pt-2">
                <IssueContext issue={issue} expiresAt={data?.expires_at} />
              </div>
            ) : null}
          </SheetHeader>

          <div
            className="flex min-h-9 shrink-0 items-center gap-2 border-b border-border bg-secondary/30 px-5 py-2 font-mono text-[10px] text-muted-foreground"
            role="status"
            aria-live="polite"
          >
            {active ? (
              <LoaderCircle
                className="size-3 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : data?.state === "failed" || displayError ? (
              <TriangleAlert
                className="size-3 text-[var(--status-error)]"
                aria-hidden="true"
              />
            ) : (
              <CheckCircle2
                className="size-3 text-[var(--status-active)]"
                aria-hidden="true"
              />
            )}
            {startPending
              ? "Starting provider search…"
              : active && data
                ? `${data.progress.provider_completed} of ${data.progress.provider_total} providers complete${data.progress.current_provider ? ` · ${data.progress.current_provider}` : ""}`
                : data?.state === "failed"
                  ? "Provider search stopped before completion"
                  : data
                    ? `${data.progress.provider_completed} providers checked · ${data.candidate_count} candidates`
                    : displayError
                      ? "Provider search could not start"
                      : "Preparing search…"}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
            {displayError ? (
              <div className="grid min-h-52 place-items-center text-center">
                <div className="max-w-sm">
                  <TriangleAlert
                    className="mx-auto size-6 text-[var(--status-error)]"
                    aria-hidden="true"
                  />
                  <h3 className="mt-3 text-sm font-semibold">
                    Search unavailable
                  </h3>
                  <p
                    role="alert"
                    className="mt-1 text-sm text-muted-foreground"
                  >
                    {getErrorMessage(displayError)}
                  </p>
                  <Button className="mt-4" variant="outline" onClick={onRetry}>
                    <RefreshCw /> Retry search
                  </Button>
                </div>
              </div>
            ) : candidates.length === 0 && active ? (
              <div className="space-y-2" aria-label="Searching providers">
                {[0, 1, 2].map((item) => (
                  <div
                    key={item}
                    className="h-20 animate-pulse rounded-md border border-border bg-secondary/30 motion-reduce:animate-none"
                  />
                ))}
              </div>
            ) : candidates.length === 0 ? (
              <div className="grid min-h-52 place-items-center text-center">
                <div className="max-w-sm">
                  <SearchX
                    className="mx-auto size-6 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <h3 className="mt-3 text-sm font-semibold">
                    No release candidates found
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Try again later or review provider failures below.
                  </p>
                  <Button className="mt-4" variant="outline" onClick={onRetry}>
                    <RefreshCw /> Search again
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {candidates.map((candidate) => {
                  const isSelected =
                    candidate.candidate_id === selected?.candidate_id;
                  return (
                    <button
                      key={candidate.candidate_id}
                      type="button"
                      onClick={() => setSelectedId(candidate.candidate_id)}
                      className="relative w-full overflow-hidden rounded-md border p-3 pl-5 text-left transition-colors hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      style={{
                        borderColor: isSelected
                          ? "var(--primary)"
                          : "var(--border)",
                      }}
                      aria-pressed={isSelected}
                    >
                      <span
                        className="absolute inset-y-0 left-0 w-1"
                        style={{ background: verdictColor(candidate) }}
                      />
                      <span className="flex items-start gap-3">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {candidate.candidate.title}
                          </span>
                          <span className="mt-1 block">
                            <CandidateFacts candidate={candidate} />
                          </span>
                        </span>
                        <VerdictPill candidate={candidate} />
                      </span>
                      {isSelected ? (
                        <CandidateReason candidate={candidate} />
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}

            {data?.provider_failures.length ? (
              <section
                className="mt-5 border-t border-border pt-4"
                aria-labelledby="provider-failures-title"
              >
                <h3
                  id="provider-failures-title"
                  className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground"
                >
                  Provider failures
                </h3>
                <div className="mt-2 space-y-2">
                  {data.provider_failures.map((failure, index) => (
                    <div
                      key={`${failure.provider}-${failure.code}-${index}`}
                      className="rounded-md border border-border p-3 text-xs"
                    >
                      <div className="flex items-center gap-2 font-medium">
                        <XCircle
                          className="size-3 text-[var(--status-error)]"
                          aria-hidden="true"
                        />
                        {failure.provider}
                      </div>
                      <div className="mt-1 text-muted-foreground">
                        {failure.detail}
                      </div>
                      <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                        {failure.code}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>

          <div className="shrink-0 border-t border-border bg-card p-4">
            <Button
              className="w-full sm:w-auto"
              disabled={!canGrab}
              onClick={() => (selected ? setConfirmation(selected) : undefined)}
            >
              <Download aria-hidden="true" />
              {selected?.verdict.overrideable && !selected.verdict.accepted
                ? "Review override"
                : "Review grab"}
            </Button>
            {selected && !canGrab ? (
              <p className="mt-2 text-xs text-muted-foreground">
                This candidate cannot be grabbed. Select a ready or overrideable
                result.
              </p>
            ) : null}
          </div>
        </SheetContent>
      </Sheet>
      {confirmation && sessionId ? (
        <ConfirmationDialog
          candidate={confirmation}
          sessionId={sessionId}
          onClose={() => setConfirmation(null)}
          onGrabbed={(result) => {
            setConfirmation(null);
            onGrabbed(result);
          }}
        />
      ) : null}
    </>
  );
}
