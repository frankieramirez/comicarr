import { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, logout as apiLogout, checkSession } from '@/lib/api';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);

  // Check session on mount
  useEffect(() => {
    const verifySession = async () => {
      try {
        const result = await checkSession();
        if (result.authenticated && result.username) {
          setUser({ username: result.username });
        }
      } catch (error) {
        console.error('Session verification failed:', error);
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
    }
  };

  const value = {
    user,
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
