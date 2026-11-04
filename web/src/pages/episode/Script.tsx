import { useEffect, useMemo, useState } from "react";
import { Beat, Screenplay, del, post, put } from "../../api";
import { OptionsContext } from "../../App";
import { Badge, Empty, Errors, Field, JobStatus, Select, useToast } from "../../components/ui";
import { useFetch } from "../../hooks";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

function estimate(sp: Screenplay): number {
  let t = 0;
  for (const b of sp.beats) {
    const words = (b.line || "").split(/\s+/).filter(Boolean).length;
    t += words ? words / 2.6 + 0.35 : 1.5;
  }
  return t;
}

function nextId(beats: Beat[]): string {
  const nums = beats.map((b) => Number(b.id.replace(/\D/g, "")) || 0);
  return `b${String(Math.max(0, ...nums) + 1).padStart(2, "0")}`;
}

export function ScriptTab({ sid, eid }: { sid: string; eid: string }) {
  const toast = useToast();
  const opts = OptionsContext.current!;
  const data = useFetch<any>(`/api/series/${sid}/episodes/${eid}/screenplay`);
  const bible = useFetch<any>(`/api/series/${sid}/bible`);
  const [sp, setSp] = useState<Screenplay | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [job, setJob] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const d = data.data;
    if (d) setSp(d.final ? clone(d.final) : d.draft ? clone(d.draft) : null);
  }, [data.data]);

  const original = data.data?.final || data.data?.draft;
  const dirty = useMemo(() => sp && JSON.stringify(sp) !== JSON.stringify(original), [sp, original]);
  const notes = useMemo(() => {
    const m: Record<string, { kind: string; text: string }[]> = {};
    const d = data.data;
    if (!d) return m;
    const add = (id: string | null, kind: string, text: string) => (m[id || "_"] ||= []).push({ kind, text });
    for (const n of d.review?.notes || []) add(n.beat_id, "review", `${n.category}: ${n.note}`);
    for (const i of d.continuity?.issues || []) {
      add(i.beat_id, i.status === "auto_fixed" ? "fixed" : i.severity, `continuity ${i.kind}: ${i.message}${i.suggestion ? ` → ${i.suggestion}` : ""}${i.status === "auto_fixed" ? " (auto-fixed)" : ""}`);
    }
    return m;
  }, [data.data]);
  const edited = new Set([...Object.keys(data.data?.edits?.beats || {}), ...((data.data?.edits?.added || []).map((b: any) => b.id))]);

  if (!data.data || !bible.data) return <Empty>Loading…</Empty>;
  if (!sp) {
    return (
      <div className="card">
        <Empty>No screenplay yet.</Empty>
        <div className="row" style={{ justifyContent: "center" }}>
          <button className="primary" onClick={async () => setJob((await post(`/api/series/${sid}/episodes/${eid}/run`, { until: "continuity_log" })).id)}>Write it</button>
        </div>
        <JobStatus jobId={job} onDone={() => data.reload()} />
      </div>
    );
  }
  const cast = sp.cast;
  const allChars = (bible.data.bible.characters || []).map((c: any) => c.id);
  const locs = (bible.data.bible.locations || []).map((l: any) => ({ value: l.id, label: l.name }));
  const setBeat = (i: number, fn: (b: Beat) => void) => setSp((s) => { const n = clone(s!); fn(n.beats[i]); return n; });
  const setSpField = (fn: (s: Screenplay) => void) => setSp((s) => { const n = clone(s!); fn(n); return n; });

  const save = async (andRun?: any) => {
    setSaving(true);
    setErr(null);
    try {
      const r = await put(`/api/series/${sid}/episodes/${eid}/screenplay`, sp);
      toast(`Saved: ${r.edited_beats.length} beat(s) edited`);
      if (andRun) {
        const j = await post(`/api/series/${sid}/episodes/${eid}/run`, andRun);
        setJob(j.id);
      } else data.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };
  const resetEdits = async () => {
    if (!confirm("Drop all your beat edits and go back to the reviewed script?")) return;
    await del(`/api/series/${sid}/episodes/${eid}/edits`);
    const j = await post(`/api/series/${sid}/episodes/${eid}/run`, { until: "continuity_log" });
    setJob(j.id);
  };
  const runtime = estimate(sp);
  const review = data.data.review;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2>{sp.title}</h2>
          <div className="row">
            <span className={`small ${runtime < 45 || runtime > 90 ? "" : "muted"}`}>≈ {runtime.toFixed(0)} s {runtime < 45 || runtime > 90 ? <Badge kind="warn">target 45–90 s</Badge> : null}</span>
            {edited.size > 0 && <button onClick={resetEdits}>Reset my edits</button>}
            <button disabled={!dirty || saving} onClick={() => setSp(clone(original))}>Discard</button>
            <button disabled={!dirty || saving} onClick={() => save()}>Save edits</button>
            <button className="primary" disabled={saving} onClick={() => save({ until: "continuity_log" })}>Save &amp; re-check</button>
            <button disabled={saving} onClick={() => save({ preset: "draft" })}>Save &amp; render draft</button>
          </div>
        </div>
        <Errors error={err} />
        {review?.scores && (
          <div className="row small" style={{ marginBottom: 10 }}>
            <span className="muted">Story editor:</span>
            {Object.entries(review.scores).map(([k, v]: any) => <Badge key={k} kind={v >= 7 ? "ok" : v >= 5 ? "warn" : "bad"}>{k} {v}</Badge>)}
            {review.applied_rewrites?.length > 0 && <span className="muted">rewrote {review.applied_rewrites.join(", ")}</span>}
            {data.data.continuity && <Badge kind={data.data.continuity.passed ? "ok" : "bad"}>continuity {data.data.continuity.counts.error}E/{data.data.continuity.counts.warning}W</Badge>}
          </div>
        )}
        {(notes["_"] || []).map((n, i) => <div key={i} className={`alert ${n.kind === "error" ? "bad" : n.kind === "warning" ? "warn" : "info"} small`} style={{ marginBottom: 6 }}>{n.text}</div>)}
        <div className="grid cols-4">
          <Field label="Title"><input value={sp.title} onChange={(e) => setSpField((s) => (s.title = e.target.value))} /></Field>
          <Field label="Location"><Select value={sp.location} options={locs} onChange={(v) => setSpField((s) => (s.location = v!))} /></Field>
          <Field label="Time of day"><Select value={sp.time_of_day} options={opts.times_of_day} onChange={(v) => setSpField((s) => (s.time_of_day = v!))} /></Field>
          <Field label="Music mood"><Select value={sp.music_mood} options={opts.music_moods} onChange={(v) => setSpField((s) => (s.music_mood = v!))} /></Field>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="small muted">Cast:</span>
          {allChars.map((c: string) => (
            <label key={c} className="check"><input type="checkbox" checked={cast.includes(c)} onChange={(e) => setSpField((s) => {
              const set = new Set(s.cast);
              if (e.target.checked) set.add(c); else set.delete(c);
              s.cast = allChars.filter((x: string) => set.has(x));
            })} /> {c}</label>
          ))}
        </div>
      </div>
      {job && <JobStatus jobId={job} onDone={() => data.reload()} />}
      {sp.beats.map((b, i) => (
        <BeatCard key={b.id} beat={b} index={i} total={sp.beats.length} cast={cast} edited={edited.has(b.id)} notes={notes[b.id] || []}
          set={(fn) => setBeat(i, fn)}
          move={(d) => setSpField((s) => { const [x] = s.beats.splice(i, 1); s.beats.splice(i + d, 0, x); })}
          remove={() => setSpField((s) => { s.beats.splice(i, 1); })}
          addAfter={() => setSpField((s) => {
            s.beats.splice(i + 1, 0, { id: nextId(s.beats), speaker: cast[0], addressee: cast[1] || null, line: "", emotion: "neutral", intensity: 0.5, action: "", performance_note: "", beat_type: "setup", props: [], fx: [], sfx: [] });
          })}
        />
      ))}
    </div>
  );
}

function BeatCard({ beat: b, index, total, cast, edited, notes, set, move, remove, addAfter }: {
  beat: Beat; index: number; total: number; cast: string[]; edited: boolean; notes: { kind: string; text: string }[];
  set: (fn: (b: Beat) => void) => void; move: (d: number) => void; remove: () => void; addAfter: () => void;
}) {
  const opts = OptionsContext.current!;
  const flagged = notes.some((n) => n.kind === "error");
  return (
    <div className={`beat ${edited ? "edited" : ""} ${flagged ? "flagged" : ""}`}>
      <div className="beat-head">
        <span className="beat-id">{b.id}</span>
        <Select value={b.beat_type || "setup"} options={opts.beat_types} onChange={(v) => set((x) => (x.beat_type = v!))} />
        {edited && <Badge kind="warn">edited</Badge>}
        <span className="spacer" />
        <button className="small ghost" disabled={index === 0} onClick={() => move(-1)}>↑</button>
        <button className="small ghost" disabled={index === total - 1} onClick={() => move(1)}>↓</button>
        <button className="small" onClick={addAfter}>+ beat</button>
        <button className="small danger" onClick={remove}>Delete</button>
      </div>
      <div className="grid cols-4">
        <Field label="Speaker"><Select value={b.speaker} allowNone noneLabel="— silent action —" options={cast} onChange={(v) => set((x) => { x.speaker = v; if (!v) x.line = ""; })} /></Field>
        <Field label="To (eyeline)"><Select value={b.addressee} allowNone options={cast} onChange={(v) => set((x) => (x.addressee = v))} /></Field>
        <Field label="Emotion"><Select value={b.emotion} options={opts.emotions} onChange={(v) => set((x) => (x.emotion = v!))} /></Field>
        <Field label={`Intensity ${b.intensity.toFixed(2)}`}><input type="range" min={0} max={1} step={0.05} value={b.intensity} onChange={(e) => set((x) => (x.intensity = Number(e.target.value)))} /></Field>
      </div>
      {b.speaker && <Field label="Line"><textarea rows={2} value={b.line} onChange={(e) => set((x) => (x.line = e.target.value))} /></Field>}
      <div className="grid cols-2" style={{ marginTop: 6 }}>
        <Field label="Action (what we see)"><textarea rows={2} value={b.action} onChange={(e) => set((x) => (x.action = e.target.value))} /></Field>
        <Field label="Performance note (acting + voice direction)"><textarea rows={2} value={b.performance_note} onChange={(e) => set((x) => (x.performance_note = e.target.value))} /></Field>
      </div>
      <div className="grid cols-4" style={{ marginTop: 6 }}>
        <Field label="Camera hint"><Select value={b.camera_hint} allowNone noneLabel="auto" options={opts.camera_hints} onChange={(v) => set((x) => (x.camera_hint = v))} /></Field>
        <Field label="Gesture"><Select value={b.gesture} allowNone options={opts.gestures} onChange={(v) => set((x) => (x.gesture = v))} /></Field>
        <Field label="Move"><Select value={b.motion?.type} allowNone options={opts.locomotion} onChange={(v) => set((x) => { x.motion = v ? { ...(x.motion || {}), type: v } : null; })} /></Field>
        <Field label="Move to / side">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input value={b.motion?.to || ""} disabled={!b.motion} placeholder="mark / character" onChange={(e) => set((x) => { if (x.motion) x.motion.to = e.target.value || null; })} />
            <Select value={b.motion?.side} allowNone options={["left", "right", "back", "front"]} onChange={(v) => set((x) => { if (x.motion) x.motion.side = v; })} />
          </div>
        </Field>
        <Field label="Pace"><Select value={b.delivery?.pace} allowNone options={opts.paces} onChange={(v) => set((x) => { x.delivery = { ...(x.delivery || {}), pace: v || undefined }; })} /></Field>
        <Field label="Volume"><Select value={b.delivery?.volume} allowNone options={opts.volumes} onChange={(v) => set((x) => { x.delivery = { ...(x.delivery || {}), volume: v || undefined }; })} /></Field>
        <Field label="Sound effects (comma separated)"><input value={(b.sfx || []).join(", ")} onChange={(e) => set((x) => (x.sfx = e.target.value.split(",").map((s) => s.trim()).filter(Boolean)))} placeholder="clock_chime, whoosh" /></Field>
      </div>
      <div className="grid cols-2" style={{ marginTop: 8 }}>
        <div>
          <div className="row small muted">Props <button className="small ghost" disabled={(b.props || []).length >= 3} onClick={() => set((x) => (x.props = [...(x.props || []), { character: cast[0], prop: opts.props[0], action: "hold" }]))}>+</button></div>
          {(b.props || []).map((p, k) => (
            <div key={k} className="row" style={{ flexWrap: "nowrap", marginTop: 4 }}>
              <Select value={p.character} options={cast} onChange={(v) => set((x) => (x.props![k].character = v!))} />
              <Select value={p.action} options={opts.prop_actions} onChange={(v) => set((x) => (x.props![k].action = v!))} />
              <Select value={p.prop} options={opts.props} onChange={(v) => set((x) => (x.props![k].prop = v!))} />
              {p.action === "give" && <Select value={p.to} allowNone options={cast} onChange={(v) => set((x) => (x.props![k].to = v))} />}
              <button className="small ghost" onClick={() => set((x) => x.props!.splice(k, 1))}>×</button>
            </div>
          ))}
        </div>
        <div>
          <div className="row small muted">Emotion FX <button className="small ghost" disabled={(b.fx || []).length >= 3} onClick={() => set((x) => (x.fx = [...(x.fx || []), { character: b.speaker || cast[0], type: opts.emotion_fx[0] }]))}>+</button></div>
          {(b.fx || []).map((f, k) => (
            <div key={k} className="row" style={{ flexWrap: "nowrap", marginTop: 4 }}>
              <Select value={f.character} options={cast} onChange={(v) => set((x) => (x.fx![k].character = v!))} />
              <Select value={f.type} options={opts.emotion_fx} onChange={(v) => set((x) => (x.fx![k].type = v!))} />
              <button className="small ghost" onClick={() => set((x) => x.fx!.splice(k, 1))}>×</button>
            </div>
          ))}
        </div>
      </div>
      {notes.length > 0 && (
        <div className="beat-notes">
          {notes.map((n, i) => <div key={i} className={`alert small ${n.kind === "error" ? "bad" : n.kind === "warning" ? "warn" : n.kind === "fixed" ? "ok" : "info"}`}>{n.text}</div>)}
        </div>
      )}
    </div>
  );
}
