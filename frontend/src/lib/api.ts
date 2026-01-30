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
      throw new Error(`HTTP error! status: ${response.status}`);
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
