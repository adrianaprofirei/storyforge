import { useState } from "react";
import { fmtBytes, fmtTime, post } from "../api";
import { Badge, Empty, JobStatus, Kv, Select, Tabs, statusKind, useToast } from "../components/ui";
import { useFetch } from "../hooks";
import { ScriptTab } from "./episode/Script";
import { ShotsTab } from "./episode/Shots";
import { StoryboardTab } from "./episode/Storyboard";
import { PreviewTab } from "./episode/Preview";
import { QualityTab } from "./episode/Quality";

export function EpisodePage({ sid, eid, tab }: { sid: string; eid: string; tab: string }) {
  const ep = useFetch<any>(`/api/series/${sid}/episodes/${eid}`, [tab]);
  if (ep.error) return <Empty>{ep.error.message}</Empty>;
  if (!ep.data) return <Empty>Loading…</Empty>;
  const e = ep.data;
  const tabs = [
    { id: "overview", label: "Overview" }, { id: "script", label: "Script" }, { id: "shots", label: "Shot list" },
    { id: "storyboard", label: "Storyboard" }, { id: "preview", label: "Preview" }, { id: "quality", label: "Quality" },
  ].map((t) => ({ ...t, href: `#/s/${sid}/ep/${eid}/${t.id}` }));
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{e.title || eid}</h1>
          <p>{e.arc_id ? <>Part {e.part}{e.parts_total ? ` of ${e.parts_total}` : ""} · <a href={`#/s/${sid}/arcs/${e.arc_id}`}>{e.arc_id}</a> · </> : null}
            <Badge kind={statusKind(e.status)}>{e.status || "planned"}</Badge></p>
        </div>
      </div>
      <Tabs tabs={tabs} active={tab} />
      {tab === "overview" && <Overview sid={sid} eid={eid} ep={e} reload={ep.reload} />}
      {tab === "script" && <ScriptTab sid={sid} eid={eid} />}
      {tab === "shots" && <ShotsTab sid={sid} eid={eid} />}
      {tab === "storyboard" && <StoryboardTab sid={sid} eid={eid} />}
      {tab === "preview" && <PreviewTab sid={sid} eid={eid} outputs={e.outputs} />}
      {tab === "quality" && <QualityTab sid={sid} eid={eid} />}
    </div>
  );
}

function Overview({ sid, eid, ep, reload }: { sid: string; eid: string; ep: any; reload: () => void }) {
  const toast = useToast();
  const [preset, setPreset] = useState("draft");
  const [ignore, setIgnore] = useState(false);
  const [job, setJob] = useState<string | null>(null);
  const llm = useFetch<any[]>(`/api/series/${sid}/episodes/${eid}/llm`);
  const run = async (body: any) => {
    try {
      const j = await post(`/api/series/${sid}/episodes/${eid}/run`, body);
      setJob(j.id);
    } catch (x: any) {
      toast(x.message, true);
    }
  };
  const stages = Object.entries(ep.stages || {}) as [string, any][];
  const tokens = (llm.data || []).reduce((acc, c) => ({ in: acc.in + (c.usage?.input_tokens || 0), out: acc.out + (c.usage?.output_tokens || 0) }), { in: 0, out: 0 });

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head"><h2>Produce</h2></div>
        <div className="row">
          <button onClick={() => run({ until: "continuity_log" })}>{ep.has_screenplay ? "Re-review script" : "Write script"}</button>
          {ep.has_screenplay && <button onClick={() => { if (confirm("Write a completely new screenplay for this part? Your beat edits are kept only if beat ids still exist.")) run({ until: "continuity_log", regenerate: true }); }}>Rewrite from scratch</button>}
          <span className="spacer" />
          <Select value={preset} options={[{ value: "proxy", label: "proxy (270×480, fastest)" }, { value: "draft", label: "draft 540×960 (EEVEE)" }, { value: "final", label: "final 1080×1920 (Cycles)" }, { value: "final_4k", label: "final 4K 2160×3840" }]} onChange={(v) => setPreset(v || "draft")} />
          <label className="check"><input type="checkbox" checked={ignore} onChange={(x) => setIgnore(x.target.checked)} /> ignore failing gates</label>
          <button className="primary" onClick={() => run({ preset, ignore_gates: ignore })}>Render</button>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>Everything is cached by content: only stages (and shots) whose inputs changed run again. Interrupted renders resume.</div>
      </div>
      {job && <JobStatus jobId={job} onDone={() => reload()} />}
      <div className="grid cols-2">
        <div className="card">
          <h3>Outputs</h3>
          {ep.files?.length ? (
            <table>
              <tbody>
                {ep.files.filter((f: any) => !f.name.startsWith("thumbnails/") || f.name.includes("_1")).map((f: any) => (
                  <tr key={f.path}>
                    <td><a href={f.url} target="_blank" rel="noreferrer" download={f.name.endsWith(".mp4") ? undefined : f.name}>{f.name}</a></td>
                    <td className="right muted small nowrap">{fmtBytes(f.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="muted">Nothing rendered yet.</div>}
          {ep.files?.some((f: any) => f.name.startsWith("thumbnails/")) && (
            <div className="row" style={{ marginTop: 10 }}>
              {ep.files.filter((f: any) => f.name.startsWith("thumbnails/")).slice(0, 6).map((f: any) => (
                <a key={f.path} href={f.url} target="_blank" rel="noreferrer"><img src={f.url} alt={f.name} style={{ height: 120, borderRadius: 8 }} /></a>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h3>Pipeline</h3>
          <table>
            <thead><tr><th>Stage</th><th>Last run</th><th className="right">Time</th></tr></thead>
            <tbody>
              {stages.map(([name, r]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td className="small muted">{fmtTime(r.finished_at)}</td>
                  <td className="right small">{r.seconds != null ? `${Number(r.seconds).toFixed(1)}s` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {llm.data && llm.data.length > 0 && (
            <div className="small muted" style={{ marginTop: 10 }}>
              LLM: {llm.data.length} calls, {tokens.in.toLocaleString()} input / {tokens.out.toLocaleString()} output tokens
              {llm.data.some((c) => c.cached) && ` (${llm.data.filter((c) => c.cached).length} from cache)`}
            </div>
          )}
        </div>
      </div>
      {ep.jobs?.length > 0 && (
        <div className="card">
          <h3>Recent jobs</h3>
          <table>
            <tbody>
              {ep.jobs.map((j: any) => (
                <tr key={j.id}>
                  <td><a href={`#/queue/${j.id}`}>{j.title}</a></td>
                  <td><Badge kind={statusKind(j.status)}>{j.status}</Badge></td>
                  <td className="small muted">{fmtTime(j.created_at)}</td>
                  <td className="small muted ellipsis" style={{ maxWidth: 380 }}>{j.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Kv items={[["Episode id", <code key="i">{eid}</code>]]} />
    </div>
  );
}
