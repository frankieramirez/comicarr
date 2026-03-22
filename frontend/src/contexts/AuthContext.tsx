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
  apiCall,
} from "@/lib/api";
import type { User, AuthContextValue, ApiKeyResponse } from "@/types";

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
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [sseKey, setSseKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [needsMigration, setNeedsMigration] = useState(false);

  // Check session on mount and restore API key from sessionStorage
  useEffect(() => {
    const verifySession = async () => {
      try {
        // Check if API key and SSE key exist in sessionStorage
        const storedApiKey = sessionStorage.getItem("comicarr_api_key");
        const storedSseKey = sessionStorage.getItem("comicarr_sse_key");
        if (storedApiKey) {
          setApiKey(storedApiKey);
        }
        if (storedSseKey) {
          setSseKey(storedSseKey);
        }

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
            const diag = await apiCall<StartupDiagnostics>(
              "getStartupDiagnostics",
            );
            if (diag.db_empty && !diag.migration_dismissed) {
              setNeedsMigration(true);
            }
          } catch {
            // Non-critical — skip migration check
          }
        } else {
          // Clear API key and SSE key if session is invalid
          sessionStorage.removeItem("comicarr_api_key");
          sessionStorage.removeItem("comicarr_sse_key");
          setApiKey(null);
          setSseKey(null);
        }
      } catch (error) {
        console.error("Session verification failed:", error);
        sessionStorage.removeItem("comicarr_api_key");
        sessionStorage.removeItem("comicarr_sse_key");
        setApiKey(null);
        setSseKey(null);
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

        // Fetch API key and SSE key after successful login
        try {
          const apiKeyResult = await apiCall<ApiKeyResponse>("getAPI", {
            username,
            password,
          });
          if (apiKeyResult.apikey) {
            setApiKey(apiKeyResult.apikey);
            // Store API key in sessionStorage for persistence
            sessionStorage.setItem("comicarr_api_key", apiKeyResult.apikey);
          }
          if (apiKeyResult.sse_key) {
            setSseKey(apiKeyResult.sse_key);
            // Store SSE key in sessionStorage for persistence
            sessionStorage.setItem("comicarr_sse_key", apiKeyResult.sse_key);
          }
        } catch (error) {
          console.error("Failed to fetch API key:", error);
        }

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
      setApiKey(null);
      setSseKey(null);
      sessionStorage.removeItem("comicarr_api_key");
      sessionStorage.removeItem("comicarr_sse_key");
    }
  };

  const dismissMigration = () => {
    setNeedsMigration(false);
    // Persist dismissal to backend config
    apiCall("setConfig", { MIGRATION_DISMISSED: "true" }).catch((err) => {
      console.warn("Failed to persist migration dismissal:", err);
    });
  };

  const value: AuthContextValue = {
    user,
    apiKey,
    sseKey,
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
