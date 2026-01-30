/**
 * Mylar4 API Client
 * Handles all API calls to the Mylar4 backend
 */

import type {
  ApiParams,
  LoginResponse,
  LogoutResponse,
  SessionResponse,
} from "@/types";

const API_BASE = "/api";
const AUTH_BASE = "/auth";

interface ApiResponseData {
  success?: boolean;
  data?: unknown;
  error?: {
    message?: string;
  };
}

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
 * Make an API call to Mylar4
 */
export async function apiCall<T = unknown>(
  cmd: string,
  params: ApiParams = {},
): Promise<T> {
  const url = new URL(API_BASE, window.location.origin);
  url.searchParams.set("cmd", cmd);

  // Add API key from sessionStorage (except for getAPI command)
  if (cmd !== "getAPI") {
    const apiKey = sessionStorage.getItem("mylar_api_key");
    if (apiKey) {
      url.searchParams.set("apikey", apiKey);
    }
  }

  // Add additional parameters
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  });

  try {
    const response = await fetch(url, {
      credentials: "include", // Send session cookies
    });

    if (!response.ok) {
      throw new ApiError(response.status);
    }

    const data: ApiResponseData = await response.json();

    // Mylar4 API returns {success: true/false, data: {...}, error: {...}}
    if (data.success === false) {
      throw new Error(data.error?.message || "API call failed");
    }

    return (data.data ?? data) as T;
  } catch (error) {
    console.error("API call failed:", { cmd, params, error });
    throw error;
  }
}

/**
 * Login with username and password
 */
export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  try {
    const url = new URL(`${AUTH_BASE}/login_json`, window.location.origin);

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        username,
        password,
      }),
      credentials: "include", // Receive session cookies
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
    const url = new URL(`${AUTH_BASE}/logout_json`, window.location.origin);

    const response = await fetch(url, {
      method: "POST",
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
    const url = new URL(`${AUTH_BASE}/check_session`, window.location.origin);

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
 * Get cover image URL for a Metron series (lazy loading)
 */
export async function getSeriesImage(seriesId: string): Promise<string | null> {
  try {
    const response = await apiCall<{ image: string | null }>("getSeriesImage", {
      id: seriesId,
    });
    return response.image;
  } catch (error) {
    console.error("Failed to fetch series image:", error);
    return null;
  }
}
