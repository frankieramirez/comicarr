import { useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createColumnHelper,
  type SortingState,
  type RowData,
} from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";
import {
  useDownloadHistory,
  useDownloadQueue,
  useInFlightItems,
  useRequeueDownload,
  type HistoryItem,
  type InFlightItem,
  type QueueItem,
} from "@/hooks/useActivity";
import { useDebounce } from "@/hooks/use-debounce";
import { TimelineView } from "@/components/activity/timeline";
import { DataTable } from "@/components/data-table/DataTable";
import {
  useTableState,
  type ComicarrTable,
  type ComicarrTableFeatures,
} from "@/components/data-table/useTableState";
import { useServerPage } from "@/components/data-table/useServerPage";
import { encodeRowId } from "@/components/data-table/rowId";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import FilterField from "@/components/ui/FilterField";
import RelativeTime from "@/components/ui/RelativeTime";
import PageHeader, { Tab, TabRow } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/toast";
import type { PaginationMeta } from "@/types";

type ActivityView = "timeline" | "in_flight" | "queue" | "history";
const PAGE_SIZE = 25;

function statusPillMeta(status: string) {
  const normalized = (status || "").trim().toLowerCase();
  if (normalized.includes("fail") || normalized.includes("error")) {
    return {
      label: "Failed",
      description: "Terminal download failure.",
      color: "var(--status-error)",
    };
  }
  if (normalized === "unknown") {
    return {
      label: "Unknown",
      description: "Manual review required; it will not retry automatically.",
      color: "var(--status-paused)",
    };
  }
  if (normalized.includes("manual") || normalized.includes("review")) {
    return {
      label: "Manual review",
      description: "Requires attention and will not retry automatically.",
      color: "var(--status-paused)",
    };
  }
  if (
    normalized.includes("down") ||
    normalized.includes("snatch") ||
    normalized === "active" ||
    normalized === "completed" ||
    normalized === "done"
  ) {
    return {
      label: status || "—",
      description: "Active download.",
      color: "var(--status-active)",
    };
  }
  if (
    normalized.includes("queue") ||
    normalized.includes("pend") ||
    normalized === "wanted"
  ) {
    return {
      label: status || "—",
      description: "Waiting for a worker.",
      color: "var(--status-paused)",
    };
  }

  return {
    label: status || "—",
    description: "Download state reported by the provider.",
    color: "var(--muted-foreground)",
  };
}

function StatusPill({ status }: { status: string }) {
  const { label, description, color } = statusPillMeta(status);

  return (
    <span
      className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase"
      style={{ color }}
      aria-label={`${label}: ${description}`}
      title={description}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}

export default function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawView = searchParams.get("view");
  // Timeline is the default landing tab (#429 / #486). Queue keeps working via
  // ?view=queue; history via ?view=history. The status bar's in-flight count
  // lands on ?state=in_flight — a different dataset than the timeline (#676).
  const currentView: ActivityView =
    searchParams.get("state") === "in_flight"
      ? "in_flight"
      : rawView === "history" || rawView === "queue"
        ? rawView
        : "timeline";

  const scope_type = searchParams.get("scope_type");
  const scope_id = searchParams.get("scope_id");

  const setView = (view: ActivityView) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (view === "in_flight") {
        next.delete("view");
        next.set("state", "in_flight");
      } else {
        next.delete("state");
        if (view === "timeline") next.delete("view");
        else next.set("view", view);
      }
      return next;
    });
  };

  const meta =
    currentView === "timeline"
      ? "what Comicarr has been doing"
      : currentView === "in_flight"
        ? "running searches and open download rows"
        : currentView === "queue"
          ? "live direct downloads"
          : "download history";

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader title="Activity" meta={meta} />

      <TabRow>
        <Tab
          active={currentView === "timeline"}
          label="Timeline"
          onClick={() => setView("timeline")}
        />
        <Tab
          active={currentView === "in_flight"}
          label="In flight"
          onClick={() => setView("in_flight")}
        />
        <Tab
          active={currentView === "queue"}
          label="Direct Downloads"
          onClick={() => setView("queue")}
        />
        <Tab
          active={currentView === "history"}
          label="Download History"
          onClick={() => setView("history")}
        />
      </TabRow>

      <div className="flex-1 min-h-0 flex flex-col">
        {currentView === "timeline" && (
          <TimelineView scope_type={scope_type} scope_id={scope_id} />
        )}
        {currentView === "in_flight" && <InFlightView />}
        {currentView === "queue" && <QueueView />}
        {currentView === "history" && <HistoryView />}
      </div>
    </div>
  );
}

function inFlightRowId(item: InFlightItem): string {
  return item.kind === "run"
    ? `run:${item.item_id}`
    : `journal:${item.release_key}`;
}

function inFlightHref(item: InFlightItem): string | null {
  if (item.comicid && item.issueid) {
    return `/library/${encodeURIComponent(item.comicid)}/issue/${encodeURIComponent(item.issueid)}`;
  }
  if (item.comicid) {
    return `/library/${encodeURIComponent(item.comicid)}`;
  }
  return null;
}

function inFlightKindLabel(item: InFlightItem): string {
  if (item.kind === "run") {
    const command = (item.command_kind || "").toLowerCase();
    if (command.includes("refresh")) return "Refreshing";
    return "Searching";
  }
  switch (item.stage) {
    case "reserved":
      return "Reserved";
    case "snatched":
      return "Snatched";
    case "downloaded":
      return "Downloaded";
    case "post_processing":
      return "Post-processing";
    case "moved":
      return "Moving";
    default:
      return item.stage || "In flight";
  }
}

function inFlightStateLabel(item: InFlightItem): string {
  if (item.kind === "run") return item.state;
  return (item.stage || "").replace(/_/g, " ");
}

function InFlightView() {
  const inflight = useInFlightItems();
  const items = inflight.data?.results ?? [];
  const hardError = !inflight.data ? inflight.error : null;

  if (inflight.isLoading && !inflight.data) {
    return <LoadingRows />;
  }

  if (hardError) {
    return (
      <div className="px-5 py-4">
        <ErrorDisplay
          error={hardError}
          title="Unable to load in-flight work"
          onRetry={() => void inflight.refetch()}
        />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="px-5 py-10">
        <EmptyState
          variant="custom"
          eyebrow="IN FLIGHT · EMPTY"
          title="Nothing in flight"
          description="Running searches and open download or post-processing rows appear here — the same items the status bar counts."
          action={{ label: "Back to timeline", to: "/activity" }}
        />
      </div>
    );
  }

  return (
    <ul
      className="flex-1 min-h-0 overflow-auto divide-y divide-border"
      aria-label="In-flight items"
    >
      {items.map((item) => {
        const href = inFlightHref(item);
        return (
          <li
            key={inFlightRowId(item)}
            className="flex items-start gap-3 px-5 py-2.5"
            data-kind={item.kind}
            data-item-id={
              item.kind === "run" ? String(item.item_id) : item.release_key
            }
          >
            <span
              className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
              style={{ background: "var(--status-active)" }}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="text-[13px]">
                {href ? (
                  <Link
                    to={href}
                    className="font-medium hover:text-[var(--primary)]"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span className="font-medium">{item.label}</span>
                )}
              </div>
              <div className="font-mono text-[11px] text-muted-foreground">
                {inFlightKindLabel(item)}
                <span className="mx-1.5">·</span>
                {inFlightStateLabel(item)}
                {item.kind === "journal" && item.provider ? (
                  <>
                    <span className="mx-1.5">·</span>
                    {item.provider}
                  </>
                ) : null}
              </div>
            </div>
            <RelativeTime value={item.updated_at} />
          </li>
        );
      })}
    </ul>
  );
}

function ActivityToolbar({
  value,
  onChange,
  label,
  placeholder,
  isRefreshing,
  onRefresh,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder: string;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="shrink-0 px-5 py-2.5 border-b border-border flex items-center gap-3">
      <div className="flex-1 max-w-lg">
        <FilterField
          placeholder={placeholder}
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          shortcut="/"
        />
      </div>
      <button
        type="button"
        onClick={onRefresh}
        disabled={isRefreshing}
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[5px] border font-mono text-[11px] text-muted-foreground disabled:opacity-60"
        style={{ borderColor: "var(--border)" }}
      >
        <RefreshCw
          className={`w-3 h-3 ${isRefreshing ? "animate-spin" : ""}`}
        />
        refresh
      </button>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className="px-5 py-4 space-y-2">
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className="h-11" />
      ))}
    </div>
  );
}

/**
 * Both activity tables are server-driven: the sort and the search are inputs to
 * the query that produces `data`, so both have to be readable *before* the
 * table exists. That is what #377's `store` adapter is for — `useTableState`
 * owns the sorting slice, the caller owns where it is kept. Here that is plain
 * React state which also resets the server page, because under
 * `manualPagination` TanStack's `autoResetPageIndex` is inert and the
 * reset-on-change rule has no other owner (#360).
 *
 * What is left here is wiring specific to this page. The table state itself —
 * sorting, selection, the row models — now lives in `useTableState`, which is
 * the generalisation of the `useActivityTableState` this replaces.
 */
function useActivityTable(defaultSortId: string) {
  const { page, limit, offset, nextPage, prevPage, resetPage } =
    useServerPage(PAGE_SIZE);
  const [search, setSearchState] = useState("");
  const debouncedSearch = useDebounce(search, 400);
  const [sorting, setSorting] = useState<SortingState>([
    { id: defaultSortId, desc: true },
  ]);
  const activeSort = sorting[0] ?? { id: defaultSortId, desc: true };

  const setSearch = useCallback(
    (value: string) => {
      setSearchState(value);
      resetPage();
    },
    [resetPage],
  );

  const store = useMemo(
    () => ({
      state: { sorting, globalFilter: "", pageIndex: page },
      setState: (patch: { sorting?: SortingState }) => {
        if (!("sorting" in patch) || !patch.sorting) return;
        setSorting(patch.sorting);
        resetPage();
      },
    }),
    [sorting, page, resetPage],
  );

  return {
    limit,
    offset,
    search,
    setSearch,
    debouncedSearch,
    activeSort,
    store,
    nextPage,
    prevPage,
  };
}

function ActivityTableView<TData extends RowData>({
  table,
  rows,
  pagination,
  search,
  onSearchChange,
  filterLabel,
  filterPlaceholder,
  isLoading,
  isFetching,
  error,
  errorTitle,
  emptyEyebrow,
  emptyTitle,
  emptyDescription,
  filteredTitle,
  onRefresh,
  onNextPage,
  onPrevPage,
}: {
  table: ComicarrTable<TData>;
  rows: TData[];
  pagination?: PaginationMeta;
  search: string;
  onSearchChange: (value: string) => void;
  filterLabel: string;
  filterPlaceholder: string;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  errorTitle: string;
  emptyEyebrow: string;
  emptyTitle: string;
  emptyDescription: string;
  filteredTitle: string;
  onRefresh: () => void;
  onNextPage: () => void;
  onPrevPage: () => void;
}) {
  return (
    <>
      <ActivityToolbar
        value={search}
        onChange={onSearchChange}
        label={filterLabel}
        placeholder={filterPlaceholder}
        isRefreshing={isFetching}
        onRefresh={onRefresh}
      />
      {isLoading && <LoadingRows />}
      {error && (
        <div className="px-5 py-4">
          <ErrorDisplay error={error} title={errorTitle} onRetry={onRefresh} />
        </div>
      )}
      {!isLoading && !error && rows.length === 0 && (
        <div className="px-5 py-4">
          <EmptyState
            variant="custom"
            eyebrow={
              search ? `${emptyEyebrow} · FILTERED` : `${emptyEyebrow} · EMPTY`
            }
            title={search ? filteredTitle : emptyTitle}
            description={search ? "Try a different filter." : emptyDescription}
            action={
              pagination && pagination.offset > 0
                ? {
                    label: "Previous",
                    onClick: onPrevPage,
                    variant: "outline",
                  }
                : undefined
            }
          />
        </div>
      )}
      {!isLoading && !error && pagination && rows.length > 0 && (
        <div className="flex-1 min-h-0 flex flex-col border-b border-border">
          <div className="flex-1 min-h-0 overflow-auto">
            <DataTable table={table} />
          </div>
          <DataTableServerPagination
            pagination={pagination}
            onNextPage={onNextPage}
            onPrevPage={onPrevPage}
          />
        </div>
      )}
    </>
  );
}

const queueColumnHelper = createColumnHelper<
  ComicarrTableFeatures,
  QueueItem
>();

function QueueView() {
  const {
    limit,
    offset,
    search,
    setSearch,
    debouncedSearch,
    activeSort,
    store,
    nextPage,
    prevPage,
  } = useActivityTable("updated");
  const { data, isLoading, isFetching, error, refetch } = useDownloadQueue({
    limit,
    offset,
    q: debouncedSearch,
    sort: activeSort.id,
    order: activeSort.desc ? "desc" : "asc",
  });
  const queue = data?.queue ?? [];
  const {
    mutateAsync: requeueDownload,
    isPending: isRequeuePending,
    variables: requeueItemId,
  } = useRequeueDownload();
  const { addToast } = useToast();

  const handleRequeue = useCallback(
    async (item: QueueItem) => {
      if (
        !window.confirm(
          "Requeue this failed direct download? It will be retried by the DDL worker.",
        )
      ) {
        return;
      }

      try {
        await requeueDownload(item.ID);
        addToast({
          type: "success",
          message: "Direct download requeued.",
        });
      } catch (err) {
        addToast({
          type: "error",
          message: `Unable to requeue direct download: ${err instanceof Error ? err.message : "Unknown error"}`,
        });
      }
    },
    [addToast, requeueDownload],
  );

  const columns = useMemo(
    () =>
      queueColumnHelper.columns([
        queueColumnHelper.accessor("series", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Series" />
          ),
          cell: ({ row }) => {
            const content = (
              <>
                {row.original.series || "—"}
                {row.original.year && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({row.original.year})
                  </span>
                )}
              </>
            );
            return row.original.comicid ? (
              <Link
                to={`/library/${row.original.comicid}`}
                className="font-medium hover:text-[var(--primary)]"
              >
                {content}
              </Link>
            ) : (
              <span className="font-medium">{content}</span>
            );
          },
        }),
        queueColumnHelper.accessor("filename", {
          id: "file",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="File" />
          ),
          cell: ({ getValue }) => (
            <span className="font-mono text-[11px] text-muted-foreground">
              {getValue() || "—"}
            </span>
          ),
        }),
        queueColumnHelper.accessor("site", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Site" />
          ),
          cell: ({ getValue }) => (
            <span className="text-muted-foreground">{getValue() || "—"}</span>
          ),
        }),
        queueColumnHelper.accessor("status", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Status" />
          ),
          cell: ({ getValue }) => <StatusPill status={getValue()} />,
        }),
        queueColumnHelper.accessor("updated_date", {
          id: "updated",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Updated" />
          ),
          cell: ({ getValue }) => <RelativeTime value={getValue()} />,
        }),
        queueColumnHelper.display({
          id: "actions",
          header: "Actions",
          cell: ({ row }) => {
            const item = row.original;
            const isFailed = item.status.trim().toLowerCase() === "failed";
            if (!isFailed) return null;

            const isRequeueing = isRequeuePending && requeueItemId === item.ID;
            return (
              <button
                type="button"
                onClick={() => void handleRequeue(item)}
                disabled={isRequeueing}
                className="rounded-[4px] border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
                style={{ borderColor: "var(--border)" }}
                aria-label={`Requeue ${item.series || item.filename || "failed direct download"}`}
                title="Requeue this failed direct download after confirmation"
              >
                {isRequeueing ? "requeueing…" : "requeue"}
              </button>
            );
          },
        }),
      ]),
    [handleRequeue, isRequeuePending, requeueItemId],
  );

  const { table } = useTableState({
    data: queue,
    columns,
    store,
    manualSorting: true,
    enableSortingRemoval: false,
    getRowId: (row) => row.ID,
  });

  return (
    <ActivityTableView
      table={table}
      rows={queue}
      pagination={data?.pagination}
      search={search}
      onSearchChange={setSearch}
      filterLabel="Filter queue activity"
      filterPlaceholder="Filter by series, file, site, or status…"
      isLoading={isLoading}
      isFetching={isFetching}
      error={error}
      errorTitle="Unable to load download queue"
      emptyEyebrow="QUEUE"
      emptyTitle="No active downloads"
      emptyDescription="Queued and downloading direct downloads will appear here; failures stay visible for review."
      filteredTitle="No matching queue items"
      onRefresh={() => void refetch()}
      onNextPage={nextPage}
      onPrevPage={prevPage}
    />
  );
}

const historyColumnHelper = createColumnHelper<
  ComicarrTableFeatures,
  HistoryItem
>();

function HistoryView() {
  const {
    limit,
    offset,
    search,
    setSearch,
    debouncedSearch,
    activeSort,
    store,
    nextPage,
    prevPage,
  } = useActivityTable("date");
  const { data, isLoading, isFetching, error, refetch } = useDownloadHistory({
    limit,
    offset,
    q: debouncedSearch,
    sort: activeSort.id,
    order: activeSort.desc ? "desc" : "asc",
  });
  const history = data?.history ?? [];

  const columns = useMemo(
    () =>
      historyColumnHelper.columns([
        historyColumnHelper.accessor("ComicName", {
          id: "series",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Series" />
          ),
          cell: ({ row }) =>
            row.original.ComicID ? (
              <Link
                to={`/library/${row.original.ComicID}`}
                className="font-medium hover:text-[var(--primary)]"
              >
                {row.original.ComicName || "—"}
              </Link>
            ) : (
              <span className="font-medium">
                {row.original.ComicName || "—"}
              </span>
            ),
        }),
        historyColumnHelper.accessor("Issue_Number", {
          id: "issue",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Issue" />
          ),
          cell: ({ getValue }) => (
            <span className="font-mono text-[11px] text-muted-foreground">
              {getValue() ? `#${getValue()}` : "—"}
            </span>
          ),
        }),
        historyColumnHelper.accessor("Provider", {
          id: "provider",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Provider" />
          ),
          cell: ({ getValue }) => (
            <span className="text-muted-foreground">{getValue() || "—"}</span>
          ),
        }),
        historyColumnHelper.accessor("Status", {
          id: "status",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Status" />
          ),
          cell: ({ getValue }) => <StatusPill status={getValue()} />,
        }),
        historyColumnHelper.accessor("DateAdded", {
          id: "date",
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Date" />
          ),
          cell: ({ getValue }) => <RelativeTime value={getValue()} />,
        }),
      ]),
    [],
  );

  const { table } = useTableState({
    data: history,
    columns,
    store,
    manualSorting: true,
    enableSortingRemoval: false,
    // Was `${IssueID}-${Status}-${index}`, which is positional: the same row
    // gets a different id on any page or sort change. #383 found the real
    // identity is already database-enforced — `snatched` carries
    // UNIQUE(IssueID, Status, Provider) — so there is something to key on
    // without a backend change. Encoded rather than joined because `Status`
    // takes the value `Post-Processed`, which contains the delimiter a bare
    // join would use.
    getRowId: (row) => encodeRowId([row.IssueID, row.Status, row.Provider]),
  });

  return (
    <ActivityTableView
      table={table}
      rows={history}
      pagination={data?.pagination}
      search={search}
      onSearchChange={setSearch}
      filterLabel="Filter download history"
      filterPlaceholder="Filter by series, issue, provider, status, or file…"
      isLoading={isLoading}
      isFetching={isFetching}
      error={error}
      errorTitle="Unable to load download history"
      emptyEyebrow="HISTORY"
      emptyTitle="No download history"
      emptyDescription="Download events will appear here."
      filteredTitle="No matching history"
      onRefresh={() => void refetch()}
      onNextPage={nextPage}
      onPrevPage={prevPage}
    />
  );
}
