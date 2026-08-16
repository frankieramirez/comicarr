import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import { LogsTab } from "@/components/settings/LogsTab";
import type { LogLevelContext } from "@/hooks/useLogs";

const UNPINNED: LogLevelContext = {
  effective: 1,
  effective_name: "info",
  saved: 1,
  saved_name: "info",
  restart_level: 1,
  restart_name: "info",
  restart_source: "the config file",
  pinned: false,
};

const PINNED: LogLevelContext = {
  effective: 0,
  effective_name: "warning",
  saved: 0,
  saved_name: "warning",
  restart_level: 2,
  restart_name: "debug",
  restart_source: "the COMICARR_LOG_LEVEL environment variable",
  pinned: true,
};

const LINES = [
  "11-Aug-2026 14:28:02 - DEBUG   :: comicarr.db : MainThread : pool open",
  "11-Aug-2026 14:29:14 - WARNING :: comicarr.search : Thread-3 : indexer empty",
  "11-Aug-2026 14:30:02 - ERROR   :: comicarr.downloaders : Thread-5 : refused",
];

function stubLogs(logs: string[], level: LogLevelContext) {
  server.use(
    http.get("/api/system/logs", () =>
      HttpResponse.json({
        logs,
        level,
        requested: 200,
        path: "/config/logs/comicarr.log",
      }),
    ),
  );
}

function renderTab(overrides: { log_level?: number } = {}) {
  const onChange = vi.fn();
  render(
    <LogsTab
      config={{
        log_level: overrides.log_level ?? 1,
        log_dir: "/config/logs",
        max_logsize: 10_000_000,
        max_logfiles: 5,
      }}
      formData={{}}
      onChange={onChange}
    />,
  );
  return { onChange };
}

describe("LogsTab", () => {
  it("shows the retention ceiling and log directory as context", async () => {
    stubLogs(LINES, UNPINNED);
    renderTab();

    expect(await screen.findByText(/keeps 10 MB × 5 files/)).toBeTruthy();
    expect(screen.getByText("/config/logs")).toBeTruthy();
  });

  it("renders the returned lines verbatim", async () => {
    stubLogs(LINES, UNPINNED);
    renderTab();

    await waitFor(() => expect(screen.getByText(/pool open/)).toBeTruthy());
    expect(screen.getByText(/refused/)).toBeTruthy();
  });

  it("wraps long log lines instead of forcing horizontal scroll", async () => {
    const unbrokenToken = `/config/cache/${"a".repeat(200)}.cbz`;
    stubLogs(
      [
        ...LINES,
        `11-Aug-2026 14:31:40 - DEBUG   :: comicarr.postprocessor : Thread-7 : scanned ${unbrokenToken}`,
      ],
      UNPINNED,
    );
    renderTab();

    const consoleBox = await screen.findByText(/pool open/);
    const pre = consoleBox.closest("pre");
    expect(pre?.textContent).toContain(unbrokenToken);
    expect(pre?.className).toContain("whitespace-pre-wrap");
    expect(pre?.className).toContain("break-words");
  });

  it("says nothing extra when the config file is the top of the chain", async () => {
    stubLogs(LINES, UNPINNED);
    renderTab();

    await waitFor(() => expect(screen.getByText(/pool open/)).toBeTruthy());
    expect(screen.queryByText(/next restart/i)).toBeNull();
  });

  it("names the pinning source and both levels when one outranks the dial", async () => {
    stubLogs(LINES, PINNED);
    renderTab({ log_level: 0 });

    expect(
      await screen.findByText(
        /the COMICARR_LOG_LEVEL environment variable sets the log level, not this page/i,
      ),
    ).toBeTruthy();
    const callout = screen.getByText(/On the next restart it returns to/);
    expect(callout.textContent).toContain("0 (warning)");
    expect(callout.textContent).toContain("2 (debug)");
  });

  it("tells an operator which level produced an empty file", async () => {
    stubLogs([], UNPINNED);
    renderTab();

    expect(
      await screen.findByText(
        /Nothing in comicarr\.log yet\. Comicarr is logging at 1 \(info\)/,
      ),
    ).toBeTruthy();
  });

  it("reports the level change through the shared settings save path", async () => {
    stubLogs(LINES, UNPINNED);
    const { onChange } = renderTab();
    await waitFor(() => expect(screen.getByText(/pool open/)).toBeTruthy());

    await userEvent.click(screen.getByLabelText("Log level"));
    await userEvent.click(
      await screen.findByText(/2 · Debug — everything, including diagnostics/),
    );

    expect(onChange).toHaveBeenCalledWith("log_level", 2);
  });

  it("surfaces a read failure instead of an empty console", async () => {
    server.use(
      http.get("/api/system/logs", () =>
        HttpResponse.json({
          logs: [],
          level: UNPINNED,
          requested: 200,
          path: "/config/logs/comicarr.log",
          error: "Permission denied",
        }),
      ),
    );
    renderTab();

    expect(await screen.findByText(/Permission denied/)).toBeTruthy();
  });
});
