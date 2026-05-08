/** Shared label for resume profile pickers (mock interview, etc.). */

export type ResumeProfileListItem = {
  profile_id: string;
  version: number;
  jd_id?: string | null;
  profile_data: Record<string, unknown>;
  created_at?: string;
  source_filename?: string | null;
};

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, Math.max(0, max - 1))}…`;
}

/**
 * Human-readable, unique label: display name (or default), optional source file,
 * created time, version, and a short id tail so two v1 profiles never look identical.
 */
export function formatResumeProfileOptionLabel(p: ResumeProfileListItem): string {
  const rawName = typeof p.profile_data?.name === "string" ? p.profile_data.name.trim() : "";
  const displayName = rawName || "Resume profile";

  const file =
    typeof p.source_filename === "string" && p.source_filename.trim()
      ? truncate(p.source_filename.trim(), 42)
      : null;

  let dateStr = "";
  if (typeof p.created_at === "string" && p.created_at) {
    const d = new Date(p.created_at);
    if (!Number.isNaN(d.getTime())) {
      dateStr = d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }

  const ver = p.version ?? 1;
  const idTail = p.profile_id.replace(/-/g, "").slice(0, 8);

  const parts: string[] = [displayName];
  if (file) parts.push(file);
  if (dateStr) parts.push(dateStr);
  parts.push(`v${ver}`);
  parts.push(idTail);
  return parts.join(" · ");
}
