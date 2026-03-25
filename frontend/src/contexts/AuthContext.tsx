import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  checkSession,
  checkSetup,
  apiRequest,
} from "@/lib/api";
import type { User, AuthContextValue } from "@/types";

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

interface StartupDiagnostics {
  db_empty: boolean;
  migration_dismissed: boolean;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [needsMigration, setNeedsMigration] = useState(false);

  // Check session on mount (JWT cookie-based — no sessionStorage needed)
  useEffect(() => {
    const verifySession = async () => {
      try {
        // Check if first-run setup is needed
        const setupResult = await checkSetup();
        if (setupResult.needs_setup) {
          setNeedsSetup(true);
          setIsLoading(false);
          return;
        }

        const result = await checkSession();
        if (result.authenticated && result.username) {
          setUser({ username: result.username });

          // Check if first-run migration is needed
          try {
            const diag = await apiRequest<StartupDiagnostics>(
              "GET",
              "/api/system/diagnostics",
            );
            if (diag.db_empty && !diag.migration_dismissed) {
              setNeedsMigration(true);
            }
          } catch {
            // Non-critical — skip migration check
          }
        }
      } catch (error) {
        console.error("Session verification failed:", error);
      } finally {
        setIsLoading(false);
      }
    };

    verifySession();
  }, []);

  const login = async (
    username: string,
    password: string,
  ): Promise<{ success: boolean; error?: string }> => {
    setIsVerifying(true);
    try {
      const result = await apiLogin(username, password);
      if (result.success && result.username) {
        setUser({ username: result.username });
        return { success: true };
      } else {
        return { success: false, error: result.error || "Login failed" };
      }
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    } finally {
      setIsVerifying(false);
    }
  };

  const logout = async (): Promise<void> => {
    try {
      await apiLogout();
    } catch (error) {
      console.error("Logout failed:", error);
    } finally {
      setUser(null);
    }
  };

  const dismissMigration = () => {
    setNeedsMigration(false);
    // Persist dismissal to backend config
    apiRequest("PUT", "/api/config", { MIGRATION_DISMISSED: "true" }).catch(
      (err) => {
        console.warn("Failed to persist migration dismissal:", err);
      },
    );
  };

  const value: AuthContextValue = {
    user,
    isAuthenticated: !!user,
    isLoading,
    isVerifying,
    needsSetup,
    needsMigration,
    dismissMigration,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
