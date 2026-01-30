/**
 * API-related type definitions
 */

/** Generic API response wrapper */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: {
    message: string;
    code?: string;
  };
}

/** Pagination metadata returned by paginated endpoints */
export interface PaginationMeta {
  total: number;
  limit: number;
  offset: number;
  returned?: number;
  has_more?: boolean;
}

/** Paginated response wrapper */
export interface PaginatedResponse<T> {
  results: T[];
  pagination: PaginationMeta;
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

/** API key response from getAPI command */
export interface ApiKeyResponse {
  apikey?: string;
  sse_key?: string;
}

/** API command names */
export type ApiCommand =
  | 'getAPI'
  | 'getIndex'
  | 'getComic'
  | 'getConfig'
  | 'setConfig'
  | 'findComic'
  | 'addComic'
  | 'delComic'
  | 'pauseComic'
  | 'resumeComic'
  | 'refreshComic'
  | 'queueIssue'
  | 'unqueueIssue'
  | 'getWanted'
  | 'getUpcoming'
  | 'forceSearch'
  | 'checkGlobalMessages';

/** API call parameters */
export type ApiParams = Record<string, string | number | boolean | undefined | null>;
