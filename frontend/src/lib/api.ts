/**
 * Comicarr API Client
 * Handles all API calls to the Comicarr backend
 */

import type { LoginResponse, LogoutResponse, SessionResponse } from "@/types";
import { isMockEnabled, mockApiResponse } from "@/lib/mockData";

const AUTH_BASE = "/api/auth";

/** Common headers for all requests — includes CSRF protection header */
const COMMON_HEADERS: Record<string, string> = {
  "X-Requested-With": "ComicarrFrontend",
};

/**
 * User-friendly error messages for common HTTP status codes
 */
const HTTP_ERROR_MESSAGES: Record<number, string> = {
  400: "The request was invalid. Please check your input and try again.",
  401: "Your session has expired. Please log in again.",
  403: "You don't have permission to perform this action.",
  404: "The requested resource was not found.",
  408: "The request timed out. Please try again.",
  429: "Too many requests. Please wait a moment and try again.",
  500: "The server encountered an error. Please try again later.",
  502: "Unable to reach the server. Please check your connection.",
  503: "The service is temporarily unavailable. Please try again later.",
  504: "The server took too long to respond. Please try again.",
};

/**
 * API Error class with user-friendly messages
 */
export class ApiError extends Error {
  status: number;
  userMessage: string;
  isRetryable: boolean;

  constructor(status: number, originalMessage?: string) {
    const userMessage =
      HTTP_ERROR_MESSAGES[status] ||
      `An unexpected error occurred (${status}). Please try again.`;

    super(originalMessage || userMessage);
    this.name = "ApiError";
    this.status = status;
    this.userMessage = userMessage;
    // 5xx errors and timeouts are typically retryable
    this.isRetryable = status >= 500 || status === 408 || status === 429;
  }
}

/**
 * Get a user-friendly error message from any error
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.userMessage;
  }
  if (error instanceof Error) {
    // Check for network errors
    if (error.message.includes("fetch") || error.message.includes("network")) {
      return "Unable to connect to the server. Please check your internet connection.";
    }
    // Check for HTTP error pattern
    const httpMatch = error.message.match(/HTTP error! status: (\d+)/);
    if (httpMatch) {
      const status = parseInt(httpMatch[1], 10);
      return HTTP_ERROR_MESSAGES[status] || error.message;
    }
    return error.message;
  }
  return "An unexpected error occurred. Please try again.";
}

/**
 * Check if an error is retryable
 */
export function isRetryableError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.isRetryable;
  }
  if (error instanceof Error) {
    const httpMatch = error.message.match(/HTTP error! status: (\d+)/);
    if (httpMatch) {
      const status = parseInt(httpMatch[1], 10);
      return status >= 500 || status === 408 || status === 429;
    }
    // Network errors are typically retryable
    if (error.message.includes("fetch") || error.message.includes("network")) {
      return true;
    }
  }
  return false;
}

/**
 * Login with username and password
 */
export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  try {
    const url = new URL(`${AUTH_BASE}/login`, window.location.origin);

    const response = await fetch(url, {
      method: "POST",
      headers: {
        ...COMMON_HEADERS,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
      credentials: "include", // Receive JWT cookie
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: LoginResponse = await response.json();
    return data;
  } catch (error) {
    console.error("Login failed:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

/**
 * Logout the current user
 */
export async function logout(): Promise<LogoutResponse> {
  try {
    const url = new URL(`${AUTH_BASE}/logout`, window.location.origin);

    const response = await fetch(url, {
      method: "POST",
      headers: COMMON_HEADERS,
      credentials: "include",
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: LogoutResponse = await response.json();
    return data;
  } catch (error) {
    console.error("Logout failed:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

/**
 * Check if user has a valid session
 */
export async function checkSession(): Promise<SessionResponse> {
  try {
    const url = new URL(`${AUTH_BASE}/check-session`, window.location.origin);

    const response = await fetch(url, {
      credentials: "include",
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: SessionResponse = await response.json();
    return data;
  } catch (error) {
    console.error("Session check failed:", error);
    return { success: true, authenticated: false };
  }
}

/**
 * Check if initial setup is needed (no credentials configured)
 */
export async function checkSetup(): Promise<{ needs_setup: boolean }> {
  try {
    const url = new URL(`${AUTH_BASE}/check-setup`, window.location.origin);
    const response = await fetch(url, {
      headers: COMMON_HEADERS,
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    console.error("Setup check failed:", error);
    return { needs_setup: false };
  }
}

/**
 * Set up initial credentials (first-run only)
 */
export async function setupCredentials(
  username: string,
  password: string,
  setupToken?: string,
): Promise<{ success: boolean; error?: string; username?: string }> {
  try {
    const url = new URL(`${AUTH_BASE}/setup`, window.location.origin);
    const body: Record<string, string> = { username, password };
    if (setupToken) {
      body.setup_token = setupToken;
    }
    const response = await fetch(url, {
      method: "POST",
      headers: {
        ...COMMON_HEADERS,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
  } catch (error) {
    console.error("Setup failed:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}

/**
 * Make a RESTful API request to FastAPI endpoints.
 *
 * All API calls go through this function. Auth is handled by
 * the JWT session cookie (credentials: "include").
 */
export async function apiRequest<T = unknown>(
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH",
  path: string,
  body?: Record<string, unknown> | null,
): Promise<T> {
  if (isMockEnabled()) {
    const mocked = mockApiResponse(method, path);
    if (mocked !== undefined) {
      return mocked as T;
    }
    // Fall through for unmocked endpoints — in mock mode the backend may
    // not be running, so most writes will 502. That's fine for browsing.
  }

  const url = new URL(path, window.location.origin);

  const options: RequestInit = {
    method,
    headers: {
      ...COMMON_HEADERS,
    },
    credentials: "include",
  };

  if (body && method !== "GET") {
    (options.headers as Record<string, string>)["Content-Type"] =
      "application/json";
    options.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(url, options);

    if (!response.ok) {
      throw new ApiError(response.status);
    }

    const data = await response.json();
    return data as T;
  } catch (error) {
    console.error("API request failed:", { method, path, error });
    throw error;
  }
}

/**
 * Get cover image URL for a Metron series (lazy loading)
 */
export async function getSeriesImage(seriesId: string): Promise<string | null> {
  try {
    const response = await apiRequest<{ image: string | null }>(
      "GET",
      `/api/metadata/series-image/${seriesId}`,
    );
    return response.image;
  } catch (error) {
    console.error("Failed to fetch series image:", error);
    return null;
  }
}
