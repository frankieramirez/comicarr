/**
 * Authentication-related type definitions
 */

import type { LogoutResponse } from "./api";

/** User object */
export interface User {
  username: string;
}

/** Auth context value */
export interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isVerifying: boolean;
  needsSetup: boolean;
  needsMigration: boolean;
  dismissMigration: () => void;
  login: (
    username: string,
    password: string,
    remember?: boolean,
  ) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<LogoutResponse>;
}
