/**
 * When `NEXT_PUBLIC_API_URL` is unset in the browser, requests use same-origin `/api/...`
 * and Next.js rewrites them to the backend (see `next.config.mjs`). This avoids CORS and
 * mixed localhost vs 127.0.0.1 issues during local dev.
 */
function clientBase(): string {
  if (typeof window === "undefined") return "";
  return process.env.NEXT_PUBLIC_API_URL?.trim() || "";
}

function serverBase(): string {
  return process.env.NEXT_PUBLIC_API_URL?.trim() || "http://127.0.0.1:8080";
}

function apiBase(): string {
  return typeof window === "undefined" ? serverBase() : clientBase() || "";
}

function joinUrl(path: string): string {
  const base = apiBase();
  if (!base) return path.startsWith("/") ? path : `/${path}`;
  const b = base.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

async function doFetch(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (e) {
    const hint =
      "Cannot reach the API. Start the FastAPI server (e.g. port 8080). " +
      "If the app is on localhost but the API was on 127.0.0.1, leave NEXT_PUBLIC_API_URL unset " +
      "so this app proxies `/api` through Next.js, or set NEXT_PUBLIC_API_URL to the exact backend URL.";
    if (e instanceof TypeError) throw new Error(hint);
    throw e;
  }
}

/** FastAPI exposes `detail` as string | object | validation array */
export function parseApiError(payload: unknown): string {
  if (payload !== null && typeof payload === "object" && "detail" in payload) {
    const d = (payload as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      const parts = d
        .map((e) =>
          typeof e === "object" && e !== null && "msg" in e ? String((e as { msg: unknown }).msg) : "",
        )
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
    if (d !== null && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  return "";
}

async function parseJsonSafe(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return {};
  }
}

function bearerAuth(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const t = localStorage.getItem("access_token") ?? "";
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await doFetch(joinUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...bearerAuth(),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await parseJsonSafe(res);
  if (!res.ok) {
    throw new Error(parseApiError(data) || res.statusText);
  }
  return data as T;
}

/**
 * Direct-to-backend POST that bypasses the Next.js dev-server rewrite proxy.
 *
 * Use this for long-running calls (e.g. `/analyze`) where the Next.js rewrite
 * proxy closes the socket after ~60 s, causing ECONNRESET. The backend exposes
 * permissive CORS for the dev origin, so the browser can talk to it directly.
 */
export async function apiPostDirect<T>(path: string, body: unknown): Promise<T> {
  const base =
    (typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_BACKEND_URL?.trim() ||
        process.env.NEXT_PUBLIC_API_URL?.trim() ||
        "http://127.0.0.1:8080"
      : "http://127.0.0.1:8080"
    ).replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  const res = await doFetch(`${base}${p}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...bearerAuth(),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await parseJsonSafe(res);
  if (!res.ok) {
    throw new Error(parseApiError(data) || res.statusText);
  }
  return data as T;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await doFetch(joinUrl(path), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...bearerAuth(),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await parseJsonSafe(res);
  if (!res.ok) {
    throw new Error(parseApiError(data) || res.statusText);
  }
  return data as T;
}

export async function apiGetJson<T>(path: string): Promise<T> {
  const res = await doFetch(joinUrl(path), {
    headers: {
      ...bearerAuth(),
    },
    cache: "no-store",
  });
  const data = await parseJsonSafe(res);
  if (!res.ok) {
    throw new Error(parseApiError(data) || res.statusText);
  }
  return data as T;
}

/** Multipart uploads; omit Content-Type so the browser sets the boundary */
export async function apiUploadFile(path: string, file: File, fieldName = "file"): Promise<unknown> {
  const form = new FormData();
  form.append(fieldName, file);

  const res = await doFetch(joinUrl(path), {
    method: "POST",
    headers: {
      ...bearerAuth(),
    },
    body: form,
    cache: "no-store",
  });
  const data = await parseJsonSafe(res);
  if (!res.ok) {
    throw new Error(parseApiError(data) || res.statusText);
  }
  return data;
}

/** Human-readable base URL for settings / footer */
export function pickApiUrl(): string {
  const v = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (v) return v;
  if (typeof window !== "undefined") {
    return `${window.location.origin}/api → backend (see next.config rewrites)`;
  }
  return "http://127.0.0.1:8080";
}
