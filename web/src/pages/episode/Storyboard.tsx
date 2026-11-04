import { useState } from "react";
import { post } from "../../api";
import { Badge, Empty, JobStatus, useToast } from "../../components/ui";
import { useFetch } from "../../hooks";

export function StoryboardTab({ sid, eid }: { sid: string; eid: string }) {
  const toast = useToast();
  const board = useFetch<any>(`/api/series/${sid}/episodes/${eid}/storyboard`);
  const [job, setJob] = useState<string | null>(null);
  const make = async () => {
    try {
      setJob((await post(`/api/series/${sid}/episodes/${eid}/storyboard`)).id);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const shots: any[] = board.data?.shots || [];
  return (
    <div className="stack">
      <div className="card row between">
        <div>
          <h2 style={{ margin: 0 }}>Storyboard</h2>
          <div className="small muted">One proxy still per shot (its middle frame), rendered from the real scene: check framing before a full render.</div>
        </div>
        <button className="primary" onClick={make} disabled={!!job}>{shots.length ? "Refresh storyboard" : "Generate storyboard"}</button>
      </div>
      {job && <JobStatus jobId={job} onDone={() => { setJob(null); board.reload(); }} />}
      {!shots.length && !job && <Empty>No storyboard yet.</Empty>}
      <div className="thumb-grid">
        {shots.map((s) => (
          <div key={s.shot} className="thumb">
            <a href={s.url} target="_blank" rel="noreferrer"><img src={s.url} alt={s.shot} loading="lazy" /></a>
            <div className="meta">
              <div className="row between"><b className="mono">{s.shot}</b><span className="muted">{s.start?.toFixed(1)}s</span></div>
              <div className="chip-row" style={{ margin: "4px 0" }}>
                <Badge kind="accent">{s.type?.replace(/_/g, " ")}</Badge>
                {s.movement && s.movement !== "static" && <Badge>{s.movement.replace(/_/g, " ")}</Badge>}
                <Badge>{Math.round(s.lens_mm)}mm</Badge>
              </div>
              <div className="small"><b>{s.speaker || "action"}</b> <span className="muted">{(s.line || s.action || "").slice(0, 80)}</span></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
