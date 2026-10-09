import { useEffect, useMemo, useState } from "react";
import { Copy, FilePlus2, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Callout } from "@/components/ui/callout";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import {
  LOG_LINE_CHOICES,
  useLogs,
  useLogFiles,
  useStartNewLog,
  type LogLevelContext,
} from "@/hooks/useLogs";
import {
  formatRetention,
  parseLogLines,
  type LogLineSeverity,
} from "@/lib/logLines";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface LogsTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

/**
 * Number, name, and consequence — the three things #620 settled the dial has to
 * say. The name is the stdlib threshold the level resolves to, which is why
 * there is no "quiet": level 0 still emits warnings and errors.
 */
const LEVEL_OPTIONS = [
  { value: 0, name: "Warning", consequence: "warnings and errors only" },
  { value: 1, name: "Info", consequence: "normal activity, warnings, errors" },
  { value: 2, name: "Debug", consequence: "everything, including diagnostics" },
] as const;

const VIEW_FILTERS: { value: "all" | LogLineSeverity; label: string }[] = [
  { value: "all", label: "All lines" },
  { value: "DEBUG", label: "Debug and above" },
  { value: "INFO", label: "Info and above" },
  { value: "WARNING", label: "Warnings and errors" },
  { value: "ERROR", label: "Errors only" },
];

/**
 * Shown only when a source the dial cannot reach is winning the startup chain.
 *
 * When config is the top of the chain there is nothing to say and saying it
 * anyway is noise — the dial's value simply is what runs. When a startup
 * argument or `COMICARR_LOG_LEVEL` is in force, the dial still applies live but
 * will not survive a restart, and an operator finding that out by restarting is
 * #610 happening a second time.
 */
function OverrideCallout({ level }: { level: LogLevelContext }) {
  if (!level.pinned) return null;
  const appliedLive = level.effective !== level.restart_level;
  return (
    <div
      className="rounded-control border px-3 py-2.5 text-[12.5px] leading-relaxed"
      style={{
        borderColor:
          "color-mix(in oklab, var(--status-paused) 40%, transparent)",
        background: "var(--status-paused-bg)",
        color: "var(--status-paused)",
      }}
    >
      <div className="font-medium">
        {level.restart_source} sets the log level, not this page.
      </div>
      <p className="mt-1">
        Comicarr is running at{" "}
        <strong>
          {level.effective} ({level.effective_name})
        </strong>
        {appliedLive ? " after a save on this page" : ""}. On the next restart
        it returns to{" "}
        <strong>
          {level.restart_level} ({level.restart_name})
        </strong>{" "}
        from {level.restart_source}. The dial below edits{" "}
        <span className="font-mono">LOG_LEVEL</span> in the config file, which
        that source outranks — remove it to make this page's value stick.
      </p>
    </div>
  );
}

export function LogsTab({ config, formData, onChange }: LogsTabProps) {
  const [lineCount, setLineCount] = useState<number>(LOG_LINE_CHOICES[0]);
  const [viewFilter, setViewFilter] = useState<"all" | LogLineSeverity>("all");
  const [selector, setSelector] = useState("current");
  const [query, setQuery] = useState("");
  const [component, setComponent] = useState("");
  const [submitted, setSubmitted] = useState({ query: "", component: "" });
  const { copy, isCopied } = useCopyToClipboard();
  const { addToast } = useToast();
  const files = useLogFiles();
  const { data, isLoading, isFetching, error, refetch } = useLogs(lineCount, {
    search: {
      selector,
      ...submitted,
      severity: viewFilter === "all" ? undefined : viewFilter,
    },
  });
  const refresh = () => {
    files.refetch();
    refetch();
  };
  const startNewLog = useStartNewLog();

  const handleStartNewLog = async () => {
    if (
      !confirm(
        "Start a new log file? The current log is kept as a rotated archive — the viewer will show only what happens from now on.",
      )
    ) {
      return;
    }
    try {
      const result = await startNewLog.mutateAsync();
      setSelector("current");
      addToast({
        type: "success",
        message: result.rotated
          ? "Started a new log file. The previous log was archived."
          : "Cleared the log view. No log file is being written to disk.",
      });
    } catch {
      addToast({ type: "error", message: "Failed to start a new log file" });
    }
  };

  const savedLevel = config.log_level;
  useEffect(() => {
    refetch();
  }, [savedLevel, refetch]);

  const level = formData.log_level ?? config.log_level ?? 1;
  const parsed = useMemo(() => parseLogLines(data?.logs ?? []), [data?.logs]);
  const text = parsed.map((line) => line.raw).join("\n");
  const readError = error || files.error;
  const hasError = Boolean(readError || data?.error);
  const selectedName =
    data?.file?.name ||
    files.data?.files.find((file) => file.selector === selector)?.name ||
    "the selected log file";

  const retention = formatRetention(config.max_logsize, config.max_logfiles);
  const effectiveName = data?.level.effective_name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-base font-medium tracking-wide">Logs</div>
          <div className="text-[13px] text-muted-foreground">
            Search current and retained files
            {retention ? ` · keeps ${retention}` : ""}
            {config.log_dir ? (
              <>
                {" · "}
                <span className="font-mono text-[12px] break-all">
                  {config.log_dir}
                </span>
              </>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            Level
            <Select
              value={String(level)}
              onValueChange={(next) => onChange("log_level", Number(next))}
            >
              <SelectTrigger
                className="h-8 w-[13rem] text-[12.5px]"
                aria-label="Log level"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEVEL_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {option.value} · {option.name} — {option.consequence}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={isFetching || files.isFetching}
          >
            <RefreshCw
              className={isFetching ? "size-3.5 animate-spin" : "size-3.5"}
            />
            Refresh
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => copy(text)}
            disabled={!text || hasError || isFetching}
          >
            <Copy className="size-3.5" />
            {isCopied ? "Copied" : "Copy"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleStartNewLog}
            disabled={startNewLog.isPending}
          >
            <FilePlus2 className="size-3.5" />
            New log
          </Button>
        </div>
      </div>

      {data?.level ? <OverrideCallout level={data.level} /> : null}

      <form
        aria-label="Search log records"
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (query === submitted.query && component === submitted.component)
            refetch();
          else setSubmitted({ query, component });
        }}
      >
        <label className="flex min-w-0 flex-col gap-1 text-sm text-muted-foreground">
          File
          <Select
            value={selector}
            onValueChange={(next) => {
              if (next) setSelector(next);
            }}
          >
            <SelectTrigger className="h-9 w-56" aria-label="Log file">
              <SelectValue>
                {files.data?.files.find((file) => file.selector === selector)
                  ?.name ||
                  (selector === "current"
                    ? "comicarr.log"
                    : "Unavailable file")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {!files.data?.files.some((file) => file.selector === selector) ? (
                <SelectItem value={selector} disabled>
                  {data?.file?.name ||
                    (selector === "current"
                      ? "comicarr.log"
                      : "Selected file")}{" "}
                  (unavailable)
                </SelectItem>
              ) : null}
              {(files.data?.files ?? []).map((file) => (
                <SelectItem key={file.selector} value={file.selector}>
                  {file.name} · {file.size.toLocaleString()} bytes ·{" "}
                  {new Date(file.modified).toLocaleString()}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm text-muted-foreground">
          Search text
          <Input
            className="h-9"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={1000}
            placeholder="Literal text, any record line"
          />
        </label>
        <label className="flex min-w-40 flex-col gap-1 text-sm text-muted-foreground">
          Component
          <Input
            className="h-9"
            value={component}
            onChange={(event) => setComponent(event.target.value)}
            maxLength={200}
            placeholder="Logger function, e.g. backup_files"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Severity
          <Select
            value={viewFilter}
            onValueChange={(next) =>
              setViewFilter(next as "all" | LogLineSeverity)
            }
          >
            <SelectTrigger className="h-9 w-44" aria-label="Filter log lines">
              <SelectValue>
                {
                  VIEW_FILTERS.find((filter) => filter.value === viewFilter)
                    ?.label
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {VIEW_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          Record limit
          <Select
            value={String(lineCount)}
            onValueChange={(next) => setLineCount(Number(next))}
          >
            <SelectTrigger className="h-9 w-24" aria-label="Record limit">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LOG_LINE_CHOICES.map((choice) => (
                <SelectItem key={choice} value={String(choice)}>
                  {choice}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <Button type="submit" size="sm" className="h-9" disabled={isFetching}>
          <Search className="size-3.5" />
          Search
        </Button>
      </form>

      {data?.file && !hasError ? (
        <p role="status" className="text-sm text-muted-foreground">
          <span className="font-mono">{data.file.name}</span> ·{" "}
          {data.lines_scanned?.toLocaleString()} lines scanned ·{" "}
          {data.records_matched?.toLocaleString()} matched ·{" "}
          {data.records_returned?.toLocaleString()} returned
          {data.truncated
            ? ` · Truncated: newest whole records only (up to ${data.record_limit?.toLocaleString()} records / 8 MiB)`
            : " · Complete matches"}
          {isFetching ? " · Searching…" : ""}
        </p>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-[min(62vh,640px)] w-full" />
      ) : hasError ? (
        <Callout tone="error" className="px-3 py-2.5 text-[12.5px]">
          Could not read {selectedName}:{" "}
          {data?.error ||
            (readError instanceof Error ? readError.message : "unknown error")}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-3"
            onClick={refresh}
            disabled={isFetching || files.isFetching}
          >
            Refresh files and results
          </Button>
        </Callout>
      ) : (
        <pre
          className="max-h-[min(62vh,640px)] overflow-auto rounded-lg border p-3 font-mono text-[11.5px] leading-[1.45] whitespace-pre-wrap break-words"
          style={{
            borderColor: "var(--border)",
            background: "color-mix(in oklab, var(--card) 70%, black)",
          }}
        >
          {text ||
            ((data?.lines_scanned ?? parsed.length) === 0
              ? `Nothing in ${data?.file?.name || "comicarr.log"} yet.${
                  effectiveName
                    ? ` Comicarr is logging at ${data?.level.effective} (${effectiveName}) — raise the level above to capture more.`
                    : ""
                }`
              : "No records match this search.")}
        </pre>
      )}

      <p className="text-[11px] text-muted-foreground">
        Provider secrets are redacted before these lines leave the server.
        Retention is set in <span className="font-mono">config.ini</span> and is
        shown here read-only. Search scans the selected file and returns whole
        records, including tracebacks, up to 5,000 records or 8 MiB. Component
        matches the logger function name in either log format.
      </p>
    </div>
  );
}
