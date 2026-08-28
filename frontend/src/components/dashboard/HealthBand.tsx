import { useSyncExternalStore } from "react";
import { AlertTriangle, Check, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { useSearchHealth } from "@/hooks/useAcquisitionHealth";
import { useConfig } from "@/hooks/useConfig";
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

const TONE_BG: Record<HealthTone, string> = {
  healthy: "transparent",
  degraded: "var(--status-paused-bg)",
  blocked: "var(--status-error-bg)",
};

/** A row for a signal that needs the operator's eye, with its fix link. */
function SignalRow({ signal }: { signal: HealthBandView["signals"][number] }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[11px]">
      <AlertTriangle
        className="w-3 h-3 shrink-0"
        style={{ color: TONE_COLOR[signal.tone] }}
        aria-hidden="true"
      />
      <span style={{ color: TONE_COLOR[signal.tone] }}>{signal.text}</span>
      {signal.fix && (
        <Link
          to={signal.fix.to}
          className="text-muted-foreground hover:text-foreground underline decoration-dotted"
        >
          {signal.fix.label} →
        </Link>
      )}
    </div>
  );
}

export default function HealthBand() {
  const health = useSearchHealth();
  const config = useConfig();
  const now = useNow();

  if (health.isPending) {
    return (
      <div
        className="px-5 py-3 border-b border-border"
        data-testid="health-band-loading"
      >
        {/* Two rows at the height of the resolved band, so it does not shift. */}
        <div aria-hidden="true" className="flex flex-col gap-2">
          <div className="h-2.5 w-72 animate-pulse rounded-[2px] bg-primary/10" />
          <div className="h-2.5 w-52 animate-pulse rounded-[2px] bg-primary/10" />
        </div>
      </div>
    );
  }

  const view = healthBandView({
    health: health.isError ? null : (health.data ?? null),
    searchIntervalMinutes:
      config.data?.search_interval ?? DEFAULT_SEARCH_INTERVAL_MINUTES,
    now,
  });

  const quiet = view.signals.filter((signal) => signal.tone === "healthy");
  const loud = view.signals.filter((signal) => signal.tone !== "healthy");

  return (
    <section
      aria-label="Acquisition health"
      data-tone={view.tone}
      className="px-5 py-3 border-b border-border"
      style={{
        background: TONE_BG[view.tone],
        boxShadow:
          view.tone === "healthy"
            ? undefined
            : `inset 3px 0 0 ${TONE_COLOR[view.tone]}`,
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-col gap-1.5 min-w-0">
          {loud.map((signal) => (
            <SignalRow key={signal.key} signal={signal} />
          ))}

          {quiet.length > 0 && (
            <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
              {loud.length === 0 && (
                <Check
                  className="w-3 h-3 shrink-0"
                  style={{ color: TONE_COLOR.healthy }}
                  aria-hidden="true"
                />
              )}
              <span className="truncate">
                {quiet.map((signal) => signal.text).join(" · ")}
              </span>
            </div>
          )}

          {/* Never hidden, in any state, at any age. */}
          <div
            className="font-mono text-[11px]"
            style={{
              color: view.lastSearch.stale
                ? TONE_COLOR.degraded
                : "var(--muted-foreground)",
            }}
          >
            {view.lastSearch.text}
          </div>
        </div>

        <button
          type="button"
          onClick={() => void health.refetch()}
          disabled={health.isFetching}
          aria-label="Recheck acquisition health"
          className="inline-flex shrink-0 items-center gap-1.5 px-2 py-1 rounded-[5px] border border-border font-mono text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw
            className={`w-3 h-3 ${health.isFetching ? "animate-spin" : ""}`}
          />
          {health.isFetching ? "checking…" : "recheck"}
        </button>
      </div>
    </section>
  );
}
