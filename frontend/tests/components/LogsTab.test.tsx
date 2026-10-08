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

const FILES = [
  {
    selector: "current",
    name: "comicarr.log",
    size: 500,
    modified: "2026-08-11T14:30:00Z",
  },
  {
    selector: "rotation-2",
    name: "comicarr.log.2",
    size: 800,
    modified: "2026-08-10T14:30:00Z",
  },
];

function stubLogs(logs: string[], level: LogLevelContext) {
  server.use(
    http.get("/api/system/logs/files", () =>
      HttpResponse.json({ files: FILES }),
    ),
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

  it("searches only on submit and combines file, component and severity on the server", async () => {
    stubLogs(LINES, UNPINNED);
    const requests: URLSearchParams[] = [];
    server.use(
      http.get("/api/system/logs", ({ request }) => {
        const params = new URL(request.url).searchParams;
        requests.push(params);
        return HttpResponse.json({
          logs: params.get("query")
            ? ["matching header [REDACTED]\n", "  whole traceback\n"]
            : LINES,
          level: UNPINNED,
          file: FILES.find((file) => file.selector === params.get("selector")),
          lines_scanned: 6001,
          records_matched: 301,
          records_returned: 200,
          truncated: true,
          record_limit: 200,
          byte_limit: 8388608,
        });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await screen.findByText(/pool open/);
    const beforeTyping = requests.length;
    await user.type(screen.getByLabelText("Search text"), "needle");
    await user.type(screen.getByLabelText("Component"), "search");
    expect(requests).toHaveLength(beforeTyping);
    await user.click(screen.getByLabelText("Log file"));
    await user.click(
      await screen.findByRole("option", { name: /comicarr.log.2/ }),
    );
    await user.click(screen.getByLabelText("Filter log lines"));
    await user.click(
      await screen.findByRole("option", { name: "Errors only" }),
    );
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText(/whole traceback/);
    await waitFor(() => expect(requests.at(-1)?.get("query")).toBe("needle"));
    const last = requests.at(-1)!;
    expect(last.get("selector")).toBe("rotation-2");
    expect(last.get("component")).toBe("search");
    expect(last.get("severity")).toBe("ERROR");
    expect(screen.getByRole("status").textContent).toContain(
      "6,001 lines scanned",
    );
    expect(screen.getByRole("status").textContent).toContain("301 matched");
    expect(screen.getByRole("status").textContent).toContain("200 returned");
    expect(screen.getByRole("status").textContent).toContain("Truncated");
    const clipboard = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(clipboard).toHaveBeenCalledWith(
      "matching header [REDACTED]\n  whole traceback",
    );
  });

  it("refreshes missing rotated files and results without losing the search", async () => {
    stubLogs(LINES, UNPINNED);
    let available = false;
    let lists = 0;
    server.use(
      http.get("/api/system/logs/files", () => {
        lists++;
        return HttpResponse.json({ files: FILES });
      }),
      http.get("/api/system/logs", () =>
        available
          ? HttpResponse.json({
              logs: ["recovered match"],
              level: UNPINNED,
              file: FILES[1],
              lines_scanned: 1,
              records_matched: 1,
              records_returned: 1,
              truncated: false,
            })
          : HttpResponse.json(
              {
                error: "The log file no longer exists. Refresh the file list.",
                code: "missing",
              },
              { status: 404 },
            ),
      ),
    );
    renderTab();
    await screen.findByText(/The log file no longer exists/);
    expect(screen.queryByText(/Nothing in/)).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Copy" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    available = true;
    const before = lists;
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh files and results" }),
    );
    await screen.findByText(/recovered match/);
    expect(lists).toBeGreaterThan(before);
  });

  it("shows no matching records separately from an empty file", async () => {
    stubLogs([], UNPINNED);
    server.use(
      http.get("/api/system/logs", () =>
        HttpResponse.json({
          logs: [],
          level: UNPINNED,
          file: FILES[0],
          lines_scanned: 6001,
          records_matched: 0,
          records_returned: 0,
          truncated: false,
        }),
      ),
    );
    renderTab();
    expect(
      await screen.findByText("No records match this search."),
    ).toBeTruthy();
  });

  it("surfaces a read failure instead of an empty console", async () => {
    stubLogs([], UNPINNED);
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
