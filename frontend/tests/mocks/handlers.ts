/**
 * MSW request handlers for mocking API calls during tests.
 *
 * These handlers intercept network requests and return mock responses.
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
// API Handlers
// =============================================================================

export const handlers = [
  // -------------------------------------------------------------------------
  // Authentication endpoints
  // -------------------------------------------------------------------------

  http.post("/auth/login_json", async ({ request }) => {
    // Login sends form data (application/x-www-form-urlencoded), not JSON
    const text = await request.text();
    const params = new URLSearchParams(text);
    const username = params.get("username");
    const password = params.get("password");

    if (username === "testuser" && password === "testpass") {
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
      { status: 401 }
    );
  }),

  http.get("/auth/check_session", () => {
    return HttpResponse.json({
      success: true,
      authenticated: true,
      username: "testuser",
    });
  }),

  http.get("/auth/logout", () => {
    return HttpResponse.json({
      success: true,
    });
  }),

  // -------------------------------------------------------------------------
  // API endpoints (all through /api?cmd=...)
  // -------------------------------------------------------------------------

  http.get("/api", ({ request }) => {
    const url = new URL(request.url);
    const cmd = url.searchParams.get("cmd");

    switch (cmd) {
      // Auth & API key
      case "getAPI":
        return HttpResponse.json({
          success: true,
          data: {
            apikey: "test_api_key_32_characters_long_",
            sse_key: "test_sse_key_32_characters_long__",
          },
        });

      // Comic library
      case "getIndex":
        return HttpResponse.json({
          success: true,
          data: mockComics,
        });

      case "getComic": {
        const comicId = url.searchParams.get("id");
        const comic = mockComics.find((c) => c.ComicID === comicId);
        if (comic) {
          return HttpResponse.json({
            success: true,
            data: { comic, issues: mockIssues },
          });
        }
        return HttpResponse.json(
          {
            success: false,
            error: { message: "Comic not found" },
          },
          { status: 404 }
        );
      }

      // Search
      case "findComic": {
        const query = url.searchParams.get("name");
        if (!query || query.length < 3) {
          return HttpResponse.json({
            success: true,
            data: { results: [], pagination: { total: 0 } },
          });
        }
        return HttpResponse.json({
          success: true,
          data: mockSearchResults,
        });
      }

      case "findManga": {
        const query = url.searchParams.get("name");
        if (!query || query.length < 3) {
          return HttpResponse.json({
            success: true,
            data: { results: [], pagination: { total: 0 } },
          });
        }
        return HttpResponse.json({
          success: true,
          data: {
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
          },
        });
      }

      // Add comic
      case "addComic": {
        const comicId = url.searchParams.get("id");
        return HttpResponse.json({
          success: true,
          data: { message: `Comic ${comicId} added successfully` },
        });
      }

      // Queue operations
      case "getWanted":
        return HttpResponse.json({
          success: true,
          data: [
            {
              IssueID: "102",
              ComicID: "1",
              ComicName: "Spider-Man",
              Issue_Number: "2",
              IssueDate: "2020-02-01",
              Status: "Wanted",
            },
          ],
        });

      // Configuration
      case "getConfig":
        return HttpResponse.json({
          success: true,
          data: {
            http_host: "0.0.0.0",
            http_port: 8090,
            comic_dir: "/comics",
            api_enabled: true,
          },
        });

      case "setConfig":
        return HttpResponse.json({
          success: true,
          data: { message: "Configuration updated" },
        });

      // Server-Sent Events check
      case "checkGlobalMessages":
        return HttpResponse.json({
          success: true,
          data: { messages: [] },
        });

      // Default: unknown command
      default:
        return HttpResponse.json(
          {
            success: false,
            error: { message: `Unknown command: ${cmd}` },
          },
          { status: 400 }
        );
    }
  }),

  // Handle POST requests to /api
  http.post("/api", async ({ request }) => {
    const url = new URL(request.url);
    const cmd = url.searchParams.get("cmd");

    switch (cmd) {
      case "setConfig": {
        return HttpResponse.json({
          success: true,
          data: { message: "Configuration updated" },
        });
      }

      default:
        return HttpResponse.json(
          {
            success: false,
            error: { message: `Unknown command: ${cmd}` },
          },
          { status: 400 }
        );
    }
  }),
];

// =============================================================================
// Handler utilities for tests
// =============================================================================

/**
 * Create a handler that returns an error response for a specific command.
 */
export function createErrorHandler(cmd: string, errorMessage: string) {
  return http.get("/api", ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("cmd") === cmd) {
      return HttpResponse.json(
        {
          success: false,
          error: { message: errorMessage },
        },
        { status: 500 }
      );
    }
  });
}

/**
 * Create a handler that returns a custom response for a specific command.
 */
export function createCustomHandler<T>(cmd: string, data: T) {
  return http.get("/api", ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("cmd") === cmd) {
      return HttpResponse.json({
        success: true,
        data,
      });
    }
  });
}
