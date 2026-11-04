import { useEffect, useRef, useState } from "react";
import { Job, del, fmtSeconds, fmtTime, get, post } from "../api";
import { Badge, Empty, Progress, Select, statusKind, useToast } from "../components/ui";
import { go, useFetch, useInterval } from "../hooks";

export function QueuePage({ jobId }: { jobId?: string }) {
  const toast = useToast();
  const [status, setStatus] = useState<string | null>(null);
  const jobs = useFetch<Job[]>(`/api/jobs?limit=200${status ? `&status=${status}` : ""}`, [status]);
  useInterval(() => jobs.reload(), 1500);
  const list = jobs.data || [];
  const active = list.filter((j) => j.status === "running" || j.status === "queued");
  const act = async (fn: () => Promise<any>, msg: string) => {
    try {
      await fn();
      toast(msg);
      jobs.reload();
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Render queue</h1>
          <p>{active.length} active · lanes run in parallel (story, render, preview); jobs touching the same episode wait for each other.</p>
        </div>
        <Select value={status} allowNone noneLabel="all statuses" options={["running", "queued", "done", "failed", "cancelled", "interrupted"]} onChange={setStatus} />
      </div>
      <div className="grid" style={{ gridTemplateColumns: jobId ? "minmax(0, 1.1fr) minmax(0, 1fr)" : "1fr", alignItems: "start" }}>
        <div className="card table-wrap">
          {!list.length ? <Empty>No jobs yet.</Empty> : (
            <table>
              <thead><tr><th>Job</th><th>Lane</th><th>Status</th><th style={{ width: 160 }}>Progress</th><th>ETA</th><th>Created</th><th /></tr></thead>
              <tbody>
                {list.map((j) => (
                  <tr key={j.id} className={j.id === jobId ? "selected" : ""} onClick={() => go(`queue/${j.id}`)} style={{ cursor: "pointer" }}>
                    <td>
                      <div><b>{j.title}</b></div>
                      <div className="small muted ellipsis" style={{ maxWidth: 360 }}>{j.status === "failed" ? j.error?.split("\n")[0] : j.message}</div>
                    </td>
                    <td><Badge>{j.lane}</Badge></td>
                    <td><Badge kind={statusKind(j.status)}>{j.status}</Badge></td>
                    <td>{j.status === "running" ? <Progress value={j.progress} /> : j.status === "done" ? <span className="small muted">100%</span> : null}</td>
                    <td className="small nowrap">{j.status === "running" ? fmtSeconds(j.eta_seconds) : j.finished_at && j.started_at ? <span className="muted">took {fmtSeconds(j.finished_at - j.started_at)}</span> : "–"}</td>
                    <td className="small muted nowrap">{fmtTime(j.created_at)}</td>
                    <td className="nowrap" onClick={(e) => e.stopPropagation()}>
                      {(j.status === "running" || j.status === "queued") && <button className="small danger" onClick={() => act(() => post(`/api/jobs/${j.id}/cancel`), "Cancel requested")}>Cancel</button>}
                      {["failed", "cancelled", "interrupted", "done"].includes(j.status) && <button className="small" onClick={() => act(() => post(`/api/jobs/${j.id}/retry`), "Re-queued")}>Retry</button>}
                      {!["running", "queued"].includes(j.status) && <button className="small ghost" onClick={() => act(() => del(`/api/jobs/${j.id}`), "Removed")}>×</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {jobId && <JobDetail jobId={jobId} />}
      </div>
    </div>
  );
}

function JobDetail({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [log, setLog] = useState("");
  const offset = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    offset.current = 0;
    setLog("");
  }, [jobId]);
  const poll = async () => {
    try {
      const [j, l] = await Promise.all([get<Job>(`/api/jobs/${jobId}`), get<{ text: string; offset: number }>(`/api/jobs/${jobId}/log?offset=${offset.current}`)]);
      setJob(j);
      if (l.text) {
        offset.current = l.offset;
        setLog((x) => (x + l.text).slice(-400_000));
        requestAnimationFrame(() => box.current && (box.current.scrollTop = box.current.scrollHeight));
      }
    } catch {
      /* ignore */
    }
  };
  useEffect(() => { poll(); }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(poll, job && ["done", "failed", "cancelled", "interrupted"].includes(job.status) ? null : 1000);
  if (!job) return <div className="card"><Empty>Loading…</Empty></div>;
  const outputs: any[] = job.result?.outputs || (job.result?.parts || []).flatMap((p: any) => p.outputs || []);
  return (
    <div className="card stack">
      <div className="row between">
        <h3 style={{ margin: 0 }}>{job.title}</h3>
        <Badge kind={statusKind(job.status)}>{job.status}</Badge>
      </div>
      {job.status === "running" && <><Progress value={job.progress} /><div className="small muted">{job.message} · ETA {fmtSeconds(job.eta_seconds)}</div></>}
      {job.status === "failed" && <div className="alert bad small"><pre>{job.error}</pre></div>}
      {job.series && job.episode && <div className="small"><a href={`#/s/${job.series}/ep/${job.episode}`}>open episode →</a></div>}
      {outputs.length > 0 && (
        <div className="small">
          <b>Downloads</b>
          <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
            {outputs.filter((o) => !o.name.startsWith("thumbnails/")).map((o) => (
              <li key={o.path}><a href={`/api/files/${job.series}/${o.path}`} target="_blank" rel="noreferrer">{o.name}</a></li>
            ))}
          </ul>
        </div>
      )}
      <div className="log" ref={box}>{log || "…"}</div>
    </div>
  );
}
