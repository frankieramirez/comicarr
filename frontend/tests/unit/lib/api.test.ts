/**
 * Unit tests for src/lib/api.ts
 *
 * Tests the API client functions, error handling, and utility functions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "../../mocks/server";
import { http, HttpResponse } from "msw";
import {
  apiCall,
  login,
  logout,
  checkSession,
  ApiError,
  getErrorMessage,
  isRetryableError,
} from "@/lib/api";

describe("API Client", () => {
  beforeEach(() => {
    // Clear sessionStorage before each test
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  // ===========================================================================
  // ApiError class
  // ===========================================================================

  describe("ApiError", () => {
    it("should create error with user-friendly message for known status codes", () => {
      const error = new ApiError(401);
      expect(error.status).toBe(401);
      expect(error.userMessage).toContain("session has expired");
      expect(error.isRetryable).toBe(false);
    });

    it("should mark 5xx errors as retryable", () => {
      const error500 = new ApiError(500);
      expect(error500.isRetryable).toBe(true);

      const error503 = new ApiError(503);
      expect(error503.isRetryable).toBe(true);
    });

    it("should mark 408 (timeout) and 429 (rate limit) as retryable", () => {
      expect(new ApiError(408).isRetryable).toBe(true);
      expect(new ApiError(429).isRetryable).toBe(true);
    });

    it("should not mark 4xx client errors as retryable", () => {
      expect(new ApiError(400).isRetryable).toBe(false);
      expect(new ApiError(403).isRetryable).toBe(false);
      expect(new ApiError(404).isRetryable).toBe(false);
    });

    it("should handle unknown status codes", () => {
      const error = new ApiError(418); // I'm a teapot
      expect(error.userMessage).toContain("unexpected error");
      expect(error.userMessage).toContain("418");
    });
  });

  // ===========================================================================
  // getErrorMessage utility
  // ===========================================================================

  describe("getErrorMessage", () => {
    it("should return userMessage from ApiError", () => {
      const error = new ApiError(401);
      expect(getErrorMessage(error)).toBe(error.userMessage);
    });

    it("should detect network errors", () => {
      const error = new Error("Failed to fetch");
      expect(getErrorMessage(error)).toContain("internet connection");
    });

    it("should parse HTTP error pattern from message", () => {
      const error = new Error("HTTP error! status: 404");
      expect(getErrorMessage(error)).toContain("not found");
    });

    it("should return generic message for unknown errors", () => {
      expect(getErrorMessage("string error")).toContain("unexpected error");
      expect(getErrorMessage(null)).toContain("unexpected error");
      expect(getErrorMessage(undefined)).toContain("unexpected error");
    });

    it("should return error message for standard errors", () => {
      const error = new Error("Custom error message");
      expect(getErrorMessage(error)).toBe("Custom error message");
    });
  });

  // ===========================================================================
  // isRetryableError utility
  // ===========================================================================

  describe("isRetryableError", () => {
    it("should return true for ApiError with isRetryable=true", () => {
      expect(isRetryableError(new ApiError(500))).toBe(true);
    });

    it("should return false for ApiError with isRetryable=false", () => {
      expect(isRetryableError(new ApiError(400))).toBe(false);
    });

    it("should detect retryable HTTP errors from message", () => {
      expect(isRetryableError(new Error("HTTP error! status: 500"))).toBe(true);
      expect(isRetryableError(new Error("HTTP error! status: 400"))).toBe(false);
    });

    it("should consider network errors retryable", () => {
      expect(isRetryableError(new Error("Failed to fetch"))).toBe(true);
      expect(isRetryableError(new Error("network error"))).toBe(true);
    });

    it("should return false for unknown error types", () => {
      expect(isRetryableError("string error")).toBe(false);
      expect(isRetryableError(null)).toBe(false);
    });
  });

  // ===========================================================================
  // apiCall function
  // ===========================================================================

  describe("apiCall", () => {
    it("should make GET request with cmd parameter", async () => {
      const result = await apiCall<{ comics: unknown[] }>("getIndex");
      expect(result).toBeDefined();
    });

    it("should include API key from sessionStorage", async () => {
      sessionStorage.setItem("mylar_api_key", "test_api_key_123");

      // Use a custom handler to verify the apikey parameter
      let capturedUrl: URL | null = null;
      server.use(
        http.get("/api", ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ success: true, data: {} });
        })
      );

      await apiCall("getIndex");

      expect(capturedUrl).not.toBeNull();
      expect(capturedUrl!.searchParams.get("apikey")).toBe("test_api_key_123");
    });

    it("should not include API key for getAPI command", async () => {
      sessionStorage.setItem("mylar_api_key", "test_api_key_123");

      let capturedUrl: URL | null = null;
      server.use(
        http.get("/api", ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({
            success: true,
            data: { apikey: "new_key", sse_key: "sse_key" },
          });
        })
      );

      await apiCall("getAPI", { username: "test", password: "test" });

      expect(capturedUrl).not.toBeNull();
      expect(capturedUrl!.searchParams.get("apikey")).toBeNull();
    });

    it("should pass additional parameters", async () => {
      let capturedUrl: URL | null = null;
      server.use(
        http.get("/api", ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ success: true, data: { results: [] } });
        })
      );

      await apiCall("findComic", { name: "Spider-Man", page: 1 });

      expect(capturedUrl).not.toBeNull();
      expect(capturedUrl!.searchParams.get("name")).toBe("Spider-Man");
      expect(capturedUrl!.searchParams.get("page")).toBe("1");
    });

    it("should throw ApiError on non-OK response", async () => {
      server.use(
        http.get("/api", () => {
          return new HttpResponse(null, { status: 500 });
        })
      );

      await expect(apiCall("getIndex")).rejects.toThrow(ApiError);
    });

    it("should throw error when API returns success=false", async () => {
      server.use(
        http.get("/api", () => {
          return HttpResponse.json({
            success: false,
            error: { message: "Something went wrong" },
          });
        })
      );

      await expect(apiCall("getIndex")).rejects.toThrow("Something went wrong");
    });

    it("should handle null/undefined parameters gracefully", async () => {
      let capturedUrl: URL | null = null;
      server.use(
        http.get("/api", ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ success: true, data: {} });
        })
      );

      await apiCall("getIndex", { name: undefined, id: null });

      expect(capturedUrl).not.toBeNull();
      expect(capturedUrl!.searchParams.has("name")).toBe(false);
      expect(capturedUrl!.searchParams.has("id")).toBe(false);
    });
  });

  // ===========================================================================
  // login function
  // ===========================================================================

  describe("login", () => {
    it("should return success for valid credentials", async () => {
      const result = await login("testuser", "testpass");
      expect(result.success).toBe(true);
      expect(result.username).toBe("testuser");
    });

    it("should return error for invalid credentials", async () => {
      const result = await login("wronguser", "wrongpass");
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it("should handle network errors gracefully", async () => {
      server.use(
        http.post("/auth/login_json", () => {
          return HttpResponse.error();
        })
      );

      const result = await login("testuser", "testpass");
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });
  });

  // ===========================================================================
  // logout function
  // ===========================================================================

  describe("logout", () => {
    it("should call logout endpoint", async () => {
      server.use(
        http.post("/auth/logout_json", () => {
          return HttpResponse.json({ success: true });
        })
      );

      const result = await logout();
      expect(result.success).toBe(true);
    });

    it("should handle errors gracefully", async () => {
      server.use(
        http.post("/auth/logout_json", () => {
          return HttpResponse.error();
        })
      );

      const result = await logout();
      expect(result.success).toBe(false);
    });
  });

  // ===========================================================================
  // checkSession function
  // ===========================================================================

  describe("checkSession", () => {
    it("should return authenticated=true for valid session", async () => {
      const result = await checkSession();
      expect(result.authenticated).toBe(true);
      expect(result.username).toBe("testuser");
    });

    it("should return authenticated=false on error", async () => {
      server.use(
        http.get("/auth/check_session", () => {
          return HttpResponse.error();
        })
      );

      const result = await checkSession();
      expect(result.authenticated).toBe(false);
    });
  });
});
