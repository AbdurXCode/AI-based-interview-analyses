"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { apiGetJson, apiPatch, apiPost, apiPostDirect, apiUploadFile } from "@/lib/api";

// ─── types ────────────────────────────────────────────────────────────────────

type JD = { id: string; title: string | null; raw_text: string; role_hint: string | null };
type UploadOut = { upload_id: string; filename: string };
type Profile = {
  profile_id: string;
  version: number;
  jd_id: string | null;
  profile_data: Record<string, unknown>;
  created_at?: string;
  source_filename?: string | null;
  match_result?: Record<string, unknown> | null;
  feedback?: Record<string, unknown> | null;
};

type BulletFeedback = {
  path?: string;
  topic?: string;
  original_text?: string;
  quality?: string;
  issue?: string;
  why?: string;
  suggested_rewrite?: string;
  suggestion?: string;
};

type Feedback = {
  summary?: string;
  sections?: Array<{
    name?: string;
    score_1_to_10?: number;
    reason?: string;
    improvement?: string;
  }>;
  bullets?: BulletFeedback[];
  keywords?: {
    matched?: string[];
    partial?: Array<{ term?: string; note?: string }>;
    missing?: Array<{ keyword?: string; reason?: string }>;
  };
  ats?: {
    overall?: string;
    checks?: Array<{ key?: string; label?: string; status?: string; detail?: unknown }>;
  };
  smart_insights?: {
    role_fit_titles?: string[];
    skills_to_learn_next?: string[];
    strategic_tip?: string;
  };
};

type AnalyzeResult = {
  match_percent: number;
  dimensions: Record<string, number>;
  formula?: string;
  feedback?: Feedback;
};

// ─── constants ────────────────────────────────────────────────────────────────

const DIM_LABELS: Record<string, string> = {
  keyword_coverage: "Keyword Coverage",
  experience_relevance: "Experience Relevance",
  skills_alignment: "Skills Alignment",
};

// ─── component ────────────────────────────────────────────────────────────────

export default function ResumePage() {
  const { user, loading: authLoading } = useAuth();
  const { toast } = useToast();
  const router = useRouter();
  const dropRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [jds, setJds] = useState<JD[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [upload, setUpload] = useState<UploadOut | null>(null);
  const [selectedJd, setSelectedJd] = useState("");
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [analyzeProgress, setAnalyzeProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [jdText, setJdText] = useState("");
  const [jdTitle, setJdTitle] = useState("");
  const [showJdForm, setShowJdForm] = useState(false);
  const [view, setView] = useState<"setup" | "results">("setup");
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);

  const activeProfile = profiles.find((p) => p.profile_id === activeProfileId) ?? profiles[0] ?? null;

  const reload = useCallback(async () => {
    const [j, p] = await Promise.all([
      apiGetJson<JD[]>("/api/v1/job-descriptions"),
      apiGetJson<Profile[]>("/api/v1/resume-profiles"),
    ]);
    setJds(j);
    setProfiles(p);
    return p;
  }, []);

  useEffect(() => {
    if (authLoading || !user) return;
    void (async () => {
      try {
        const p = await reload();
        if (p.length > 0) {
          setActiveProfileId(p[0].profile_id);
          setView("results");
        }
      } catch { /* ignore */ }
    })();
  }, [authLoading, user, reload]);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  // Restore last saved analysis when profile loads
  useEffect(() => {
    if (!activeProfile?.match_result || analyzeResult) return;
    const m = activeProfile.match_result;
    setAnalyzeResult({
      match_percent: Number(m.match_percent) || 0,
      dimensions: (m.dimensions as Record<string, number>) || {},
      formula: typeof m.formula === "string" ? m.formula : undefined,
      feedback: (activeProfile.feedback as Feedback | undefined) ?? undefined,
    });
  }, [activeProfile?.profile_id, activeProfile?.match_result, activeProfile?.feedback, analyzeResult]);

  // ── file upload ──────────────────────────────────────────────────────────────

  async function handleFile(file: File) {
    setBusy("Uploading resume…");
    try {
      const out = (await apiUploadFile("/api/v1/resume-uploads", file)) as UploadOut;
      setUpload(out);
      toast("success", `Uploaded: ${out.filename}`);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Upload failed");
    } finally { setBusy(null); }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) void handleFile(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) void handleFile(f);
  }

  // ── JD save ─────────────────────────────────────────────────────────────────

  async function onSaveJd(e: React.FormEvent) {
    e.preventDefault();
    setBusy("Saving job description…");
    try {
      const row = await apiPost<JD>("/api/v1/job-descriptions", { raw_text: jdText, title: jdTitle || null });
      setJds((p) => [row, ...p]);
      setSelectedJd(row.id);
      setJdText(""); setJdTitle(""); setShowJdForm(false);
      toast("success", "Job description saved.");
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to save JD");
    } finally { setBusy(null); }
  }

  // ── analysis ─────────────────────────────────────────────────────────────────

  function startProgressTick() {
    setAnalyzeProgress(0);
    const start = Date.now();
    const totalMs = 90000;
    const tick = () => {
      const elapsed = Date.now() - start;
      const pct = Math.min(90, Math.round((elapsed / totalMs) * 90));
      setAnalyzeProgress(pct);
      if (pct < 90) setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
  }

  async function runAnalysis(profileId: string, jdId: string) {
    setBusy("Analysing with AI… this takes 60–120 s");
    startProgressTick();
    try {
      await apiPatch(`/api/v1/resume-profiles/${profileId}`, { jd_id: jdId });
      // Bypass Next.js dev proxy (which times out at ~60s) by hitting the backend directly.
      // Backend CORS is configured for localhost:3000 / 127.0.0.1:3000.
      const res = await apiPostDirect<AnalyzeResult>(`/api/v1/resume-profiles/${profileId}/analyze`, {});
      setAnalyzeProgress(100);
      setAnalyzeResult(res);
      await reload();
      toast("success", `Analysis complete — ${res.match_percent.toFixed(0)}% JD match`);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(null);
      setTimeout(() => setAnalyzeProgress(0), 1000);
    }
  }

  async function onAnalyseResume() {
    if (!upload) { toast("error", "Upload a resume first"); return; }
    if (!selectedJd) { toast("error", "Select or paste a job description first"); return; }
    setBusy("Parsing resume…");
    try {
      const profile = await apiPost<Profile>("/api/v1/resume-profiles/from-upload", {
        upload_id: upload.upload_id,
        jd_id: selectedJd,
      });
      await reload();
      const pid = profile.profile_id;
      setActiveProfileId(pid);
      setAnalyzeResult(null);
      setView("results");
      await runAnalysis(pid, selectedJd);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed");
    } finally { setBusy(null); }
  }

  async function onReAnalyze() {
    if (!activeProfile) return;
    const jdId = selectedJd || activeProfile.jd_id || "";
    if (!jdId) { toast("error", "Select a job description first"); return; }
    setAnalyzeResult(null);
    await runAnalysis(activeProfile.profile_id, jdId);
  }

  // ─── derived display data ──────────────────────────────────────────────────

  const matchPct = analyzeResult?.match_percent ?? null;
  const dims = analyzeResult?.dimensions ?? {};
  const fb = analyzeResult?.feedback;
  const kwBlock = fb?.keywords;
  const matchedKw = kwBlock?.matched ?? [];
  const partialKw = kwBlock?.partial ?? [];
  const missingKw = kwBlock?.missing ?? [];
  const atsData = fb?.ats;
  const smart = fb?.smart_insights;
  const activeJd = jds.find((j) => j.id === (activeProfile?.jd_id ?? selectedJd));
  const jdHeadline =
    activeJd?.title?.trim() ||
    activeJd?.raw_text?.split("\n").find((l) => l.trim().length > 8)?.slice(0, 72) ||
    "Target Role";

  if (authLoading) return null;

  // ═══════════════════════════════════════════════════════════════════════════
  //  SETUP SCREEN
  // ═══════════════════════════════════════════════════════════════════════════

  if (view === "setup") {
    return (
      <div>
        {/* Header */}
        <div className="resume-page-header">
          <div>
            <div className="page-title">Resume Analyser</div>
            <div className="page-subtitle">Upload your resume + job description — get a full AI-powered analysis in one click</div>
          </div>
          {profiles.length > 0 && (
            <button className="btn-secondary" onClick={() => setView("results")}>
              View Last Analysis →
            </button>
          )}
        </div>

        {/* Step indicators */}
        <div className="setup-steps">
          <div className={`setup-step ${upload ? "done" : "active"}`}>
            <div className="step-num">{upload ? "✓" : "1"}</div>
            <div className="step-label">Upload Resume</div>
          </div>
          <div className="step-connector" />
          <div className={`setup-step ${selectedJd ? "done" : upload ? "active" : ""}`}>
            <div className="step-num">{selectedJd ? "✓" : "2"}</div>
            <div className="step-label">Add Job Description</div>
          </div>
          <div className="step-connector" />
          <div className={`setup-step ${busy ? "active" : ""}`}>
            <div className="step-num">
              {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : "3"}
            </div>
            <div className="step-label">Analyse</div>
          </div>
        </div>

        {/* Upload + JD grid */}
        <div className="setup-grid">
          {/* Resume upload */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">📎 Resume File</div>
              {upload && <span className="tag tag-teal">Uploaded</span>}
            </div>
            <div
              ref={dropRef}
              className={`upload-zone${dragging ? " dragging" : ""}${upload ? " uploaded" : ""}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <input ref={fileRef} type="file" accept=".pdf,.doc,.docx" style={{ display: "none" }} onChange={onFileChange} />
              {upload ? (
                <>
                  <div className="upload-icon">✅</div>
                  <div className="upload-title">{upload.filename}</div>
                  <div className="upload-sub">Click to replace</div>
                </>
              ) : (
                <>
                  <div className="upload-icon">📄</div>
                  <div className="upload-title">Drop your resume here</div>
                  <div className="upload-sub">PDF or Word · Click to browse</div>
                </>
              )}
            </div>
          </div>

          {/* Job description */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">💼 Job Description</div>
              {jds.length > 0 && <span className="tag tag-purple">{jds.length} saved</span>}
            </div>

            {jds.length > 0 && (
              <div className="form-group">
                <div className="form-label">Select saved JD</div>
                <select className="input-field" value={selectedJd} onChange={(e) => setSelectedJd(e.target.value)}>
                  <option value="">— Select a job description —</option>
                  {jds.map((j) => (
                    <option key={j.id} value={j.id}>{(j.title || "Untitled JD").slice(0, 55)}</option>
                  ))}
                </select>
              </div>
            )}

            <button
              className="btn-secondary"
              style={{ width: "100%", justifyContent: "center", marginBottom: showJdForm ? 12 : 0 }}
              onClick={() => setShowJdForm(!showJdForm)}
            >
              {showJdForm ? "✕ Cancel" : jds.length > 0 ? "+ Add Another JD" : "+ Paste Job Description"}
            </button>

            {showJdForm && (
              <form onSubmit={onSaveJd} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <div className="form-label">Role title (optional)</div>
                  <input className="input-field" value={jdTitle} onChange={(e) => setJdTitle(e.target.value)} placeholder="e.g. Senior ML Engineer at Google" />
                </div>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <div className="form-label">Job posting text</div>
                  <textarea
                    className="input-field"
                    style={{ minHeight: 140, resize: "vertical" }}
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    minLength={20}
                    required
                    placeholder="Paste the full job description here…"
                  />
                </div>
                <button type="submit" className="btn-primary" disabled={!!busy}>
                  {busy === "Saving job description…"
                    ? <><span className="spinner" style={{ width: 13, height: 13 }} /> Saving…</>
                    : "Save Job Description"}
                </button>
              </form>
            )}
          </div>
        </div>

        {/* CTA */}
        <button
          className="btn-primary"
          style={{ width: "100%", justifyContent: "center", fontSize: 15, padding: "14px 24px", marginTop: 8 }}
          onClick={onAnalyseResume}
          disabled={!!busy || !upload || !selectedJd}
        >
          {busy
            ? <><span className="spinner" style={{ width: 15, height: 15 }} />{busy}</>
            : !upload
              ? "Upload a resume to continue"
              : !selectedJd
                ? "Select or paste a Job Description to continue"
                : "Analyse Resume →"}
        </button>

        {analyzeProgress > 0 && <ProgressBar pct={analyzeProgress} label={busy ?? "Processing…"} />}
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  //  RESULTS SCREEN
  // ═══════════════════════════════════════════════════════════════════════════

  return (
    <div>
      {/* Top bar */}
      <div className="resume-page-header" style={{ marginBottom: 20 }}>
        <div>
          <div className="page-title">Analysis Results</div>
          <div className="page-subtitle">
            vs <strong style={{ color: "var(--text-primary)" }}>{jdHeadline}</strong>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn-secondary" onClick={() => { setView("setup"); setAnalyzeResult(null); }}>
            ← New Analysis
          </button>
          <button className="btn-secondary" onClick={onReAnalyze} disabled={!!busy}>
            {busy ? <><span className="spinner" style={{ width: 11, height: 11 }} /> Analysing…</> : "↻ Re-run"}
          </button>
        </div>
      </div>

      {/* Progress bar during re-run */}
      {analyzeProgress > 0 && <ProgressBar pct={analyzeProgress} label={busy ?? "Processing…"} />}

      {/* ── Analysing spinner ── */}
      {busy && matchPct === null && (
        <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🔍</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)", marginBottom: 6 }}>
            Analysing your resume…
          </div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            The AI is reading your resume against the job description. This takes 60–120 seconds.
          </div>
        </div>
      )}

      {/* ── Score card ── */}
      {matchPct !== null && (
        <>
          <div className="ra-score-card" style={{ marginBottom: 20 }}>
            <div className="ra-big-score-wrap">
              <div className="ra-big-score">{matchPct.toFixed(0)}<span>%</span></div>
              <div className="ra-jd-match-label">JD Match</div>
            </div>

            <div className="ra-bars-section">
              <div className="score-breakdown-title" style={{ marginBottom: 8 }}>Score breakdown</div>
              {Object.entries(dims).map(([key, val]) => {
                const pct = Math.min(100, Math.max(0, Number(val)));
                const label = DIM_LABELS[key] ?? key.replace(/_/g, " ");
                const barColor = pct >= 70 ? "#00D4AA" : pct >= 50 ? "#6C47FF" : "#FFB547";
                const scoreColor = pct >= 70 ? "var(--success)" : pct >= 50 ? "var(--brand-primary)" : "var(--warning)";
                return (
                  <div key={key} className="ra-bar-row">
                    <div className="ra-bar-meta">
                      <span className="ra-bar-name">{label}</span>
                      <span className="ra-bar-pct" style={{ color: scoreColor }}>{pct.toFixed(0)}%</span>
                    </div>
                    <div className="ra-bar-track">
                      <div className="ra-bar-fill" style={{ width: `${pct}%`, background: barColor }} />
                    </div>
                  </div>
                );
              })}
              {analyzeResult?.formula && (
                <div className="ra-score-formula">{analyzeResult.formula}</div>
              )}
            </div>

            <div className="ra-score-actions">
              <Link href="/mock-interview" className="btn-secondary" style={{ justifyContent: "center" }}>
                🎙 Practice Interview
              </Link>
            </div>
          </div>

          {/* ── Coach summary ── */}
          {fb?.summary && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header"><div className="card-title">💬 Coach Summary</div></div>
              <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7, margin: 0 }}>{fb.summary}</p>
            </div>
          )}

          {/* ── Two-column layout ── */}
          <div className="ra-two-col">

            {/* ── Left column ── */}
            <div className="ra-left-col">

              {/* Keywords */}
              {(matchedKw.length > 0 || missingKw.length > 0 || partialKw.length > 0) && (
                <div className="ra-panel">
                  <div className="ra-panel-title">Keywords Analysis</div>

                  {matchedKw.length > 0 && (
                    <>
                      <div className="ra-tag-group-label">Matched</div>
                      <div className="ra-tags">
                        {matchedKw.map((k) => (
                          <span key={k} className="ra-tag ra-tag-matched">{k}</span>
                        ))}
                        {partialKw.map((p, i) => (
                          <span key={`p-${i}`} className="ra-tag ra-tag-partial" title={p.note ?? ""}>
                            {p.term ?? ""} (partial)
                          </span>
                        ))}
                      </div>
                    </>
                  )}

                  {missingKw.length > 0 && (
                    <>
                      <div className="ra-tag-group-label" style={{ marginTop: 12 }}>
                        Top missing — most impactful gaps for this JD
                      </div>
                      <div className="ra-tags">
                        {missingKw.slice(0, 5).map((m, i) => (
                          <span
                            key={`${m.keyword}-${i}`}
                            className="ra-tag ra-tag-missing"
                            title={m.reason ?? ""}
                          >
                            {m.keyword ?? ""}
                          </span>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Bullet-level feedback — grouped by quality, Weak open by default */}
              {fb?.bullets && fb.bullets.length > 0 && (
                <BulletFeedbackPanel bullets={fb.bullets} />
              )}
            </div>

            {/* ── Right column ── */}
            <div className="ra-right-col">

              {/* Section scores */}
              {fb?.sections && fb.sections.length > 0 && (
                <div className="ra-side-card">
                  <div className="ra-side-title">
                    Section Scores
                    <span className="ra-issues-badge">
                      {fb.sections.filter((s) => (s.score_1_to_10 ?? 0) < 7).length} below 7
                    </span>
                  </div>
                  {fb.sections.map((s, i) => {
                    const sc = s.score_1_to_10 ?? 0;
                    const fill = sc >= 8 ? "#00D4AA" : sc >= 6 ? "#6C47FF" : sc >= 4 ? "#FFB547" : "#FF6B6B";
                    return (
                      <div key={i}>
                        <div className="ra-sec-row">
                          <span className="ra-sec-name">{(s.name ?? `Section ${i + 1}`).replace(/ \/ .*/, "").slice(0, 18)}</span>
                          <div className="ra-sec-track">
                            <div className="ra-sec-fill" style={{ width: `${sc * 10}%`, background: fill }} />
                          </div>
                          <span className="ra-sec-score">{sc}/10</span>
                        </div>
                        {(s.reason || s.improvement) && (
                          <div style={{ fontSize: 11, color: "var(--text-muted)", margin: "-4px 0 10px 80px", lineHeight: 1.45 }}>
                            {s.reason}
                            {s.improvement && <> · <em style={{ color: "var(--text-secondary)" }}>{s.improvement}</em></>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Smart insights */}
              {(smart?.role_fit_titles?.length || smart?.skills_to_learn_next?.length || smart?.strategic_tip) && (
                <div className="ra-side-card">
                  <div className="ra-side-title">Smart Insights</div>
                  {smart?.role_fit_titles?.length ? (
                    <div className="ra-insight-block">
                      <div className="ra-insight-title">You are ready for</div>
                      <div className="ra-insight-body">{smart.role_fit_titles.join(", ")}</div>
                    </div>
                  ) : null}
                  {smart?.skills_to_learn_next?.length ? (
                    <div className="ra-insight-block">
                      <div className="ra-insight-title">Top skills to learn next</div>
                      <div className="ra-tags" style={{ marginTop: 6 }}>
                        {smart.skills_to_learn_next.map((sk, i) => (
                          <span key={`${sk}-${i}`} className="ra-tag ra-tag-med">{sk}</span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {smart?.strategic_tip && (
                    <div className="ra-insight-block">
                      <div className="ra-insight-title">Strategic tip</div>
                      <div className="ra-insight-body">{smart.strategic_tip}</div>
                    </div>
                  )}
                </div>
              )}

              {/* ATS */}
              <div className="ra-side-card">
                <div className="ra-side-title">
                  ATS Formatting
                  {atsData?.overall && (
                    <span className={atsData.overall === "pass" ? "ra-pass-badge" : "ra-issues-badge"}>
                      {atsData.overall === "warning" ? "Review" : atsData.overall === "fail" ? "Issues" : "Pass"}
                    </span>
                  )}
                </div>
                {atsData?.checks && atsData.checks.length > 0 ? (
                  atsData.checks.map((c, i) => {
                    const st = (c.status ?? "pass").toLowerCase();
                    const icon = st === "fail" ? "✕" : st === "warning" ? "⚠" : "✓";
                    const col = st === "fail" ? "var(--danger)" : st === "warning" ? "var(--warning)" : "var(--success)";
                    const detail = c.detail != null ? String(c.detail) : "";
                    return (
                      <div key={String(c.key ?? i)} className="ra-ats-row">
                        <span className="ra-ats-icon" style={{ color: col }}>{icon}</span>
                        <span className="ra-ats-text">
                          <strong style={{ color: "var(--text-primary)" }}>{c.label ?? ""}</strong>
                          {detail ? <> — {detail}</> : null}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No ATS data yet — run analysis first.</div>
                )}
              </div>

            </div>
          </div>
        </>
      )}

      {/* Status dock */}
      {busy && (
        <div className="status-dock" role="status" aria-live="polite">
          <span className="spinner" />
          <span>{busy}</span>
        </div>
      )}
    </div>
  );
}

// ─── shared progress bar ──────────────────────────────────────────────────────

function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div style={{ marginTop: 12, marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)", marginBottom: 4 }}>
        <span>{label}</span>
        <span>{pct}%</span>
      </div>
      <div style={{ height: 6, background: "rgba(108,71,255,0.15)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: "linear-gradient(90deg, #6C47FF, #00D4AA)", borderRadius: 4, transition: "width 0.8s ease" }} />
      </div>
    </div>
  );
}

// ─── bullet feedback (grouped + collapsible) ─────────────────────────────────

type BulletQuality = "weak" | "acceptable" | "strong";

const QUALITY_META: Record<BulletQuality, { label: string; bhCls: string; bsCls: string }> = {
  weak:       { label: "Weak",       bhCls: "ra-bh-weak",   bsCls: "ra-bs-weak" },
  acceptable: { label: "Acceptable", bhCls: "ra-bh-ok",     bsCls: "ra-bs-ok" },
  strong:     { label: "Strong",     bhCls: "ra-bh-strong", bsCls: "ra-bs-strong" },
};

function BulletFeedbackPanel({ bullets }: { bullets: BulletFeedback[] }) {
  // Default: only "Weak" expanded
  const [open, setOpen] = useState<Record<BulletQuality, boolean>>({
    weak: true,
    acceptable: false,
    strong: false,
  });

  const groups: Record<BulletQuality, BulletFeedback[]> = { weak: [], acceptable: [], strong: [] };
  for (const b of bullets) {
    const q = ((b.quality ?? "acceptable").toLowerCase() as BulletQuality);
    (groups[q] ?? groups.acceptable).push(b);
  }

  const order: BulletQuality[] = ["weak", "acceptable", "strong"];

  return (
    <div className="ra-panel">
      <div className="ra-panel-title">Bullet-Level Feedback</div>

      {order.map((q) => {
        const list = groups[q];
        if (list.length === 0) return null;
        const meta = QUALITY_META[q];
        const isOpen = open[q];
        return (
          <div key={q} className="ra-bullet-group">
            <button
              type="button"
              className={`ra-bullet-group-head ${meta.bhCls}`}
              aria-expanded={isOpen}
              onClick={() => setOpen((s) => ({ ...s, [q]: !s[q] }))}
            >
              <span className={`ra-bullet-group-status ${meta.bsCls}`}>
                {meta.label}
              </span>
              <span className="ra-bullet-group-count">({list.length})</span>
              <span className={`ra-bullet-chevron ${isOpen ? "open" : ""}`}>▾</span>
            </button>

            {isOpen && (
              <div className="ra-bullet-group-body">
                {list.map((b, i) => {
                  const sug = b.suggested_rewrite || b.suggestion || "";
                  const showSug = q !== "strong" && sug;
                  return (
                    <div key={`${b.path ?? ""}-${i}`} className="ra-bullet-card">
                      <div className={`ra-bullet-header ${meta.bhCls}`}>
                        {b.topic && (
                          <div className="ra-bullet-topic">
                            <span className="ra-bullet-topic-tag">In</span>
                            <span className="ra-bullet-topic-name">{b.topic}</span>
                          </div>
                        )}
                        <div className={`ra-bullet-status ${meta.bsCls}`}>
                          {b.issue ?? meta.label}
                        </div>
                        {b.original_text && (
                          <div className="ra-bullet-original">
                            <span className="ra-bullet-quote">“</span>
                            {b.original_text}
                            <span className="ra-bullet-quote">”</span>
                          </div>
                        )}
                        {b.why && <div className="ra-bullet-reason">{b.why}</div>}
                      </div>
                      {showSug && (
                        <div className="ra-bullet-suggest">
                          <div className="ra-suggest-label">✦ Suggested rewrite</div>
                          <div className="ra-suggest-text">{sug}</div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
