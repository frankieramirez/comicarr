import { useSyncExternalStore } from "react";
import { ChevronRight, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { useSearchHealth } from "@/hooks/useAcquisitionHealth";
import { useConfig } from "@/hooks/useConfig";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import {
  DEFAULT_SEARCH_INTERVAL_MINUTES,
  healthBandView,
  type HealthBandView,
  type HealthTone,
} from "@/lib/healthBand";

/**
 * The top of the dashboard: quiet when the automation is fine, unmissable when
 * it is not (docs/architecture/dashboard-spec.md §3.1).
 *
 * It is a band rather than a card because it is not one panel among panels —
 * it is the answer to the only question whose answer can require action today.
 * Its one hard rule: it never infers health from the absence of bad news. A
 * failing health endpoint renders degraded ("Cannot determine health"), never
 * healthy and never absent.
 */

/** How often the last-successful-search age re-reads the clock. */
const TICK_MS = 30_000;

function subscribeToClock(onTick: () => void): () => void {
  const tick = setInterval(onTick, TICK_MS);
  return () => clearInterval(tick);
}

/**
 * The wall clock, read as the external system it is — reading it during render
 * would be impure, and the last-successful-search age has to keep growing while
 * the page sits open. Quantized to the tick so the snapshot is stable between
 * ticks; nothing here needs sub-half-minute precision.
 */
function readClock(): number {
  return Math.floor(Date.now() / TICK_MS) * TICK_MS;
}

function useNow(): number {
  return useSyncExternalStore(subscribeToClock, readClock, readClock);
}

const TONE_COLOR: Record<HealthTone, string> = {
  healthy: "var(--status-active)",
  degraded: "var(--status-paused)",
  blocked: "var(--status-error)",
};

/** One signal: a status dot, the plain sentence, and its fix link if any. */
function SignalRow({ signal }: { signal: HealthBandView["signals"][number] }) {
  return (
    <li className="flex items-start gap-2 py-1 text-[13px]">
      <span
        className="mt-[7px] size-1.5 shrink-0 rounded-full"
        style={{ background: TONE_COLOR[signal.tone] }}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1">
        <span
          className={
            signal.tone === "healthy" ? "text-foreground-2" : "text-foreground"
          }
        >
          {signal.text}
        </span>
        {signal.fix && (
          <>
            {" "}
            <Link
              to={signal.fix.to}
              className="whitespace-nowrap text-foreground-2 underline underline-offset-2 hover:text-foreground"
            >
              {signal.fix.label}
            </Link>
          </>
        )}
      </span>
    </li>
  );
}

/**
 * The dashboard rail's System health section. Loud signals first, quiet ones
 * after, and the last-successful-search line always last and always shown.
 */
export default function HealthBand() {
  const health = useSearchHealth();
  const config = useConfig();
  const now = useNow();

  if (health.isPending) {
    return (
      <section data-testid="health-band-loading">
        <SectionHeader variant="rail" title="System health" />
        {/* Rows at the height of the resolved section, so it does not shift. */}
        <div aria-hidden="true" className="flex flex-col gap-3 py-1">
          <Skeleton className="h-2.5 w-56 rounded-sm" />
          <Skeleton className="h-2.5 w-44 rounded-sm" />
        </div>
      </section>
    );
  }

  const view = healthBandView({
    health: health.isError ? null : (health.data ?? null),
    searchIntervalMinutes:
      config.data?.search_interval ?? DEFAULT_SEARCH_INTERVAL_MINUTES,
    now,
  });

  const loud = view.signals.filter((signal) => signal.tone !== "healthy");
  const quiet = view.signals.filter((signal) => signal.tone === "healthy");

  return (
    <section aria-label="Acquisition health" data-tone={view.tone}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          System health
        </h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => void health.refetch()}
            disabled={health.isFetching}
            aria-label="Recheck acquisition health"
            title={health.isFetching ? "checking…" : "recheck"}
            className="inline-flex size-6 items-center justify-center rounded-control text-muted-foreground hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw
              className={`size-3 ${health.isFetching ? "animate-spin" : ""}`}
            />
          </button>
          <Link
            to="/settings?section=acquisition"
            className="inline-flex items-center gap-0.5 text-[13px] text-foreground-2 hover:text-foreground"
          >
            Details
            <ChevronRight className="size-3.5 text-muted-foreground" />
          </Link>
        </div>
      </div>
      <ul>
        {[...loud, ...quiet].map((signal) => (
          <SignalRow key={signal.key} signal={signal} />
        ))}
        {/* Never hidden, in any state, at any age. */}
        <li className="flex items-start gap-2 py-1 text-[13px]">
          <span
            className="mt-[7px] size-1.5 shrink-0 rounded-full"
            style={{
              background: view.lastSearch.stale
                ? TONE_COLOR.degraded
                : TONE_COLOR.healthy,
            }}
            aria-hidden="true"
          />
          <span
            className={
              view.lastSearch.stale ? "text-foreground" : "text-foreground-2"
            }
          >
            {view.lastSearch.text}
          </span>
        </li>
      </ul>
    </section>
  );
}
