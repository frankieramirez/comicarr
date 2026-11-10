/**
 * API-related type definitions
 */

/** Pagination metadata returned by paginated endpoints */
export interface PaginationMeta {
  total: number;
  limit: number;
  offset: number;
  returned?: number;
  has_more?: boolean;
}

/** Login response */
export interface LoginResponse {
  success: boolean;
  username?: string;
  error?: string;
}

/** Logout response */
export interface LogoutResponse {
  success: boolean;
  error?: string;
}

/** Session check response */
export interface SessionResponse {
  success: boolean;
  authenticated: boolean;
  username?: string;
}
