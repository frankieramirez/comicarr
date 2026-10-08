import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import PageHeader from "@/components/layout/PageHeader";
import ActivityPage from "@/pages/ActivityPage";
import AttentionPage from "@/pages/AttentionPage";
import ChatPage from "@/pages/ChatPage";
import DashboardPage from "@/pages/DashboardPage";
import DiscoverPage from "@/pages/DiscoverPage";
import ImportPage from "@/pages/ImportPage";
import IssueDetailPage from "@/pages/IssueDetailPage";
import LoginPage from "@/pages/LoginPage";
import ReleasesPage from "@/pages/ReleasesPage";
import SearchPage from "@/pages/SearchPage";
import SeriesDetailPage from "@/pages/SeriesDetailPage";
import SeriesListPage from "@/pages/SeriesListPage";
import SettingsPage from "@/pages/SettingsPage";
import StoryArcDetailPage from "@/pages/StoryArcDetailPage";
import StoryArcsPage from "@/pages/StoryArcsPage";
import WantedPage from "@/pages/WantedPage";

async function expectOneH1(name: string | RegExp) {
  await waitFor(() => {
    expect(screen.getByRole("heading", { level: 1, name })).toBeTruthy();
  });
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
}

const listPages: Array<{ name: string; ui: ReactElement }> = [
  { name: "Activity", ui: <ActivityPage /> },
  { name: "Needs attention", ui: <AttentionPage /> },
  { name: "Dashboard", ui: <DashboardPage /> },
  { name: "Discover", ui: <DiscoverPage /> },
  { name: "Import", ui: <ImportPage /> },
  { name: "Sign in", ui: <LoginPage /> },
  { name: "Releases", ui: <ReleasesPage /> },
  { name: "Search", ui: <SearchPage /> },
  {
    name: "Library",
    ui: (
      <NuqsAdapter>
        <SeriesListPage />
      </NuqsAdapter>
    ),
  },
  { name: "Settings", ui: <SettingsPage /> },
  { name: "Story Arcs", ui: <StoryArcsPage /> },
  { name: "Wanted", ui: <WantedPage /> },
];

describe("page headings", () => {
  it("renders PageHeader title as a single h1", () => {
    render(<PageHeader title="Activity" meta="in flight" />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Activity" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it.each(listPages)(
    "exposes exactly one h1 on $name",
    async ({ name, ui }) => {
      const view = render(ui);
      await expectOneH1(name);
      view.unmount();
    },
  );

  it("exposes exactly one h1 on Chat", async () => {
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: false, circuit_state: "closed" }),
      ),
    );
    const view = render(
      <Routes>
        <Route path="/chat" element={<ChatPage />} />
      </Routes>,
      { route: "/chat", useMemoryRouter: true },
    );
    await expectOneH1("Connect an AI provider");
    view.unmount();
  });

  it("exposes exactly one h1 on series detail", async () => {
    const view = render(
      <Routes>
        <Route path="/library/:comicId" element={<SeriesDetailPage />} />
      </Routes>,
      { route: "/library/1", useMemoryRouter: true },
    );
    await expectOneH1("Spider-Man");
    view.unmount();
  });

  it("keeps the series-detail error title at body size", async () => {
    server.use(
      http.get("/api/series/:comicId", () =>
        HttpResponse.json({ error: "gone" }, { status: 404 }),
      ),
    );
    const view = render(
      <Routes>
        <Route path="/library/:comicId" element={<SeriesDetailPage />} />
      </Routes>,
      { route: "/library/missing", useMemoryRouter: true },
    );
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Failed to load series",
    });
    expect(heading.className).toContain("text-sm");
    expect(heading.className).not.toContain("text-3xl");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    view.unmount();
  });

  it("exposes exactly one h1 on issue detail", async () => {
    server.use(
      http.get("/api/metadata/issue/:issueId", () =>
        HttpResponse.json({
          IssueID: "issue-1",
          ComicID: "1",
          ComicName: "Spider-Man",
          Issue_Number: "1",
          IssueName: "Issue 1",
          Status: "Wanted",
        }),
      ),
    );
    const view = render(
      <Routes>
        <Route
          path="/library/:comicId/issue/:issueId"
          element={<IssueDetailPage />}
        />
      </Routes>,
      { route: "/library/1/issue/issue-1", useMemoryRouter: true },
    );
    await expectOneH1("Issue 1");
    view.unmount();
  });

  it("exposes exactly one h1 on story-arc detail", async () => {
    server.use(
      http.get("/api/storyarcs/:storyArcId", () =>
        HttpResponse.json({
          arc: {
            StoryArcID: "arc-1",
            StoryArc: "Infinite Crisis",
            Publisher: "DC",
            Have: 1,
            Total: 2,
            percent: 50,
          },
          issues: [],
          missing: [],
        }),
      ),
    );
    const view = render(
      <Routes>
        <Route
          path="/story-arcs/:storyArcId"
          element={<StoryArcDetailPage />}
        />
      </Routes>,
      { route: "/story-arcs/arc-1", useMemoryRouter: true },
    );
    await expectOneH1("Infinite Crisis");
    view.unmount();
  });
});
