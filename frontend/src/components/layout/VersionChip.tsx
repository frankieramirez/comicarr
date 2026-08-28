import { useState } from "react";
import { ArrowRight, Copy, ExternalLink } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { isUpdateBehind, useVersionInfo } from "@/hooks/useVersion";
import { useReleaseNotes } from "@/hooks/useReleaseNotes";
import { APP_VERSION, formatAppVersion } from "@/lib/version";
import { getUpdateGuidance, releaseTagUrl } from "@/lib/updateGuidance";
import { cn } from "@/lib/utils";

/**
 * Sidebar version pill: quiet primary status-dot when behind, popover with
 * notes + how-to-update guidance. Closing the popover does not clear the cue.
 */
export default function VersionChip() {
  const [open, setOpen] = useState(false);
  const [showGuidance, setShowGuidance] = useState(false);
  const { status, data } = useVersionInfo();
  const behind = isUpdateBehind(status, data);
  const localLabel = formatAppVersion(false);
  const latest = data?.latest_version ?? null;
  const notesQuery = useReleaseNotes(APP_VERSION, latest, open && behind);
  const { copy, isCopied } = useCopyToClipboard();

  const guidance =
    behind && latest ? getUpdateGuidance(data?.install_type, latest) : null;

  const ariaLabel = behind
    ? `Version ${localLabel}, update available`
    : `Version ${localLabel}`;

  return (
    <Popover
      open={behind ? open : false}
      onOpenChange={(next) => {
        if (!behind) {
          setOpen(false);
          return;
        }
        setOpen(next);
        if (!next) setShowGuidance(false);
      }}
    >
      <PopoverTrigger
        className={cn(
          "group-data-[collapsible=icon]:hidden relative font-mono text-[10px] px-1.5 py-0.5 border rounded-sm transition-colors",
          behind
            ? "border-primary/50 text-foreground pr-3.5 hover:bg-primary/5"
            : "border-sidebar-border text-muted-foreground",
          !behind && "pointer-events-none",
        )}
        aria-label={ariaLabel}
        disabled={!behind}
      >
        {localLabel}
        {behind && (
          <span
            className="absolute right-1 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-primary"
            aria-hidden
          />
        )}
      </PopoverTrigger>

      {behind && latest && (
        <PopoverContent
          side="right"
          align="start"
          sideOffset={10}
          positionMethod="fixed"
          collisionPadding={8}
          className="z-[100] w-80 p-0 overflow-hidden"
        >
          <div className="bg-primary/10 border-b border-border px-4 py-3">
            <div className="text-[10px] font-mono uppercase tracking-wider text-primary">
              Update available
            </div>
            <div className="mt-1 flex items-center gap-2 font-mono text-[13px]">
              <span className="text-muted-foreground">{localLabel}</span>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span className="font-semibold text-foreground">{latest}</span>
            </div>
          </div>

          <div className="px-4 py-3 space-y-3">
            <div>
              <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                What&apos;s new
              </div>
              <NotesBody
                isLoading={notesQuery.isLoading}
                isError={notesQuery.isError}
                sections={notesQuery.data?.sections}
              />
            </div>

            {showGuidance && guidance && (
              <GuidancePanel
                guidance={guidance}
                onCopy={async (text) => {
                  await copy(text, { withToast: true });
                }}
                copied={isCopied}
              />
            )}

            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                type="button"
                onClick={() => setShowGuidance((v) => !v)}
              >
                How to update
              </Button>
              <a
                href={releaseTagUrl(latest)}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "inline-flex flex-1 items-center justify-center gap-2 h-8 rounded-md px-3 text-xs font-medium border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
                )}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                Release
              </a>
            </div>
          </div>
        </PopoverContent>
      )}
    </Popover>
  );
}

function NotesBody({
  isLoading,
  isError,
  sections,
}: {
  isLoading: boolean;
  isError: boolean;
  sections: { version: string; bullets: string[] }[] | undefined;
}) {
  if (isLoading) {
    return (
      <p className="text-[12px] text-muted-foreground">
        Loading release notes…
      </p>
    );
  }
  if (isError) {
    return (
      <p className="text-[12px] text-muted-foreground">
        Notes unavailable — use the Release link.
      </p>
    );
  }
  if (!sections?.length) {
    return (
      <p className="text-[12px] text-muted-foreground">
        No notes for this release yet — use the Release link.
      </p>
    );
  }

  const MAX_BULLETS = 6;
  let remaining = MAX_BULLETS;
  const shown: { version: string; bullets: string[] }[] = [];
  for (const section of sections) {
    if (remaining <= 0) break;
    const take = section.bullets.slice(0, remaining);
    if (take.length) {
      shown.push({ version: section.version, bullets: take });
      remaining -= take.length;
    }
  }
  const multi = sections.length > 1 || shown.length > 1;

  return (
    <div className="space-y-2 max-h-40 overflow-y-auto">
      {shown.map((section) => (
        <div key={section.version}>
          {multi && (
            <div className="mb-0.5 font-mono text-[10px] text-muted-foreground">
              {section.version}
            </div>
          )}
          <ul className="space-y-1 text-[12px] text-muted-foreground">
            {section.bullets.map((b, i) => (
              <li
                key={`${section.version}-${i}`}
                className="whitespace-pre-wrap"
              >
                · {b}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function GuidancePanel({
  guidance,
  onCopy,
  copied,
}: {
  guidance: ReturnType<typeof getUpdateGuidance>;
  onCopy: (text: string) => void | Promise<void>;
  copied: boolean;
}) {
  return (
    <div className="rounded-md border border-border bg-secondary/40 px-3 py-2 space-y-2">
      <div className="text-[11px] font-medium text-foreground">
        {guidance.title}
      </div>
      <p className="text-[11px] text-muted-foreground leading-snug">
        {guidance.intro}
      </p>
      {guidance.commands.map((cmd) => (
        <div key={cmd} className="relative group">
          <pre className="rounded-sm bg-background border border-border px-2 py-1.5 text-[10px] font-mono whitespace-pre-wrap break-all text-foreground">
            {cmd}
          </pre>
          <button
            type="button"
            className="absolute top-1 right-1 p-1 rounded-sm text-muted-foreground hover:text-foreground hover:bg-secondary"
            aria-label={copied ? "Copied" : "Copy command"}
            onClick={() => void onCopy(cmd)}
          >
            <Copy className="h-3 w-3" />
          </button>
        </div>
      ))}
      {guidance.note && (
        <p className="text-[10px] text-muted-foreground/90 leading-snug">
          {guidance.note}
        </p>
      )}
    </div>
  );
}
