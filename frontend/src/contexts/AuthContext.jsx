import { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, logout as apiLogout, checkSession, apiCall } from '@/lib/api';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [apiKey, setApiKey] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);

  // Check session on mount and restore API key from sessionStorage
  useEffect(() => {
    const verifySession = async () => {
      try {
        // Check if API key exists in sessionStorage
        const storedApiKey = sessionStorage.getItem('mylar_api_key');
        if (storedApiKey) {
          setApiKey(storedApiKey);
        }

        const result = await checkSession();
        if (result.authenticated && result.username) {
          setUser({ username: result.username });
        } else {
          // Clear API key if session is invalid
          sessionStorage.removeItem('mylar_api_key');
          setApiKey(null);
        }
      } catch (error) {
        console.error('Session verification failed:', error);
        sessionStorage.removeItem('mylar_api_key');
        setApiKey(null);
      } finally {
        setIsLoading(false);
      }
    };

    verifySession();
  }, []);

  const login = async (username, password) => {
    setIsVerifying(true);
    try {
      const result = await apiLogin(username, password);
      if (result.success && result.username) {
        setUser({ username: result.username });

        // Fetch API key after successful login
        try {
          const apiKeyResult = await apiCall('getAPI', { username, password });
          if (apiKeyResult.apikey) {
            setApiKey(apiKeyResult.apikey);
            // Store API key in sessionStorage for persistence
            sessionStorage.setItem('mylar_api_key', apiKeyResult.apikey);
          }
        } catch (error) {
          console.error('Failed to fetch API key:', error);
        }

        return { success: true };
      } else {
        return { success: false, error: result.error || 'Login failed' };
      }
    } catch (error) {
      return { success: false, error: error.message };
    } finally {
      setIsVerifying(false);
    }
  };

  const logout = async () => {
    try {
      await apiLogout();
    } catch (error) {
      console.error('Logout failed:', error);
    } finally {
      setUser(null);
      setApiKey(null);
      sessionStorage.removeItem('mylar_api_key');
    }
  };

  const value = {
    user,
    apiKey,
    isAuthenticated: !!user,
    isLoading,
    isVerifying,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
