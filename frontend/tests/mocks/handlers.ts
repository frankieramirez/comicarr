/**
 * MSW request handlers for mocking API calls during tests.
 *
 * These handlers intercept network requests and return mock responses,
 * matching the new RESTful FastAPI endpoint patterns.
 */

import { http, HttpResponse } from "msw";

// =============================================================================
// Mock Data
// =============================================================================

const mockComics = [
  {
    ComicID: "1",
    ComicName: "Spider-Man",
    ComicYear: "2020",
    ComicPublisher: "Marvel",
    Status: "Active",
    Total: 50,
    Have: 25,
    LatestIssue: "50",
    LatestDate: "2024-01-15",
    ComicImage: "https://example.com/spiderman.jpg",
  },
  {
    ComicID: "2",
    ComicName: "Batman",
    ComicYear: "2019",
    ComicPublisher: "DC Comics",
    Status: "Active",
    Total: 100,
    Have: 100,
    LatestIssue: "100",
    LatestDate: "2024-01-10",
    ComicImage: "https://example.com/batman.jpg",
  },
];

const mockSearchResults = {
  results: [
    {
      comicid: "12345",
      name: "Amazing Spider-Man",
      comicyear: "2022",
      issues: 75,
      publisher: "Marvel",
      comicimage: "https://example.com/amazing-spiderman.jpg",
      description: "The amazing adventures of Spider-Man",
    },
    {
      comicid: "67890",
      name: "Spider-Man: Miles Morales",
      comicyear: "2021",
      issues: 30,
      publisher: "Marvel",
      comicimage: "https://example.com/miles.jpg",
      description: "Miles Morales takes up the Spider-Man mantle",
      in_library: true,
    },
  ],
  pagination: {
    total: 2,
    limit: 50,
    offset: 0,
    returned: 2,
  },
};

const mockIssues = [
  {
    IssueID: "101",
    ComicID: "1",
    Issue_Number: "1",
    IssueName: "First Issue",
    IssueDate: "2020-01-01",
    Status: "Downloaded",
  },
  {
    IssueID: "102",
    ComicID: "1",
    Issue_Number: "2",
    IssueName: "Second Issue",
    IssueDate: "2020-02-01",
    Status: "Wanted",
  },
];

// =============================================================================
// API Handlers — RESTful FastAPI endpoints
// =============================================================================

export const handlers = [
  // -------------------------------------------------------------------------
  // Authentication endpoints
  // -------------------------------------------------------------------------

  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as {
      username?: string;
      password?: string;
    };

    if (body.username === "testuser" && body.password === "testpass") {
      return HttpResponse.json({
        success: true,
        username: "testuser",
      });
    }

    return HttpResponse.json(
      {
        success: false,
        error: "Invalid username or password",
      },
      { status: 401 },
    );
  }),

  http.get("/api/auth/check-session", () => {
    return HttpResponse.json({
      success: true,
      authenticated: true,
      username: "testuser",
    });
  }),

  http.post("/api/auth/logout", () => {
    return HttpResponse.json({
      success: true,
    });
  }),

  http.get("/api/auth/check-setup", () => {
    return HttpResponse.json({
      success: true,
      needs_setup: false,
    });
  }),

  // -------------------------------------------------------------------------
  // Dashboard endpoints
  // -------------------------------------------------------------------------

  http.get("/api/dashboard", () => {
    return HttpResponse.json({
      recently_downloaded: [
        {
          ComicName: "Spider-Man",
          Issue_Number: "1",
          DateAdded: "2026-04-05T12:00:00",
          Status: "Snatched",
          Provider: "nzb",
          ComicID: "1",
          IssueID: "101",
          ComicImage: "https://example.com/spiderman.jpg",
        },
      ],
      upcoming_releases: [
        {
          ComicName: "Batman",
          IssueNumber: "5",
          IssueDate: "2026-04-07",
          Publisher: "DC Comics",
          ComicID: "2",
          Status: "Wanted",
        },
      ],
      stats: {
        total_series: 10,
        total_issues: 250,
        total_expected: 500,
        completion_pct: 50.0,
      },
      ai_activity: [],
      ai_configured: false,
    });
  }),

  // -------------------------------------------------------------------------
  // Series endpoints
  // -------------------------------------------------------------------------

  http.get("/api/series", () => {
    return HttpResponse.json(mockComics);
  }),

  http.get("/api/series/wanted", () => {
    return HttpResponse.json({
      issues: [
        {
          IssueID: "102",
          ComicID: "1",
          ComicName: "Spider-Man",
          Issue_Number: "2",
          IssueDate: "2020-02-01",
          Status: "Wanted",
        },
      ],
      pagination: { total: 1, limit: 50, offset: 0, returned: 1 },
    });
  }),

  http.get("/api/series/:comicId", ({ params }) => {
    const comic = mockComics.find((c) => c.ComicID === params.comicId);
    if (comic) {
      return HttpResponse.json({ comic, issues: mockIssues });
    }
    return HttpResponse.json(
      { error: "Comic not found" },
      { status: 404 },
    );
  }),

  http.delete("/api/series/:comicId", () => {
    return HttpResponse.json({ success: true });
  }),

  http.put("/api/series/:comicId/pause", () => {
    return HttpResponse.json({ success: true });
  }),

  http.put("/api/series/:comicId/resume", () => {
    return HttpResponse.json({ success: true });
  }),

  http.post("/api/series/:comicId/refresh", () => {
    return HttpResponse.json({ success: true });
  }),

  http.put("/api/series/issues/:issueId/queue", () => {
    return HttpResponse.json({ success: true });
  }),

  http.put("/api/series/issues/:issueId/unqueue", () => {
    return HttpResponse.json({ success: true });
  }),

  // -------------------------------------------------------------------------
  // Search endpoints
  // -------------------------------------------------------------------------

  http.post("/api/search/comics", async ({ request }) => {
    const body = (await request.json()) as { name?: string };
    if (!body.name || body.name.length < 3) {
      return HttpResponse.json({
        results: [],
        pagination: { total: 0, limit: 50, offset: 0, returned: 0 },
      });
    }
    return HttpResponse.json(mockSearchResults);
  }),

  http.post("/api/search/manga", async ({ request }) => {
    const body = (await request.json()) as { name?: string };
    if (!body.name || body.name.length < 3) {
      return HttpResponse.json({
        results: [],
        pagination: { total: 0, limit: 50, offset: 0, returned: 0 },
      });
    }
    return HttpResponse.json({
      results: [
        {
          comicid: "manga-1",
          name: "One Piece",
          comicyear: "1997",
          issues: 1100,
          publisher: "Shueisha",
          comicimage: "https://example.com/onepiece.jpg",
        },
      ],
      pagination: { total: 1, limit: 50, offset: 0, returned: 1 },
    });
  }),

  http.post("/api/search/add", () => {
    return HttpResponse.json({ success: true });
  }),

  http.post("/api/search/add-manga", () => {
    return HttpResponse.json({ success: true });
  }),

  http.post("/api/search/force", () => {
    return HttpResponse.json({ success: true });
  }),

  // -------------------------------------------------------------------------
  // Config endpoints
  // -------------------------------------------------------------------------

  http.get("/api/config", () => {
    return HttpResponse.json({
      http_host: "0.0.0.0",
      http_port: 8090,
      comic_dir: "/comics",
      api_enabled: true,
    });
  }),

  http.put("/api/config", () => {
    return HttpResponse.json({ success: true, message: "Configuration updated" });
  }),

  // -------------------------------------------------------------------------
  // System endpoints
  // -------------------------------------------------------------------------

  http.get("/api/system/version", () => {
    return HttpResponse.json({
      current_version: "1.0.0",
      latest_version: "1.0.0",
      commits_behind: 0,
    });
  }),

  http.get("/api/system/diagnostics", () => {
    return HttpResponse.json({
      db_empty: false,
      migration_dismissed: false,
    });
  }),

  http.post("/api/system/shutdown", () => {
    return HttpResponse.json({ success: true, message: "Shutdown initiated" });
  }),

  http.post("/api/system/restart", () => {
    return HttpResponse.json({ success: true, message: "Restart initiated" });
  }),

  // -------------------------------------------------------------------------
  // Metadata endpoints
  // -------------------------------------------------------------------------

  http.post("/api/metadata/metatag/bulk", () => {
    return HttpResponse.json({ success: true });
  }),

  http.get("/api/metadata/series-image/:seriesId", () => {
    return HttpResponse.json({ image: null });
  }),

  // -------------------------------------------------------------------------
  // Story arcs endpoints
  // -------------------------------------------------------------------------

  http.get("/api/storyarcs", () => {
    return HttpResponse.json([]);
  }),

  http.post("/api/storyarcs", () => {
    return HttpResponse.json({ success: true });
  }),

  // -------------------------------------------------------------------------
  // Migration endpoints
  // -------------------------------------------------------------------------

  http.post("/api/system/migration/preview", () => {
    return HttpResponse.json({
      valid: true,
      version: "0.7.2",
      series_count: 10,
      issue_count: 500,
      tables: [],
      config_categories: [],
      path_warnings: [],
    });
  }),

  http.post("/api/system/migration/start", () => {
    return HttpResponse.json({ status: "started" });
  }),

  http.get("/api/system/migration/progress", () => {
    return HttpResponse.json({
      status: "idle",
      current_table: "",
      tables_complete: 0,
      tables_total: 0,
      error: null,
    });
  }),
];

// =============================================================================
// Handler utilities for tests
// =============================================================================

/**
 * Create a handler that returns an error response for a specific endpoint.
 */
export function createErrorHandler(
  method: "get" | "post" | "put" | "delete",
  path: string,
  errorMessage: string,
) {
  return http[method](path, () => {
    return HttpResponse.json(
      { error: errorMessage },
      { status: 500 },
    );
  });
}

/**
 * Create a handler that returns a custom response for a specific endpoint.
 */
export function createCustomHandler<T>(
  method: "get" | "post" | "put" | "delete",
  path: string,
  data: T,
) {
  return http[method](path, () => {
    return HttpResponse.json(data);
  });
}
