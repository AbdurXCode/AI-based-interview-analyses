"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";
import { apiPost } from "@/lib/api";

export default function LoginPage() {
  const { refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await apiPost<{ access_token: string; refresh_token: string }>(
        "/api/v1/auth/login",
        { email, password },
      );
      localStorage.setItem("access_token", res.access_token);
      if (res.refresh_token) localStorage.setItem("refresh_token", res.refresh_token);
      await refresh();
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-logo">
        <div className="logo-icon">IP</div>
        <div className="logo-text">Prep<span>AI</span></div>
      </div>
      <div className="auth-title">Welcome back</div>
      <div className="auth-sub">Sign in to continue your interview prep</div>

      <form onSubmit={onSubmit}>
        <div className="form-group">
          <label className="form-label" htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            className="input-field"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="input-field"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>
        {error && (
          <div style={{ background: "rgba(255,107,107,0.08)", border: "1px solid rgba(255,107,107,0.2)", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "var(--danger)", marginBottom: 16 }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          className="btn-primary"
          style={{ width: "100%", justifyContent: "center", padding: 12 }}
          disabled={loading}
        >
          {loading ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Signing in…</> : "Sign In →"}
        </button>
      </form>

      <div className="auth-link">
        Don&apos;t have an account?{" "}
        <Link href="/register">Create one →</Link>
      </div>
    </div>
  );
}
