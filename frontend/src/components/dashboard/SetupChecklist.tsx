import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SetupStep } from "@/lib/setupSteps";

/**
 * "Finish setting up" on a fresh install (audit finding 1): the four steps to
 * a first download, each done or one button away. The first open step carries
 * the page's one filled button.
 */
export default function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const done = steps.filter((step) => step.done).length;
  const next = steps.find((step) => !step.done)?.key;

  return (
    <section aria-label={t`Finish setting up`} data-testid="setup-checklist">
      <SectionHeader
        title={t`Needs you`}
        meta={t`${done} of ${ph({ length: steps.length })} set up`}
      />
      <div className="border-t border-border-subtle pt-3">
        <p className="text-sm font-medium text-foreground">
          <Trans>Finish setting up</Trans>
        </p>
        <div
          className="mt-2 mb-1 flex h-1 gap-1"
          role="progressbar"
          aria-label={t`Setup progress`}
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={done}
        >
          {steps.map((step) => (
            <span
              key={step.key}
              className="h-1 flex-1 rounded-full"
              style={{
                background: step.done
                  ? "var(--status-active)"
                  : "var(--surface-3)",
              }}
            />
          ))}
        </div>
        <ol>
          {steps.map((step) => (
            <li
              key={step.key}
              data-testid="setup-step"
              data-done={step.done}
              className="flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-border-subtle py-3"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-[18px] shrink-0 items-center justify-center rounded-full border",
                  step.done ? "border-transparent" : "border-border-strong",
                )}
                style={
                  step.done ? { background: "var(--status-active)" } : undefined
                }
              >
                {step.done && <Check className="size-3 text-background" />}
              </span>
              <div className="min-w-0 flex-1 basis-[calc(100%-32px)] sm:basis-0">
                <div
                  className={cn(
                    "text-sm font-medium",
                    step.done ? "text-foreground-2" : "text-foreground",
                  )}
                >
                  {step.title}
                  <span className="sr-only">
                    {step.done ? t` (done)` : t` (to do)`}
                  </span>
                </div>
                <div
                  className={cn(
                    "text-[13px] text-foreground-2 sm:truncate",
                    step.done && step.key === "library" && "font-mono text-xs",
                  )}
                >
                  {step.detail}
                </div>
              </div>
              {!step.done && (
                <Link
                  to={step.fix.to}
                  className={cn(
                    buttonVariants({
                      variant: step.key === next ? "default" : "outline",
                      size: "toolbar",
                    }),
                    "max-sm:ms-8",
                  )}
                >
                  {step.fix.label}
                </Link>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
