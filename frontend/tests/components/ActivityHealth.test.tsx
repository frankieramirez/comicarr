import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ActivityPage from "@/pages/ActivityPage";
import { ago, connectionRows, jobRows, until } from "@/lib/healthRows";

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

describe("healthRows", () => {
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
