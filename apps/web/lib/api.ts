"use client";

import type { StarkEvent } from "./types";

const KEY_URL = "stark.apiUrl";
const KEY_TOKEN = "stark.token";

function stores(): Storage[] {
  const out: Storage[] = [];
  try {
    out.push(window.sessionStorage);
  } catch {
    /* unavailable */
  }
  try {
    out.push(window.localStorage);
  } catch {
    /* unavailable */
  }
  return out;
}

function safeGet(key: string): string | null {
  for (const st of stores()) {
    try {
      const v = st.getItem(key);
      if (v) return v;
    } catch {
      /* ignore */
    }
  }
  return null;
}

export interface Connection {
  url: string;
  token: string;
  remember?: boolean;
}

export function loadConnection(): Connection | null {
  if (typeof window === "undefined") return null;
  const url = safeGet(KEY_URL) || process.env.NEXT_PUBLIC_STARK_API_URL || "http://127.0.0.1:8000";
  const token = safeGet(KEY_TOKEN);
  return token ? { url, token } : null;
}

/** The token lives in sessionStorage (cleared when the tab closes) unless the user ticks "remember". */
export function saveConnection(c: Connection | null) {
  for (const st of stores()) {
    try {
      st.removeItem(KEY_URL);
      st.removeItem(KEY_TOKEN);
    } catch {
      /* ignore */
    }
  }
  if (!c) return;
  const [session, local] = stores();
  const target = c.remember ? local || session : session || local;
  try {
    target?.setItem(KEY_URL, c.url);
    target?.setItem(KEY_TOKEN, c.token);
  } catch {
    /* storage unavailable: connection lasts for this page only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class StarkClient {
  constructor(private conn: Connection) {}

  get url() {
    return this.conn.url.replace(/\/$/, "");
  }

  async req<T = any>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${this.url}${path}`, {
      ...init,
      headers: {
        authorization: `Bearer ${this.conn.token}`,
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      } catch {
        /* non-JSON error */
      }
      throw new ApiError(res.status, detail);
    }
    const ct = res.headers.get("content-type") || "";
    return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
  }

  get<T = any>(path: string) {
    return this.req<T>(path);
  }
  post<T = any>(path: string, body?: unknown) {
    return this.req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
  }
  patch<T = any>(path: string, body: unknown) {
    return this.req<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  }
  del<T = any>(path: string) {
    return this.req<T>(path, { method: "DELETE" });
  }
  /** A binary response (e.g. a generated image) with the token in the header, never in the URL. */
  async blob(path: string): Promise<Blob> {
    const res = await fetch(`${this.url}${path}`, { headers: { authorization: `Bearer ${this.conn.token}` } });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  }

  /** Server-sent events. EventSource cannot set headers, so the token travels as a query parameter
   * (the API never writes access logs). The browser retries dropped connections itself; if the server
   * answers with an error status the stream closes for good, so we reopen it with backoff. */
  events(onEvent: (e: StarkEvent) => void, onState: (connected: boolean) => void): () => void {
    let es: EventSource | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let delay = 1000;
    const open = () => {
      if (stopped) return;
      es = new EventSource(`${this.url}/api/events?token=${encodeURIComponent(this.conn.token)}`);
      es.onopen = () => {
        delay = 1000;
        onState(true);
      };
      es.onerror = () => {
        onState(false);
        if (es && es.readyState === EventSource.CLOSED && !stopped) {
          retry = setTimeout(open, delay);
          delay = Math.min(delay * 2, 30_000);
        }
      };
      es.onmessage = (m) => {
        try {
          onEvent(JSON.parse(m.data));
        } catch {
          /* ignore malformed */
        }
      };
    };
    open();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      es?.close();
    };
  }
}
