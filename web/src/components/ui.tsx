import { ReactNode, createContext, useCallback, useContext, useState } from "react";
import { ApiError, Job, fmtSeconds, post } from "../api";
import { useJob } from "../hooks";

// ---------------------------------------------------------------- toasts
type Toast = { id: number; text: string; bad?: boolean };
const ToastCtx = createContext<(text: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, bad = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, bad }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), bad ? 8000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.bad ? "bad" : ""}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------- small pieces
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export function Select({ value, options, onChange, allowNone, noneLabel = "—" }: {
  value: string | null | undefined;
  options: (string | { value: string; label: string })[];
  onChange: (v: string | null) => void;
  allowNone?: boolean;
  noneLabel?: string;
}) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}>
      {allowNone && <option value="">{noneLabel}</option>}
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const l = typeof o === "string" ? o.replace(/_/g, " ") : o.label;
        return <option key={v} value={v}>{l}</option>;
      })}
    </select>
  );
}

export function Badge({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`badge ${kind || ""}`}>{children}</span>;
}

export function statusKind(s?: string | null): string {
  switch (s) {
    case "pass":
    case "done":
    case "rendered":
      return "ok";
    case "warn":
    case "queued":
    case "cancelled":
    case "interrupted":
      return "warn";
    case "fail":
    case "failed":
      return "bad";
    case "running":
    case "reviewed":
    case "scripted":
      return "info";
    default:
      return "";
  }
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" title={`${Math.round(value * 100)}%`}>
      <div style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function Errors({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  const list = e.errors && e.errors.length ? e.errors : [e.message || String(error)];
  return (
    <div className="alert bad">
      {list.length === 1 ? list[0] : (
        <>
          <b>{list.length} problems</b>
          <ul>{list.slice(0, 30).map((x, i) => <li key={i}>{x}</li>)}</ul>
        </>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Tabs({ tabs, active, onChange }: {
  tabs: { id: string; label: ReactNode; href?: string }[];
  active: string;
  onChange?: (id: string) => void;
}) {
  return (
    <div className="tabs">
      {tabs.map((t) =>
        t.href ? (
          <a key={t.id} href={t.href} className={active === t.id ? "active" : ""}>{t.label}</a>
        ) : (
          <button key={t.id} className={active === t.id ? "active" : ""} onClick={() => onChange?.(t.id)}>{t.label}</button>
        ),
      )}
    </div>
  );
}

/** Live progress of a job with cancel; calls onDone when it finishes. */
export function JobStatus({ jobId, onDone, compact }: { jobId: string | null; onDone?: (j: Job) => void; compact?: boolean }) {
  const toast = useToast();
  const job = useJob(jobId, (j) => {
    if (j.status === "failed") toast(`${j.title}: ${j.message || "failed"}`, true);
    else if (j.status === "done") toast(`${j.title}: done`);
    onDone?.(j);
  });
  if (!jobId || !job) return null;
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className={`stack ${compact ? "" : "card"}`} style={{ gap: 6 }}>
      <div className="row between">
        <div className="row">
          <span className={`status-dot ${active ? "run" : statusKind(job.status)}`} />
          <b>{job.title}</b>
          <Badge kind={statusKind(job.status)}>{job.status}</Badge>
        </div>
        <div className="row small muted">
          {active && job.eta_seconds ? <span>ETA {fmtSeconds(job.eta_seconds)}</span> : null}
          <a href={`#/queue/${job.id}`}>log</a>
          {active && <button className="small danger" onClick={() => post(`/api/jobs/${job.id}/cancel`)}>Cancel</button>}
        </div>
      </div>
      {active && <Progress value={job.progress} />}
      <div className="small muted ellipsis">{job.status === "failed" ? job.error?.split("\n")[0] : job.message}</div>
    </div>
  );
}

export function Kv({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
