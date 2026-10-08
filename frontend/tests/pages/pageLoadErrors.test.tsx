import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import SeriesDetailPage from "@/pages/SeriesDetailPage";
import IssueDetailPage from "@/pages/IssueDetailPage";
import StoryArcDetailPage from "@/pages/StoryArcDetailPage";
import StoryArcsPage from "@/pages/StoryArcsPage";
import SettingsPage from "@/pages/SettingsPage";

const seriesPayload = {
  comic: {
    ComicID: "1",
    ComicName: "Absolute Batman",
    ComicYear: "2024",
    Status: "Active",
  },
  issues: [],
  annuals: [],
};

const issuePayload = {
  IssueID: "issue-23",
  ComicID: "1",
  ComicName: "Absolute Batman",
  Issue_Number: "23",
  IssueName: "Issue 23",
  Status: "Wanted",
};

const arcPayload = {
  StoryArcID: "arc-1",
  StoryArc: "The Death of Superman",
  TotalIssues: 1,
  Have: 0,
  Total: 1,
  percent: 0,
  SpanYears: "1992",
  CV_ArcID: null,
  Publisher: "DC Comics",
  ArcImage: null,
};

function failThenSucceed(
  method: typeof http.get,
  path: string,
  success: object,
  failures = 1,
) {
  let calls = 0;
  server.use(
    method(path, () => {
      calls += 1;
      if (calls <= failures) {
        return HttpResponse.json({ detail: "unavailable" }, { status: 503 });
      }
      return HttpResponse.json(success);
    }),
  );
}

describe("page load ErrorDisplay retry", () => {
  it("retries series detail after a 503", async () => {
    const user = userEvent.setup();
    failThenSucceed(http.get, "/api/series/1", seriesPayload);
    render(
      <Routes>
        <Route path="/library/:comicId" element={<SeriesDetailPage />} />
      </Routes>,
      { route: "/library/1", useMemoryRouter: true },
    );

    expect(await screen.findByRole("button", { name: "Try Again" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("Absolute Batman")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull();
  });

  it("shows series not-found without retry on 404", async () => {
    server.use(
      http.get("/api/series/missing", () =>
        HttpResponse.json({ detail: "not found" }, { status: 404 }),
      ),
    );
    render(
      <Routes>
        <Route path="/library/:comicId" element={<SeriesDetailPage />} />
      </Routes>,
      { route: "/library/missing", useMemoryRouter: true },
    );
    expect(await screen.findByText("Series not found")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull();
  });

  it("retries issue detail after a 503", async () => {
    const user = userEvent.setup();
    failThenSucceed(http.get, "/api/metadata/issue/issue-23", issuePayload);
    server.use(
      http.get("/api/series/1", () => HttpResponse.json(seriesPayload)),
    );
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      { route: "/library/1/issue/issue-23", useMemoryRouter: true },
    );

    expect(await screen.findByRole("button", { name: "Try Again" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByTestId("issue-detail-title")).toBeTruthy();
  });

  it("shows issue not-found without retry on 404", async () => {
    server.use(
      http.get("/api/metadata/issue/missing", () =>
        HttpResponse.json({ detail: "No issue found" }, { status: 404 }),
      ),
    );
    render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      { route: "/library/1/issue/missing", useMemoryRouter: true },
    );
    expect(await screen.findByText("Issue not found")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull();
  });

  it("retries story arc detail after a 503", async () => {
    const user = userEvent.setup();
    failThenSucceed(http.get, "/api/storyarcs/arc-1", {
      arc: arcPayload,
      issues: [],
      missing: [],
    });
    render(
      <Routes>
        <Route
          path="/story-arcs/:storyArcId"
          element={<StoryArcDetailPage />}
        />
      </Routes>,
      { route: "/story-arcs/arc-1", useMemoryRouter: true },
    );

    expect(await screen.findByRole("button", { name: "Try Again" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("The Death of Superman")).toBeTruthy();
  });

  it("shows story arc not-found without retry on 404", async () => {
    server.use(
      http.get("/api/storyarcs/missing", () =>
        HttpResponse.json({ detail: "not found" }, { status: 404 }),
      ),
    );
    render(
      <Routes>
        <Route
          path="/story-arcs/:storyArcId"
          element={<StoryArcDetailPage />}
        />
      </Routes>,
      { route: "/story-arcs/missing", useMemoryRouter: true },
    );
    expect(await screen.findByText("Story arc not found")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull();
  });

  it("retries the story arcs list after a 503", async () => {
    const user = userEvent.setup();
    failThenSucceed(http.get, "/api/storyarcs", [arcPayload]);
    render(<StoryArcsPage />);

    expect(await screen.findByRole("button", { name: "Try Again" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("The Death of Superman")).toBeTruthy();
  });

  it("retries settings after a 503", async () => {
    const user = userEvent.setup();
    failThenSucceed(
      http.get,
      "/api/config",
      { http_host: "0.0.0.0", http_port: 8090, comic_dir: "/comics" },
      2,
    );
    render(<SettingsPage />);

    expect(await screen.findByRole("button", { name: "Try Again" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("Settings")).toBeTruthy();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Try Again" })).toBeNull(),
    );
  });
});
