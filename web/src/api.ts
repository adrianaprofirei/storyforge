// Thin typed client for the StoryForge REST API (see storyforge/api/routes.py).

export class ApiError extends Error {
  status: number;
  errors: string[];
  constructor(status: number, message: string, errors: string[] = []) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const init: RequestInit = { method: opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET") };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(path.startsWith("/") ? path : `/api/${path}`, init);
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? data.detail : data;
    if (detail && typeof detail === "object" && Array.isArray(detail.errors)) {
      throw new ApiError(res.status, detail.errors[0] || `HTTP ${res.status}`, detail.errors);
    }
    if (Array.isArray(detail)) {
      const errs = detail.map((d: any) => `${(d.loc || []).join(".")}: ${d.msg}`);
      throw new ApiError(res.status, errs[0] || `HTTP ${res.status}`, errs);
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body: unknown = {}) => api<T>(p, { method: "POST", body });
export const put = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PUT", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

// ---------------------------------------------------------------- shared types
export interface Job {
  id: string;
  kind: string;
  lane: string;
  title: string;
  series?: string;
  episode?: string;
  params: Record<string, any>;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  progress: number;
  message: string;
  eta_seconds?: number | null;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  result?: any;
  error?: string | null;
}

export interface Beat {
  id: string;
  speaker: string | null;
  addressee?: string | null;
  line: string;
  emotion: string;
  intensity: number;
  action: string;
  performance_note: string;
  camera_hint?: string | null;
  beat_type?: string;
  gesture?: string | null;
  motion?: { type: string; character?: string | null; to?: string | null; side?: string | null } | null;
  props?: { character: string; prop: string; action: string; to?: string | null }[];
  fx?: { character: string; type: string }[];
  sfx?: string[];
  delivery?: { pace?: string; volume?: string };
}

export interface Screenplay {
  title: string;
  logline?: string;
  part?: number;
  cast: string[];
  location: string;
  time_of_day: string;
  music_mood?: string;
  hook?: string;
  mini_payoff?: string;
  cliffhanger?: string | null;
  beats: Beat[];
  [k: string]: any;
}

export interface Gate {
  name: string;
  status: "pass" | "warn" | "fail" | "skip";
  summary: string;
  details: any[];
  fix?: Record<string, any> | null;
}

export interface Options {
  emotions: string[];
  gestures: string[];
  locomotion: string[];
  props: string[];
  prop_actions: string[];
  emotion_fx: string[];
  shot_types: string[];
  camera_moves: string[];
  camera_hints: string[];
  beat_types: string[];
  times_of_day: string[];
  music_moods: string[];
  paces: string[];
  volumes: string[];
  styles: string[];
  surfaces: string[];
  rooms: string[];
  grades: Record<string, any>;
  caption_styles: string[];
  locations: Record<string, { name: string; kind: string; description: string }>;
  hair_styles: string[];
  accessories: string[];
  tops: string[];
  bottoms: string[];
  patterns: string[];
  body_keys: string[];
  color_keys: string[];
  voices: { openai: string[]; piper: string[] };
  presets: string[];
  stages: string[];
}

export function fmtSeconds(s?: number | null): string {
  if (s === undefined || s === null || !isFinite(s)) return "–";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtTime(ts?: number | null): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleTimeString();
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
