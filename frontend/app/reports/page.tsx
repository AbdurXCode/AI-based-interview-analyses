"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";
import { apiGetJson } from "@/lib/api";

type Session = {
  id: string;
  role: string;
  level: string;
  interview_type: string;
  phase: string;
  ended_at: string | null;
  final_report: Record<string, unknown> | null;
};

function gradeFromScore(s: number): string {
  if (s >= 90) return "A+";
  if (s >= 80) return "A";
  if (s >= 70) return "B+";
  if (s >= 60) return "B";
  if (s >= 50) return "C";
  return "D";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function BarChart({ scores }: { scores: number[] }) {
  const max = Math.max(...scores, 1);
  return (
    <div className="chart-bars" style={{ height: 120 }}>
      {scores.map((s, i) => {
        const h = Math.round((s / max) * 95);
        return (
          <div key={i} className="bar-wrap">
            <div className={`bar${i === scores.length - 1 ? " highlight" : ""}`} style={{ height: `${Math.max(h, 4)}%` }} title={`Session ${i + 1}: ${s.toFixed(0)}/100`} />
            <div className="bar-label">{i + 1}</div>
          </div>
        );
      })}
    </div>
  );
}

export default function ReportsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetched = useRef(false);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  useEffect(() => {
    if (authLoading || !user || fetched.current) return;
    fetched.current = true;
    void (async () => {
      try {
        const s = await apiGetJson<Session[]>("/api/v1/interviews/sessions");
        setSessions(s);
        const ended = s.filter((x) => x.ended_at);
        if (ended.length) setSelectedId(ended[0].id);
      } catch { /* ignore */ } finally { setLoading(false); }
    })();
  }, [authLoading, user]);

  const endedSessions = sessions.filter((s) => s.ended_at);
  const selectedSession = sessions.find((s) => s.id === selectedId) ?? endedSessions[0] ?? null;
  const finalReport = selectedSession?.final_report;
  const finalScore = finalReport && typeof finalReport.overall_percent === "number" ? finalReport.overall_percent : null;

  const sessionScores = endedSessions
    .map((s) => (s.final_report && typeof s.final_report.overall_percent === "number" ? s.final_report.overall_percent : null))
    .filter((v): v is number => v !== null);

  const avgScore = sessionScores.length > 0 ? sessionScores.reduce((a, b) => a + b, 0) / sessionScores.length : null;
  const bestScore = sessionScores.length > 0 ? Math.max(...sessionScores) : null;
  const firstScore = sessionScores.length > 1 ? sessionScores[sessionScores.length - 1] : null;
  const improvement = bestScore !== null && firstScore !== null ? bestScore - firstScore : null;

  const strengths: string[] = finalReport && Array.isArray(finalReport.strengths) ? finalReport.strengths as string[] : [];
  const weaknesses: string[] = finalReport && Array.isArray(finalReport.weaknesses) ? finalReport.weaknesses as string[] : [];

  if (authLoading || loading) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⏳</div>
        <h3>Loading reports…</h3>
      </div>
    );
  }

  if (endedSessions.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📊</div>
        <h3>No completed interviews yet</h3>
        <p>Complete a mock interview to see your performance report here.</p>
        <Link href="/mock-interview" className="btn-primary">Start an Interview →</Link>
      </div>
    );
  }

  return (
    <div style={{ paddingBottom: 40 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Performance Report</div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            {selectedSession?.interview_type} Interview — {selectedSession?.role} · {endedSessions.length} interview{endedSessions.length !== 1 ? "s" : ""} tracked
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {endedSessions.length > 1 && (
            <select className="input-field" style={{ width: 200 }} value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}>
              {endedSessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.role} · {s.interview_type} {s.ended_at ? `— ${formatDate(s.ended_at)}` : ""}
                </option>
              ))}
            </select>
          )}
          <Link href="/mock-interview" className="btn-primary">↻ New Interview</Link>
        </div>
      </div>

      {finalReport && (
        <div className="report-hero">
          <div className="report-score-area">
            <div className="big-grade">{gradeFromScore(finalScore ?? 0)}</div>
            <div>
              <div className="report-main-score">{finalScore !== null ? `${finalScore.toFixed(0)} / 100` : "—"}</div>
              <div className="report-subtitle">
                {finalScore !== null && finalScore >= 80 ? "Strong performance" : finalScore !== null && finalScore >= 60 ? "Solid effort" : "Room to grow"}
              </div>
              <div className="report-meta">
                {selectedSession?.role} · {selectedSession?.interview_type} · {selectedSession?.level}
                {selectedSession?.ended_at ? ` · ${formatDate(selectedSession.ended_at)}` : ""}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                {finalScore !== null && finalScore >= 70 ? <span className="tag tag-teal">Technical: Excellent</span> : <span className="tag tag-amber">Technical: Needs Work</span>}
              </div>
            </div>
          </div>
          {improvement !== null && (
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>Progress over time</div>
              <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 24, fontWeight: 700, color: improvement >= 0 ? "var(--success)" : "var(--danger)" }}>
                {improvement >= 0 ? "↑" : "↓"} {Math.abs(improvement).toFixed(0)} pts
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>vs. first session</div>
            </div>
          )}
        </div>
      )}

      <div className="strengths-weaknesses">
        <div className="sw-card">
          <div className="sw-title"><div className="sw-dot green" />Strengths</div>
          <div className="sw-list">
            {strengths.length > 0 ? strengths.map((s, i) => (
              <div key={i} className="sw-item"><span className="sw-icon">✅</span>{s}</div>
            )) : (
              <div className="sw-item" style={{ color: "var(--text-muted)" }}>No strengths data for this session.</div>
            )}
          </div>
        </div>
        <div className="sw-card">
          <div className="sw-title"><div className="sw-dot red" />Areas to Improve</div>
          <div className="sw-list">
            {weaknesses.length > 0 ? weaknesses.map((w, i) => (
              <div key={i} className="sw-item"><span className="sw-icon">⚠️</span>{w}</div>
            )) : (
              <div className="sw-item" style={{ color: "var(--text-muted)" }}>No improvement data for this session.</div>
            )}
          </div>
        </div>
      </div>

      {typeof finalReport?.coach_note === "string" && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><div className="card-title">Coach Note</div></div>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>{finalReport.coach_note}</p>
        </div>
      )}

      <div className="two-col">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Score Trend (Last {Math.min(sessionScores.length, 8)} Interviews)</div>
            <span className="card-link">{sessionScores.length} total</span>
          </div>
          {sessionScores.length > 0 ? (
            <>
              <BarChart scores={sessionScores.slice(-8)} />
              <div style={{ display: "flex", gap: 16, marginTop: 16 }}>
                <div style={{ flex: 1, background: "var(--bg-surface)", borderRadius: 10, padding: 12, textAlign: "center" }}>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Average</div>
                  <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 20, fontWeight: 700 }}>{avgScore !== null ? avgScore.toFixed(1) : "—"}</div>
                </div>
                <div style={{ flex: 1, background: "var(--bg-surface)", borderRadius: 10, padding: 12, textAlign: "center" }}>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Best</div>
                  <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 20, fontWeight: 700, color: "var(--success)" }}>{bestScore !== null ? bestScore.toFixed(0) : "—"}</div>
                </div>
                <div style={{ flex: 1, background: "var(--bg-surface)", borderRadius: 10, padding: 12, textAlign: "center" }}>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>Sessions</div>
                  <div style={{ fontFamily: "'Syne',sans-serif", fontSize: 20, fontWeight: 700, color: "var(--brand-primary)" }}>{endedSessions.length}</div>
                </div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: "center", padding: 32, color: "var(--text-muted)", fontSize: 13 }}>
              Complete interviews to see your score trend
            </div>
          )}
        </div>

        <div className="gap-col">
          <div className="card">
            <div className="card-header"><div className="card-title">All Sessions</div></div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 280, overflowY: "auto" }}>
              {endedSessions.map((s) => {
                const score = s.final_report && typeof s.final_report.overall_percent === "number" ? s.final_report.overall_percent : null;
                const isSelected = s.id === selectedId;
                return (
                  <div
                    key={s.id}
                    style={{
                      padding: "10px 12px",
                      borderRadius: 10,
                      background: isSelected ? "rgba(108,71,255,0.12)" : "var(--bg-surface)",
                      border: `1px solid ${isSelected ? "rgba(108,71,255,0.25)" : "transparent"}`,
                      cursor: "pointer",
                      fontSize: 13,
                    }}
                    onClick={() => setSelectedId(s.id)}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>{s.role}</span>
                      <span style={{ color: score !== null && score >= 70 ? "var(--success)" : "var(--warning)", fontWeight: 600 }}>
                        {score !== null ? `${score.toFixed(0)}/100` : "—"}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 8, color: "var(--text-muted)", fontSize: 11 }}>
                      <span>{s.interview_type}</span>
                      <span>·</span>
                      <span>{s.level}</span>
                      {s.ended_at && <><span>·</span><span>{formatDate(s.ended_at)}</span></>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card">
            <div className="card-header"><div className="card-title">Resume Feedback Loop</div></div>
            <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 12, lineHeight: 1.6 }}>
              Weak answers from your interviews can highlight gaps in your resume. Update your resume to reflect your real-world experience better.
            </div>
            <Link href="/resume" className="btn-primary" style={{ width: "100%", justifyContent: "center" }}>
              📄 Update Resume →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
