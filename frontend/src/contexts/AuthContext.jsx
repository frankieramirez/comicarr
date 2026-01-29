import { createContext, useContext, useState, useEffect } from 'react';
import { verifyApiKey } from '@/lib/api';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('apiKey'));
  const [isVerifying, setIsVerifying] = useState(false);

  const login = async (key) => {
    setIsVerifying(true);
    try {
      const isValid = await verifyApiKey(key);
      if (isValid) {
        localStorage.setItem('apiKey', key);
        setApiKey(key);
        return { success: true };
      } else {
        return { success: false, error: 'Invalid API key' };
      }
    } catch (error) {
      return { success: false, error: error.message };
    } finally {
      setIsVerifying(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('apiKey');
    setApiKey(null);
  };

  const value = {
    apiKey,
    isAuthenticated: !!apiKey,
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
