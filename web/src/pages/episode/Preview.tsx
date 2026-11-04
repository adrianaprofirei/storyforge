import { useEffect, useMemo, useRef, useState } from "react";
import { post } from "../../api";
import { Badge, Empty, JobStatus, Select, useToast } from "../../components/ui";
import { useFetch } from "../../hooks";

const SHOT_COLORS: Record<string, string> = {
  establishing_wide: "#3b6fb6", wide: "#4a7fc4", medium_wide: "#5b8fd0", two_shot: "#7b6fd6", medium: "#9a5fd0",
  over_the_shoulder: "#b05cc0", medium_close: "#c45a9e", close_up: "#d4576f", extreme_close_up: "#de6a4a", insert: "#c99a2e",
};
const SPEAKER_COLORS = ["#1f9d63", "#2d7ff9", "#c78300", "#d23f45", "#7b6fd6", "#0aa3a3"];

export function PreviewTab({ sid, eid, outputs }: { sid: string; eid: string; outputs: Record<string, any> }) {
  const toast = useToast();
  const presets = Object.keys(outputs || {});
  const [preset, setPreset] = useState<string>(presets.includes("draft") ? "draft" : presets[presets.length - 1] || "");
  const [clean, setClean] = useState(false);
  const [t, setT] = useState(0);
  const [job, setJob] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const tl = useFetch<any>(`/api/series/${sid}/episodes/${eid}/timeline`);

  useEffect(() => {
    // follow the playhead; the <video> element may mount after the timeline loads
    let raf = 0;
    let last = -1;
    const loop = () => {
      const v = video.current;
      if (v && v.currentTime !== last) {
        last = v.currentTime;
        setT(last);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const data = tl.data;
  const lead = data?.lead_seconds || 0;
  const total = (data?.duration || 1) + lead;
  const speakers = useMemo(() => Array.from(new Set((data?.beats || []).filter((b: any) => b.speaker).map((b: any) => b.speaker))) as string[], [data]);
  if (!presets.length) return <Empty>Nothing rendered yet: render a draft from the Overview tab.</Empty>;
  if (!data) return <Empty>Loading…</Empty>;
  const story = t - lead;
  const curShot = data.shots.find((s: any) => story >= s.start && story < s.end);
  const curBeat = data.beats.find((b: any) => story >= b.start && story < b.end);
  const pct = (x: number) => `${(100 * x) / total}%`;
  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * total;
    if (video.current) video.current.currentTime = Math.max(0, Math.min(total - 0.05, x));
  };
  const src = clean ? outputs[preset]?.clean : outputs[preset]?.video;
  const word = curBeat?.words?.find((w: any) => story >= w.start && story < w.end);
  const rerender = async () => {
    if (!curShot) return;
    try {
      setJob((await post(`/api/series/${sid}/episodes/${eid}/shots/${curShot.id}/rerender`, { preset: preset === "final" ? "final" : "draft" })).id);
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  return (
    <div className="player">
      <div className="stack">
        <video ref={video} key={src} src={src} controls playsInline preload="auto" />
        <div className="row">
          <Select value={preset} options={presets} onChange={(v) => setPreset(v || preset)} />
          <label className="check"><input type="checkbox" checked={clean} onChange={(e) => setClean(e.target.checked)} /> clean (no captions)</label>
          <a className="small" href={src} download>download</a>
        </div>
      </div>
      <div className="stack">
        <div className="card">
          <div className="row between">
            <b className="mono">{t.toFixed(2)}s / {total.toFixed(1)}s</b>
            {lead > 0 && story < 0 ? <Badge kind="accent">recap</Badge> : curShot && (
              <span className="row">
                <Badge kind="accent">{curShot.id}</Badge>
                <Badge>{curShot.type.replace(/_/g, " ")}</Badge>
                <Badge>{Math.round(curShot.lens_mm)}mm</Badge>
                {curShot.movement && curShot.movement !== "static" && <Badge>{curShot.movement.replace(/_/g, " ")}</Badge>}
                <button className="small" onClick={rerender}>Re-render this shot</button>
              </span>
            )}
          </div>
          {curBeat && story >= 0 && (
            <div style={{ marginTop: 8 }}>
              <span className="beat-id">{curBeat.id}</span>{" "}
              <b>{curBeat.speaker || "action"}</b>{curBeat.addressee ? <span className="muted"> → {curBeat.addressee}</span> : null}{" "}
              <Badge>{curBeat.emotion}</Badge>
              <div style={{ marginTop: 4 }}>
                {curBeat.words?.length ? curBeat.words.map((w: any, i: number) => (
                  <span key={i} style={{ background: w === word ? "var(--accent-soft)" : undefined, borderRadius: 4, padding: "0 2px" }}>{w.word} </span>
                )) : <span className="muted">{curBeat.action}</span>}
              </div>
            </div>
          )}
        </div>
        {job && <JobStatus jobId={job} />}
        <div className="card lanes">
          <div className="lane-label">Shots</div>
          <div className="lane" onClick={seek}>
            {lead > 0 && <div className="seg" style={{ left: 0, width: pct(lead), background: "#555" }}>recap</div>}
            {data.shots.map((s: any) => (
              <div key={s.id} className={`seg ${curShot?.id === s.id ? "current" : ""}`} title={`${s.id} ${s.type}`}
                style={{ left: pct(lead + s.start), width: pct(s.end - s.start), background: SHOT_COLORS[s.type] || "#777" }}>{s.type.replace(/_/g, " ")}</div>
            ))}
            <div className="playhead" style={{ left: pct(t) }} />
          </div>
          {speakers.map((spk, i) => (
            <div key={spk}>
              <div className="lane-label">{spk}</div>
              <div className="lane" onClick={seek}>
                {data.beats.filter((b: any) => b.speaker === spk).map((b: any) => (
                  <div key={b.id} className={`seg ${curBeat?.id === b.id ? "current" : ""}`} title={b.line}
                    style={{ left: pct(lead + b.start), width: pct(b.end - b.start), background: SPEAKER_COLORS[i % SPEAKER_COLORS.length] }}>{b.line}</div>
                ))}
                <div className="playhead" style={{ left: pct(t) }} />
              </div>
            </div>
          ))}
          <div className="lane-label">Action beats</div>
          <div className="lane" onClick={seek}>
            {data.beats.filter((b: any) => !b.speaker).map((b: any) => (
              <div key={b.id} className={`seg ${curBeat?.id === b.id ? "current" : ""}`} title={b.action}
                style={{ left: pct(lead + b.start), width: pct(b.end - b.start), background: "#6b7086" }}>{b.action}</div>
            ))}
            <div className="playhead" style={{ left: pct(t) }} />
          </div>
          <div className="small muted">Click a lane to jump. Times include the {lead > 0 ? `${lead}s recap lead-in` : "story only"}.</div>
        </div>
      </div>
    </div>
  );
}
