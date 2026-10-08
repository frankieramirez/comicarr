import { describe, expect, it } from "vitest";
import {
  filterByMinSeverity,
  formatRetention,
  parseLogLines,
} from "@/lib/logLines";

/** Current formatter (comicarr/logger.py) — `name.funcName.lineno : threadName`. */
const CURRENT =
  "11-Aug-2026 14:28:01 - INFO    :: comicarr.config.read : MainThread : Config loaded";
/** Retired locale-branch formatter (#628) — still present in upgraded log files. */
const LEGACY =
  "11-Aug-2026 09:00:00 - WARNING :: MainThread : maintenance.py:backup_files:539 : No COMIC_DIR configured";

describe("parseLogLines", () => {
  it("reads the severity of the current formatter", () => {
    expect(parseLogLines([CURRENT])[0].severity).toBe("INFO");
  });

  it("reads the severity of the pre-#628 formatter in the same file", () => {
    expect(parseLogLines([LEGACY])[0].severity).toBe("WARNING");
  });

  it("carries a traceback's severity down its continuation lines", () => {
    const lines = parseLogLines([
      "11-Aug-2026 14:30:02 - ERROR   :: comicarr.search.search : Thread-5 : boom",
      "Traceback (most recent call last):",
      '  File "search.py", line 12, in run',
    ]);
    expect(lines.map((line) => line.severity)).toEqual([
      "ERROR",
      "ERROR",
      "ERROR",
    ]);
  });

  it("leaves a line with no header above it unknown rather than guessing", () => {
    expect(parseLogLines(["  orphaned continuation"])[0].severity).toBeNull();
  });

  it("maps CRITICAL onto the error band an operator would filter for", () => {
    const line =
      "11-Aug-2026 14:30:02 - CRITICAL :: comicarr.app.main : MainThread : down";
    expect(parseLogLines([line])[0].severity).toBe("ERROR");
  });

  it("preserves whitespace inside whole records for the view and Copy", () => {
    expect(parseLogLines(["  traceback detail  \n", "\n"])[0].raw).toBe(
      "  traceback detail  ",
    );
    expect(parseLogLines(["  traceback detail  \n", "\n"])[1].raw).toBe("");
  });

  it("strips the trailing newline the file carries", () => {
    expect(parseLogLines([`${CURRENT}\n`])[0].raw).toBe(CURRENT);
  });
});

describe("filterByMinSeverity", () => {
  const lines = parseLogLines([
    "11-Aug-2026 14:28:02 - DEBUG   :: comicarr.db : MainThread : pool open",
    CURRENT,
    LEGACY,
    "11-Aug-2026 14:30:02 - ERROR   :: comicarr.downloaders : Thread-5 : refused",
    "  File 'qbittorrent.py', line 12, in connect",
  ]);

  it("keeps everything under All", () => {
    expect(filterByMinSeverity(lines, "all")).toHaveLength(5);
  });

  it("drops only what sits below the floor", () => {
    const kept = filterByMinSeverity(lines, "WARNING").map((l) => l.severity);
    expect(kept).toEqual(["WARNING", "ERROR", "ERROR"]);
  });

  it("keeps a traceback body attached to the error it belongs to", () => {
    const kept = filterByMinSeverity(lines, "ERROR");
    expect(kept.map((line) => line.raw.trim())).toEqual([
      "11-Aug-2026 14:30:02 - ERROR   :: comicarr.downloaders : Thread-5 : refused",
      "File 'qbittorrent.py', line 12, in connect",
    ]);
  });

  it("never hides a line whose severity could not be read at all", () => {
    const orphan = parseLogLines([
      "a banner line written before any log record",
    ]);
    expect(filterByMinSeverity(orphan, "ERROR")).toHaveLength(1);
  });
});

describe("formatRetention", () => {
  it("renders the ceiling the way the header states it", () => {
    expect(formatRetention(10_000_000, 5)).toBe("10 MB × 5 files");
  });

  it("does not pluralise a single file", () => {
    expect(formatRetention(1_000_000, 1)).toBe("1 MB × 1 file");
  });

  it("says nothing when the config did not supply the numbers", () => {
    expect(formatRetention(undefined, 5)).toBeNull();
  });
});
