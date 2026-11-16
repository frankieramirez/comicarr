import { t } from "@lingui/core/macro";
import { TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SearchBlocker } from "@/lib/searchBlockers";

const TITLES = (): Record<SearchBlocker["key"], string> => ({
  indexer: t`Nothing can be searched until you add an indexer`,
  client: t`Nothing can be downloaded until you add a download client`,
});

/**
 * One line above a list that would otherwise promise searches that cannot
 * run. It carries the page's one filled button: the fix.
 */
export default function SearchBlockedBanner({
  blocker,
  className,
}: {
  blocker: SearchBlocker;
  className?: string;
}) {
  return (
    <div
      role="status"
      data-testid="search-blocked"
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-subtle bg-surface-1 px-4 py-3",
        className,
      )}
    >
      <TriangleAlert
        aria-hidden="true"
        className="size-4 shrink-0"
        style={{ color: "var(--status-paused)" }}
      />
      <div className="min-w-0 flex-1 basis-64">
        <p className="text-sm text-foreground">{TITLES()[blocker.key]}</p>
        <p className="mt-0.5 text-[13px] text-foreground-2">{blocker.detail}</p>
      </div>
      <Link
        to={blocker.fix.to}
        className={cn(buttonVariants({ variant: "default", size: "toolbar" }))}
      >
        {blocker.fix.label}
      </Link>
    </div>
  );
}
