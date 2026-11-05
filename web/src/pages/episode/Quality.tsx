import { useState } from "react";
import { Gate } from "../../api";
import { Badge, Empty, Select, statusKind } from "../../components/ui";
import { useFetch } from "../../hooks";

const GATE_LABELS: Record<string, string> = {
  audio_clipping: "Audio clipping", loudness: "Loudness (-14 LUFS, <= -1 dBTP)", captions_safe_area: "Captions in safe area",
  runtime: "Runtime", continuity: "Continuity", unrigged: "Rigged characters", t_pose: "No T-poses", foot_sliding: "Foot sliding",
  interpenetration: "Interpenetration", speaker_on_screen: "Speaker on screen", eyelines: "Eyelines", static_shots: "No frozen shots",
  lipsync_offset: "Lip-sync offset (<= 1 frame)",
};

export function QualityTab({ sid, eid }: { sid: string; eid: string }) {
  const [preset, setPreset] = useState<string | null>(null);
  const q = useFetch<any>(`/api/series/${sid}/episodes/${eid}/quality${preset ? `?preset=${preset}` : ""}`);
  if (!q.data) return <Empty>Loading…</Empty>;
  const report = q.data.report;
  const pre = q.data.preflight?.[q.data.preset];
  const presets = Object.keys(q.data.reports || {});
  if (!report && !pre) return <Empty>No quality report yet: it is written when an episode renders.</Empty>;
  const gates: Gate[] = (report || pre).gates;
  const counts = gates.reduce((acc: any, g) => ({ ...acc, [g.status]: (acc[g.status] || 0) + 1 }), {});

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <div className="row">
            <h2 style={{ margin: 0 }}>Quality report</h2>
            <Badge kind={(report || pre).passed ? "ok" : "bad"}>{(report || pre).passed ? "PASS" : "FAIL"}</Badge>
            {Object.entries(counts).map(([k, v]: any) => <Badge key={k} kind={statusKind(k)}>{v} {k}</Badge>)}
          </div>
          {presets.length > 1 && <Select value={q.data.preset} options={presets} onChange={(v) => setPreset(v)} />}
        </div>
        <div className="small muted">Checked before the render (preflight, with automatic fixes) and again on the finished MP4.</div>
      </div>
      {pre?.rounds?.length > 0 && (
        <div className="card">
          <h3>Automatic fixes before rendering</h3>
          {pre.rounds.map((r: any) => (
            <div key={r.round} style={{ marginBottom: 6 }}>
              <b>Round {r.round}</b> <span className="muted small">re-ran {r.reran.join(", ") || "nothing"}</span>
              <ul style={{ margin: "4px 0" }}>{r.applied.map((a: any, i: number) => <li key={i}><Badge>{a.gate}</Badge> {a.detail}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
      <div className="card">
        <table>
          <thead><tr><th>Gate</th><th>Status</th><th>Result</th></tr></thead>
          <tbody>
            {gates.map((g) => <GateRow key={g.name} g={g} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GateRow({ g }: { g: Gate }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr onClick={() => setOpen((o) => !o)} style={{ cursor: g.details?.length ? "pointer" : undefined }}>
        <td className="nowrap"><b>{GATE_LABELS[g.name] || g.name}</b></td>
        <td><Badge kind={statusKind(g.status)}>{g.status}</Badge></td>
        <td>{g.summary} {g.details?.length ? <span className="muted small">({open ? "hide" : "details"})</span> : null}</td>
      </tr>
      {open && g.details?.length > 0 && (
        <tr>
          <td colSpan={3}>
            <pre className="small">{g.details.slice(0, 40).map((d) => JSON.stringify(d)).join("\n")}</pre>
            {g.fix && <div className="small muted" style={{ marginTop: 6 }}>auto-fix: <code>{JSON.stringify(g.fix)}</code></div>}
          </td>
        </tr>
      )}
    </>
  );
}
