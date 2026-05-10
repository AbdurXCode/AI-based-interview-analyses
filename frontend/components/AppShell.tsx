"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";

const NAV_ITEMS = [
  {
    id: "dashboard",
    href: "/dashboard",
    label: "Dashboard",
    icon: (
      <svg className="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zm6-4a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zm6-3a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
      </svg>
    ),
  },
  {
    id: "resume",
    href: "/resume",
    label: "Resume Analyzer",
    badge: "AI",
    icon: (
      <svg className="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    id: "interview",
    href: "/mock-interview",
    label: "Mock Interview",
    badge: "AI",
    icon: (
      <svg className="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clipRule="evenodd" />
      </svg>
    ),
  },
  {
    id: "reports",
    href: "/reports",
    label: "Reports",
    icon: (
      <svg className="nav-icon" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 0l-2 2a1 1 0 101.414 1.414L8 10.414l1.293 1.293a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
      </svg>
    ),
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/resume": "Resume Analyzer",
  "/mock-interview": "Mock Interview",
  "/reports": "Performance Report",
};

const TAB_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/resume", label: "Resume Analyzer" },
  { href: "/mock-interview", label: "Mock Interview" },
  { href: "/reports", label: "Performance Report" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, logout } = useAuth();
  const isAuthPage = pathname === "/login" || pathname === "/register" || pathname === "/";

  if (isAuthPage) {
    return <div className="auth-layout">{children}</div>;
  }

  const pageTitle = PAGE_TITLES[pathname] ?? "PrepAI";
  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="logo-area">
          <Link href="/dashboard" className="logo">
            <div className="logo-icon">IP</div>
            <div className="logo-text">Prep<span>AI</span></div>
          </Link>
        </div>

        <div className="nav-section">
          <div className="nav-label">Main</div>
          {NAV_ITEMS.slice(0, 4).map((item) => (
            <Link
              key={item.id}
              href={item.href}
              className={`nav-item${pathname.startsWith(item.href) ? " active" : ""}`}
            >
              {item.icon}
              <span>{item.label}</span>
              {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
            </Link>
          ))}
        </div>

        <div className="sidebar-footer">
          {loading ? null : user ? (
            <div className="user-card" onClick={() => logout()} title="Click to sign out">
              <div className="user-avatar">{initials}</div>
              <div className="user-info">
                <div className="user-name">{user.email}</div>
                <div className="user-role">Click to sign out</div>
              </div>
            </div>
          ) : (
            <div className="user-card" onClick={() => router.push("/login")}>
              <div className="user-avatar">?</div>
              <div className="user-info">
                <div className="user-name">Not signed in</div>
                <div className="user-role">Click to log in</div>
              </div>
            </div>
          )}
        </div>
      </aside>

      <div className="main-content">
        <div className="topbar">
          <div className="topbar-title">{pageTitle}</div>
        </div>

        <div className="screen-tabs">
          {TAB_ITEMS.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              className={`screen-tab${pathname.startsWith(t.href) ? " active" : ""}`}
            >
              {t.label}
            </Link>
          ))}
        </div>

        <div className="screen-area">
          <div className="screen-pad">{children}</div>
        </div>
      </div>
    </div>
  );
}
