import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { SettingGroup } from "./SettingGroup";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { downloadSupportBundle } from "@/lib/supportBundle";
import type { ApiError } from "@/lib/api";

type Phase = "idle" | "confirming" | "creating" | "error";

const COMPLETE_STATUS =
  "Support bundle download started. Review it before sharing.";
const PARTIAL_STATUS =
  "Support bundle download started with some diagnostics unavailable. Review manifest.json before sharing.";
const CANCELED_STATUS = "Support bundle download canceled.";
const SAFETY_MESSAGE =
  "Comicarr stopped the download because the bundle did not pass its safety checks. No file was downloaded.";

export function SupportBundleSection() {
  const { addToast } = useToast();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  const [phase, setPhase] = useState<Phase>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [retryEnabled, setRetryEnabled] = useState(true);

  const clearRetryTimer = () => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      clearRetryTimer();
    };
  }, []);

  const focusTrigger = () => {
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  };

  const closeDialog = useCallback((announceCancel: boolean) => {
    abortRef.current?.abort();
    abortRef.current = null;
    clearRetryTimer();
    setPhase("idle");
    setErrorMessage(null);
    setRetryable(false);
    setRetryEnabled(true);
    if (announceCancel) {
      setStatusMessage(CANCELED_STATUS);
    }
    focusTrigger();
  }, []);

  const handleDialogOpenChange = (open: boolean) => {
    if (!open) {
      if (phase === "creating") {
        closeDialog(true);
        return;
      }
      if (phase === "confirming" || phase === "error") {
        closeDialog(phase === "confirming" ? false : false);
      }
    }
  };

  const applyError = (error: ApiError, retryAfterSeconds?: number) => {
    const code =
      typeof error.body?.code === "string" ? error.body.code : undefined;
    let message = error.userMessage;
    let canRetry = error.isRetryable;

    if (error.status === 401) {
      message =
        "Your session has expired. Sign in again before creating a support bundle.";
      canRetry = false;
    } else if (error.status === 403) {
      message =
        "Comicarr blocked the request. Refresh the page before trying again.";
      canRetry = false;
    } else if (
      code === "support_bundle_validation_failed" ||
      message === SAFETY_MESSAGE
    ) {
      message = SAFETY_MESSAGE;
      canRetry = false;
    } else if (code === "support_bundle_in_progress") {
      message =
        "Another support bundle is being created. Try again in a moment.";
      canRetry = true;
    }

    setErrorMessage(message);
    setRetryable(canRetry);
    setPhase("error");
    setStatusMessage("");

    if (canRetry && retryAfterSeconds && retryAfterSeconds > 0) {
      setRetryEnabled(false);
      clearRetryTimer();
      retryTimerRef.current = window.setTimeout(() => {
        setRetryEnabled(true);
        retryTimerRef.current = null;
      }, retryAfterSeconds * 1000);
    } else {
      setRetryEnabled(true);
    }
  };

  const runCreate = async () => {
    if (phase === "creating") return;
    clearRetryTimer();
    setErrorMessage(null);
    setRetryable(false);
    setRetryEnabled(true);
    setPhase("creating");
    setStatusMessage("Creating support bundle. This may take a moment.");

    const controller = new AbortController();
    abortRef.current = controller;
    const result = await downloadSupportBundle(controller.signal);
    if (controller.signal.aborted) {
      return;
    }
    abortRef.current = null;

    if (result.ok) {
      const message =
        result.status === "partial" ? PARTIAL_STATUS : COMPLETE_STATUS;
      setPhase("idle");
      setStatusMessage(message);
      setErrorMessage(null);
      if (result.status === "partial") {
        addToast({ type: "info", message });
      } else {
        addToast({ type: "success", message });
      }
      focusTrigger();
      return;
    }

    if (
      result.error.userMessage === CANCELED_STATUS ||
      (result.error.status === 0 &&
        result.error.userMessage.includes("canceled"))
    ) {
      setPhase("idle");
      setStatusMessage(CANCELED_STATUS);
      focusTrigger();
      return;
    }

    applyError(result.error, result.retryAfterSeconds);
  };

  const openConfirm = () => {
    setErrorMessage(null);
    setRetryable(false);
    setRetryEnabled(true);
    setPhase("confirming");
    window.setTimeout(() => cancelRef.current?.focus(), 0);
  };

  const busy = phase === "creating";

  return (
    <SettingGroup
      title="Support bundle"
      description="Create a diagnostic archive to help troubleshoot Comicarr."
    >
      <div
        className="rounded-lg border px-3.5 py-3 space-y-3"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
        data-testid="support-bundle-section"
      >
        <ol className="grid gap-3 sm:grid-cols-3 sm:gap-0 sm:divide-x">
          {[
            [
              "1. Create",
              "Comicarr builds a fresh archive of allowlisted diagnostic facts.",
            ],
            [
              "2. Inspect",
              "Open the ZIP and read README.txt, manifest.json, and diagnostics.json.",
            ],
            [
              "3. Share",
              "Attach it publicly only when comfortable; otherwise send it privately to a maintainer.",
            ],
          ].map(([label, copy]) => (
            <li
              key={label}
              className="sm:px-3 first:sm:pl-0 last:sm:pr-0 list-none"
            >
              <div className="font-mono text-[11px] uppercase tracking-[0.05em] text-muted-foreground">
                {label}
              </div>
              <div className="mt-0.5 text-[13px] leading-snug text-foreground">
                {copy}
              </div>
            </li>
          ))}
        </ol>

        <p className="text-[12.5px] text-muted-foreground leading-relaxed">
          It does not include your database, settings values, raw log lines,
          library names, paths, chat content, or other free text.
        </p>

        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <Button
            ref={triggerRef}
            type="button"
            variant="outline"
            size="sm"
            onClick={openConfirm}
            disabled={busy}
            aria-busy={busy || undefined}
          >
            Create support bundle
          </Button>
        </div>

        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="min-h-[1.25rem] text-[12.5px] text-muted-foreground"
          data-testid="support-bundle-status"
        >
          {statusMessage}
        </div>
      </div>

      <Dialog
        open={
          phase === "confirming" || phase === "creating" || phase === "error"
        }
        onOpenChange={handleDialogOpenChange}
      >
        <DialogContent
          className="max-w-md"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
        >
          <DialogHeader>
            <DialogTitle id={titleId}>Create a support bundle?</DialogTitle>
            <DialogDescription id={descriptionId}>
              Comicarr will create and download a ZIP of allowlisted diagnostic
              facts. It does not change your library or settings.
            </DialogDescription>
          </DialogHeader>

          {phase !== "error" && (
            <div
              className="rounded-md border px-3 py-2 text-[13px] leading-snug"
              style={{ borderColor: "var(--border)" }}
            >
              Review the files before attaching the bundle to a public issue. If
              anything looks sensitive, share it privately with a maintainer
              instead.
            </div>
          )}

          {phase === "error" && errorMessage && (
            <div
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-[13px] leading-snug text-foreground"
              data-testid="support-bundle-error"
            >
              {errorMessage}
            </div>
          )}

          <DialogFooter>
            {phase === "error" ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => closeDialog(false)}
                  data-testid="support-bundle-error-close"
                >
                  Close
                </Button>
                {retryable && (
                  <Button
                    type="button"
                    onClick={() => void runCreate()}
                    disabled={!retryEnabled}
                    data-testid="support-bundle-error-retry"
                  >
                    Try again
                  </Button>
                )}
              </>
            ) : (
              <>
                <Button
                  ref={cancelRef}
                  type="button"
                  variant="outline"
                  onClick={() => closeDialog(phase === "creating")}
                  disabled={false}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  onClick={() => void runCreate()}
                  disabled={busy}
                  aria-busy={busy || undefined}
                >
                  {busy ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2
                        className="h-4 w-4 animate-spin"
                        aria-hidden="true"
                      />
                      Creating…
                    </span>
                  ) : (
                    "Create and download"
                  )}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingGroup>
  );
}
