import { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { Activity, Download, Clock, CheckCircle2, XCircle } from "lucide-react";
import {
  useDownloadHistory,
  useDownloadQueue,
  type HistoryItem,
  type QueueItem,
} from "@/hooks/useActivity";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";

type ActivityView = "queue" | "history";

export default function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentView = (searchParams.get("view") as ActivityView) || "queue";

  const setView = (view: ActivityView) => {
    setSearchParams({ view });
  };

  return (
    <div className="page-transition">
      <div className="flex items-center gap-3 mb-6">
        <Activity className="w-6 h-6 text-muted-foreground" />
        <div>
          <h1 className="text-[32px] font-bold tracking-tight">Activity</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Download queue and history
          </p>
        </div>
      </div>

      {/* View Toggle */}
      <div className="flex gap-2 mb-6">
        <Button
          variant={currentView === "queue" ? "default" : "outline"}
          onClick={() => setView("queue")}
          size="sm"
        >
          <Download className="w-4 h-4 mr-2" />
          Queue
        </Button>
        <Button
          variant={currentView === "history" ? "default" : "outline"}
          onClick={() => setView("history")}
          size="sm"
        >
          <Clock className="w-4 h-4 mr-2" />
          History
        </Button>
      </div>

      {currentView === "queue" ? <QueueView /> : <HistoryView />}
    </div>
  );
}

function QueueView() {
  const { data: queue, isLoading, error, refetch } = useDownloadQueue();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
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
      <div className="rounded-lg border border-card-border bg-card p-8 text-center">
        <Download className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-muted-foreground">No active downloads</p>
        <p className="text-sm text-muted-foreground/70 mt-1">
          Downloads will appear here when items are being processed
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-card-border overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-card-border bg-muted/50">
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              Series
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              File
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              Site
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              Status
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              Updated
            </th>
          </tr>
        </thead>
        <tbody>
          {queue.map((item: QueueItem) => (
            <tr
              key={item.ID}
              className="border-b border-card-border last:border-0 hover:bg-muted/30"
            >
              <td className="px-4 py-2.5 text-sm font-medium">
                {item.comicid ? (
                  <Link
                    to={`/library/${item.comicid}`}
                    className="hover:underline"
                  >
                    {item.series}
                    {item.year && (
                      <span className="text-muted-foreground">
                        {" "}
                        ({item.year})
                      </span>
                    )}
                  </Link>
                ) : (
                  <>
                    {item.series}
                    {item.year && (
                      <span className="text-muted-foreground">
                        {" "}
                        ({item.year})
                      </span>
                    )}
                  </>
                )}
              </td>
              <td className="px-4 py-2.5 text-sm text-muted-foreground truncate max-w-xs">
                {item.filename || "—"}
              </td>
              <td className="px-4 py-2.5 text-sm text-muted-foreground">
                {item.site || "—"}
              </td>
              <td className="px-4 py-2.5">
                <QueueStatusBadge status={item.status} />
              </td>
              <td className="px-4 py-2.5 text-sm text-muted-foreground">
                {item.updated_date || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
      <div className="space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
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
      <div className="rounded-lg border border-card-border bg-card p-8 text-center">
        <Clock className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-muted-foreground">No download history</p>
        <p className="text-sm text-muted-foreground/70 mt-1">
          Completed downloads will appear here
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="text-sm text-muted-foreground mb-4">
        {pagination?.total || history.length} total entries
      </div>

      <div className="rounded-lg border border-card-border overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-card-border bg-muted/50">
              <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                Comic
              </th>
              <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                Issue
              </th>
              <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                Provider
              </th>
              <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                Status
              </th>
              <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                Date
              </th>
            </tr>
          </thead>
          <tbody>
            {history.map((item: HistoryItem, index: number) => (
              <tr
                key={`${item.IssueID}-${item.Status}-${index}`}
                className="border-b border-card-border last:border-0 hover:bg-muted/30"
              >
                <td className="px-4 py-2.5 text-sm font-medium">
                  {item.ComicID ? (
                    <Link
                      to={`/library/${item.ComicID}`}
                      className="hover:underline"
                    >
                      {item.ComicName}
                    </Link>
                  ) : (
                    item.ComicName
                  )}
                </td>
                <td className="px-4 py-2.5 text-sm text-muted-foreground">
                  {item.Issue_Number ? `#${item.Issue_Number}` : "—"}
                </td>
                <td className="px-4 py-2.5 text-sm text-muted-foreground">
                  {item.Provider || "—"}
                </td>
                <td className="px-4 py-2.5">
                  <HistoryStatusBadge status={item.Status} />
                </td>
                <td className="px-4 py-2.5 text-sm text-muted-foreground">
                  {item.DateAdded || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pagination && pagination.total > limit && (
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-card-border">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page + 1} of {Math.ceil(pagination.total / limit)}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => p + 1)}
            disabled={!pagination.has_more}
          >
            Next
          </Button>
        </div>
      )}
    </>
  );
}

function QueueStatusBadge({ status }: { status: string }) {
  const lower = status?.toLowerCase() || "";
  if (lower === "downloading" || lower === "active") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600">
        <Download className="w-3 h-3" />
        {status}
      </span>
    );
  }
  if (lower === "queued" || lower === "pending") {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-600">
        {status}
      </span>
    );
  }
  if (lower === "completed" || lower === "done") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-600">
        <CheckCircle2 className="w-3 h-3" />
        {status}
      </span>
    );
  }
  if (lower === "failed" || lower === "error") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-600">
        <XCircle className="w-3 h-3" />
        {status}
      </span>
    );
  }
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
      {status || "Unknown"}
    </span>
  );
}

function HistoryStatusBadge({ status }: { status: string }) {
  const lower = status?.toLowerCase() || "";
  if (lower === "snatched" || lower === "downloaded") {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-600">
        <CheckCircle2 className="w-3 h-3" />
        {status}
      </span>
    );
  }
  if (lower === "wanted" || lower === "queued") {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-600">
        {status}
      </span>
    );
  }
  if (lower.includes("fail") || lower.includes("error")) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-600">
        <XCircle className="w-3 h-3" />
        {status}
      </span>
    );
  }
  return (
    <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
      {status || "Unknown"}
    </span>
  );
}
