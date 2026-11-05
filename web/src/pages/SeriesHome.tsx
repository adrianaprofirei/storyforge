import { useState } from "react";
import { post } from "../api";
import { Badge, Empty, JobStatus, statusKind, useToast } from "../components/ui";
import { useFetch } from "../hooks";

export function SeriesHome({ sid }: { sid: string }) {
  const toast = useToast();
  const ser = useFetch<any>(`/api/series/${sid}`);
  const eps = useFetch<any[]>(`/api/series/${sid}/episodes`);
  const [job, setJob] = useState<string | null>(null);

  const runArc = async (aid: string, body: any) => {
    try {
      const j = await post(`/api/series/${sid}/arcs/${aid}/run`, body);
      setJob(j.id);
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  if (!ser.data || !eps.data) return <Empty>Loading…</Empty>;
  const byArc: Record<string, any[]> = {};
  for (const e of eps.data) (byArc[e.arc_id || "_"] ||= []).push(e);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{ser.data.title}</h1>
          <p>{ser.data.logline}</p>
        </div>
        <div className="row">
          <a className="btn" href={`#/s/${sid}/arcs`}>Plan a new arc</a>
        </div>
      </div>
      {job && <JobStatus jobId={job} onDone={() => eps.reload()} />}
      {ser.data.arcs.length === 0 && <Empty>No arcs yet. <a href={`#/s/${sid}/arcs`}>Plan one from an idea.</a></Empty>}
      {ser.data.arcs.map((arc: any) => (
        <div key={arc.arc_id} className="card">
          <div className="card-head">
            <div>
              <h2><a href={`#/s/${sid}/arcs/${arc.arc_id}`}>{arc.title}</a></h2>
              <div className="small muted">{arc.premise}</div>
            </div>
            <div className="row">
              <button onClick={() => runArc(arc.arc_id, { until: "continuity_log" })}>Write &amp; review all</button>
              <button onClick={() => runArc(arc.arc_id, { preset: "draft" })}>Render drafts</button>
              <button className="primary" onClick={() => runArc(arc.arc_id, { preset: "final" })}>Render finals</button>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Part</th><th>Title</th><th>Status</th><th>Continuity</th><th>Outputs</th><th /></tr></thead>
              <tbody>
                {(byArc[arc.arc_id] || []).map((e) => (
                  <tr key={e.id}>
                    <td>{e.part}/{arc.parts.length}</td>
                    <td><a href={`#/s/${sid}/ep/${e.id}`}>{e.title || e.id}</a></td>
                    <td><Badge kind={statusKind(e.status)}>{e.status || "planned"}</Badge></td>
                    <td>{e.continuity ? (
                      e.continuity.error ? <Badge kind="bad">{e.continuity.error} errors</Badge>
                        : e.continuity.warning ? <Badge kind="warn">{e.continuity.warning} warnings</Badge> : <Badge kind="ok">clean</Badge>
                    ) : <span className="muted">–</span>}</td>
                    <td>
                      <div className="row">
                        {Object.entries(e.outputs || {}).map(([preset, o]: any) => (
                          <a key={preset} href={o.video} target="_blank" rel="noreferrer">
                            <Badge kind={o.quality === false ? "bad" : o.quality ? "ok" : ""}>{preset}</Badge>
                          </a>
                        ))}
                        {!Object.keys(e.outputs || {}).length && <span className="muted">–</span>}
                      </div>
                    </td>
                    <td className="right"><a href={`#/s/${sid}/ep/${e.id}/script`}>script</a> · <a href={`#/s/${sid}/ep/${e.id}/preview`}>preview</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {byArc["_"] && (
        <div className="card">
          <h2>Standalone episodes</h2>
          {byArc["_"].map((e) => <div key={e.id}><a href={`#/s/${sid}/ep/${e.id}`}>{e.title || e.id}</a></div>)}
        </div>
      )}
    </div>
  );
}
