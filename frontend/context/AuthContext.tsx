"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, apiGetJson } from "@/lib/api";

export type AuthUser = { id: string; email: string };

type AuthCtx = {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (typeof window === "undefined") return;
    const raw = localStorage.getItem("access_token");
    if (!raw) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await apiGetJson<AuthUser>("/api/v1/auth/me");
      setUser(me);
    } catch (e) {
      // Only clear tokens on true auth failures. During backend restarts,
      // transient network/5xx errors should not log the user out.
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        localStorage.removeItem("access_token");
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      refresh,
      logout,
    }),
    [user, loading, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth requires AuthProvider");
  return v;
}
