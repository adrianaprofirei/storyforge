import { useEffect, useMemo, useState } from "react";
import { get, post, put } from "../api";
import { OptionsContext } from "../App";
import { Badge, Empty, Errors, Field, Select, Tabs, useToast } from "../components/ui";
import { useFetch } from "../hooks";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export function BiblePage({ sid, tab }: { sid: string; tab: string }) {
  const toast = useToast();
  const opts = OptionsContext.current!;
  const remote = useFetch<any>(`/api/series/${sid}/bible`);
  const [bible, setBible] = useState<any>(null);
  const [yamlText, setYamlText] = useState("");
  const [message, setMessage] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (remote.data) {
      setBible(clone(remote.data.bible));
      setYamlText(remote.data.yaml);
    }
  }, [remote.data]);

  const dirty = useMemo(() => remote.data && bible && JSON.stringify(remote.data.bible) !== JSON.stringify(bible), [remote.data, bible]);
  if (!bible) return <Empty>Loading…</Empty>;
  const set = (fn: (b: any) => void) => setBible((b: any) => {
    const n = clone(b);
    fn(n);
    return n;
  });

  const save = async (payload: any) => {
    setSaving(true);
    setErr(null);
    try {
      const r = await put(`/api/series/${sid}/bible`, { ...payload, message: message || undefined });
      toast(`Bible saved as version ${r.version}`);
      setMessage("");
      remote.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };

  const chars: any[] = bible.characters || [];
  const tabs = [
    { id: "world", label: "World & format" }, { id: "characters", label: `Characters (${chars.length})` },
    { id: "locations", label: "Locations" }, { id: "relationships", label: "Relationships & gags" },
    { id: "look", label: "Look" }, { id: "continuity", label: "Arcs & continuity" },
    { id: "yaml", label: "YAML" }, { id: "history", label: "History" },
  ].map((t) => ({ ...t, href: `#/s/${sid}/bible/${t.id}` }));

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Series bible</h1>
          <p>Version {remote.data?.version}. Every save creates a new version; the pipeline always reads the latest.</p>
        </div>
        {tab !== "yaml" && tab !== "history" && (
          <div className="row">
            <input style={{ width: 260 }} placeholder="What changed? (optional)" value={message} onChange={(e) => setMessage(e.target.value)} />
            <button disabled={!dirty || saving} onClick={() => setBible(clone(remote.data.bible))}>Discard</button>
            <button className="primary" disabled={!dirty || saving} onClick={() => save({ bible })}>Save version</button>
          </div>
        )}
      </div>
      <Tabs tabs={tabs} active={tab} />
      <Errors error={err} />

      {tab === "world" && (
        <div className="grid cols-2">
          <div className="card stack">
            <Field label="Title"><input value={bible.title || ""} onChange={(e) => set((b) => (b.title = e.target.value))} /></Field>
            <Field label="Logline"><textarea value={bible.logline || ""} onChange={(e) => set((b) => (b.logline = e.target.value))} /></Field>
            <Field label="Setting"><textarea value={bible.world?.setting || ""} onChange={(e) => set((b) => (b.world.setting = e.target.value))} /></Field>
            <Field label="Tone"><input value={bible.world?.tone || ""} onChange={(e) => set((b) => (b.world.tone = e.target.value))} /></Field>
            <Field label="Target audience"><input value={bible.world?.target_audience || ""} onChange={(e) => set((b) => (b.world.target_audience = e.target.value))} /></Field>
            <Field label="Content rules (one per line, enforced by the writer, reviewer and continuity check)">
              <textarea rows={6} value={(bible.world?.content_rules || []).join("\n")} onChange={(e) => set((b) => (b.world.content_rules = lines(e.target.value)))} />
            </Field>
          </div>
          <div className="card stack">
            <h3>Format</h3>
            <div className="grid cols-2">
              <Field label="Frame rate"><Select value={String(bible.format?.fps || 30)} options={["30", "60"]} onChange={(v) => set((b) => ((b.format ||= {}).fps = Number(v)))} /></Field>
              <Field label="Recap length (s, parts 2+)"><input type="number" step="0.5" min={2} max={3} value={bible.format?.recap_seconds ?? 2.5} onChange={(e) => set((b) => ((b.format ||= {}).recap_seconds = Number(e.target.value)))} /></Field>
              <Field label="Part minimum (s)"><input type="number" value={bible.format?.part_min_seconds ?? 45} onChange={(e) => set((b) => ((b.format ||= {}).part_min_seconds = Number(e.target.value)))} /></Field>
              <Field label="Part maximum (s)"><input type="number" value={bible.format?.part_max_seconds ?? 90} onChange={(e) => set((b) => ((b.format ||= {}).part_max_seconds = Number(e.target.value)))} /></Field>
              <Field label="Continuity errors" hint="block = stop before voicing/rendering">
                <Select value={bible.format?.continuity_gate || "warn"} options={["warn", "block"]} onChange={(v) => set((b) => ((b.format ||= {}).continuity_gate = v))} />
              </Field>
              <Field label="Continuity auto-fix">
                <Select value={bible.format?.continuity_autofix === false ? "off" : "on"} options={["on", "off"]} onChange={(v) => set((b) => ((b.format ||= {}).continuity_autofix = v === "on"))} />
              </Field>
            </div>
            <h3 style={{ marginTop: 10 }}>"Part N" card</h3>
            <div className="grid cols-2">
              <Field label="Shown"><Select value={bible.format?.part_card?.enabled === false ? "no" : "yes"} options={["yes", "no"]} onChange={(v) => set((b) => (((b.format ||= {}).part_card ||= {}).enabled = v === "yes"))} /></Field>
              <Field label="Seconds on screen"><input type="number" step="0.1" value={bible.format?.part_card?.seconds ?? 2.0} onChange={(e) => set((b) => (((b.format ||= {}).part_card ||= {}).seconds = Number(e.target.value)))} /></Field>
              <Field label="Text ({n} = part number)"><input value={bible.format?.part_card?.text ?? "PART {n}"} onChange={(e) => set((b) => (((b.format ||= {}).part_card ||= {}).text = e.target.value))} /></Field>
              <div className="row">
                <Field label="Badge"><input type="color" value={bible.format?.part_card?.color || "#FFD447"} onChange={(e) => set((b) => (((b.format ||= {}).part_card ||= {}).color = e.target.value.toUpperCase()))} /></Field>
                <Field label="Text colour"><input type="color" value={bible.format?.part_card?.text_color || "#1B1B2F"} onChange={(e) => set((b) => (((b.format ||= {}).part_card ||= {}).text_color = e.target.value.toUpperCase()))} /></Field>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "characters" && (
        <div className="stack">
          {chars.map((c, i) => (
            <div key={i} className="card">
              <div className="card-head">
                <h3>{c.name || c.id} <span className="muted mono small">{c.id}</span></h3>
                <div className="row">
                  <a className="small" href={`#/s/${sid}/cast/${c.id}`}>look &amp; voice →</a>
                  <button className="small danger" onClick={() => set((b) => b.characters.splice(i, 1))}>Remove</button>
                </div>
              </div>
              <div className="grid cols-3">
                <Field label="Name"><input value={c.name || ""} onChange={(e) => set((b) => (b.characters[i].name = e.target.value))} /></Field>
                <Field label="Role"><input value={c.role || ""} onChange={(e) => set((b) => (b.characters[i].role = e.target.value))} /></Field>
                <Field label="Voice direction"><input value={c.voice_direction || ""} onChange={(e) => set((b) => (b.characters[i].voice_direction = e.target.value))} /></Field>
                <Field label="Personality"><textarea value={c.personality || ""} onChange={(e) => set((b) => (b.characters[i].personality = e.target.value))} /></Field>
                <Field label="Speech patterns"><textarea value={c.speech_patterns || ""} onChange={(e) => set((b) => (b.characters[i].speech_patterns = e.target.value))} /></Field>
                <Field label="Catchphrases (one per line)"><textarea value={(c.catchphrases || []).join("\n")} onChange={(e) => set((b) => (b.characters[i].catchphrases = lines(e.target.value)))} /></Field>
                <Field label="Wants"><input value={c.wants || ""} onChange={(e) => set((b) => (b.characters[i].wants = e.target.value))} /></Field>
                <Field label="Fears"><input value={c.fears || ""} onChange={(e) => set((b) => (b.characters[i].fears = e.target.value))} /></Field>
              </div>
            </div>
          ))}
          <AddCharacter sid={sid} existing={chars.map((c) => c.id)} onAdd={(id, name) => set((b) => b.characters.push({ id, name, role: "", personality: "", speech_patterns: "", catchphrases: [] }))} />
        </div>
      )}

      {tab === "locations" && (
        <div className="stack">
          {(bible.locations || []).map((l: any, i: number) => (
            <div key={i} className="card">
              <div className="grid cols-4">
                <Field label="Id"><input value={l.id} onChange={(e) => set((b) => (b.locations[i].id = e.target.value))} /></Field>
                <Field label="Name"><input value={l.name || ""} onChange={(e) => set((b) => (b.locations[i].name = e.target.value))} /></Field>
                <Field label="Set (Blender preset)"><Select value={l.preset} options={Object.entries(opts.locations).map(([k, v]) => ({ value: k, label: `${v.name} (${v.kind})` }))} onChange={(v) => set((b) => (b.locations[i].preset = v))} /></Field>
                <Field label="Floor surface (footsteps)"><Select value={l.surface} allowNone noneLabel="preset default" options={opts.surfaces} onChange={(v) => set((b) => { if (v) b.locations[i].surface = v; else delete b.locations[i].surface; })} /></Field>
              </div>
              <div className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}><Field label="Description"><input value={l.description || ""} onChange={(e) => set((b) => (b.locations[i].description = e.target.value))} /></Field></div>
                <button className="small danger" onClick={() => set((b) => b.locations.splice(i, 1))}>Remove</button>
              </div>
            </div>
          ))}
          <div><button onClick={() => set((b) => (b.locations ||= []).push({ id: `place_${(b.locations || []).length + 1}`, name: "New place", preset: Object.keys(opts.locations)[0] }))}>Add location</button></div>
        </div>
      )}

      {tab === "relationships" && (
        <div className="grid cols-2">
          <div className="card stack">
            <h3>Relationships</h3>
            {(bible.relationships || []).map((r: any, i: number) => (
              <div key={i} className="grid cols-4" style={{ alignItems: "end" }}>
                <Field label="A"><Select value={r.a} options={chars.map((c) => c.id)} onChange={(v) => set((b) => (b.relationships[i].a = v))} /></Field>
                <Field label="B"><Select value={r.b} options={chars.map((c) => c.id)} onChange={(v) => set((b) => (b.relationships[i].b = v))} /></Field>
                <Field label="Type"><input value={r.type || ""} onChange={(e) => set((b) => (b.relationships[i].type = e.target.value))} /></Field>
                <button className="small danger" onClick={() => set((b) => b.relationships.splice(i, 1))}>Remove</button>
                <div style={{ gridColumn: "1 / -1" }}><Field label="Notes"><input value={r.notes || ""} onChange={(e) => set((b) => (b.relationships[i].notes = e.target.value))} /></Field></div>
              </div>
            ))}
            <div><button onClick={() => set((b) => (b.relationships ||= []).push({ a: chars[0]?.id, b: chars[1]?.id, type: "friends", notes: "" }))}>Add relationship</button></div>
          </div>
          <div className="card stack">
            <h3>Running gags</h3>
            {(bible.running_gags || []).map((g: any, i: number) => (
              <div key={i} className="row" style={{ alignItems: "flex-end" }}>
                <div style={{ width: 150 }}><Field label="Id"><input value={g.id} onChange={(e) => set((b) => (b.running_gags[i].id = e.target.value))} /></Field></div>
                <div style={{ flex: 1 }}><Field label="Description"><input value={g.description || ""} onChange={(e) => set((b) => (b.running_gags[i].description = e.target.value))} /></Field></div>
                <button className="small danger" onClick={() => set((b) => b.running_gags.splice(i, 1))}>Remove</button>
              </div>
            ))}
            <div><button onClick={() => set((b) => (b.running_gags ||= []).push({ id: `gag_${(b.running_gags || []).length + 1}`, description: "" }))}>Add gag</button></div>
          </div>
        </div>
      )}

      {tab === "look" && (
        <div className="grid cols-2">
          <div className="card stack">
            <h3>Visual style</h3>
            <Field label="Style"><Select value={bible.look?.style || bible.world?.visual_style} options={opts.styles} onChange={(v) => set((b) => { (b.look ||= {}).style = v; b.world.visual_style = v; })} /></Field>
            <Field label="Caption style"><Select value={bible.look?.caption_style || "bold_pop"} options={opts.caption_styles} onChange={(v) => set((b) => ((b.look ||= {}).caption_style = v))} /></Field>
            <Field label="Accent colour (caption highlight, Part card)">
              <input type="color" value={bible.look?.accent_color || "#FFD447"} onChange={(e) => set((b) => ((b.look ||= {}).accent_color = e.target.value.toUpperCase()))} />
            </Field>
          </div>
          <div className="card stack">
            <h3>Series grade</h3>
            <Field label="Preset"><Select value={bible.look?.grade?.preset || "warm_storybook"} options={Object.keys(opts.grades)} onChange={(v) => set((b) => (((b.look ||= {}).grade ||= {}).preset = v))} /></Field>
            <div className="grid cols-2">
              {[["exposure", -1, 1, 0.05], ["contrast", 0.8, 1.3, 0.01], ["saturation", 0.6, 1.4, 0.01], ["warmth", -0.2, 0.2, 0.01], ["vignette", 0, 1, 0.01], ["grain", 0, 0.15, 0.005]].map(([k, lo, hi, step]) => {
                const preset = opts.grades[bible.look?.grade?.preset || "warm_storybook"] || {};
                const v = bible.look?.grade?.[k as string] ?? preset[k as string] ?? 0;
                return (
                  <Field key={k as string} label={`${k} (${Number(v).toFixed(3)})`}>
                    <input type="range" min={lo as number} max={hi as number} step={step as number} value={v}
                      onChange={(e) => set((b) => ((((b.look ||= {}).grade ||= {}))[k as string] = Number(e.target.value)))} />
                  </Field>
                );
              })}
            </div>
            <Field label="LUT file (assets/luts, optional)"><input value={bible.look?.grade?.lut || ""} onChange={(e) => set((b) => { const g = ((b.look ||= {}).grade ||= {}); if (e.target.value) g.lut = e.target.value; else delete g.lut; })} placeholder="my_look.cube" /></Field>
          </div>
        </div>
      )}

      {tab === "continuity" && (
        <div className="grid cols-2">
          <div className="card">
            <h3>Arcs &amp; episodes</h3>
            {(bible.arcs || []).map((a: any) => (
              <div key={a.id} style={{ marginBottom: 10 }}>
                <b>{a.title}</b> <Badge>{a.status}</Badge>
                <div className="chip-row" style={{ marginTop: 4 }}>
                  {(bible.episodes || []).filter((e: any) => e.arc_id === a.id).map((e: any) => (
                    <a key={e.id} href={`#/s/${sid}/ep/${e.id}`}><Badge kind={e.status === "rendered" ? "ok" : e.status === "scripted" ? "info" : ""}>P{e.part} {e.status}</Badge></a>
                  ))}
                </div>
              </div>
            ))}
            {!(bible.arcs || []).length && <div className="muted">No arcs yet.</div>}
          </div>
          <div className="card">
            <h3>Continuity log</h3>
            <div className="small muted" style={{ marginBottom: 8 }}>Written by the LLM after each part's script is locked; the next parts, the arc planner and the continuity check read it.</div>
            {(bible.continuity_log || []).map((e: any) => (
              <div key={e.episode_id} className="card" style={{ boxShadow: "none" }}>
                <div className="row between"><b>{e.title || e.episode_id}</b><Badge kind={e.status === "rendered" ? "ok" : "info"}>{e.status}</Badge></div>
                <p style={{ margin: "6px 0" }}>{e.summary}</p>
                {e.open_threads?.length > 0 && <div className="small"><b>Open threads:</b> {e.open_threads.join(" · ")}</div>}
                {e.object_states?.length > 0 && <div className="small muted">Objects: {e.object_states.map((o: any) => `${o.object} → ${o.holder || "nobody"} (${o.status})`).join(", ")}</div>}
              </div>
            ))}
            {!(bible.continuity_log || []).length && <div className="muted">Empty: run a part through the review stage.</div>}
          </div>
        </div>
      )}

      {tab === "yaml" && (
        <div className="card stack">
          <div className="small muted">Full bible as YAML. Saving validates it against the bible schema.</div>
          <textarea className="mono" rows={34} value={yamlText} onChange={(e) => setYamlText(e.target.value)} spellCheck={false} />
          <div className="row">
            <input style={{ width: 300 }} placeholder="What changed? (optional)" value={message} onChange={(e) => setMessage(e.target.value)} />
            <button className="primary" disabled={saving || yamlText === remote.data?.yaml} onClick={() => save({ yaml: yamlText })}>Save YAML as new version</button>
          </div>
        </div>
      )}

      {tab === "history" && <History sid={sid} onRestored={() => remote.reload()} />}
    </div>
  );
}

function AddCharacter({ sid, existing, onAdd }: { sid: string; existing: string[]; onAdd: (id: string, name: string) => void }) {
  const cast = useFetch<any[]>(`/api/series/${sid}/cast`);
  const free = (cast.data || []).filter((c) => !existing.includes(c.id));
  return (
    <div className="card">
      <h3>Add a character</h3>
      <div className="small muted" style={{ marginBottom: 8 }}>Characters need a cast entry (look, rig, voice). Create one on the <a href={`#/s/${sid}/cast`}>cast page</a>, then add it here.</div>
      <div className="row">
        {free.map((c) => <button key={c.id} onClick={() => onAdd(c.id, c.name)}>+ {c.name}</button>)}
        {!free.length && <span className="muted small">Every cast member is already in the bible.</span>}
      </div>
    </div>
  );
}

function History({ sid, onRestored }: { sid: string; onRestored: () => void }) {
  const toast = useToast();
  const versions = useFetch<any[]>(`/api/series/${sid}/bible/versions`);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const [diff, setDiff] = useState<any[] | null>(null);

  useEffect(() => {
    if (versions.data && versions.data.length > 1 && a === null) {
      setB(versions.data[0].version);
      setA(versions.data[1].version);
    }
  }, [versions.data, a]);
  useEffect(() => {
    if (a && b) get(`/api/series/${sid}/bible/diff?a=${a}&b=${b}`).then(setDiff);
  }, [sid, a, b]);

  const restore = async (v: number) => {
    const r = await post(`/api/series/${sid}/bible/versions/${v}/restore`);
    toast(`Restored v${v} as v${r.version}`);
    versions.reload();
    onRestored();
  };
  const show = (x: any) => (x === null || x === undefined ? "∅" : typeof x === "object" ? JSON.stringify(x).slice(0, 160) : String(x).slice(0, 160));

  return (
    <div className="grid cols-2">
      <div className="card">
        <h3>Versions</h3>
        <table>
          <thead><tr><th>v</th><th>Saved</th><th>Message</th><th>Compare</th><th /></tr></thead>
          <tbody>
            {(versions.data || []).map((v) => (
              <tr key={v.version} className={v.version === a || v.version === b ? "selected" : ""}>
                <td className="mono">{v.version}</td>
                <td className="small nowrap">{v.saved_at?.replace("T", " ").slice(0, 19)}</td>
                <td className="small">{v.message}</td>
                <td className="nowrap"><button className="small ghost" onClick={() => setA(v.version)}>A</button><button className="small ghost" onClick={() => setB(v.version)}>B</button></td>
                <td><button className="small" onClick={() => restore(v.version)}>Restore</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Changes v{a} → v{b}</h3>
        {diff && diff.length === 0 && <div className="muted">No differences.</div>}
        <div className="stack small">
          {(diff || []).slice(0, 200).map((d, i) => (
            <div key={i}>
              <code>{d.path}</code> <Badge kind={d.change === "added" ? "ok" : d.change === "removed" ? "bad" : "info"}>{d.change}</Badge>
              <div><span className="diff-old">{show(d.old)}</span> → <span className="diff-new">{show(d.new)}</span></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
