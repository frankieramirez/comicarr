/**
 * Reading `comicarr.log` on the client.
 *
 * The server hands back raw lines — redaction has already happened there, and
 * there is deliberately no second redaction path here. All this module does is
 * work out which severity a line carries so the view filter can hide the ones
 * an operator is not chasing.
 *
 * Two formatter generations live in one file. Installs that upgraded through
 * #628 have the retired locale branch's `LEVEL :: MainThread : file.py:fn:12 :`
 * behind them and the current `LEVEL :: comicarr.fn.12 : MainThread :` ahead of
 * it. Both share the prefix `<timestamp> - <LEVEL> :: `, which is the only part
 * this parser reads, so the boundary costs nothing.
 */

export const LOG_LEVEL_NAMES = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

export type LogLineSeverity = (typeof LOG_LEVEL_NAMES)[number];

export type LogLine = {
  raw: string;
  /** Severity of this line, or of the line it continues. */
  severity: LogLineSeverity | null;
};

/** `11-Aug-2026 14:28:01 - INFO    :: …` — common to both formatter generations. */
const LINE_RE = /^(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}) - ([A-Z]+)\s*:: /;

const SEVERITIES: Record<string, LogLineSeverity> = {
  DEBUG: "DEBUG",
  INFO: "INFO",
  WARNING: "WARNING",
  WARN: "WARNING",
  ERROR: "ERROR",
  CRITICAL: "ERROR",
  FATAL: "ERROR",
  EXCEPTION: "ERROR",
};

/**
 * Attach a severity to every line.
 *
 * A line that does not carry a timestamped header is a continuation — the body
 * of a traceback, most often — and inherits the severity of the line above it
 * so that filtering for errors keeps the traceback attached to its error. A
 * continuation with nothing above it stays `null`: unknown, never hidden.
 */
export function parseLogLines(raw: string[]): LogLine[] {
  let carried: LogLineSeverity | null = null;
  return raw.map((line) => {
    const match = line.match(LINE_RE);
    if (match) {
      carried = SEVERITIES[match[2].toUpperCase()] ?? null;
    }
    return { raw: line.replace(/\s+$/, ""), severity: carried };
  });
}

/**
 * Keep lines at or above `min`.
 *
 * Lines whose severity could not be read are always kept: dropping a line
 * because the parser did not recognise it would be the viewer quietly deciding
 * an operator does not need to see something.
 */
export function filterByMinSeverity(
  lines: LogLine[],
  min: "all" | LogLineSeverity,
): LogLine[] {
  if (min === "all") return lines;
  const floor = LOG_LEVEL_NAMES.indexOf(min);
  return lines.filter(
    (line) =>
      line.severity === null || LOG_LEVEL_NAMES.indexOf(line.severity) >= floor,
  );
}

/** `10 MB × 5 files` — the retention ceiling, shown but never editable. */
export function formatRetention(
  bytes: number | undefined,
  files: number | undefined,
): string | null {
  if (!bytes || !files) return null;
  const mb = Math.round(bytes / 1_000_000);
  return `${mb} MB × ${files} file${files === 1 ? "" : "s"}`;
}
