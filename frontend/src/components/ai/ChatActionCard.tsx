import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ChatAction, ChatActionCandidate } from "@/types/chat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { confirmChatAction, dismissChatAction } from "@/lib/chatApi";
import { CheckCircle2, CircleOff, LoaderCircle, XCircle } from "lucide-react";

interface ChatActionCardProps {
  action: ChatAction;
  threadId: string;
  messageId: string;
  onActionChange?: (action: ChatAction) => void;
}

function CandidateRow({
  candidate,
  selected,
  disabled,
  onSelect,
}: {
  candidate: ChatActionCandidate;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      className="relative w-full rounded-md border p-2.5 text-left transition-colors hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
      style={{
        borderColor: selected ? "var(--primary)" : "var(--border)",
      }}
    >
      <span className="flex items-center gap-3">
        <span className="h-14 w-10 shrink-0 overflow-hidden rounded-sm border bg-muted">
          {candidate.image ? (
            <img
              src={candidate.image}
              alt=""
              className="size-full object-cover"
              loading="lazy"
            />
          ) : (
            <span className="flex size-full items-center justify-center font-mono text-[9px] text-muted-foreground">
              —
            </span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {candidate.name || candidate.comicid}
          </span>
          <span className="mono-meta mt-1 flex items-center gap-2">
            {candidate.year && <span>{candidate.year}</span>}
            {candidate.publisher && (
              <span className="truncate">{candidate.publisher}</span>
            )}
            {candidate.issues != null && <span>{candidate.issues} issues</span>}
          </span>
        </span>
        {candidate.in_library && (
          <Badge variant="secondary" className="shrink-0 uppercase">
            In library
          </Badge>
        )}
      </span>
    </button>
  );
}

export function ChatActionCard({
  action,
  threadId,
  messageId,
  onActionChange,
}: ChatActionCardProps) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const preview = action.preview;
  const candidates = preview?.candidates ?? [];
  const affected = preview?.issues ?? [];
  const isAddSeries = action.action_id === "add_series";
  const confirmable =
    action.status === "pending" &&
    !busy &&
    !messageId.startsWith("local-") &&
    (!isAddSeries || Boolean(selectedId));

  const confirm = async () => {
    setBusy(true);
    setLocalError(null);
    try {
      const response = await confirmChatAction(threadId, messageId, {
        comicid: selectedId ?? undefined,
      });
      onActionChange?.(response.action);
    } catch (err) {
      setLocalError(
        err instanceof Error ? err.message : "The action could not be applied.",
      );
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async () => {
    setBusy(true);
    setLocalError(null);
    try {
      const response = await dismissChatAction(threadId, messageId);
      onActionChange?.(response.action);
    } catch (err) {
      setLocalError(
        err instanceof Error ? err.message : "Could not dismiss this action.",
      );
    } finally {
      setBusy(false);
    }
  };

  const resultComicId = action.result?.comicid;

  return (
    <div className="w-full max-w-2xl rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <span className="mono-label shrink-0">Suggested action</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      <p className="mt-2 text-sm font-medium text-foreground">
        {action.summary || "Apply this change?"}
      </p>

      {action.status === "error" && (
        <p className="mt-2 text-sm text-muted-foreground" role="alert">
          {action.error || "This action could not be prepared."}
        </p>
      )}

      {action.status === "pending" && isAddSeries && (
        <div className="mt-3 flex flex-col gap-2">
          {candidates.map((candidate) => (
            <CandidateRow
              key={candidate.comicid}
              candidate={candidate}
              selected={selectedId === candidate.comicid}
              disabled={busy}
              onSelect={() => setSelectedId(candidate.comicid)}
            />
          ))}
        </div>
      )}

      {action.status === "pending" && action.action_id === "mark_issues" && (
        <div className="mt-3">
          <p className="mono-meta">
            {preview?.comic_name}
            {preview?.comic_year ? ` (${preview.comic_year})` : ""} ·{" "}
            {preview?.scope === "annuals" ? "annuals" : "issues"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {affected.slice(0, 40).map((item) => (
              <span
                key={item.issue_id}
                className="mono-meta rounded border bg-secondary/40 px-1.5 py-0.5"
              >
                {item.kind === "annual" ? "Annual " : "#"}
                {item.number ?? item.issue_id}
              </span>
            ))}
            {affected.length > 40 && (
              <span className="mono-meta px-1.5 py-0.5">
                +{affected.length - 40} more
              </span>
            )}
          </div>
        </div>
      )}

      {action.status === "confirmed" && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <CheckCircle2
            className="size-4 shrink-0"
            style={{ color: "var(--status-active)" }}
          />
          <span>{action.result?.message || "Done."}</span>
        </div>
      )}

      {action.status === "dismissed" && (
        <div className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
          <CircleOff className="size-4 shrink-0" />
          <span>Dismissed</span>
        </div>
      )}

      {(localError || (action.status === "pending" && action.error)) && (
        <div
          role="alert"
          className="mt-2 flex items-center gap-2 text-sm"
          style={{ color: "var(--status-error)" }}
        >
          <XCircle className="size-4 shrink-0" />
          <span>{localError || action.error}</span>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        {action.status === "pending" && (
          <>
            <Button
              size="sm"
              onClick={() => void confirm()}
              disabled={!confirmable}
            >
              {busy && (
                <LoaderCircle className="animate-spin motion-reduce:animate-none" />
              )}
              Confirm
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void dismiss()}
              disabled={busy || messageId.startsWith("local-")}
            >
              Dismiss
            </Button>
          </>
        )}
        {action.status === "confirmed" && resultComicId && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate(`/library/${resultComicId}`)}
          >
            Open series
          </Button>
        )}
      </div>
    </div>
  );
}
