/**
 * Normalise mock-interview turn evaluations from the API for live / aggregate UI.
 * API shape: { scores: { technical, structure, clarity }, average, weak }.
 */

export type MockEvalTurn = {
  role: string;
  content: string;
  evaluation: Record<string, unknown> | null;
};

/** Backend may return Gemini scores 0–10; UI uses 0–100 for bars. */
export function scoreToPercent(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n <= 10) return Math.min(100, Math.max(0, n * 10));
  return Math.min(100, Math.max(0, n));
}

export type LiveEvalMetrics = {
  technical: number;
  structure: number;
  communication: number;
  depth: number;
};

/** Running averages of per-answer scores from user turns. */
export function liveEvalAverages(turns: MockEvalTurn[]): LiveEvalMetrics | null {
  const rows: LiveEvalMetrics[] = [];

  for (const t of turns) {
    if (t.role !== "user" || !t.evaluation) continue;
    const ev = t.evaluation as Record<string, unknown>;
    // Policy / guardrail refusals are not real interview answers — omit from skill averages
    if (ev.policy_block) continue;
    // Semantically off-topic or non-answers (evaluator did not connect to the question)
    if (ev.exclude_from_live_scores) continue;
    const scores = ev.scores as Record<string, unknown> | undefined;

    if (scores && typeof scores === "object") {
      const rawT = scores.technical;
      const rawS = scores.structure;
      const rawC = scores.clarity;
      if (typeof rawT === "number" && typeof rawS === "number") {
        const technical = scoreToPercent(rawT);
        const structure = scoreToPercent(rawS);
        const communication =
          typeof rawC === "number" ? scoreToPercent(rawC) : (technical + structure) / 2;
        const depth = (technical + communication) / 2;
        rows.push({ technical, structure, communication, depth });
        continue;
      }
    }

    const ta = ev.technical_accuracy;
    const st = ev.answer_structure;
    const co = ev.communication;
    const de = ev.depth_and_detail;
    if (typeof ta === "number" && typeof st === "number") {
      const technical = scoreToPercent(ta);
      const structure = scoreToPercent(st);
      const communication = typeof co === "number" ? scoreToPercent(co) : (technical + structure) / 2;
      const depth =
        typeof de === "number" ? scoreToPercent(de) : (technical + communication) / 2;
      rows.push({ technical, structure, communication, depth });
    }
  }

  if (!rows.length) return null;
  const n = rows.length;
  return {
    technical: rows.reduce((a, b) => a + b.technical, 0) / n,
    structure: rows.reduce((a, b) => a + b.structure, 0) / n,
    communication: rows.reduce((a, b) => a + b.communication, 0) / n,
    depth: rows.reduce((a, b) => a + b.depth, 0) / n,
  };
}
