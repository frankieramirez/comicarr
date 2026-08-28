import { useEffect, useMemo, useState } from "react";
import { Copy, FilePlus2, RefreshCw } from "lucide-react";
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
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import {
  LOG_LINE_CHOICES,
  useLogs,
  useStartNewLog,
  type LogLevelContext,
} from "@/hooks/useLogs";
import {
  filterByMinSeverity,
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
      className="rounded-[5px] border px-3 py-2.5 text-[12.5px] leading-relaxed"
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
  const { copy, isCopied } = useCopyToClipboard();
  const { addToast } = useToast();
  const { data, isLoading, isFetching, error, refetch } = useLogs(lineCount);
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
  const visible = useMemo(
    () => filterByMinSeverity(parsed, viewFilter),
    [parsed, viewFilter],
  );
  const text = visible.map((line) => line.raw).join("\n");

  const retention = formatRetention(config.max_logsize, config.max_logfiles);
  const effectiveName = data?.level.effective_name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-base font-medium tracking-wide">Logs</div>
          <div className="text-[13px] text-muted-foreground">
            Last {lineCount} lines of{" "}
            <span className="font-mono text-[12px]">comicarr.log</span>
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

          <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            Show
            <Select
              value={viewFilter}
              onValueChange={(next) =>
                setViewFilter(next as "all" | LogLineSeverity)
              }
            >
              <SelectTrigger
                className="h-8 w-[11rem] text-[12.5px]"
                aria-label="Filter log lines"
              >
                <SelectValue />
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

          <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            Lines
            <Select
              value={String(lineCount)}
              onValueChange={(next) => setLineCount(Number(next))}
            >
              <SelectTrigger
                className="h-8 w-[6rem] text-[12.5px]"
                aria-label="Number of lines"
              >
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

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
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
            disabled={!text}
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

      {isLoading ? (
        <Skeleton className="h-[min(62vh,640px)] w-full" />
      ) : error || data?.error ? (
        <div
          className="rounded-[5px] border px-3 py-2.5 text-[12.5px]"
          style={{
            borderColor:
              "color-mix(in oklab, var(--status-error) 30%, transparent)",
            background: "var(--status-error-bg)",
            color: "var(--status-error)",
          }}
        >
          Could not read {data?.path || "the log file"}:{" "}
          {data?.error ||
            (error instanceof Error ? error.message : "unknown error")}
        </div>
      ) : (
        <pre
          className="max-h-[min(62vh,640px)] overflow-auto rounded-[6px] border p-3 font-mono text-[11.5px] leading-[1.45] whitespace-pre-wrap break-words"
          style={{
            borderColor: "var(--border)",
            background: "color-mix(in oklab, var(--card) 70%, black)",
          }}
        >
          {text ||
            (parsed.length === 0
              ? // An install that has just upgraded has little or no history —
                `Nothing in comicarr.log yet.${
                  effectiveName
                    ? ` Comicarr is logging at ${data?.level.effective} (${effectiveName}) — raise the level above to capture more.`
                    : ""
                }`
              : "No lines match this filter.")}
        </pre>
      )}

      <p className="text-[11px] text-muted-foreground">
        Provider secrets are redacted before these lines leave the server.
        Retention is set in <span className="font-mono">config.ini</span> and is
        shown here read-only. Rotated files are not read — only the current one.
      </p>
    </div>
  );
}
