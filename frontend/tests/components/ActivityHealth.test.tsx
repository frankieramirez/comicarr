import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ActivityPage from "@/pages/ActivityPage";
import {
  ago,
  connectionRows,
  jobRows,
  responseLabel,
  until,
} from "@/lib/healthRows";

const now = Math.floor(Date.now() / 1000);

const job = (
  id: string,
  name: string,
  extra: Record<string, unknown> = {},
) => ({
  id,
  name,
  next_run_time: new Date((now + 3600) * 1000).toISOString(),
  status: "Waiting",
  state: "waiting",
  dispatch: {
    state: "waiting",
    last_attempt: now - 600,
    last_success: now - 600,
    last_failure: null,
    last_error: null,
  },
  ...extra,
});

const failingMonitor = job("monitor", "Folder Monitor", {
  status: "Error",
  state: "error",
  dispatch: {
    state: "error",
    last_attempt: now - 60,
    last_success: now - 86400,
    last_failure: now - 60,
    last_error: "Folder not found: /downloads",
  },
});

describe("Activity > Health", () => {
  it("lists failing jobs first, counts them on the tab, and runs one now", async () => {
    const ran: string[] = [];
    server.use(
      http.get("/api/system/jobs", () =>
        HttpResponse.json({
          jobs: [job("rss", "RSS Feeds"), failingMonitor],
        }),
      ),
      http.post("/api/system/jobs/:id/run", ({ params }) => {
        ran.push(String(params.id));
        return HttpResponse.json({ accepted: true, state: "queued" });
      }),
    );
    const user = userEvent.setup();
    render(<ActivityPage />, {
      useMemoryRouter: true,
      route: "/activity?view=health",
    });

    const rows = await screen.findAllByTestId("health-job");
    expect(rows[0].textContent).toContain("Folder monitor");
    expect(rows[0].textContent).toContain("Folder not found: /downloads");
    expect(rows[1].textContent).toContain("RSS check");
    expect(screen.getByText("1 of 2 failing")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Health/ }).textContent,
    ).toContain("1 failing");

    await user.click(screen.getByRole("button", { name: "Run RSS check now" }));
    expect(
      await screen.findByText("RSS check will run in a moment."),
    ).toBeTruthy();
    expect(ran).toEqual(["rss"]);
  });

  it("shows connections from route health", async () => {
    server.use(
      http.get("/api/search/health", () =>
        HttpResponse.json({
          routes: {
            nzb: {
              configured: true,
              ready: true,
              downstream: "sabnzbd",
              last_attempt: now - 120,
              providers: [
                {
                  name: "a",
                  kind: "newznab",
                  blocked: false,
                  attempted: true,
                  last_attempt: now - 120,
                },
                {
                  name: "b",
                  kind: "newznab",
                  blocked: true,
                  attempted: true,
                  last_attempt: now - 300,
                },
              ],
            },
            torrent: { configured: false },
          },
        }),
      ),
    );
    render(<ActivityPage />, {
      useMemoryRouter: true,
      route: "/activity?view=health",
    });

    const rows = await screen.findAllByTestId("health-connection");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("SABnzbd"),
      expect.stringContaining("Indexers, 1 of 2"),
    ]);
    expect(rows[1].textContent).toContain("1 paused after errors");
  });
});

describe("Activity > Health connections", () => {
  it("shows response times and tests one connection", async () => {
    const tested: string[] = [];
    const check = (key: string, extra: Record<string, unknown> = {}) => ({
      key,
      label: key === "sabnzbd" ? "SABnzbd" : "ComicVine",
      kind: key === "sabnzbd" ? "client" : "metadata",
      route: key === "sabnzbd" ? "nzb" : null,
      checked_at: now - 60,
      ok: true,
      result: "Reachable",
      latency_ms: 42.4,
      latency_label: null,
      version: null,
      active: null,
      ...extra,
    });
    server.use(
      http.get("/api/system/connections", () =>
        HttpResponse.json({
          connections: [
            check("sabnzbd"),
            check("comicvine", { checked_at: null, ok: null, result: null }),
          ],
        }),
      ),
      http.post("/api/system/connections/:key/test", ({ params }) => {
        tested.push(String(params.key));
        return HttpResponse.json(
          check(String(params.key), { latency_ms: 210, checked_at: now }),
        );
      }),
    );
    const user = userEvent.setup();
    render(<ActivityPage />, {
      useMemoryRouter: true,
      route: "/activity?view=health",
    });

    const rows = await screen.findAllByTestId("health-connection");
    const cv = () =>
      screen
        .getAllByTestId("health-connection")
        .find((row) => row.textContent?.includes("ComicVine"))!;
    expect(rows[0].textContent).toContain("42 ms");
    expect(cv().textContent).toContain("Not checked yet");

    await user.click(screen.getByRole("button", { name: "Test ComicVine" }));
    expect(tested).toEqual(["comicvine"]);
    await screen.findByText("210 ms");
    expect(cv().textContent).toContain("Reachable");
  });

  it("shows what each job did last time", async () => {
    server.use(
      http.get("/api/system/jobs", () =>
        HttpResponse.json({
          jobs: [
            job("search", "Auto-Search", {
              result: "1 grabbed of 40 searched",
            }),
          ],
        }),
      ),
    );
    render(<ActivityPage />, {
      useMemoryRouter: true,
      route: "/activity?view=health",
    });
    const [row] = await screen.findAllByTestId("health-job");
    expect(row.textContent).toContain("1 grabbed of 40 searched");
  });
});

describe("healthRows", () => {
  it("labels latency the way the design does", () => {
    expect(responseLabel(undefined)).toBe("—");
    expect(responseLabel({ latency_ms: 118.2, latency_label: "median" })).toBe(
      "118 ms median",
    );
    expect(responseLabel({ latency_ms: null, latency_label: "local" })).toBe(
      "local",
    );
  });

  it("treats a failure newer than the last success as failing", () => {
    const [row] = jobRows([failingMonitor]);
    expect(row).toMatchObject({ failing: true, tone: "fail", runnable: true });
  });

  it("does not offer Run now for a paused or housekeeping job", () => {
    const rows = jobRows([
      job("rss", "RSS Feeds", { next_run_time: null }),
      job("ledger_retention", "Ledger Retention"),
    ]);
    expect(rows.every((row) => !row.runnable)).toBe(true);
  });

  it("leaves out routes that aren't configured", () => {
    expect(connectionRows({ routes: { ddl: { configured: false } } })).toEqual(
      [],
    );
  });

  it("says when in plain words", () => {
    const at = Date.UTC(2026, 0, 1, 12);
    expect(ago(new Date(at - 6 * 3_600_000), at)).toBe("6h ago");
    expect(until(new Date(at + 8 * 60_000), at)).toBe("in 8m");
    expect(until(null, at)).toBe("paused");
  });
});
