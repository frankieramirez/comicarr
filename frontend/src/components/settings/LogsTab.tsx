import { i18n, type MessageDescriptor } from "@lingui/core";
import { msg, ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useEffect, useMemo, useState } from "react";
import { Copy, Download, FilePlus2, RefreshCw, Search } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
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
import { cn } from "@/lib/utils";
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
import { formatDate, formatNumber } from "@/lib/intl";

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
  {
    value: 0,
    name: msg`Warning`,
    consequence: msg`warnings and errors only`,
  },
  {
    value: 1,
    name: msg`Info`,
    consequence: msg`normal activity, warnings, errors`,
  },
  {
    value: 2,
    name: msg`Debug`,
    consequence: msg`everything, including diagnostics`,
  },
] as const;

const VIEW_FILTERS: {
  value: "all" | LogLineSeverity;
  label: MessageDescriptor;
}[] = [
  { value: "all", label: msg`All lines` },
  { value: "DEBUG", label: msg`Debug and above` },
  { value: "INFO", label: msg`Info and above` },
  { value: "WARNING", label: msg`Warnings and errors` },
  { value: "ERROR", label: msg`Errors only` },
];

function searchSummary(
  scanned: number,
  matched: number,
  returned: number,
): string {
  const lines = plural(scanned, {
    one: "# line scanned",
    other: "# lines scanned",
  });
  return t`${lines} · ${matched} matched · ${returned} returned`;
}

function truncatedNote(limit: number): string {
  return t`Truncated: newest whole records only (up to ${limit} records / 8 MiB)`;
}

function emptyLogMessage(
  fileName: string,
  level: number | undefined,
  levelName: string | null | undefined,
): string {
  const levelNumber = level ?? "";
  return levelName
    ? t`Nothing in ${fileName} yet. Comicarr is logging at ${levelNumber} (${levelName}) — raise the level above to capture more.`
    : t`Nothing in ${fileName} yet.`;
}

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
  const source = level.restart_source;
  const running = level.effective;
  const runningName = level.effective_name;
  const restart = level.restart_level;
  const restartName = level.restart_name;
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
        <Trans>{source} sets the log level, not this page.</Trans>
      </div>
      <p className="mt-1">
        {appliedLive ? (
          <Trans>
            Comicarr is running at{" "}
            <strong>
              {running} ({runningName})
            </strong>{" "}
            after a save on this page. On the next restart it returns to{" "}
            <strong>
              {restart} ({restartName})
            </strong>{" "}
            from {source}. The dial below edits{" "}
            <span className="font-mono">LOG_LEVEL</span> in the config file,
            which that source outranks — remove it to make this page's value
            stick.
          </Trans>
        ) : (
          <Trans>
            Comicarr is running at{" "}
            <strong>
              {running} ({runningName})
            </strong>
            . On the next restart it returns to{" "}
            <strong>
              {restart} ({restartName})
            </strong>{" "}
            from {source}. The dial below edits{" "}
            <span className="font-mono">LOG_LEVEL</span> in the config file,
            which that source outranks — remove it to make this page's value
            stick.
          </Trans>
        )}
      </p>
    </div>
  );
}

export function LogsTab({ config, formData, onChange }: LogsTabProps) {
  const [lineCount, setLineCount] = useState<number>(LOG_LINE_CHOICES[0]);
  const [viewFilter, setViewFilter] = useState<"all" | LogLineSeverity>("all");
  const [selector, setSelector] = useState("current");
  // The issue page links here with ?logq= so the log opens on its lines.
  const [initialQuery] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get("logq") ?? "";
    } catch {
      return "";
    }
  });
  const [query, setQuery] = useState(initialQuery);
  const [component, setComponent] = useState("");
  const [submitted, setSubmitted] = useState({
    query: initialQuery,
    component: "",
  });
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
        t`Start a new log file? The current log is kept as a rotated archive — the viewer will show only what happens from now on.`,
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
          ? t`Started a new log file. The previous log was archived.`
          : t`Cleared the log view. No log file is being written to disk.`,
      });
    } catch {
      addToast({ type: "error", message: t`Failed to start a new log file` });
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
  const selectedFile = files.data?.files.find(
    (file) => file.selector === selector,
  );
  const selectedFileName = selectedFile?.name ?? "";
  const selectedName =
    data?.file?.name || selectedFile?.name || t`the selected log file`;
  const readErrorText =
    data?.error ||
    (readError instanceof Error ? readError.message : t`unknown error`);

  const retention = formatRetention(config.max_logsize, config.max_logfiles);
  const effectiveName = data?.level.effective_name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-base font-medium tracking-wide">
            <Trans>Logs</Trans>
          </div>
          <div className="text-[13px] text-muted-foreground">
            <Trans>Search current and retained files</Trans>
            {retention ? ` · ${t`keeps ${retention}`}` : ""}
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
            <Trans>Level</Trans>
            <Select
              value={String(level)}
              onValueChange={(next) => onChange("log_level", Number(next))}
            >
              <SelectTrigger
                className="h-8 w-[13rem] text-[12.5px]"
                aria-label={t`Log level`}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEVEL_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {option.value} · {i18n._(option.name)} —{" "}
                    {i18n._(option.consequence)}
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
            <Trans>Refresh</Trans>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => copy(text)}
            disabled={!text || hasError || isFetching}
          >
            <Copy className="size-3.5" />
            {isCopied ? t`Copied` : t`Copy results`}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleStartNewLog}
            disabled={startNewLog.isPending}
          >
            <FilePlus2 className="size-3.5" />
            <Trans>New log</Trans>
          </Button>
        </div>
      </div>

      {data?.level ? <OverrideCallout level={data.level} /> : null}

      <form
        aria-label={t`Search log records`}
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (query === submitted.query && component === submitted.component)
            refetch();
          else setSubmitted({ query, component });
        }}
      >
        <label className="flex min-w-0 flex-col gap-1 text-sm text-muted-foreground">
          <Trans>File</Trans>
          <Select
            value={selector}
            onValueChange={(next) => {
              if (next) setSelector(next);
            }}
          >
            <SelectTrigger className="h-9 w-56" aria-label={t`Log file`}>
              <SelectValue>
                {files.data?.files.find((file) => file.selector === selector)
                  ?.name ||
                  (selector === "current"
                    ? "comicarr.log"
                    : t`Unavailable file`)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {!files.data?.files.some((file) => file.selector === selector) ? (
                <SelectItem value={selector} disabled>
                  {t`${ph({
                    file:
                      data?.file?.name ||
                      (selector === "current"
                        ? "comicarr.log"
                        : t`Selected file`),
                  })} (unavailable)`}
                </SelectItem>
              ) : null}
              {(files.data?.files ?? []).map((file) => (
                <SelectItem key={file.selector} value={file.selector}>
                  {file.name} ·{" "}
                  {t`${ph({ size: formatNumber(file.size) })} bytes`} ·{" "}
                  {formatDate(new Date(file.modified), {
                    dateStyle: "short",
                    timeStyle: "medium",
                  })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        {selectedFile ? (
          <a
            href={`/api/system/logs/download?${new URLSearchParams({ selector })}`}
            download
            className={cn(
              buttonVariants({ variant: "outline", size: "sm" }),
              "h-9",
            )}
          >
            <Download className="size-3.5" />
            <Trans>Download full file</Trans>
          </a>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9"
            disabled
          >
            <Download className="size-3.5" />
            <Trans>Download full file</Trans>
          </Button>
        )}
        <label className="flex min-w-40 flex-1 flex-col gap-1 text-sm text-muted-foreground">
          <Trans>Search text</Trans>
          <Input
            className="h-9"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={1000}
            placeholder={t`Literal text, any record line`}
          />
        </label>
        <label className="flex min-w-40 flex-col gap-1 text-sm text-muted-foreground">
          <Trans>Component</Trans>
          <Input
            className="h-9"
            value={component}
            onChange={(event) => setComponent(event.target.value)}
            maxLength={200}
            placeholder={t`Logger function, e.g. backup_files`}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          <Trans>Severity</Trans>
          <Select
            value={viewFilter}
            onValueChange={(next) =>
              setViewFilter(next as "all" | LogLineSeverity)
            }
          >
            <SelectTrigger
              className="h-9 w-44"
              aria-label={t`Filter log lines`}
            >
              <SelectValue>
                {i18n._(
                  VIEW_FILTERS.find((filter) => filter.value === viewFilter)
                    ?.label ?? VIEW_FILTERS[0].label,
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {VIEW_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {i18n._(option.label)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted-foreground">
          <Trans>Record limit</Trans>
          <Select
            value={String(lineCount)}
            onValueChange={(next) => setLineCount(Number(next))}
          >
            <SelectTrigger className="h-9 w-24" aria-label={t`Record limit`}>
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
          <Trans>Search</Trans>
        </Button>
      </form>

      {data?.file && !hasError ? (
        <p role="status" className="text-sm text-muted-foreground">
          <span className="font-mono">{data.file.name}</span> ·{" "}
          {searchSummary(
            data.lines_scanned ?? 0,
            data.records_matched ?? 0,
            data.records_returned ?? 0,
          )}
          {data.truncated
            ? ` · ${truncatedNote(data.record_limit ?? 0)}`
            : ` · ${t`Complete matches`}`}
          {isFetching ? ` · ${t`Searching…`}` : ""}
        </p>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-[min(62vh,640px)] w-full" />
      ) : hasError ? (
        <Callout tone="error" className="px-3 py-2.5 text-[12.5px]">
          {t`Could not read ${selectedName}: ${readErrorText}`}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-3"
            onClick={refresh}
            disabled={isFetching || files.isFetching}
          >
            <Trans>Refresh files and results</Trans>
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
              ? emptyLogMessage(
                  data?.file?.name || "comicarr.log",
                  data?.level.effective,
                  effectiveName,
                )
              : t`No records match this search.`)}
        </pre>
      )}

      <p className="text-xs text-muted-foreground">
        {selectedFile ? (
          <>
            <Trans>
              Download full file saves all of{" "}
              <span className="font-mono">{selectedFileName}</span> as{" "}
              <span className="font-mono">{selectedFileName}.redacted.txt</span>
              , with secrets redacted.
            </Trans>
          </>
        ) : (
          t`Download full file saves the whole selected file with secrets redacted.`
        )}{" "}
        <Trans>
          It is an operator diagnostic and can contain series names and library
          paths. Copy results copies only the records shown above.
        </Trans>
      </p>

      <p className="text-[11px] text-muted-foreground">
        <Trans>
          Provider secrets are redacted before these lines leave the server.
          Retention is set in <span className="font-mono">config.ini</span> and
          is shown here read-only. Search scans the selected file and returns
          whole records, including tracebacks, up to 5,000 records or 8 MiB.
          Component matches the logger function name in either log format.
        </Trans>
      </p>
    </div>
  );
}
