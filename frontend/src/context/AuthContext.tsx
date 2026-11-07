import React, { createContext, useContext, useState, useEffect } from 'react';
import { api, getAuthToken, setAuthToken as setClientToken, getBaseUrl, setBaseUrl as setClientUrl } from '../api/client';

interface AuthContextType {
  token: string;
  setToken: (token: string) => void;
  baseUrl: string;
  setBaseUrl: (url: string) => void;
  isConnected: boolean;
  authMode?: string;
  isChecking: boolean;
  checkConnection: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setTokenState] = useState<string>(getAuthToken());
  const [baseUrl, setBaseUrlState] = useState<string>(getBaseUrl());
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [authMode, setAuthMode] = useState<string | undefined>(undefined);
  const [isChecking, setIsChecking] = useState<boolean>(true);

  const setToken = (newToken: string) => {
    setClientToken(newToken);
    setTokenState(newToken);
  };

  const setBaseUrl = (newUrl: string) => {
    setClientUrl(newUrl);
    setBaseUrlState(newUrl);
  };

  const checkConnection = async (): Promise<boolean> => {
    setIsChecking(true);
    try {
      const res = await api.checkHealth();
      setIsConnected(res.status === 'healthy' || res.status === 'ok');
      setAuthMode(res.auth_mode);
      setIsChecking(false);
      return true;
    } catch {
      setIsConnected(false);
      setIsChecking(false);
      return false;
    }
  };

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, 15000);
    return () => clearInterval(interval);
  }, [baseUrl, token]);

  return (
    <AuthContext.Provider
      value={{
        token,
        setToken,
        baseUrl,
        setBaseUrl,
        isConnected,
        authMode,
        isChecking,
        checkConnection,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

