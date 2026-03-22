/**
 * Authentication-related type definitions
 */

/** User object */
export interface User {
  username: string;
}

/** Auth context value */
export interface AuthContextValue {
  user: User | null;
  apiKey: string | null;
  sseKey: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isVerifying: boolean;
  needsSetup: boolean;
  needsMigration: boolean;
  dismissMigration: () => void;
  login: (
    username: string,
    password: string,
  ) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<void>;
}

/** Login credentials */
export interface LoginCredentials {
  username: string;
  password: string;
}

/** Auth state */
export interface AuthState {
  user: User | null;
  apiKey: string | null;
  sseKey: string | null;
  isLoading: boolean;
  isVerifying: boolean;
}
