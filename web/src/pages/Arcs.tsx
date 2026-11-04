import { useEffect, useState } from "react";
import { del, post, put } from "../api";
import { OptionsContext } from "../App";
import { Badge, Empty, Errors, Field, JobStatus, Select, useToast } from "../components/ui";
import { go, useFetch } from "../hooks";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export function ArcsPage({ sid, aid }: { sid: string; aid?: string }) {
  const arcs = useFetch<any[]>(`/api/series/${sid}/arcs`);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Arc planner</h1>
          <p>One idea → a 2–5 part arc. Every part gets a hook in the first seconds, a mini-payoff and a cliffhanger (the finale lands the payoff).</p>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "300px 1fr", alignItems: "start" }}>
        <div className="stack">
          <Planner sid={sid} onPlanned={(id) => { arcs.reload(); go(`s/${sid}/arcs/${id}`); }} />
          <div className="card" style={{ padding: 8 }}>
            {(arcs.data || []).map((a) => (
              <div key={a.arc_id} className={`cast-item ${a.arc_id === aid ? "active" : ""}`} onClick={() => go(`s/${sid}/arcs/${a.arc_id}`)}>
                <div>
                  <b>{a.title}</b>
                  <div className="small muted">{a.parts.length} parts · {a.arc_id}</div>
                </div>
              </div>
            ))}
            {arcs.data && !arcs.data.length && <div className="muted small" style={{ padding: 8 }}>No arcs yet.</div>}
          </div>
        </div>
        {aid ? <ArcEditor key={aid} sid={sid} aid={aid} onDeleted={() => { arcs.reload(); go(`s/${sid}/arcs`); }} /> : <Empty>Pick an arc or plan a new one.</Empty>}
      </div>
    </div>
  );
}

function Planner({ sid, onPlanned }: { sid: string; onPlanned: (id: string) => void }) {
  const [idea, setIdea] = useState("");
  const [parts, setParts] = useState(2);
  const [job, setJob] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const submit = async () => {
    setErr(null);
    try {
      const j = await post(`/api/series/${sid}/arcs/plan`, { idea, parts });
      setJob(j.id);
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div className="card stack">
      <h3>New arc from an idea</h3>
      <Field label="Idea"><textarea rows={4} value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Gus finds a library book that rewrites its own ending every night." /></Field>
      <Field label="Parts"><Select value={String(parts)} options={["2", "3", "4", "5"]} onChange={(v) => setParts(Number(v))} /></Field>
      <Errors error={err} />
      <button className="primary" disabled={idea.trim().length < 8 || !!job} onClick={submit}>Plan arc</button>
      <JobStatus jobId={job} compact onDone={(j) => { setJob(null); if (j.status === "done") onPlanned(j.result.arc_id); }} />
    </div>
  );
}

function ArcEditor({ sid, aid, onDeleted }: { sid: string; aid: string; onDeleted: () => void }) {
  const toast = useToast();
  const opts = OptionsContext.current!;
  const remote = useFetch<any>(`/api/series/${sid}/arcs/${aid}`);
  const bible = useFetch<any>(`/api/series/${sid}/bible`);
  const eps = useFetch<any[]>(`/api/series/${sid}/episodes`);
  const [arc, setArc] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [job, setJob] = useState<string | null>(null);
  const [ignoreGates, setIgnoreGates] = useState(false);
  useEffect(() => { if (remote.data) setArc(clone(remote.data)); }, [remote.data]);
  if (!arc || !bible.data) return <Empty>Loading…</Empty>;
  const dirty = JSON.stringify(arc) !== JSON.stringify(remote.data);
  const chars = (bible.data.bible.characters || []).map((c: any) => c.id);
  const locs = (bible.data.bible.locations || []).map((l: any) => ({ value: l.id, label: l.name }));
  const set = (fn: (a: any) => void) => setArc((a: any) => { const n = clone(a); fn(n); return n; });

  const save = async () => {
    setErr(null);
    try {
      await put(`/api/series/${sid}/arcs/${aid}`, arc);
      toast("Arc saved");
      remote.reload();
    } catch (e) {
      setErr(e);
    }
  };
  const run = async (body: any) => {
    try {
      const j = await post(`/api/series/${sid}/arcs/${aid}/run`, body);
      setJob(j.id);
    } catch (e: any) {
      toast(e.message, true);
    }
  };
  const remove = async () => {
    if (!confirm(`Delete the arc "${arc.title}" and its episodes (screenplays, renders)?`)) return;
    await del(`/api/series/${sid}/arcs/${aid}`);
    toast("Arc deleted");
    onDeleted();
  };
  const epOf = (part: number) => (eps.data || []).find((e) => e.id === `${aid}_p${part}`);

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2>{arc.title}</h2>
          <div className="row">
            <button className="danger" onClick={remove}>Delete</button>
            <button disabled={!dirty} onClick={() => setArc(clone(remote.data))}>Discard</button>
            <button className="primary" disabled={!dirty} onClick={save}>Save plan</button>
          </div>
        </div>
        <Errors error={err} />
        <div className="grid cols-2">
          <Field label="Title"><input value={arc.title} onChange={(e) => set((a) => (a.title = e.target.value))} /></Field>
          <Field label="Theme"><input value={arc.theme || ""} onChange={(e) => set((a) => (a.theme = e.target.value))} /></Field>
          <Field label="Premise"><textarea value={arc.premise} onChange={(e) => set((a) => (a.premise = e.target.value))} /></Field>
          <Field label="Final payoff (landed by the last part)"><textarea value={arc.final_payoff} onChange={(e) => set((a) => (a.final_payoff = e.target.value))} /></Field>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={() => run({ until: "continuity_log" })} disabled={dirty}>Write &amp; review all parts</button>
          <button onClick={() => run({ preset: "draft" })} disabled={dirty}>Render drafts (540×960)</button>
          <button className="primary" onClick={() => run({ preset: "final", ignore_gates: ignoreGates })} disabled={dirty}>Render finals (1080×1920)</button>
          <label className="check"><input type="checkbox" checked={ignoreGates} onChange={(e) => setIgnoreGates(e.target.checked)} /> render even if quality gates fail</label>
          {dirty && <span className="small muted">save the plan first</span>}
        </div>
      </div>
      {job && <JobStatus jobId={job} onDone={() => eps.reload()} />}
      {arc.parts.map((p: any, i: number) => {
        const ep = epOf(p.part);
        const finale = i === arc.parts.length - 1;
        return (
          <div key={i} className="card part-card">
            <div className="card-head">
              <h3>Part {p.part}{finale ? " · finale" : ""}</h3>
              <div className="row small">
                {ep && <Badge kind={ep.status === "rendered" ? "ok" : "info"}>{ep.status}</Badge>}
                {ep && <a href={`#/s/${sid}/ep/${ep.id}/script`}>open episode →</a>}
              </div>
            </div>
            <div className="grid cols-2">
              <Field label="Title"><input value={p.title} onChange={(e) => set((a) => (a.parts[i].title = e.target.value))} /></Field>
              <Field label="Logline"><input value={p.logline} onChange={(e) => set((a) => (a.parts[i].logline = e.target.value))} /></Field>
              <Field label="Hook (first 1–2 seconds)"><input value={p.hook} onChange={(e) => set((a) => (a.parts[i].hook = e.target.value))} /></Field>
              <Field label="Escalation"><input value={p.escalation} onChange={(e) => set((a) => (a.parts[i].escalation = e.target.value))} /></Field>
              <Field label="Mini-payoff"><input value={p.mini_payoff} onChange={(e) => set((a) => (a.parts[i].mini_payoff = e.target.value))} /></Field>
              {finale ? <Field label="Cliffhanger"><input disabled value="(finale: lands the final payoff)" /></Field> : (
                <Field label="Cliffhanger"><input value={p.cliffhanger || ""} onChange={(e) => set((a) => (a.parts[i].cliffhanger = e.target.value))} /></Field>
              )}
              {i > 0 && <Field label="Recap line (2–3 s 'previously' opening)"><input value={p.recap || ""} onChange={(e) => set((a) => (a.parts[i].recap = e.target.value))} /></Field>}
              <div className="grid cols-3" style={{ gridColumn: i > 0 ? "auto" : "1 / -1" }}>
                <Field label="Location"><Select value={p.location} options={locs} onChange={(v) => set((a) => (a.parts[i].location = v))} /></Field>
                <Field label="Time of day"><Select value={p.time_of_day} options={opts.times_of_day} onChange={(v) => set((a) => (a.parts[i].time_of_day = v))} /></Field>
                <Field label="Music mood"><Select value={p.music_mood} allowNone options={opts.music_moods} onChange={(v) => set((a) => { if (v) a.parts[i].music_mood = v; else delete a.parts[i].music_mood; })} /></Field>
              </div>
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <span className="small muted">Cast:</span>
              {chars.map((c: string) => (
                <label key={c} className="check">
                  <input type="checkbox" checked={p.cast.includes(c)} onChange={(e) => set((a) => {
                    const cast = new Set(a.parts[i].cast);
                    if (e.target.checked) cast.add(c); else cast.delete(c);
                    a.parts[i].cast = chars.filter((x: string) => cast.has(x));
                  })} /> {c}
                </label>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
