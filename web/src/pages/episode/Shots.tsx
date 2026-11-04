import { useEffect, useMemo, useState } from "react";
import { post, put } from "../../api";
import { OptionsContext } from "../../App";
import { Badge, Empty, Errors, JobStatus, Select, useToast } from "../../components/ui";
import { useFetch } from "../../hooks";

export function ShotsTab({ sid, eid }: { sid: string; eid: string }) {
  const toast = useToast();
  const opts = OptionsContext.current!;
  const data = useFetch<any>(`/api/series/${sid}/episodes/${eid}/shots`);
  const tl = useFetch<any>(`/api/series/${sid}/episodes/${eid}/timeline`);
  const [ov, setOv] = useState<Record<string, any>>({});
  const [err, setErr] = useState<unknown>(null);
  const [job, setJob] = useState<string | null>(null);
  const [preset, setPreset] = useState("draft");

  useEffect(() => { if (data.data) setOv(JSON.parse(JSON.stringify(data.data.overrides || {}))); }, [data.data]);
  const dirty = useMemo(() => data.data && JSON.stringify(ov) !== JSON.stringify(data.data.overrides || {}), [ov, data.data]);
  if (!data.data) return <Empty>Loading…</Empty>;
  if (!data.data.shotlist) return <Empty>No shot list yet: run the episode at least once (any preset).</Empty>;
  const shots: any[] = data.data.shotlist.shots;
  const beats: Record<string, any> = Object.fromEntries((tl.data?.beats || []).map((b: any) => [b.id, b]));
  const thumbs: Record<string, string> = Object.fromEntries((data.data.storyboard?.shots || []).map((s: any) => [s.shot, s.url]));
  const cast: string[] = tl.data?.cast || [];
  const auto = data.data.auto_overrides || {};

  const setField = (id: string, k: string, v: any) => setOv((o) => {
    const n = { ...o, [id]: { ...(o[id] || {}) } };
    if (v === null || v === "" || v === undefined) delete n[id][k]; else n[id][k] = v;
    if (!Object.keys(n[id]).length) delete n[id];
    return n;
  });
  const save = async (then?: any) => {
    setErr(null);
    try {
      await put(`/api/series/${sid}/episodes/${eid}/shots/overrides`, ov);
      toast("Shot overrides saved");
      if (then) setJob((await post(`/api/series/${sid}/episodes/${eid}/run`, then)).id);
      else data.reload();
    } catch (e) {
      setErr(e);
    }
  };
  const rerender = async (shot: string) => {
    try {
      if (dirty) await put(`/api/series/${sid}/episodes/${eid}/shots/overrides`, ov);
      setJob((await post(`/api/series/${sid}/episodes/${eid}/shots/${shot}/rerender`, { preset })).id);
    } catch (e: any) {
      toast(e.message, true);
    }
  };

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>Shot list</h2>
            <div className="small muted">Designed automatically (film grammar: establishing → coverage, 180° rule, eyelines, no jump cuts, cut on action). Override any shot; only changed shots re-render.</div>
          </div>
          <div className="row">
            <Select value={preset} options={["proxy", "draft", "final"]} onChange={(v) => setPreset(v || "draft")} />
            <button disabled={!dirty} onClick={() => setOv(JSON.parse(JSON.stringify(data.data.overrides || {})))}>Discard</button>
            <button disabled={!dirty} onClick={() => save()}>Save overrides</button>
            <button className="primary" onClick={() => save({ preset })}>Save &amp; render {preset}</button>
          </div>
        </div>
        <Errors error={err} />
      </div>
      {job && <JobStatus jobId={job} onDone={() => data.reload()} />}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th /><th>Shot</th><th>Time</th><th>Beat</th><th>Type</th><th>Lens</th><th>Move</th><th>Subject</th><th>Why</th><th /></tr>
          </thead>
          <tbody>
            {shots.map((s) => {
              const o = ov[s.id] || {};
              const b = beats[s.beat] || {};
              return (
                <tr key={s.id} className={ov[s.id] ? "overridden" : ""}>
                  <td style={{ width: 52 }}>{thumbs[s.id] ? <img src={thumbs[s.id]} alt="" style={{ width: 44, borderRadius: 4 }} /> : null}</td>
                  <td className="mono nowrap">{s.id}{auto[s.id] && <div><Badge kind="info">auto-fix</Badge></div>}</td>
                  <td className="small nowrap">{s.start.toFixed(1)}–{s.end.toFixed(1)}s</td>
                  <td className="small" style={{ maxWidth: 260 }}>
                    <b>{b.speaker || "action"}</b> <span className="muted">{(b.line || b.action || "").slice(0, 90)}</span>
                  </td>
                  <td style={{ minWidth: 130 }}><Select value={o.type ?? s.type} options={opts.shot_types} onChange={(v) => setField(s.id, "type", v === s.type && !o.type ? null : v)} /></td>
                  <td style={{ width: 80 }}><input type="number" value={o.lens_mm ?? Math.round(s.lens_mm)} onChange={(e) => setField(s.id, "lens_mm", Number(e.target.value))} /></td>
                  <td style={{ minWidth: 120 }}><Select value={o.movement ?? s.movement?.type} options={["static", ...opts.camera_moves]} onChange={(v) => setField(s.id, "movement", v)} /></td>
                  <td style={{ minWidth: 100 }}><Select value={o.subject ?? s.subject} options={cast} onChange={(v) => setField(s.id, "subject", v)} /></td>
                  <td className="small muted" style={{ maxWidth: 220 }}>{s.reason}</td>
                  <td className="nowrap">
                    {ov[s.id] && <button className="small ghost" onClick={() => setOv((x) => { const n = { ...x }; delete n[s.id]; return n; })}>reset</button>}
                    <button className="small" onClick={() => rerender(s.id)}>Re-render</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
