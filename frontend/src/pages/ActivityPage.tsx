import { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  useDownloadHistory,
  useDownloadQueue,
  type HistoryItem,
  type QueueItem,
} from "@/hooks/useActivity";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import PageHeader, { Tab, TabRow } from "@/components/layout/PageHeader";

type ActivityView = "queue" | "history";

function StatusPill({ status }: { status: string }) {
  const s = (status || "").toLowerCase();
  let color = "var(--muted-foreground)";
  if (
    s.includes("down") ||
    s.includes("snatch") ||
    s === "active" ||
    s === "completed" ||
    s === "done"
  )
    color = "var(--status-active)";
  else if (s.includes("queue") || s.includes("pend") || s === "wanted")
    color = "var(--status-paused)";
  else if (s.includes("fail") || s.includes("error"))
    color = "var(--status-error)";
  return (
    <span
      className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase"
      style={{ color }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color }}
      />
      {status || "—"}
    </span>
  );
}

export default function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const currentView: ActivityView =
    viewParam === "history" ? "history" : "queue";

  const setView = (view: ActivityView) => {
    setSearchParams({ view });
  };

  return (
    <div className="-mx-4 sm:-mx-6 lg:-mx-8 -my-8 page-transition">
      <PageHeader
        title="Activity"
        meta={
          currentView === "queue"
            ? "live download queue"
            : "completed downloads"
        }
      />

      <TabRow>
        <Tab
          active={currentView === "queue"}
          label="Queue"
          onClick={() => setView("queue")}
        />
        <Tab
          active={currentView === "history"}
          label="History"
          onClick={() => setView("history")}
        />
      </TabRow>

      <div className="px-5 py-4">
        {currentView === "queue" ? <QueueView /> : <HistoryView />}
      </div>
    </div>
  );
}

function DenseTable({
  headers,
  gridTemplate,
  children,
}: {
  headers: string[];
  gridTemplate: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-[6px] border overflow-x-auto"
      style={{ borderColor: "var(--border)" }}
    >
      <div
        className="grid px-4 py-2 border-b font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground"
        style={{
          borderColor: "var(--border)",
          background: "var(--card)",
          gridTemplateColumns: gridTemplate,
        }}
      >
        {headers.map((h) => (
          <div key={h}>{h}</div>
        ))}
      </div>
      {children}
    </div>
  );
}

function QueueView() {
  const { data: queue, isLoading, error, refetch } = useDownloadQueue();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load download queue"
        onRetry={() => refetch()}
      />
    );
  }

  if (!queue || queue.length === 0) {
    return (
      <EmptyState
        variant="custom"
        eyebrow="QUEUE · EMPTY"
        title="No active downloads"
        description="Downloads will appear here while items are being processed."
      />
    );
  }

  const gridTpl = "1.5fr 2fr 100px 110px 110px";

  return (
    <DenseTable
      headers={["series", "file", "site", "status", "updated"]}
      gridTemplate={gridTpl}
    >
      {queue.map((item: QueueItem) => (
        <div
          key={item.ID}
          className="grid items-center px-4 py-2 text-[12px] border-b last:border-b-0"
          style={{
            borderColor: "var(--border-soft, var(--border))",
            gridTemplateColumns: gridTpl,
          }}
        >
          <div className="font-medium truncate">
            {item.comicid ? (
              <Link
                to={`/library/${item.comicid}`}
                className="hover:text-[var(--primary)]"
              >
                {item.series}
                {item.year && (
                  <span className="text-muted-foreground"> ({item.year})</span>
                )}
              </Link>
            ) : (
              <>
                {item.series}
                {item.year && (
                  <span className="text-muted-foreground"> ({item.year})</span>
                )}
              </>
            )}
          </div>
          <div className="font-mono text-[11px] text-muted-foreground truncate">
            {item.filename || "—"}
          </div>
          <div className="text-muted-foreground truncate">
            {item.site || "—"}
          </div>
          <StatusPill status={item.status} />
          <div className="font-mono text-[11px] text-muted-foreground">
            {item.updated_date || "—"}
          </div>
        </div>
      ))}
    </DenseTable>
  );
}

function HistoryView() {
  const [page, setPage] = useState(0);
  const limit = 50;
  const offset = page * limit;
  const { data, isLoading, error, refetch } = useDownloadHistory(limit, offset);
  const history = data?.history || [];
  const pagination = data?.pagination;

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load download history"
        onRetry={() => refetch()}
      />
    );
  }

  if (history.length === 0) {
    return (
      <EmptyState
        variant="custom"
        eyebrow="HISTORY · EMPTY"
        title="No download history"
        description="Completed downloads will appear here."
      />
    );
  }

  const gridTpl = "2fr 80px 160px 120px 120px";

  return (
    <div className="space-y-3">
      <div className="font-mono text-[11px] text-muted-foreground">
        {pagination?.total || history.length} entries
      </div>
      <DenseTable
        headers={["comic", "issue", "provider", "status", "date"]}
        gridTemplate={gridTpl}
      >
        {history.map((item: HistoryItem, index: number) => (
          <div
            key={`${item.IssueID}-${item.Status}-${index}`}
            className="grid items-center px-4 py-2 text-[12px] border-b last:border-b-0"
            style={{
              borderColor: "var(--border-soft, var(--border))",
              gridTemplateColumns: gridTpl,
            }}
          >
            <div className="font-medium truncate">
              {item.ComicID ? (
                <Link
                  to={`/library/${item.ComicID}`}
                  className="hover:text-[var(--primary)]"
                >
                  {item.ComicName}
                </Link>
              ) : (
                item.ComicName
              )}
            </div>
            <div className="font-mono text-[11px] text-muted-foreground">
              {item.Issue_Number ? `#${item.Issue_Number}` : "—"}
            </div>
            <div className="text-muted-foreground truncate">
              {item.Provider || "—"}
            </div>
            <StatusPill status={item.Status} />
            <div className="font-mono text-[11px] text-muted-foreground">
              {item.DateAdded || "—"}
            </div>
          </div>
        ))}
      </DenseTable>

      {pagination && pagination.total > limit && (
        <div
          className="flex items-center justify-between pt-3 border-t font-mono text-[11px] text-muted-foreground"
          style={{ borderColor: "var(--border)" }}
        >
          <button
            type="button"
            className="px-2.5 py-1 rounded border disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ← prev
          </button>
          <span>
            page {page + 1} / {Math.ceil(pagination.total / limit)}
          </span>
          <button
            type="button"
            className="px-2.5 py-1 rounded border disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
            onClick={() => setPage((p) => p + 1)}
            disabled={!pagination.has_more}
          >
            next →
          </button>
        </div>
      )}
    </div>
  );
}
