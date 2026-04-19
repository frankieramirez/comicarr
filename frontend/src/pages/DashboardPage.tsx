import { Link } from "react-router-dom";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { useDashboard } from "@/hooks/useDashboard";

function Kpi({
  label,
  value,
  borderLeft,
}: {
  label: string;
  value: string;
  borderLeft?: boolean;
}) {
  return (
    <div className={`px-5 py-4 ${borderLeft ? "border-l border-border" : ""}`}>
      <div className="mono-label">{label}</div>
      <div className="flex items-end gap-2 mt-1.5">
        <div className="text-[26px] font-semibold tracking-tight leading-none">
          {value}
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data, isLoading, error } = useDashboard();

  if (error) {
    return (
      <div className="p-8">
        <ErrorDisplay
          error={error}
          title="Unable to load dashboard"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  const stats = data?.stats;
  const downloads = data?.recently_downloaded || [];
  const upcoming = data?.upcoming_releases || [];

  const activeSeries = stats?.total_series ?? 0;
  const totalIssues = stats?.total_issues ?? 0;
  const completion = stats?.completion_pct ?? 0;
  const queueCount = downloads.filter((d) =>
    /snatch|queue|wanted/i.test(d.Status),
  ).length;

  return (
    <div className="h-full flex flex-col page-transition">
      {/* Page header */}
      <div className="px-5 py-4 border-b border-border flex items-center gap-3">
        <div>
          <div className="text-[18px] font-semibold tracking-tight">
            Dashboard
          </div>
          <div className="font-mono text-[11px] text-muted-foreground mt-0.5">
            {isLoading
              ? "loading…"
              : `${activeSeries} series · ${totalIssues} issues · ${queueCount} in queue`}
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 border-b border-border">
        <Kpi
          label="Active series"
          value={isLoading ? "—" : String(activeSeries)}
        />
        <Kpi
          label="Issues"
          value={isLoading ? "—" : String(totalIssues)}
          borderLeft
        />
        <Kpi
          label="Completion"
          value={isLoading ? "—" : `${completion.toFixed(1)}%`}
          borderLeft
        />
        <Kpi label="Queue" value={String(queueCount)} borderLeft />
      </div>

      {/* Two-column body */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] border-b border-border min-h-[320px]">
        {/* Queue & recent activity */}
        <section className="px-5 py-4 lg:border-r lg:border-border">
          <div className="flex items-center gap-2.5 mb-3">
            <div className="text-[13px] font-semibold">
              Queue & recent activity
            </div>
            <div className="font-mono text-[10px] text-[var(--text-muted)] tracking-wider uppercase">
              {downloads.length} events
            </div>
          </div>

          {isLoading && (
            <div className="font-mono text-[11px] text-muted-foreground py-4">
              loading activity…
            </div>
          )}

          {!isLoading && downloads.length === 0 && (
            <div className="font-mono text-[11px] text-muted-foreground py-4">
              no recent activity
            </div>
          )}

          <div className="font-mono text-[11px]">
            {downloads.slice(0, 8).map((d, i) => {
              const action = d.Status?.toLowerCase() || "—";
              const color = action.includes("down")
                ? "var(--chart-4)"
                : action.includes("post") || action.includes("import")
                  ? "var(--status-active)"
                  : action.includes("snatch") || action.includes("queue")
                    ? "var(--status-paused)"
                    : "var(--muted-foreground)";
              return (
                <div
                  key={`${d.ComicID}-${d.IssueID}-${i}`}
                  className="grid items-center gap-2 py-1.5"
                  style={{
                    gridTemplateColumns: "60px 90px 1fr 140px 60px 20px",
                    borderTop:
                      i > 0
                        ? "1px solid var(--border-soft, var(--border))"
                        : "none",
                  }}
                >
                  <span className="text-[var(--text-muted)]">
                    {d.DateAdded?.slice(11, 16) || "—"}
                  </span>
                  <span className="uppercase truncate" style={{ color }}>
                    {action}
                  </span>
                  <div className="flex items-center gap-2 min-w-0">
                    {d.ComicID && (
                      <img
                        src={`/api/metadata/art/${d.ComicID}`}
                        alt=""
                        className="w-4 h-6 object-cover rounded-[1px] shrink-0"
                        onError={(e) => {
                          e.currentTarget.style.visibility = "hidden";
                        }}
                      />
                    )}
                    <Link
                      to={`/library/${d.ComicID}`}
                      className="font-sans text-foreground truncate hover:text-[var(--primary)]"
                    >
                      {d.ComicName} #{d.Issue_Number}
                    </Link>
                  </div>
                  <span className="text-muted-foreground truncate">
                    {d.Provider || "—"}
                  </span>
                  <span className="text-[var(--text-muted)] text-right">—</span>
                  <span className="text-[var(--text-muted)] text-right">
                    ···
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        {/* This week */}
        <section className="px-5 py-4">
          <div className="flex items-center gap-2.5 mb-3">
            <div className="text-[13px] font-semibold">This week</div>
            <div className="font-mono text-[10px] text-[var(--text-muted)] tracking-wider uppercase">
              {upcoming.length} releases
            </div>
          </div>

          {isLoading && (
            <div className="font-mono text-[11px] text-muted-foreground py-4">
              loading releases…
            </div>
          )}

          {!isLoading && upcoming.length === 0 && (
            <div className="font-mono text-[11px] text-muted-foreground py-4">
              nothing upcoming this week
            </div>
          )}

          {upcoming.slice(0, 6).map((u, i) => (
            <div
              key={`${u.ComicID}-${u.IssueNumber}-${i}`}
              className="flex items-center gap-2.5 py-2.5"
              style={{
                borderTop:
                  i > 0
                    ? "1px solid var(--border-soft, var(--border))"
                    : "none",
              }}
            >
              <div className="font-mono text-[10px] text-muted-foreground w-12 shrink-0">
                {u.IssueDate?.slice(5) || "—"}
              </div>
              <div className="flex-1 min-w-0">
                <Link
                  to={`/library/${u.ComicID}`}
                  className="text-[12px] truncate block hover:text-[var(--primary)]"
                >
                  {u.ComicName}
                </Link>
                <div className="font-mono text-[10px] text-[var(--text-muted)]">
                  #{u.IssueNumber}
                </div>
              </div>
              <div className="font-mono text-[10px] text-[var(--text-muted)]">
                {u.Status || "auto"}
              </div>
            </div>
          ))}

          <div className="mt-4 p-3 rounded-[6px] border border-border bg-card">
            <div
              className="font-mono text-[10px] mb-1.5"
              style={{ color: "var(--primary)" }}
            >
              ⌘K · COMMAND HINT
            </div>
            <div className="text-[12px] text-muted-foreground leading-relaxed">
              Try <span className="text-foreground">"search wolverine"</span>,{" "}
              <span className="text-foreground">"queue pause"</span>, or{" "}
              <span className="text-foreground">"import /downloads/new"</span>.
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
