import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes, Navigate, useLocation } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import IssueDetailPage from "@/pages/IssueDetailPage";
import SeriesDetailPage from "@/pages/SeriesDetailPage";

const issuePayload = {
  IssueID: "issue-23",
  ComicID: "series-9",
  ComicName: "Absolute Batman",
  Issue_Number: "23",
  IssueName: "Issue 23",
  IssueDate: "2025-11-01",
  ReleaseDate: "2025-11-05",
  Status: "Wanted",
  Location: "/library/comics/absolute-batman/023.cbz",
};

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

/** Minimal protected-shell route tree matching App.tsx path ranking. */
function LibraryRoutes() {
  return (
    <Routes>
      <Route path="/" element={<div>Dashboard</div>} />
      <Route path="/library" element={<div>Library list</div>} />
      <Route
        path="/library/:comicId/issue/:issueId"
        element={<IssueDetailPage />}
      />
      <Route path="/library/:comicId" element={<SeriesDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

describe("IssueDetailPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/metadata/issue/:issueId", ({ params }) => {
        if (params.issueId === "issue-23") {
          return HttpResponse.json(issuePayload);
        }
        if (params.issueId === "other-series-issue") {
          return HttpResponse.json({
            ...issuePayload,
            IssueID: "other-series-issue",
            ComicID: "other-series",
          });
        }
        return HttpResponse.json(
          { detail: "No issue found with ID: missing" },
          { status: 404 },
        );
      }),
      http.get("/api/series/series-9", () =>
        HttpResponse.json({
          comic: {
            ComicID: "series-9",
            ComicName: "Absolute Batman",
            ComicYear: "2024",
            Status: "Active",
          },
          issues: [issuePayload],
          annuals: [],
        }),
      ),
    );
  });

  it("loads issue detail from the route series and issue identifiers", async () => {
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      {
        route: "/library/series-9/issue/issue-23",
        useMemoryRouter: true,
      },
    );

    expect((await screen.findByTestId("issue-detail-title")).textContent).toBe(
      "Issue 23",
    );
    expect(screen.getByTestId("issue-detail-ids").textContent).toBe(
      "series:series-9 · issue:issue-23",
    );
    expect(screen.getAllByText("Wanted").length).toBeGreaterThan(0);
    expect(screen.getByText("2025-11-05")).toBeTruthy();
    expect(
      screen.getByText("/library/comics/absolute-batman/023.cbz"),
    ).toBeTruthy();
    const seriesLinks = screen.getAllByRole("link", {
      name: "Absolute Batman",
    });
    expect(seriesLinks.length).toBeGreaterThan(0);
    expect(
      seriesLinks.every(
        (link) => link.getAttribute("href") === "/library/series-9",
      ),
    ).toBe(true);

    const activityLink = screen.getByRole("link", {
      name: "View activity for this issue",
    });
    expect(activityLink.getAttribute("href")).toBe(
      "/activity?scope_type=issue&scope_id=issue-23",
    );
  });

  it("shows a clear not-found state for unknown issue ids", async () => {
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      {
        route: "/library/series-9/issue/missing",
        useMemoryRouter: true,
      },
    );

    expect(await screen.findByText("Issue not found")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Back to series" }).getAttribute("href"),
    ).toBe("/library/series-9");
  });

  it("rejects issues that do not belong to the series in the URL", async () => {
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      {
        route: "/library/series-9/issue/other-series-issue",
        useMemoryRouter: true,
      },
    );

    expect(await screen.findByText("Issue not found")).toBeTruthy();
    expect(
      await screen.findByText("Issue not found for this series"),
    ).toBeTruthy();
  });

  it("sets the issue status from the badge menu", async () => {
    const calls: { issueId: string; body: unknown }[] = [];
    server.use(
      http.put(
        "/api/series/issues/:issueId/status",
        async ({ params, request }) => {
          calls.push({
            issueId: String(params.issueId),
            body: await request.json(),
          });
          return HttpResponse.json({ success: true, entity_type: "issue" });
        },
      ),
    );
    const user = userEvent.setup();
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      {
        route: "/library/series-9/issue/issue-23",
        useMemoryRouter: true,
      },
    );

    await screen.findByTestId("issue-detail-title");
    await user.click(
      screen.getByRole("button", { name: "Change status for Issue 23" }),
    );
    await user.click(await screen.findByRole("menuitem", { name: "Skipped" }));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      issueId: "issue-23",
      body: { status: "Skipped" },
    });
  });
});

describe("series issue link routing", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/metadata/issue/:issueId", ({ params }) => {
        if (params.issueId === "issue-23") {
          return HttpResponse.json(issuePayload);
        }
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
      http.get("/api/series/series-9", () =>
        HttpResponse.json({
          comic: {
            ComicID: "series-9",
            ComicName: "Absolute Batman",
            ComicYear: "2024",
            ComicPublisher: "DC Comics",
            Status: "Active",
            Have: 1,
            Total: 2,
          },
          issues: [
            {
              ...issuePayload,
              displayState: "Wanted",
              missing: true,
              monitored: true,
            },
          ],
          annuals: [],
          summary: {
            total: 1,
            issues: 1,
            annuals: 0,
            owned: 0,
            missing: 1,
            monitored: 1,
            completionPercent: 0,
          },
        }),
      ),
    );
  });

  it("propagates series row identifiers into the issue detail path", async () => {
    render(
      <>
        <LocationProbe />
        <LibraryRoutes />
      </>,
      {
        route: "/library/series-9",
        useMemoryRouter: true,
      },
    );

    const issueLink = await screen.findByRole("link", { name: "Issue 23" });
    expect(issueLink.getAttribute("href")).toBe(
      "/library/series-9/issue/issue-23",
    );
  });

  it("opens issue detail instead of redirecting to the Dashboard", async () => {
    render(
      <>
        <LocationProbe />
        <LibraryRoutes />
      </>,
      {
        route: "/library/series-9/issue/issue-23",
        useMemoryRouter: true,
      },
    );

    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe(
        "/library/series-9/issue/issue-23",
      );
    });
    expect(screen.queryByText("Dashboard")).toBeNull();
    expect((await screen.findByTestId("issue-detail-title")).textContent).toBe(
      "Issue 23",
    );
  });
});
