import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiRequest, clearStoredToken, getStoredToken, storeToken } from '../services/api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(getStoredToken);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(getStoredToken()));
  const [sessionError, setSessionError] = useState('');

  const clearSession = useCallback((message = '') => {
    clearStoredToken();
    setToken(null);
    setUser(null);
    setSessionError(message);
    setLoading(false);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => clearSession('Your session expired. Please log in again.');
    window.addEventListener('skillswap:unauthorized', onUnauthorized);
    return () => window.removeEventListener('skillswap:unauthorized', onUnauthorized);
  }, [clearSession]);

  useEffect(() => {
    let active = true;
    if (!token) {
      setLoading(false);
      return undefined;
    }

    setLoading(true);
    apiRequest('/api/auth/me', { auth: true })
      .then((result) => {
        if (!active) return;
        setUser(result.user);
        setSessionError('');
      })
      .catch((error) => {
        if (!active) return;
        if (error.status === 401) clearSession('Your session expired. Please log in again.');
        else setSessionError(error.message);
      })
      .finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
  }, [token, clearSession]);

  const login = useCallback(async (credentials) => {
    const result = await apiRequest('/api/auth/login', { method: 'POST', body: credentials });
    storeToken(result.access_token);
    setToken(result.access_token);
    setUser(result.user);
    setSessionError('');
    return result;
  }, []);

  const register = useCallback((details) => apiRequest('/api/auth/register', {
    method: 'POST',
    body: details,
  }), []);

  const logout = useCallback(() => clearSession(''), [clearSession]);

  const value = useMemo(() => ({
    token,
    user,
    role: user?.role || null,
    loading,
    sessionError,
    login,
    register,
    logout,
  }), [token, user, loading, sessionError, login, register, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
