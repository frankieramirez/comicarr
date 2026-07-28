import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import ActivityPage from "@/pages/ActivityPage";

const queueItem = {
  ID: "queue-1",
  series: "Absolute Flash",
  year: "2026",
  filename: "Absolute Flash 013.cbz",
  size: "10 MB",
  issueid: "issue-13",
  comicid: "comic-1",
  link: "",
  status: "Downloading",
  remote_filesize: "10 MB",
  updated_date: "2026-07-10 08:40",
  site: "DDL(GetComics)",
  submit_date: "2026-07-10 08:35",
};

describe("ActivityPage", () => {
  it("labels terminal and manual-review queue rows truthfully and only retries failed DDL work after confirmation", async () => {
    const queueRows = [
      {
        ...queueItem,
        ID: "failed-ddl",
        series: "Failed Series",
        status: "Failed",
      },
      {
        ...queueItem,
        ID: "unknown-ddl",
        series: "Unknown Series",
        status: "Unknown",
      },
      {
        ...queueItem,
        ID: "manual-ddl",
        series: "Manual Series",
        status: "manual_review",
      },
      {
        ...queueItem,
        ID: "active-ddl",
        series: "Active Series",
        status: "Downloading",
      },
    ];
    const confirm = vi.fn(() => true);
    let requeueCalls = 0;
    vi.stubGlobal("confirm", confirm);
    server.use(
      http.get("/api/downloads/queue", () =>
        HttpResponse.json({
          queue: queueRows,
          pagination: { total: 4, limit: 25, offset: 0, has_more: false },
        }),
      ),
      http.post("/api/downloads/failed-ddl/requeue", () => {
        requeueCalls += 1;
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();
    render(<ActivityPage />, { route: "/activity", useMemoryRouter: true });

    await screen.findByText("Failed Series");
    expect(screen.getByLabelText(/failed: terminal/i)).toBeTruthy();
    expect(
      screen.getByLabelText(/unknown: manual review required/i),
    ).toBeTruthy();
    expect(
      screen.getByLabelText(/manual review: requires attention/i),
    ).toBeTruthy();
    expect(screen.getByLabelText(/downloading: active/i)).toBeTruthy();

    expect(
      screen.queryByRole("button", { name: /requeue unknown series/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /requeue manual series/i }),
    ).toBeNull();

    await user.click(
      screen.getByRole("button", { name: /requeue failed series/i }),
    );

    expect(confirm).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(requeueCalls).toBe(1);
    });
    expect(await screen.findByText("Direct download requeued.")).toBeTruthy();
  });

  /**
   * The server-paginated model gets no page reset from TanStack:
   * `autoResetPageIndex` is inert under `manualPagination` (#360), so this
   * invariant has no owner but the caller. It was hand-rolled inside
   * `useActivityTableState`, which #393 deleted, and nothing else pinned it —
   * a reset that quietly stopped happening would leave a user on page 3 of a
   * result set that no longer has one.
   */
  it("returns to the first page when the sort or the filter changes", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/downloads/queue", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const offset = Number(url.searchParams.get("offset") || 0);
        return HttpResponse.json({
          queue: [{ ...queueItem, ID: `queue-${offset}` }],
          pagination: { total: 90, limit: 25, offset, has_more: true },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, { route: "/activity", useMemoryRouter: true });
    await screen.findByText("Absolute Flash");

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("25");
    });

    await user.click(screen.getByRole("button", { name: /Updated/ }));
    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("order")).toBe("asc");
      expect(last?.searchParams.get("offset")).toBe("0");
    });

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("25");
    });

    await user.type(
      screen.getByRole("textbox", { name: "Filter queue activity" }),
      "flash",
    );
    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("q")).toBe("flash");
      expect(last?.searchParams.get("offset")).toBe("0");
    });
  });

  it("filters, sorts, and paginates the live queue through the API", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/downloads/queue", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const offset = Number(url.searchParams.get("offset") || 0);
        return HttpResponse.json({
          queue: offset === 0 ? [queueItem] : [],
          pagination: {
            total: offset === 0 ? 30 : 20,
            limit: 25,
            offset,
            has_more: offset === 0,
          },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, { route: "/activity", useMemoryRouter: true });

    await screen.findByText("Absolute Flash");
    await user.type(
      screen.getByRole("textbox", { name: "Filter queue activity" }),
      "flash",
    );
    await waitFor(() => {
      expect(
        requests.some((url) => url.searchParams.get("q") === "flash"),
      ).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: /Updated/ }));
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.searchParams.get("sort") === "updated" &&
            url.searchParams.get("order") === "asc",
        ),
      ).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(
        requests.some((url) => url.searchParams.get("offset") === "25"),
      ).toBe(true);
    });
    expect(await screen.findByText("No matching queue items")).toBeTruthy();
    expect(screen.queryByText(/Showing \d+ to \d+ of/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("0");
    });
  });

  it("uses the shared table for history with newest-first defaults", async () => {
    let historyRequest: URL | undefined;
    server.use(
      http.get("/api/downloads/history", ({ request }) => {
        historyRequest = new URL(request.url);
        return HttpResponse.json({
          history: [
            {
              IssueID: "issue-13",
              ComicName: "Absolute Flash",
              Issue_Number: "13",
              Size: 0,
              DateAdded: "2026-07-10 08:40:00",
              Status: "Post-Processed",
              FolderName: "",
              ComicID: "comic-1",
              Provider: "NZBGeek",
            },
          ],
          pagination: { total: 1, limit: 25, offset: 0, has_more: false },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, {
      route: "/activity?view=history",
      useMemoryRouter: true,
    });

    await screen.findByText("Absolute Flash");
    expect(historyRequest?.searchParams.get("sort")).toBe("date");
    expect(historyRequest?.searchParams.get("order")).toBe("desc");
    expect(screen.getByRole("button", { name: /Date/ })).toBeTruthy();
    await user.type(
      screen.getByRole("textbox", { name: "Filter download history" }),
      "nzb",
    );
    await waitFor(() => {
      expect(historyRequest?.searchParams.get("q")).toBe("nzb");
    });
  });
});
