"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";
import { apiGetJson } from "@/lib/api";
import { liveEvalAverages } from "@/lib/mockInterviewEval";

type Profile = {
  profile_id: string;
  version: number;
  jd_id: string | null;
  profile_data: Record<string, unknown>;
  match_result: Record<string, unknown> | null;
  feedback: Record<string, unknown> | null;
  created_at?: string;
  source_filename?: string | null;
};

type SessionSummary = {
  id: string;
  role: string;
  level: string;
  interview_type: string;
  phase: string;
  created_at?: string | null;
  ended_at: string | null;
  final_report: Record<string, unknown> | null;
};

type InterviewSessionDetail = {
  id: string;
  role?: string;
  level?: string;
  interview_type?: string;
  ended_at: string | null;
  final_report: Record<string, unknown> | null;
  turns: Array<{ role: string; content: string; evaluation: Record<string, unknown> | null }>;
};

function BarChart({ scores }: { scores: number[] }) {
  const max = Math.max(...scores, 1);
  const labels = scores.map((_, i) => String(i + 1));
  return (
    <div className="chart-bars">
      {scores.map((s, i) => {
        const h = Math.round((s / max) * 95);
        return (
          <div key={i} className="bar-wrap">
            <div
              className={`bar${i === scores.length - 1 ? " highlight" : ""}`}
              style={{ height: `${Math.max(h, 4)}%` }}
              title={`Session ${i + 1}: ${s.toFixed(0)}/100`}
            />
            <div className="bar-label">{labels[i]}</div>
          </div>
        );
      })}
    </div>
  );
}

function ScoreRing({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value));
  const circ = 2 * Math.PI * 40;
  const offset = circ - (v / 100) * circ;
  return (
    <div className="score-ring-wrap">
      <div className="score-ring">
        <svg viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
          <circle
            cx="50" cy="50" r="40" fill="none"
            stroke="url(#rg)" strokeWidth="10"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
          <defs>
            <linearGradient id="rg" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#6C47FF" />
              <stop offset="100%" stopColor="#00D4AA" />
            </linearGradient>
          </defs>
        </svg>
        <div className="score-ring-label">
          <div className="score-num">{Math.round(v)}</div>
          <div className="score-sub">/100</div>
        </div>
      </div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [latestInterviewFull, setLatestInterviewFull] = useState<InterviewSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const fetchData = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const [p, s] = await Promise.all([
        apiGetJson<Profile[]>("/api/v1/resume-profiles"),
        apiGetJson<SessionSummary[]>("/api/v1/interviews/sessions"),
      ]);
      setProfiles(p);
      setSessions(s);
    } catch {
      /* non-critical */
    } finally {
      setLoading(false);
    }
  }, [user]);

  // Fetch on mount and every time the user navigates back to this page
  useEffect(() => {
    if (authLoading || !user) return;
    void fetchData();
  }, [authLoading, user, fetchData]);

  // Also refresh when the browser tab becomes visible again (e.g. after completing
  // an interview in another tab, or returning from the mock-interview page)
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "visible" && user) {
        void fetchData();
      }
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [user, fetchData]);

  useEffect(() => {
    const ended = sessions.find(
      (s) => s.ended_at && s.final_report && typeof s.final_report.overall_percent === "number",
    );
    if (!ended) {
      setLatestInterviewFull(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const full = await apiGetJson<InterviewSessionDetail>(`/api/v1/interviews/sessions/${ended.id}`);
        if (!cancelled) setLatestInterviewFull(full);
      } catch {
        if (!cancelled) setLatestInterviewFull(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessions]);

  const latestProfile = profiles[0] ?? null;
  const resumeScore =
    latestProfile?.match_result && typeof latestProfile.match_result.match_percent === "number"
      ? latestProfile.match_result.match_percent
      : null;

  const endedSessions = sessions.filter((s) => s.ended_at);
  const interviewsCount = endedSessions.length;

  const sessionScores = endedSessions
    .map((s) =>
      s.final_report && typeof s.final_report.overall_percent === "number"
        ? s.final_report.overall_percent
        : null,
    )
    .filter((v): v is number => v !== null);

  const avgScore =
    sessionScores.length > 0
      ? sessionScores.reduce((a, b) => a + b, 0) / sessionScores.length
      : null;

  const lastScore = sessionScores.length > 0 ? sessionScores[sessionScores.length - 1] : null;

  const chartScores = sessionScores.slice(-8);

  const firstName = user?.email.split("@")[0] ?? "there";

  const latestDims = latestInterviewFull ? liveEvalAverages(latestInterviewFull.turns) : null;
  const latestOverall =
    latestInterviewFull?.final_report &&
    typeof latestInterviewFull.final_report.overall_percent === "number"
      ? (latestInterviewFull.final_report.overall_percent as number)
      : null;
  const latestStrengths =
    latestInterviewFull?.final_report && Array.isArray(latestInterviewFull.final_report.strengths)
      ? (latestInterviewFull.final_report.strengths as string[]).slice(0, 2)
      : [];
  const latestWeak =
    latestInterviewFull?.final_report && Array.isArray(latestInterviewFull.final_report.weaknesses)
      ? (latestInterviewFull.final_report.weaknesses as string[]).slice(0, 2)
      : [];

  // feedback field: { sections: [{name, score_1_to_10}], bullets: [...], summary: "" }
  const feedbackData = latestProfile?.feedback as Record<string, unknown> | null | undefined;
  const sections: Array<{ name?: unknown; score_1_to_10?: unknown }> =
    feedbackData && Array.isArray(feedbackData.sections)
      ? (feedbackData.sections as Array<{ name?: unknown; score_1_to_10?: unknown }>)
      : [];

  const sectionColors = ["teal", "", "amber", "red"];

  const activity: { dot: string; text: React.ReactNode; time: string }[] = [];

  if (latestProfile) {
    const summary =
      typeof latestProfile.profile_data.summary === "string"
        ? latestProfile.profile_data.summary.slice(0, 60)
        : "Resume";
    activity.push({
      dot: "dot-purple",
      text: (
        <>
          <strong>Resume analyzed</strong> — {summary}…
        </>
      ),
      time: "recently",
    });
  }

  endedSessions.slice(0, 3).forEach((s) => {
    const score =
      s.final_report && typeof s.final_report.overall_percent === "number"
        ? ` — Score ${s.final_report.overall_percent.toFixed(0)}/100`
        : "";
    activity.push({
      dot: "dot-teal",
      text: (
        <>
          <strong>Mock Interview</strong> completed ({s.role}){score}
        </>
      ),
      time: s.ended_at ? timeAgo(s.ended_at) : "",
    });
  });

  if (authLoading || loading) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⏳</div>
        <h3>Loading your workspace…</h3>
      </div>
    );
  }

  return (
    <div>
      <div className="welcome-banner">
        <div className="welcome-title">Welcome back, {firstName} 👋</div>
        <div className="welcome-sub">
          {resumeScore !== null
            ? `Your resume scores ${resumeScore.toFixed(0)}% against the latest JD. Keep refining to land that role!`
            : "Upload your resume and a job description to get your match score and personalized feedback."}
        </div>
        <div className="banner-actions">
          <Link href="/resume" className="btn-primary">Analyze Resume</Link>
          <Link href="/mock-interview" className="btn-secondary">Start Interview</Link>
        </div>
      </div>

      <div className="metrics-row">
        <div className="metric-card">
          <div className="metric-icon icon-purple">📄</div>
          <div className="metric-label">Resume Score</div>
          <div className="metric-value">{resumeScore !== null ? `${resumeScore.toFixed(0)}%` : "—"}</div>
          <div className={`metric-change ${resumeScore !== null ? "up" : "neutral"}`}>
            {resumeScore !== null ? "↑ vs JD target" : "No score yet"}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-icon icon-teal">🎯</div>
          <div className="metric-label">Interviews Done</div>
          <div className="metric-value">{interviewsCount}</div>
          <div className={`metric-change ${interviewsCount > 0 ? "up" : "neutral"}`}>
            {interviewsCount > 0 ? `${sessions.length} total sessions` : "No sessions yet"}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-icon icon-amber">⭐</div>
          <div className="metric-label">Avg Interview Score</div>
          <div className="metric-value">{avgScore !== null ? avgScore.toFixed(0) : "—"}</div>
          <div className={`metric-change ${avgScore !== null ? "up" : "neutral"}`}>
            {lastScore !== null ? `Latest: ${lastScore.toFixed(0)}/100` : "Complete an interview"}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-icon icon-red">📊</div>
          <div className="metric-label">Profiles Created</div>
          <div className="metric-value">{profiles.length}</div>
          <div className="metric-change neutral">
            {profiles.length > 0 ? `v${profiles[0]?.version ?? 1} active` : "Upload your resume"}
          </div>
        </div>
      </div>

      {latestInterviewFull && latestOverall !== null && (
        <div className="card" style={{ marginBottom: 24, borderColor: "rgba(0,212,170,0.22)" }}>
          <div className="card-header">
            <div className="card-title">Latest mock interview</div>
            <Link href={`/mock-interview?session=${latestInterviewFull.id}`} className="card-link">
              Full transcript →
            </Link>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "flex-start" }}>
            <div style={{ flex: "1 1 200px" }}>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Overall score</div>
              <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 36, fontWeight: 800, lineHeight: 1 }}>
                {latestOverall.toFixed(0)}
                <span style={{ fontSize: 16, color: "var(--text-muted)", fontWeight: 600 }}>/100</span>
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 8 }}>
                {(latestInterviewFull.role ?? "Interview")} · {latestInterviewFull.interview_type ?? "—"} ·{" "}
                {latestInterviewFull.level ?? "—"}
                {latestInterviewFull.ended_at && (
                  <span style={{ color: "var(--text-muted)" }}> · {timeAgo(latestInterviewFull.ended_at)}</span>
                )}
              </div>
            </div>
            {latestDims && (
              <div style={{ flex: "2 1 280px", minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>Answer quality (avg.)</div>
                <div className="section-list">
                  {[
                    { label: "Technical", val: latestDims.technical },
                    { label: "Structure", val: latestDims.structure },
                    { label: "Communication", val: latestDims.communication },
                    { label: "Depth", val: latestDims.depth },
                  ].map((row) => {
                    const pct = Math.min(100, Math.max(0, row.val));
                    const col = pct >= 70 ? "teal" : pct >= 50 ? "" : "amber";
                    return (
                      <div key={row.label} className="section-row">
                        <div className="section-meta">
                          <span className="section-name">{row.label}</span>
                          <span
                            className="section-score"
                            style={{
                              color: pct >= 70 ? "var(--success)" : pct >= 50 ? "var(--text-primary)" : "var(--warning)",
                            }}
                          >
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="progress-bar">
                          <div className={`progress-fill${col ? ` ${col}` : ""}`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div style={{ flex: "1 1 220px", minWidth: 0 }}>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>Highlights</div>
              {latestStrengths.length > 0 && (
                <ul style={{ margin: "0 0 10px 0", paddingLeft: 18, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  {latestStrengths.map((s, i) => (
                    <li key={i}>
                      <span style={{ color: "var(--success)" }}>+ </span>
                      {s}
                    </li>
                  ))}
                </ul>
              )}
              {latestWeak.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  {latestWeak.map((w, i) => (
                    <li key={i}>
                      <span style={{ color: "var(--warning)" }}>! </span>
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              {latestStrengths.length === 0 && latestWeak.length === 0 && (
                <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Open the transcript for full recruiter feedback.</span>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Interview Performance Trend</div>
            <div style={{ display: "flex", gap: 8 }}>
              <span className="tag tag-purple">Last {chartScores.length} sessions</span>
              <Link href="/reports" className="card-link">All reports →</Link>
            </div>
          </div>
          {chartScores.length > 0 ? (
            <>
              <BarChart scores={chartScores} />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16 }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>0</div>
                {lastScore !== null && (
                  <div style={{ fontSize: 12, color: "var(--success)" }}>
                    Latest: {lastScore.toFixed(0)}/100
                  </div>
                )}
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>100</div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: "center", padding: "32px 0", color: "var(--text-muted)", fontSize: 13 }}>
              Complete a mock interview to see your performance trend
            </div>
          )}

          <div className="divider" />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div className="card-title">Resume Section Scores</div>
            {sections.length > 0 && <Link href="/resume" className="card-link">Details →</Link>}
          </div>
          {sections.length > 0 ? (
            <div className="section-list">
              {sections.slice(0, 5).map((s, i) => {
                const score = typeof s.score_1_to_10 === "number" ? s.score_1_to_10 : 0;
                const pct = score * 10;
                const colorClass = score >= 8 ? "teal" : score >= 6 ? "" : "amber";
                const scoreColor = score >= 8 ? "var(--success)" : score >= 6 ? "var(--text-primary)" : "var(--warning)";
                return (
                  <div key={i} className="section-row">
                    <div className="section-meta">
                      <span className="section-name">{String(s.name ?? `Section ${i + 1}`)}</span>
                      <span className="section-score" style={{ color: scoreColor }}>{score}/10</span>
                    </div>
                    <div className="progress-bar">
                      <div className={`progress-fill${colorClass ? ` ${colorClass}` : ""}`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: 8 }}>
              <span>Run a JD match analysis to see per-section scores.</span>
              <Link href="/resume" className="btn-secondary" style={{ display: "inline-flex", width: "fit-content", fontSize: 12 }}>
                Go to Resume Analyzer →
              </Link>
            </div>
          )}
        </div>

        <div className="gap-col">
          <div className="card" style={{ flex: 1 }}>
            <div className="card-header">
              <div className="card-title">Resume Health</div>
              <span className={`tag ${resumeScore !== null ? (resumeScore >= 70 ? "tag-teal" : resumeScore >= 50 ? "tag-amber" : "tag-red") : "tag-amber"}`}>
                {resumeScore !== null ? (resumeScore >= 70 ? "Good" : resumeScore >= 50 ? "Needs Work" : "Critical") : "No Data"}
              </span>
            </div>
            <ScoreRing value={resumeScore ?? 0} />
            {resumeScore !== null ? (
              <div style={{ textAlign: "center", marginBottom: 12, fontSize: 12, color: "var(--text-muted)" }}>
                JD Match Score
              </div>
            ) : (
              <div style={{ textAlign: "center", marginBottom: 12, fontSize: 12, color: "var(--text-muted)" }}>
                No match score yet
              </div>
            )}
            {latestProfile?.match_result &&
            typeof (latestProfile.match_result as Record<string, unknown>).dimensions === "object" ? (
              <div className="section-list">
                {Object.entries(
                  (latestProfile.match_result as Record<string, unknown>).dimensions as Record<string, number>
                )
                  .slice(0, 3)
                  .map(([key, val]) => {
                    const pct = Math.min(100, Math.max(0, Number(val)));
                    const col = pct >= 70 ? "teal" : pct >= 50 ? "" : "amber";
                    return (
                      <div key={key} className="section-row">
                        <div className="section-meta">
                          <span className="section-name">{key.replace(/_/g, " ")}</span>
                          <span className="section-score" style={{ color: pct >= 70 ? "var(--success)" : pct >= 50 ? "var(--text-primary)" : "var(--warning)" }}>
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                        <div className="progress-bar">
                          <div className={`progress-fill${col ? ` ${col}` : ""}`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
              </div>
            ) : (
              <Link href="/resume" style={{ display: "flex", justifyContent: "center" }}>
                <button className="btn-secondary" style={{ fontSize: 12, marginTop: 4 }}>
                  Run Analysis →
                </button>
              </Link>
            )}
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Recent Activity</div>
              <Link href="/reports" className="card-link">View all →</Link>
            </div>
            {activity.length > 0 ? (
              <div className="activity-list">
                {activity.slice(0, 4).map((a, i) => (
                  <div key={i} className="activity-item">
                    <div className={`activity-dot ${a.dot}`} />
                    <div className="activity-text">{a.text}</div>
                    {a.time ? <div className="activity-time">{a.time}</div> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No activity yet</div>
            )}
          </div>
        </div>
      </div>

      <div className="three-col">
        <div className="card" style={{ borderColor: "rgba(108,71,255,0.2)", cursor: "pointer" }} onClick={() => router.push("/mock-interview")}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>🎤</div>
          <div className="card-title" style={{ marginBottom: 6 }}>Technical Interview</div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 14 }}>Algorithms, system design, coding</div>
          <button className="btn-primary" style={{ width: "100%" }}>Start Now →</button>
        </div>
        <div className="card" style={{ cursor: "pointer" }} onClick={() => router.push("/mock-interview")}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>🤝</div>
          <div className="card-title" style={{ marginBottom: 6 }}>Behavioral Interview</div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 14 }}>STAR method, leadership, teamwork</div>
          <button className="btn-secondary" style={{ width: "100%" }}>Start Now →</button>
        </div>
        <div className="card" style={{ cursor: "pointer" }} onClick={() => router.push("/resume")}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>📊</div>
          <div className="card-title" style={{ marginBottom: 6 }}>Resume Deep Dive</div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 14 }}>Upload resume + JD for analysis</div>
          <button className="btn-secondary" style={{ width: "100%" }}>Analyze →</button>
        </div>
      </div>
    </div>
  );
}
