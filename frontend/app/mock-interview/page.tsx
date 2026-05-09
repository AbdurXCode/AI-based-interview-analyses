"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { apiGetJson, apiPost, apiPostDirect } from "@/lib/api";
import { liveEvalAverages, type LiveEvalMetrics } from "@/lib/mockInterviewEval";
import { formatResumeProfileOptionLabel, type ResumeProfileListItem } from "@/lib/resumeProfileLabel";

type Profile = ResumeProfileListItem;
type Turn = { role: string; content: string; evaluation: Record<string, unknown> | null };
type OutlineTopic = {
  id?: string;
  title?: string;
  phase?: string;
  anchor?: string;
  jd_skill?: string | null;
  max_followups?: number;
};

type SessionState = {
  id: string;
  role?: string;
  level?: string;
  interview_type?: string;
  created_at?: string | null;
  /** Server-side last user interaction (ISO), from session_state JSON */
  last_activity_at?: string | null;
  phase: string;
  ended_at: string | null;
  final_report: Record<string, unknown> | null;
  turns: Turn[];
  topic_index?: number;
  topics?: OutlineTopic[];
  topics_total?: number;
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

const TYPES = ["technical", "behavioral", "mixed"];
const LEVELS = ["fresher", "mid", "senior"];

const SESSION_STORAGE_KEY = "mock_interview_active_session";
/** Idle auto-end after no substantive activity (see heartbeat / server last_activity_at). */
const IDLE_MS = 30 * 60 * 1000;
const IDLE_TICK_MS = 20_000;
/** Warn this many ms before IDLE_MS threshold is reached (same delta as former 4→5 min). */
const IDLE_WARN_MS = IDLE_MS - 5 * 60 * 1000;

function gradeFromScore(s: number): string {
  if (s >= 90) return "A+";
  if (s >= 80) return "A";
  if (s >= 70) return "B+";
  if (s >= 60) return "B";
  if (s >= 50) return "C";
  return "D";
}

function phaseLabel(phase: unknown): string {
  const p = typeof phase === "string" ? phase : "";
  const labels: Record<string, string> = {
    warmup: "Warm-up",
    jd_core: "JD core",
    project: "Project dive",
    problem_solving: "Problem solving",
    behavioral: "Behavioral",
    closing: "Wrapping up",
    main: "In progress",
    ended: "Complete",
    opening: "Starting",
  };
  return labels[p] || (p ? p.replace(/_/g, " ") : "Topic");
}

/** Canonical outline ordering (aligned with SYSTEM_OUTLINE). Unknown phases append after. */
const ROADMAP_PHASE_ORDER = ["warmup", "jd_core", "project", "problem_solving", "behavioral"];

function topicPhaseKey(phase: unknown): string {
  return typeof phase === "string" && phase.trim() ? phase.trim() : "other";
}

type PhaseSegmentMeta = { topic: OutlineTopic; index: number };

function dimensionScoresFromReport(fr: Record<string, unknown> | null | undefined): LiveEvalMetrics | null {
  if (!fr) return null;
  const raw = fr.dimension_scores_pct;
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const pick = (k: string): number | null => {
    const v = o[k];
    if (typeof v === "number" && Number.isFinite(v)) return Math.min(100, Math.max(0, v));
    return null;
  };
  const technical = pick("technical");
  const structure = pick("structure");
  const communication = pick("communication");
  const depth = pick("depth");
  if (technical === null || structure === null || communication === null || depth === null) return null;
  return { technical, structure, communication, depth };
}

/** Expected main + follow-up prompts for a roadmap phase block (from outline). */
function phaseQuestionBlurb(segments: PhaseSegmentMeta[]): string {
  const n = segments.length;
  let maxPrompts = 0;
  for (const s of segments) {
    const mf =
      typeof (s.topic as OutlineTopic).max_followups === "number"
        ? Math.min(4, Math.max(0, (s.topic as OutlineTopic).max_followups!))
        : 2;
    maxPrompts += 1 + mf;
  }
  return `${n} main question${n === 1 ? "" : "s"}; up to ~${maxPrompts} interviewer prompts if follow-ups are used.`;
}

function buildRoadmapPhaseGroups(topics: OutlineTopic[]): Array<{ phase: string; segments: PhaseSegmentMeta[] }> {
  const withIdx = topics.map((topic, index) => ({ topic, index }));
  const keysInOrder = new Set<string>();
  const groups: Array<{ phase: string; segments: PhaseSegmentMeta[] }> = [];
  for (const phase of ROADMAP_PHASE_ORDER) {
    const segments = withIdx.filter((x) => topicPhaseKey(x.topic.phase) === phase).sort((a, b) => a.index - b.index);
    if (segments.length) {
      groups.push({ phase, segments });
      keysInOrder.add(phase);
    }
  }
  const rest = [...new Set(withIdx.map((x) => topicPhaseKey(x.topic.phase)))].filter((p) => !keysInOrder.has(p));
  for (const phase of rest) {
    const segments = withIdx.filter((x) => topicPhaseKey(x.topic.phase) === phase).sort((a, b) => a.index - b.index);
    if (segments.length) groups.push({ phase, segments });
  }
  return groups;
}

function extractCoachingFromEval(evaluation: Record<string, unknown> | null | undefined): {
  weaknessReason?: string;
  strengths: string[];
  feedback: string[];
  suggestions: string[];
} | null {
  if (!evaluation || typeof evaluation !== "object") return null;
  const ev = evaluation as Record<string, unknown>;
  const weaknessReason = typeof ev.weakness_reason === "string" ? ev.weakness_reason.trim() : "";

  const rawSt = ev.coach_strengths;
  const strengths =
    Array.isArray(rawSt) ? rawSt.map((x) => String(x).trim()).filter(Boolean).slice(0, 4) : [];

  const rawFb = ev.coach_feedback;
  const feedback =
    Array.isArray(rawFb) ? rawFb.map((x) => String(x).trim()).filter(Boolean).slice(0, 5) : [];

  const rawSug = ev.coach_suggestions;
  const suggestions =
    Array.isArray(rawSug) ? rawSug.map((x) => String(x).trim()).filter(Boolean).slice(0, 5) : [];

  if (!weaknessReason && strengths.length === 0 && feedback.length === 0 && suggestions.length === 0) return null;
  return { weaknessReason: weaknessReason || undefined, strengths, feedback, suggestions };
}

function formatSessionWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Backend returns HTTP 410 with detail "session ended" when the mock interview is already complete. */
function isSessionAlreadyEndedError(message: string): boolean {
  const m = message.toLowerCase();
  return (
    m.includes("session ended") ||
    m.includes("gone") ||
    /\b410\b/.test(m)
  );
}

function saveActiveSession(id: string, meta: { role: string; level: string; type: string }) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ id, ...meta }));
  } catch { /* ignore */ }
}

function clearActiveSession() {
  try { localStorage.removeItem(SESSION_STORAGE_KEY); } catch { /* ignore */ }
}

function loadActiveSession(): { id: string; role: string; level: string; type: string } | null {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

/** POST /report until the session is ended with a stored final_report (retries for LLM/network). */
async function requestMockInterviewReportWithRetries(sessionId: string): Promise<SessionState> {
  const maxAttempts = 6;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      await apiPost(`/api/v1/interviews/sessions/${sessionId}/report`, {});
    } catch {
      if (attempt === maxAttempts) {
        throw new Error("Could not generate your performance report right now.");
      }
      await new Promise((r) => setTimeout(r, Math.min(12_000, 1500 * attempt)));
      continue;
    }
    const u = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/${sessionId}`);
    if (u.phase === "ended" && u.final_report) return u;
    if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, 1200));
  }
  const u2 = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/${sessionId}`);
  if (u2.phase === "ended" && u2.final_report) return u2;
  throw new Error("Report generation is taking longer than expected. You can retry.");
}

async function closeMockInterviewFully(sessionId: string): Promise<SessionState> {
  await apiPost(`/api/v1/interviews/sessions/${sessionId}/end`, {});
  return requestMockInterviewReportWithRetries(sessionId);
}

function InterviewFullscreenWait({ label, sub }: { label: string; sub?: string }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 12,
        minHeight: "min(560px, 72vh)",
        color: "var(--text-muted)",
        fontSize: 14,
      }}
    >
      <span className="spinner" />
      <span>{label}</span>
      {sub ? <span style={{ fontSize: 13, opacity: 0.85, textAlign: "center", maxWidth: 420 }}>{sub}</span> : null}
    </div>
  );
}

export default function MockInterviewPage() {
  const { user, loading: authLoading } = useAuth();
  const { toast } = useToast();
  const router = useRouter();

  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [session, setSession] = useState<SessionState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [resumingSession, setResumingSession] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const [selProfile, setSelProfile] = useState("");
  const [selType, setSelType] = useState("technical");
  const [selLevel, setSelLevel] = useState("mid");
  const [role, setRole] = useState("Software Engineer");

  const [answer, setAnswer] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  /** Ensures `/report` finalization runs once per session (handles React Strict Mode / remount). */
  const reportFinalizeStartedFor = useRef<string | null>(null);
  /** True after user confirms End until `/end` finishes — avoids Send racing the close. */
  const terminatingInterviewRef = useRef(false);

  const [sessionHistory, setSessionHistory] = useState<SessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [openingHistoryId, setOpeningHistoryId] = useState<string | null>(null);
  const [openedFromHistory, setOpenedFromHistory] = useState(false);

  const sessionRef = useRef<SessionState | null>(null);
  const busyRef = useRef<string | null>(null);
  const idleFiredSessionRef = useRef<string | null>(null);
  const idleWatchSidRef = useRef<string | null>(null);
  const warnFiredSessionRef = useRef<string | null>(null);
  const localActivityAtRef = useRef<number>(Date.now());
  const lastHeartbeatAtRef = useRef<number>(0);
  const visibleRef = useRef<boolean>(true);
  busyRef.current = busy;
  sessionRef.current = session;

  const fetchSession = useCallback(async (id: string) => {
    const s = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/${id}`);
    if (s.role) setRole(s.role);
    if (s.level) setSelLevel(s.level);
    if (s.interview_type) setSelType(s.interview_type);
    setSession(s);
    return s;
  }, []);

  const loadSessionHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const list = await apiGetJson<SessionSummary[]>("/api/v1/interviews/sessions");
      setSessionHistory(list);
    } catch {
      /* ignore */
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  async function openHistoryEntry(entry: SessionSummary) {
    setOpeningHistoryId(entry.id);
    try {
      await fetchSession(entry.id);
      setOpenedFromHistory(true);
      if (entry.phase !== "ended") {
        saveActiveSession(entry.id, { role: entry.role, level: entry.level, type: entry.interview_type });
        startRef.current = Date.now();
        toast("info", "Resumed this session.");
      } else {
        clearActiveSession();
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Could not load session");
    } finally {
      setOpeningHistoryId(null);
    }
  }

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  useEffect(() => {
    if (session?.phase === "ended") terminatingInterviewRef.current = false;
  }, [session?.phase]);

  // Load resume profiles + session list
  useEffect(() => {
    if (authLoading || !user) return;
    void (async () => {
      try {
        const p = await apiGetJson<Profile[]>("/api/v1/resume-profiles");
        setProfiles(p);
        if (p.length) setSelProfile(p[0].profile_id);
      } catch { /* ignore */ }
    })();
    void loadSessionHistory();
  }, [authLoading, user, loadSessionHistory]);

  // Deep link ?session=uuid wins over localStorage resume
  useEffect(() => {
    if (authLoading || !user) return;

    void (async () => {
      const fromQuery =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("session")
          : null;

      if (fromQuery && /^[0-9a-f-]{36}$/i.test(fromQuery)) {
        setResumingSession(true);
        try {
          const s = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/${fromQuery}`);
          if (s.role) setRole(s.role);
          if (s.level) setSelLevel(s.level);
          if (s.interview_type) setSelType(s.interview_type);
          setSession(s);
          setOpenedFromHistory(true);
          if (s.phase !== "ended") {
            saveActiveSession(s.id, {
              role: s.role ?? "General",
              level: s.level ?? "mid",
              type: s.interview_type ?? "technical",
            });
            startRef.current = Date.now();
          } else {
            clearActiveSession();
          }
          window.history.replaceState(null, "", "/mock-interview");
        } catch {
          toast("error", "Interview session not found.");
        } finally {
          setResumingSession(false);
        }
        return;
      }

      const saved = loadActiveSession();
      if (!saved) {
        // If localStorage doesn't know, try server-side active session (multi-tab / cleared storage).
        setResumingSession(true);
        try {
          const s = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/active`);
          if (s.phase !== "ended") {
            if (s.role) setRole(s.role);
            if (s.level) setSelLevel(s.level);
            if (s.interview_type) setSelType(s.interview_type);
            setSession(s);
            saveActiveSession(s.id, {
              role: s.role ?? "General",
              level: s.level ?? "mid",
              type: s.interview_type ?? "technical",
            });
            startRef.current = Date.now();
            toast("info", "Resumed your active interview session.");
          }
        } catch {
          /* no active session */
        } finally {
          setResumingSession(false);
        }
        return;
      }

      setResumingSession(true);
      try {
        const s = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/${saved.id}`);
        if (s.phase !== "ended") {
          setSelType(saved.type);
          setSelLevel(saved.level);
          setRole(saved.role);
          setSession(s);
          startRef.current = Date.now();
          toast("info", "Resumed your active interview session.");
        } else if (s.final_report) {
          setSelType(saved.type);
          setSelLevel(saved.level);
          setRole(saved.role);
          setSession(s);
          clearActiveSession();
        } else {
          clearActiveSession();
        }
      } catch {
        clearActiveSession();
        // Fallback: if localStorage is stale, see if there's a different active session on server.
        try {
          const s2 = await apiGetJson<SessionState>(`/api/v1/interviews/sessions/active`);
          if (s2.phase !== "ended") {
            if (s2.role) setRole(s2.role);
            if (s2.level) setSelLevel(s2.level);
            if (s2.interview_type) setSelType(s2.interview_type);
            setSession(s2);
            saveActiveSession(s2.id, {
              role: s2.role ?? "General",
              level: s2.level ?? "mid",
              type: s2.interview_type ?? "technical",
            });
            startRef.current = Date.now();
            toast("info", "Resumed your active interview session.");
          } else {
            toast("error", "That interview session is no longer available. Starting fresh.");
          }
        } catch {
          toast("error", "That interview session is no longer available. Starting fresh.");
        }
      } finally {
        setResumingSession(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user]);

  // Track local activity (typing/mouse) + page visibility for idle/heartbeat logic
  useEffect(() => {
    if (typeof window === "undefined") return;
    const bump = () => { localActivityAtRef.current = Date.now(); };
    const onVis = () => { visibleRef.current = !document.hidden; };
    window.addEventListener("keydown", bump, { passive: true });
    window.addEventListener("mousedown", bump, { passive: true });
    window.addEventListener("touchstart", bump, { passive: true });
    document.addEventListener("visibilitychange", onVis, { passive: true });
    return () => {
      window.removeEventListener("keydown", bump);
      window.removeEventListener("mousedown", bump);
      window.removeEventListener("touchstart", bump);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  // Auto-end after IDLE_MS with no interaction (baseline from server last_activity_at)
  useEffect(() => {
    if (!session || session.phase === "ended" || session.phase === "closing") {
      idleFiredSessionRef.current = null;
      idleWatchSidRef.current = null;
      warnFiredSessionRef.current = null;
      return;
    }
    const sid = session.id;
    if (idleWatchSidRef.current !== sid) {
      idleFiredSessionRef.current = null;
      idleWatchSidRef.current = sid;
      warnFiredSessionRef.current = null;
    }

    function idleBaseline(isoLast: string | undefined, isoCreated: string | undefined): number | null {
      if (isoLast?.trim()) {
        const t = Date.parse(isoLast);
        if (!Number.isNaN(t)) return t;
      }
      if (isoCreated?.trim()) {
        const t = Date.parse(isoCreated);
        if (!Number.isNaN(t)) return t;
      }
      return null;
    }

    function tick() {
      const cur = sessionRef.current;
      if (!cur || cur.phase === "ended" || cur.phase === "closing" || cur.id !== sid) return;
      if (idleFiredSessionRef.current === sid) return;
      if (busyRef.current) return;

      // Only auto-end while the tab is visible; if user is away, we'll evaluate on return.
      if (!visibleRef.current) return;

      const baseMs = idleBaseline(
        typeof cur.last_activity_at === "string" ? cur.last_activity_at : undefined,
        typeof cur.created_at === "string" ? cur.created_at : undefined,
      );
      if (baseMs === null) return;

      const localIdleMs = Date.now() - localActivityAtRef.current;
      const serverIdleMs = Date.now() - baseMs;

      // If user has local activity, keep the server activity fresh via heartbeat.
      if (localIdleMs < IDLE_WARN_MS && Date.now() - lastHeartbeatAtRef.current > 25_000) {
        lastHeartbeatAtRef.current = Date.now();
        void apiPost(`/api/v1/interviews/sessions/${sid}/heartbeat`, {}).catch(() => { /* ignore */ });
      }

      if (serverIdleMs >= IDLE_WARN_MS && warnFiredSessionRef.current !== sid) {
        warnFiredSessionRef.current = sid;
        toast(
          "info",
          `No answers sent for ${Math.round(IDLE_WARN_MS / 60_000)} minutes. Send a reply soon or the session will end automatically.`,
        );
      }

      if (serverIdleMs >= IDLE_MS) {
        idleFiredSessionRef.current = sid;
        void (async () => {
          let updated: SessionState | null = null;
          try {
            if (busyRef.current) return;
            setBusy("Idle timeout — ending interview…");
            await apiPost(`/api/v1/interviews/sessions/${sid}/end`, {});
            updated = await fetchSession(sid);
            clearActiveSession();
            if (updated.phase === "closing") {
              toast("info", "Session ended due to inactivity — generating your performance report…");
            } else if (updated.final_report) {
              toast(
                "info",
                `No activity for ${Math.round(IDLE_MS / 60_000)} minutes — we ended the interview and saved your performance report.`,
              );
            } else {
              toast(
                "info",
                `Session ended automatically after ${Math.round(IDLE_MS / 60_000)} minutes idle.`,
              );
            }
            void loadSessionHistory();
          } catch (e) {
            idleFiredSessionRef.current = null;
            toast("error", e instanceof Error ? e.message : "Could not end session after idle timeout.");
            setBusy(null);
            return;
          }
          if (updated?.phase === "closing" && !updated.final_report) {
            setBusy("Generating your performance report…");
          } else {
            setBusy(null);
          }
        })();
      }
    }

    const iv = window.setInterval(tick, IDLE_TICK_MS);
    tick();
    return () => window.clearInterval(iv);
  }, [session?.id, session?.phase, fetchSession]);

  // Natural interview end: goodbye is stored, then finalize report asynchronously.
  useEffect(() => {
    const s = session;
    if (!s?.id || s.phase !== "closing" || s.final_report) {
      return;
    }
    if (reportFinalizeStartedFor.current === s.id) return;
    reportFinalizeStartedFor.current = s.id;

    void (async () => {
      setBusy("Generating your performance report…");
      try {
        setReportError(null);
        const u = await requestMockInterviewReportWithRetries(s.id);
        if (u.role) setRole(u.role);
        if (u.level) setSelLevel(u.level);
        if (u.interview_type) setSelType(u.interview_type);
        setSession(u);
        if (u.phase === "ended" && u.final_report) {
          clearActiveSession();
          toast("success", "Interview complete! Your report is ready.");
          void loadSessionHistory();
          return;
        }
        reportFinalizeStartedFor.current = null;
        setReportError("Report generation is taking longer than expected. You can retry.");
      } catch (e) {
        reportFinalizeStartedFor.current = null;
        const msg = e instanceof Error ? e.message : "Could not generate your performance report right now.";
        setReportError(msg || "Could not generate your performance report right now.");
        toast("error", msg || "Could not generate your performance report right now.");
      } finally {
        setBusy(null);
      }
    })();
  }, [session?.id, session?.phase, session?.final_report, fetchSession, toast, loadSessionHistory]);

  // Timer
  useEffect(() => {
    if (session && session.phase !== "ended") {
      startRef.current = startRef.current ?? Date.now();
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - (startRef.current ?? Date.now())) / 1000));
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [session?.phase]);

  // Auto-scroll to latest message
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.turns]);

  const formatTime = (secs: number) => {
    const m = String(Math.floor(secs / 60)).padStart(2, "0");
    const s = String(secs % 60).padStart(2, "0");
    return `${m}:${s}`;
  };

  async function createInterviewCore() {
    const selectedProfile = profiles.find((p) => p.profile_id === selProfile) ?? null;
    // Session creation can trigger multiple LLM calls (outline + opening) and exceed the
    // Next.js dev rewrite proxy socket timeout; call backend directly (same approach as /analyze).
    const res = await apiPostDirect<{ session_id: string; assistant_message: string }>("/api/v1/interviews/sessions", {
      resume_profile_id: selProfile,
      jd_id: selectedProfile?.jd_id ?? null,
      role,
      level: selLevel,
      interview_type: selType,
      max_followups_per_topic: 2,
    });
    await fetchSession(res.session_id);
    startRef.current = Date.now();
    setElapsed(0);
    saveActiveSession(res.session_id, { role, level: selLevel, type: selType });
    toast("success", "Interview started! Type your answers below.");
    setOpenedFromHistory(false);
    void loadSessionHistory();
  }

  async function tryEndSession(sessionId: string): Promise<SessionState | null> {
    try {
      await apiPost(`/api/v1/interviews/sessions/${sessionId}/end`, {});
      return await fetchSession(sessionId);
    } catch (e) {
      try {
        const s = await fetchSession(sessionId);
        if (s.phase === "ended" || s.phase === "closing") return s;
      } catch {
        /* ignore */
      }
      throw e;
    }
  }

  async function cancelSessionAndReset(sessionId: string) {
    setBusy("Cancelling this attempt…");
    try {
      await apiPost(`/api/v1/interviews/sessions/${sessionId}/cancel`, {});
    } catch (e) {
      // Same recovery approach: if session is already ended, proceed with reset.
      try {
        const s = await fetchSession(sessionId);
        if (s.phase !== "ended") throw e;
      } catch {
        throw e;
      }
    } finally {
      setBusy(null);
    }

    clearActiveSession();
    setSession(null);
    setOpenedFromHistory(false);
    startRef.current = null;
    setElapsed(0);
    setAnswer("");
    void loadSessionHistory();
  }

  async function onBegin() {
    if (!selProfile) { toast("error", "Select a resume profile first"); return; }

    const ghostId = loadActiveSession()?.id ?? null;

    if (ghostId) {
      if (
        !window.confirm(
          "This ends any saved in-progress mock interview in this browser, generates its performance report, then starts a new interview with the setup below. Continue?",
        )
      ) {
        return;
      }
      setBusy("Saving previous session…");
      try {
        try {
          await closeMockInterviewFully(ghostId);
        } catch (e) {
          const msg = e instanceof Error ? e.message : "";
          if (/404|410|not found|gone/i.test(msg)) {
            clearActiveSession();
          } else {
            toast("error", msg || "Could not end your previous mock interview.");
            return;
          }
        }
        clearActiveSession();
        setSession((cur) => (cur?.id === ghostId ? null : cur));
        void loadSessionHistory();
      } finally {
        setBusy(null);
      }
    }

    setBusy("Setting up your interview session…");
    try {
      await createInterviewCore();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to start session");
    } finally { setBusy(null); }
  }

  async function onSend() {
    if (!session || !answer.trim()) return;
    if (terminatingInterviewRef.current) {
      toast("info", "Ending the interview — please wait a moment.");
      return;
    }
    if (session.phase === "ended") {
      toast("info", "This interview has already ended.");
      return;
    }
    if (session.phase === "closing") {
      toast("info", "Your interview wrap-up was sent — we are generating your report.");
      return;
    }
    setBusy("AI is evaluating your answer…");
    const text = answer.trim();
    setAnswer("");
    try {
      await apiPost(`/api/v1/interviews/sessions/${session.id}/answers`, { text, modality: "text" });
      const updated = await fetchSession(session.id);
      if (updated.phase === "closing") {
        void loadSessionHistory();
      } else if (updated.phase === "ended" && updated.final_report) {
        clearActiveSession();
        toast("success", "Interview complete! Your report is ready.");
        void loadSessionHistory();
      } else if (updated.phase === "ended" && !updated.final_report) {
        toast("info", "Interview complete. Your report will appear in a moment.");
        void loadSessionHistory();
      }
    } catch (e) {
      const raw = e instanceof Error ? e.message : "Submit failed";
      if (isSessionAlreadyEndedError(raw)) {
        try {
          const synced = await fetchSession(session.id);
          if (synced.phase === "ended") {
            clearActiveSession();
            toast("info", "That interview already ended — syncing your screen.");
            void loadSessionHistory();
          } else {
            toast("info", raw);
          }
        } catch {
          toast("info", "This session has ended. Refresh the page if the chat still looks active.");
        }
      } else {
        toast("error", raw);
        setAnswer(text);
      }
    } finally { setBusy(null); }
  }

  async function onEnd() {
    if (!session) return;
    const answered = session.turns.some((t) => t.role === "user");
    if (
      !answered &&
      !window.confirm(
        "You have not submitted any answers yet. End anyway and generate a minimal report?",
      )
    ) {
      return;
    }
    terminatingInterviewRef.current = true;
    setBusy("Generating your performance report…");
    try {
      const updated = await tryEndSession(session.id);
      clearActiveSession();
      setReportError(null);
      if (updated?.phase === "closing" && !updated.final_report) {
        setBusy("Generating your performance report…");
        toast("info", "Thanks — we're preparing your performance report.");
      } else {
        terminatingInterviewRef.current = false;
        setBusy(null);
      }
      if (updated?.phase === "ended" && updated.final_report) {
        toast("success", "Report ready! Scroll down to view your results.");
      }
      void loadSessionHistory();
    } catch (e) {
      terminatingInterviewRef.current = false;
      toast("error", e instanceof Error ? e.message : "Failed to end session");
      setBusy(null);
    }
  }

  async function onNewSession() {
    if (session && session.phase !== "ended") {
      if (
        !window.confirm(
          "End this mock interview and generate its performance report? You will return to setup afterward.",
        )
      ) {
        return;
      }
      const sid = session.id;
      setBusy("Generating your performance report…");
      try {
        await closeMockInterviewFully(sid);
        void loadSessionHistory();
      } catch (e) {
        toast("error", e instanceof Error ? e.message : "Could not end session");
        return;
      } finally {
        setBusy(null);
      }
    }
    clearActiveSession();
    setSession(null);
    setOpenedFromHistory(false);
    startRef.current = null;
    setElapsed(0);
    setAnswer("");
    void loadSessionHistory();
  }

  async function endInterviewAndConfigureNew() {
    const s = session;
    if (!s || s.phase === "ended") {
      void onNewSession();
      return;
    }
    if (
      !window.confirm(
        "Cancel this attempt and return to setup? No performance report will be generated.",
      )
    ) {
      return;
    }
    try {
      await cancelSessionAndReset(s.id);
      toast("info", "Attempt cancelled. Configure and start a new interview.");
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Could not cancel session");
      return;
    }
  }

  const aiTurns = session?.turns.filter((t) => t.role === "assistant") ?? [];
  const userTurns = session?.turns.filter((t) => t.role === "user") ?? [];

  const latestUserEval = userTurns.length ? userTurns[userTurns.length - 1]?.evaluation : null;
  const coaching = extractCoachingFromEval(latestUserEval);

  const endedDimensionScores =
    session?.phase === "ended"
      ? (dimensionScoresFromReport(session.final_report) ?? liveEvalAverages(session.turns))
      : null;
  const techScore = endedDimensionScores?.technical ?? null;
  const structScore = endedDimensionScores?.structure ?? null;
  const commScore = endedDimensionScores?.communication ?? null;
  const depthScore = endedDimensionScores?.depth ?? null;
  const finalReport = session?.final_report;
  const finalScore = finalReport && typeof finalReport.overall_percent === "number" ? finalReport.overall_percent : null;

  const displayRole = session?.role ?? role;
  const displayLevel = session?.level ?? selLevel;
  const displayType = session?.interview_type ?? selType;

  const topicIdx = session?.topic_index ?? 0;
  const roadmapGroups = session?.topics?.length ? buildRoadmapPhaseGroups(session.topics) : [];
  const currentOutlineTopic =
    session?.topics?.length ?
      session.topics[Math.min(topicIdx, Math.max(session.topics.length - 1, 0))]
      : undefined;
  if (authLoading || resumingSession) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 0", gap: 12, color: "var(--text-muted)", fontSize: 14 }}>
        <span className="spinner" />
        {resumingSession ? "Resuming your session…" : "Loading…"}
      </div>
    );
  }

  /* ── SETUP ──────────────────────────────────────────────────── */
  if (!session) {
    return (
      <div style={{ paddingBottom: 40 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="page-title">Mock Interview</div>
            <div className="page-subtitle">AI-powered, personalised to your resume and target role</div>
          </div>
        </div>

        <div className="interview-setup">
          <div className="setup-title">Configure Your Session</div>
          <div className="setup-sub">Choose your interview type, level, and role to get started</div>

          <div className="setup-section">
            <div className="setup-section-label">Interview Type</div>
            <div className="pill-options">
              {TYPES.map((t) => (
                <button key={t} className={`pill-option${selType === t ? " selected" : ""}`} onClick={() => setSelType(t)}>
                  {t === "technical" ? "🧑‍💻" : t === "behavioral" ? "🤝" : "🔀"} {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="setup-section">
            <div className="setup-section-label">Experience Level</div>
            <div className="pill-options">
              {LEVELS.map((l) => (
                <button key={l} className={`pill-option${selLevel === l ? " selected" : ""}`} onClick={() => setSelLevel(l)}>
                  {l.charAt(0).toUpperCase() + l.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="setup-section">
            <div className="setup-section-label">Target Role</div>
            <input
              className="input-field"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g. Backend Engineer, Product Manager…"
            />
          </div>

          <div className="setup-section">
            <div className="setup-section-label">Resume Profile</div>
            {profiles.length > 0 ? (
              <select className="input-field" value={selProfile} onChange={(e) => setSelProfile(e.target.value)}>
                {profiles.map((p) => (
                  <option key={p.profile_id} value={p.profile_id}>
                    {formatResumeProfileOptionLabel(p)}
                  </option>
                ))}
              </select>
            ) : (
              <div style={{ fontSize: 13, color: "var(--text-muted)", padding: "12px 0" }}>
                No resume profiles yet.{" "}
                <Link href="/resume" style={{ color: "var(--brand-primary)" }}>Upload your resume →</Link>
              </div>
            )}
          </div>

          <button
            className="btn-primary"
            style={{ width: "100%", justifyContent: "center", padding: 13, fontSize: 14 }}
            onClick={onBegin}
            disabled={!!busy || profiles.length === 0}
          >
            {busy ? <><span className="spinner" style={{ width: 14, height: 14 }} />{busy}</> : "Begin Interview →"}
          </button>

          {profiles.length === 0 && (
            <div style={{ marginTop: 16, textAlign: "center" }}>
              <Link href="/resume" className="btn-secondary" style={{ display: "inline-flex" }}>
                📄 Go to Resume Analyzer first
              </Link>
            </div>
          )}
        </div>

        <div className="card" style={{ marginTop: 28 }}>
          <div className="card-header">
            <div className="card-title">Interview history</div>
            <button type="button" className="btn-secondary" style={{ fontSize: 11, padding: "6px 10px" }} onClick={() => void loadSessionHistory()} disabled={historyLoading}>
              {historyLoading ? "…" : "Refresh"}
            </button>
          </div>
          {sessionHistory.length === 0 ? (
            <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
              Completed and in-progress sessions appear here. Finish an interview to review the full transcript anytime.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {sessionHistory.map((row) => {
                const pct =
                  row.final_report && typeof row.final_report.overall_percent === "number"
                    ? row.final_report.overall_percent
                    : null;
                const when = formatSessionWhen(row.ended_at ?? row.created_at ?? null);
                const status =
                  row.phase === "ended" ? "Completed" : row.phase === "main" ? "In progress" : row.phase;
                return (
                  <div
                    key={row.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      flexWrap: "wrap",
                      padding: "10px 12px",
                      borderRadius: 10,
                      border: "1px solid var(--border)",
                      background: "var(--bg-surface)",
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{row.role}</div>
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {row.interview_type} · {row.level}
                        {when ? ` · ${when}` : ""}
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span className={`tag ${row.phase === "ended" ? "tag-teal" : "tag-amber"}`}>{status}</span>
                      {pct !== null && <span style={{ fontSize: 13, fontWeight: 700 }}>{pct.toFixed(0)}/100</span>}
                      <button
                        type="button"
                        className="btn-primary"
                        style={{ fontSize: 12, padding: "6px 12px" }}
                        disabled={openingHistoryId === row.id}
                        onClick={() => void openHistoryEntry(row)}
                      >
                        {openingHistoryId === row.id ? "…" : "Open"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ── FINAL REPORT ───────────────────────────────────────────── */
  if (session.phase === "ended") {
    const strengths: string[] = Array.isArray(finalReport?.strengths) ? finalReport!.strengths as string[] : [];
    const weaknesses: string[] = Array.isArray(finalReport?.weaknesses) ? finalReport!.weaknesses as string[] : [];
    const grade = gradeFromScore(finalScore ?? 0);

    return (
      <div style={{ paddingBottom: 40 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="page-title">Interview Complete 🎉</div>
            <div className="page-subtitle">
              {displayType} · {displayLevel} · {displayRole}
              {session.ended_at ? ` · ${formatSessionWhen(session.ended_at)}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {openedFromHistory && (
              <button type="button" className="btn-secondary" onClick={() => void onNewSession()}>← Back to setup</button>
            )}
            <button className="btn-secondary" onClick={() => void onNewSession()}>↻ New Interview</button>
            <Link href="/reports" className="btn-primary">View All Reports →</Link>
          </div>
        </div>

        {!finalReport ? (
          <div className="card" style={{ marginBottom: 20, textAlign: "center", padding: "40px 24px" }}>
            <div style={{ fontSize: 32, marginBottom: 16 }}>⏳</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, fontFamily: "'Syne',sans-serif" }}>
              Report is being generated…
            </div>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 20 }}>
              This can take up to 30 seconds. The page will update automatically.
            </p>
            <button
              className="btn-primary"
              style={{ display: "inline-flex" }}
              onClick={() => fetchSession(session.id)}
            >
              <span className="spinner" style={{ width: 13, height: 13 }} /> Refresh Report
            </button>
          </div>
        ) : (
          <>
            <div className="report-hero">
              <div className="report-score-area">
                <div className="big-grade">{grade}</div>
                <div>
                  <div className="report-main-score">{finalScore !== null ? `${finalScore.toFixed(0)} / 100` : "—"}</div>
                  <div className="report-subtitle">
                    {finalScore !== null && finalScore >= 70 ? "Strong performance" : "Good effort — keep practising"}
                  </div>
                  <div className="report-meta">
                    {displayRole} · {displayType} · {displayLevel}
                    {session.ended_at ? ` · ${formatSessionWhen(session.ended_at)}` : ` · ${formatTime(elapsed)} elapsed`}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                    {techScore !== null && (
                      <span className={`tag ${techScore >= 70 ? "tag-teal" : "tag-amber"}`}>
                        Technical: {techScore.toFixed(0)}%
                      </span>
                    )}
                    {structScore !== null && (
                      <span className={`tag ${structScore >= 70 ? "tag-teal" : "tag-amber"}`}>
                        Structure: {structScore.toFixed(0)}%
                      </span>
                    )}
                    {commScore !== null && (
                      <span className={`tag ${commScore >= 70 ? "tag-teal" : "tag-amber"}`}>
                        Communication: {commScore.toFixed(0)}%
                      </span>
                    )}
                    {depthScore !== null && (
                      <span className={`tag ${depthScore >= 70 ? "tag-teal" : "tag-amber"}`}>
                        Depth: {depthScore.toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="strengths-weaknesses">
              <div className="sw-card">
                <div className="sw-title"><div className="sw-dot green" />Strengths</div>
                <div className="sw-list">
                  {strengths.length > 0 ? strengths.map((s, i) => (
                    <div key={i} className="sw-item"><span className="sw-icon">✅</span>{s}</div>
                  )) : (
                    <div className="sw-item"><span className="sw-icon">✅</span>Interview completed — review detailed feedback below</div>
                  )}
                </div>
              </div>
              <div className="sw-card">
                <div className="sw-title"><div className="sw-dot red" />Areas to Improve</div>
                <div className="sw-list">
                  {weaknesses.length > 0 ? weaknesses.map((w, i) => (
                    <div key={i} className="sw-item"><span className="sw-icon">⚠️</span>{w}</div>
                  )) : (
                    <div className="sw-item"><span className="sw-icon">⚠️</span>Keep practising for better scores</div>
                  )}
                </div>
              </div>
            </div>

            {typeof finalReport.coach_note === "string" && (
              <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-header"><div className="card-title">💬 Coach Note</div></div>
                <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>{finalReport.coach_note}</p>
              </div>
            )}

            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header"><div className="card-title">Dimension Scores</div></div>
              <div className="section-list">
                {[
                  { label: "Technical Accuracy", val: techScore },
                  { label: "Answer Structure", val: structScore },
                  { label: "Communication", val: commScore },
                  { label: "Depth & Detail", val: depthScore },
                ].filter((d) => d.val !== null).map((d) => {
                  const pct = Math.min(100, Math.max(0, d.val!));
                  const col = pct >= 70 ? "teal" : pct >= 50 ? "" : "amber";
                  return (
                    <div key={d.label} className="section-row">
                      <div className="section-meta">
                        <span className="section-name">{d.label}</span>
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
            </div>

            {finalReport &&
            Array.isArray(finalReport.technical_jd_score_rationale) &&
            (finalReport.technical_jd_score_rationale as unknown[]).length > 0 ? (
              <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-header"><div className="card-title">Why technical &amp; JD scores look this way</div></div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.65 }}>
                  {(finalReport.technical_jd_score_rationale as string[]).slice(0, 8).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}

        {session.turns.length > 0 && (
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="card-header"><div className="card-title">Conversation transcript</div></div>
            <div
              style={{
                maxHeight: 360,
                overflowY: "auto",
                paddingRight: 6,
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              {session.turns.map((turn, i) => (
                <div key={i} className={`msg${turn.role === "user" ? " user" : " ai"}`}>
                  <div className={`msg-avatar${turn.role === "user" ? " user-av" : " ai"}`}>
                    {turn.role === "user" ? (user?.email?.[0]?.toUpperCase() ?? "U") : "🤖"}
                  </div>
                  <div className="msg-bubble">{turn.content}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {finalReport && Array.isArray(finalReport.missed_opportunities) && (finalReport.missed_opportunities as unknown[]).length > 0 && (
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="card-header"><div className="card-title">Missed opportunities</div></div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>
              {(finalReport.missed_opportunities as string[]).slice(0, 8).map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn-primary" onClick={() => void onNewSession()}>↻ Start New Interview</button>
          <Link href="/reports" className="btn-secondary">📊 View All Reports →</Link>
          <Link href="/resume" className="btn-secondary">📄 Update Resume →</Link>
        </div>
      </div>
    );
  }

  /* ── CLOSING: full-screen wait (matches “Resuming your session…” — no chat underlay) ── */
  if (session.phase === "closing" && !session.final_report) {
    return (
      <div style={{ paddingBottom: 40 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="page-title">Mock Interview</div>
            <div className="page-subtitle">AI-powered · personalised to your resume and target role</div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className="tag tag-amber">● Generating report</span>
            <span className="tag tag-purple">{displayType} · {displayLevel}</span>
          </div>
        </div>
        <InterviewFullscreenWait
          label="Generating your performance report…"
          sub="You'll see scores and narrative feedback here as soon as this finishes — usually within a minute."
        />
        {reportError ? (
          <div style={{ display: "flex", justifyContent: "center", marginTop: 20, gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, color: "var(--danger)" }}>{reportError}</span>
            <button
              type="button"
              className="btn-secondary"
              style={{ fontSize: 12, padding: "6px 10px" }}
              onClick={() => {
                reportFinalizeStartedFor.current = null;
                setReportError(null);
                void fetchSession(session.id);
              }}
              disabled={!!busy}
            >
              Retry report
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  /* ── LIVE SESSION ───────────────────────────────────────────── */
  return (
    <div style={{ paddingBottom: 40 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <div className="page-title">Mock Interview</div>
          <div className="page-subtitle">AI-powered · personalised to your resume and target role</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="tag tag-teal">● Live</span>
          <span className="tag tag-purple">{displayType} · {displayLevel}</span>
        </div>
      </div>

      <div className="interview-session">
        {/* CHAT PANEL */}
        <div className="chat-area">
          <div className="chat-header">
            <div className="ai-avatar">🤖</div>
            <div>
              <div className="ai-name">Alex — AI Interviewer</div>
              <div className="ai-status">● Live session</div>
            </div>
            <div className="interview-timer">{formatTime(elapsed)}</div>
          </div>

          <div className="chat-messages">
            {session.turns.map((turn, i) => (
              <div key={i} className={`msg${turn.role === "user" ? " user" : " ai"}`}>
                <div className={`msg-avatar${turn.role === "user" ? " user-av" : " ai"}`}>
                  {turn.role === "user" ? (user?.email?.[0]?.toUpperCase() ?? "U") : "🤖"}
                </div>
                <div className="msg-bubble">{turn.content}</div>
              </div>
            ))}
            {busy && (
              <div className="msg ai">
                <div className="msg-avatar ai">🤖</div>
                <div className="msg-bubble" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="spinner" style={{ width: 12, height: 12 }} /> Thinking…
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="chat-input-area">
            <textarea
              className="chat-input"
              placeholder="Type your answer… (Ctrl+Enter to send)"
              rows={2}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void onSend();
                }
              }}
              disabled={!!busy}
            />
            <button
              className="btn-primary"
              style={{ padding: "10px 16px", alignSelf: "flex-end" }}
              onClick={onSend}
              disabled={!!busy || !answer.trim()}
            >
              Send ↗
            </button>
          </div>
        </div>

        {/* SIDE PANEL */}
        <div className="interview-panel">
          <div className="panel-sticky-top">
            {/* Quick actions (sticky) */}
            <div className="panel-card">
              <div className="panel-title">Quick Actions</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <button
                  className="btn-danger"
                  style={{ width: "100%", justifyContent: "center", fontSize: 12 }}
                  onClick={() => void onEnd()}
                  disabled={!!busy}
                >
                  {busy && busy.includes("performance report") ? <><span className="spinner" style={{ width: 11, height: 11 }} /> Ending…</> : "⏹ End & Get Report"}
                </button>
                <button
                  className="btn-secondary"
                  style={{ width: "100%", justifyContent: "center", fontSize: 12 }}
                  onClick={() => void endInterviewAndConfigureNew()}
                  disabled={!!busy}
                >
                  ↩ Cancel & restart (no report)
                </button>
              </div>
              <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}>
                {userTurns.length === 0
                  ? "You can end anytime; with no answers the report reflects an incomplete attempt."
                  : `${userTurns.length} answer${userTurns.length > 1 ? "s" : ""} submitted`}
              </div>
            </div>
          </div>

          {coaching ? (
            <div className="panel-card coaching-card">
              <div className="coaching-header">
                <div className="coaching-title">
                  <span className="coaching-title-icon">✦</span>
                  Coaching (latest answer)
                </div>
              </div>
              {coaching.weaknessReason ? (
                <div className="coaching-focus-simple">
                  <strong>Focus:</strong> {coaching.weaknessReason}
                </div>
              ) : null}
              {coaching.strengths.length > 0 ? (
                <div style={{ marginBottom: 10 }}>
                  <div className="coaching-section-title">What landed</div>
                  <ul className="coaching-list">
                    {coaching.strengths.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {coaching.feedback.length > 0 ? (
                <div style={{ marginBottom: coaching.suggestions.length > 0 ? 10 : 0 }}>
                  <div className="coaching-section-title">Feedback</div>
                  <ul className="coaching-list">
                    {coaching.feedback.map((line, i) => <li key={i}>{line}</li>)}
                  </ul>
                </div>
              ) : null}
              {coaching.suggestions.length > 0 ? (
                <div>
                  <div className="coaching-section-title">Suggestions</div>
                  <ul className="coaching-list">
                    {coaching.suggestions.map((line, i) => <li key={i}>{line}</li>)}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Outline roadmap (from session outline) or fallback queue */}
          <div className="panel-card">
            <div className="panel-title">{session.topics && session.topics.length > 0 ? "Interview roadmap" : "Question progress"}</div>
            {session.topics && session.topics.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {currentOutlineTopic && session.phase !== "ended" && session.phase !== "closing" ? (
                  <div
                    style={{
                      padding: "10px 12px",
                      borderRadius: 10,
                      border: "1px solid rgba(148, 95, 255, 0.35)",
                      background: "rgba(148, 95, 255, 0.08)",
                      marginBottom: 2,
                    }}
                  >
                    <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                      Now practicing
                    </div>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>
                      {phaseLabel(currentOutlineTopic.phase)}
                    </div>
                    <div style={{ fontSize: 13, lineHeight: 1.45 }}>
                      {typeof currentOutlineTopic.title === "string" && currentOutlineTopic.title.trim()
                        ? currentOutlineTopic.title
                        : `Segment ${topicIdx + 1}`}
                    </div>
                  </div>
                ) : null}

                <div className="question-queue">
                  {roadmapGroups.map((g, gi) => {
                    const ti = topicIdx;
                    const idxFirst = Math.min(...g.segments.map((s) => s.index));
                    const idxLast = Math.max(...g.segments.map((s) => s.index));
                    const phaseDone = ti > idxLast;
                    const phasePending = ti < idxFirst;
                    const phaseActive = ti >= idxFirst && ti <= idxLast;
                    return (
                      <div
                        key={g.phase + gi}
                        className={`q-item${phaseDone ? " done" : phaseActive ? " current" : ""}`}
                        style={{ alignItems: "flex-start" }}
                      >
                        <div className="q-num">{phaseDone ? "✓" : phaseActive ? "●" : gi + 1}</div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: phaseActive ? 700 : 600, fontSize: 13 }}>
                            {phaseLabel(g.phase)}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6, whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.45 }}>
                            {phaseQuestionBlurb(g.segments)}
                          </div>
                          {phasePending ? (
                            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>Later in the interview</div>
                          ) : null}
                          {phaseActive ? (
                            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>Your current arc</div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="question-queue">
                {session.turns
                  .filter((t) => t.role === "assistant")
                  .map((t, i) => {
                    const topic = t.content.split("?")[0].split(".")[0].slice(0, 44);
                    const isDone = i < aiTurns.length - 1;
                    const isCurrent = i === aiTurns.length - 1;
                    return (
                      <div key={i} className={`q-item${isDone ? " done" : isCurrent ? " current" : ""}`}>
                        <div className="q-num">{isDone ? "✓" : i + 1}</div>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{topic}</div>
                      </div>
                    );
                  })}
              </div>
            )}
            {session.topics_total != null && session.topics_total > 0 && (
              <div style={{ marginTop: 10, fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}>
                Segment {(session.topic_index ?? 0) + 1} of {session.topics_total}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
