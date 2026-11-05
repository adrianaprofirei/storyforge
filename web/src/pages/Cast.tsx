import { useEffect, useMemo, useState } from "react";
import { api, Job, post, put } from "../api";
import { OptionsContext } from "../App";
import { CharacterSVG } from "../components/CharacterSVG";
import { Badge, Empty, Errors, Field, JobStatus, Select, useToast } from "../components/ui";
import { go, useDebounced, useFetch } from "../hooks";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const EXPRESSIONS = ["neutral", "happy", "sad", "shocked"];

export function CastPage({ sid, cid }: { sid: string; cid?: string }) {
  const cast = useFetch<any[]>(`/api/series/${sid}/cast`);
  const [showNew, setShowNew] = useState(false);
  useEffect(() => {
    if (!cid && cast.data?.length) go(`s/${sid}/cast/${cast.data[0].id}`);
  }, [cid, cast.data, sid]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Cast &amp; characters</h1>
          <p>Original characters only. A character looks and sounds identical in every episode: this registry is the single source.</p>
        </div>
        <button onClick={() => setShowNew((v) => !v)}>New / import character</button>
      </div>
      {showNew && <NewCharacter sid={sid} onCreated={(id) => { setShowNew(false); cast.reload(); go(`s/${sid}/cast/${id}`); }} />}
      <div className="char-layout">
        <div className="card" style={{ padding: 8 }}>
          {(cast.data || []).map((c) => (
            <div key={c.id} className={`cast-item ${c.id === cid ? "active" : ""}`} onClick={() => go(`s/${sid}/cast/${c.id}`)}>
              {c._preview ? <img src={c._preview} alt="" /> : <CharacterSVG look={c.look || {}} width={40} />}
              <div>
                <div><b>{c.name}</b></div>
                <div className="small muted">{c.id} · {c.kind}</div>
              </div>
            </div>
          ))}
        </div>
        {cid && cast.data && <Editor key={cid} sid={sid} entry={cast.data.find((c) => c.id === cid)} onSaved={() => cast.reload()} />}
      </div>
    </div>
  );
}

function Editor({ sid, entry, onSaved }: { sid: string; entry: any; onSaved: () => void }) {
  const toast = useToast();
  const opts = OptionsContext.current!;
  const [e, setE] = useState<any>(() => clone(entry || {}));
  const [err, setErr] = useState<unknown>(null);
  const [expr, setExpr] = useState("neutral");
  const [previewJob, setPreviewJob] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(entry?._preview || null);
  const [autoPreview, setAutoPreview] = useState(false);
  const dirty = useMemo(() => JSON.stringify(e) !== JSON.stringify(entry), [e, entry]);
  const debounced = useDebounced(e, 1200);

  useEffect(() => {
    if (autoPreview) renderPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, autoPreview]);

  if (!entry) return <Empty>Unknown character.</Empty>;
  const look = e.look || {};
  const set = (fn: (x: any) => void) => setE((x: any) => {
    const n = clone(x);
    fn(n);
    return n;
  });
  const save = async () => {
    setErr(null);
    try {
      await put(`/api/series/${sid}/cast/${e.id}`, e);
      toast(`${e.name} saved`);
      onSaved();
    } catch (x) {
      setErr(x);
    }
  };
  async function renderPreview() {
    try {
      const j = await post(`/api/series/${sid}/cast/${e.id}/preview`, { cast: e });
      setPreviewJob(j.id);
    } catch (x: any) {
      toast(x.message, true);
    }
  }
  const onPreviewDone = (j: Job) => {
    if (j.status === "done" && j.result?.image) setPreviewUrl(`/api/files/${sid}/${j.result.image}?t=${Date.now()}`);
  };
  const accs = new Map((look.accessories || []).map((a: any) => [a.type, a]));

  return (
    <>
      <div className="stack">
        <div className="card">
          <div className="card-head">
            <h2>{e.name} <span className="muted small mono">{e.id}</span> {e.kind === "imported" && <Badge kind="info">imported rig</Badge>}</h2>
            <div className="row">
              <button disabled={!dirty} onClick={() => setE(clone(entry))}>Discard</button>
              <button className="primary" disabled={!dirty} onClick={save}>Save</button>
            </div>
          </div>
          <Errors error={err} />
          <div className="grid cols-3">
            <Field label="Name"><input value={e.name} onChange={(x) => set((n) => (n.name = x.target.value))} /></Field>
            <Field label="Walk style"><Select value={e.settings?.walk_style || "normal"} options={["normal", "bouncy", "sneaky", "heavy", "brisk"]} onChange={(v) => set((n) => ((n.settings ||= {}).walk_style = v))} /></Field>
            <Field label={`Idle energy (${Number(e.settings?.idle_energy ?? 0.6).toFixed(2)})`}><input type="range" min={0.1} max={1.2} step={0.05} value={e.settings?.idle_energy ?? 0.6} onChange={(x) => set((n) => ((n.settings ||= {}).idle_energy = Number(x.target.value)))} /></Field>
            <Field label={`Gesture scale (${Number(e.settings?.gesture_scale ?? 1).toFixed(2)})`}><input type="range" min={0.5} max={1.6} step={0.05} value={e.settings?.gesture_scale ?? 1} onChange={(x) => set((n) => ((n.settings ||= {}).gesture_scale = Number(x.target.value)))} /></Field>
            <Field label={`Blink rate (${Number(e.settings?.blink_rate ?? 1).toFixed(2)})`}><input type="range" min={0.5} max={1.8} step={0.05} value={e.settings?.blink_rate ?? 1} onChange={(x) => set((n) => ((n.settings ||= {}).blink_rate = Number(x.target.value)))} /></Field>
          </div>
        </div>

        {e.kind === "imported" ? (
          <div className="card stack">
            <h3>Imported character</h3>
            <Field label="File (relative to the series' characters folder or assets/characters)"><input value={e.import?.file || ""} onChange={(x) => set((n) => ((n.import ||= {}).file = x.target.value))} /></Field>
            <Field label="Scale (empty = fit to height)"><input type="number" step="0.01" value={e.import?.scale ?? ""} onChange={(x) => set((n) => { (n.import ||= {}); if (x.target.value) n.import.scale = Number(x.target.value); else delete n.import.scale; })} /></Field>
            <Field label="Bone map overrides (JSON: canonical → your bone)">
              <textarea className="mono" value={JSON.stringify(e.import?.bone_map || {}, null, 1)} onChange={(x) => { try { const v = JSON.parse(x.target.value); set((n) => ((n.import ||= {}).bone_map = v)); } catch { /* typing */ } }} />
            </Field>
          </div>
        ) : (
          <>
            <div className="card">
              <h3>Body</h3>
              <div className="grid cols-4">
                {opts.body_keys.map((k) => (
                  <Field key={k} label={`${k.replace(/_/g, " ")} (${Number(look.body?.[k] ?? 1).toFixed(2)})`}>
                    <input type="range" min={0.6} max={1.5} step={0.01} value={look.body?.[k] ?? 1} onChange={(x) => set((n) => (((n.look ||= {}).body ||= {})[k] = Number(x.target.value)))} />
                  </Field>
                ))}
              </div>
            </div>
            <div className="card">
              <h3>Colours</h3>
              <div className="swatches">
                {opts.color_keys.map((k) => (
                  <label key={k} className="swatch">
                    <input type="color" value={look.colors?.[k] || "#888888"} onChange={(x) => set((n) => (((n.look ||= {}).colors ||= {})[k] = x.target.value.toUpperCase()))} />
                    {k.replace(/_/g, " ")}
                  </label>
                ))}
              </div>
            </div>
            <div className="card">
              <h3>Hair, clothing, face</h3>
              <div className="grid cols-4">
                <Field label="Hair"><Select value={look.hair?.style || "short"} options={opts.hair_styles} onChange={(v) => set((n) => (((n.look ||= {}).hair ||= {}).style = v))} /></Field>
                <Field label="Top"><Select value={look.clothing?.top || "tshirt"} options={opts.tops} onChange={(v) => set((n) => (((n.look ||= {}).clothing ||= {}).top = v))} /></Field>
                <Field label="Pattern"><Select value={look.clothing?.top_pattern || "solid"} options={opts.patterns} onChange={(v) => set((n) => (((n.look ||= {}).clothing ||= {}).top_pattern = v))} /></Field>
                <Field label="Bottom"><Select value={look.clothing?.bottom || "pants"} options={opts.bottoms} onChange={(v) => set((n) => (((n.look ||= {}).clothing ||= {}).bottom = v))} /></Field>
                <Field label={`Eye size (${Number(look.face?.eye_size ?? 1).toFixed(2)})`}><input type="range" min={0.7} max={1.4} step={0.01} value={look.face?.eye_size ?? 1} onChange={(x) => set((n) => (((n.look ||= {}).face ||= {}).eye_size = Number(x.target.value)))} /></Field>
                <Field label={`Brows (${Number(look.face?.brow_thickness ?? 1).toFixed(2)})`}><input type="range" min={0.5} max={1.8} step={0.01} value={look.face?.brow_thickness ?? 1} onChange={(x) => set((n) => (((n.look ||= {}).face ||= {}).brow_thickness = Number(x.target.value)))} /></Field>
                <Field label={`Mouth width (${Number(look.face?.mouth_width ?? 1).toFixed(2)})`}><input type="range" min={0.7} max={1.4} step={0.01} value={look.face?.mouth_width ?? 1} onChange={(x) => set((n) => (((n.look ||= {}).face ||= {}).mouth_width = Number(x.target.value)))} /></Field>
                <label className="check" style={{ alignSelf: "end" }}><input type="checkbox" checked={!!look.face?.freckles} onChange={(x) => set((n) => (((n.look ||= {}).face ||= {}).freckles = x.target.checked))} /> freckles</label>
              </div>
              <h3 style={{ marginTop: 12 }}>Accessories</h3>
              <div className="row">
                {opts.accessories.map((t) => {
                  const a: any = accs.get(t);
                  return (
                    <label key={t} className="check" style={{ border: "1px solid var(--line)", padding: "4px 8px", borderRadius: 8 }}>
                      <input type="checkbox" checked={!!a} onChange={(x) => set((n) => {
                        const list = ((n.look ||= {}).accessories ||= []).filter((y: any) => y.type !== t);
                        if (x.target.checked) list.push({ type: t, color: "#5A4A3A" });
                        n.look.accessories = list;
                      })} />
                      {t}
                      {a && <input type="color" value={a.color || "#5A4A3A"} onChange={(x) => set((n) => { n.look.accessories.find((y: any) => y.type === t).color = x.target.value.toUpperCase(); })} />}
                    </label>
                  );
                })}
              </div>
            </div>
          </>
        )}

        <div className="card">
          <h3>Voice</h3>
          <div className="grid cols-3">
            <Field label="OpenAI TTS voice"><Select value={e.voice?.openai?.voice} allowNone options={opts.voices.openai} onChange={(v) => set((n) => (((n.voice ||= {}).openai ||= {}).voice = v))} /></Field>
            <Field label="ElevenLabs voice id"><input value={e.voice?.elevenlabs?.voice_id || ""} placeholder="from your ElevenLabs voice library" onChange={(x) => set((n) => (((n.voice ||= {}).elevenlabs ||= {}).voice_id = x.target.value || null))} /></Field>
            <Field label="Piper voice (offline)"><Select value={e.voice?.piper?.model} allowNone options={opts.voices.piper.length ? opts.voices.piper : [e.voice?.piper?.model].filter(Boolean)} onChange={(v) => set((n) => (((n.voice ||= {}).piper ||= {}).model = v))} /></Field>
            <Field label={`Pitch shift (${Number(e.voice?.pitch_semitones ?? 0).toFixed(1)} semitones)`}><input type="range" min={-6} max={6} step={0.5} value={e.voice?.pitch_semitones ?? 0} onChange={(x) => set((n) => ((n.voice ||= {}).pitch_semitones = Number(x.target.value)))} /></Field>
            <div style={{ gridColumn: "span 2" }}><Field label="Base voice direction (sent with every line)"><input value={e.voice?.base_direction || ""} onChange={(x) => set((n) => ((n.voice ||= {}).base_direction = x.target.value))} /></Field></div>
          </div>
        </div>
      </div>

      <div className="card char-preview stack">
        <div className="row between">
          <h3 style={{ margin: 0 }}>Preview</h3>
          <Select value={expr} options={EXPRESSIONS} onChange={(v) => setExpr(v || "neutral")} />
        </div>
        <div className="preview-box"><CharacterSVG look={look} width={200} expression={expr} /></div>
        <div className="small muted">Instant sketch. The Blender render below is the real character.</div>
        <div className="row">
          <button onClick={renderPreview}>Render in Blender</button>
          <label className="check"><input type="checkbox" checked={autoPreview} onChange={(x) => setAutoPreview(x.target.checked)} /> auto</label>
        </div>
        <JobStatus jobId={previewJob} onDone={onPreviewDone} compact />
        {previewUrl && <div className="preview-box"><img src={previewUrl} alt="Blender preview" /></div>}
      </div>
    </>
  );
}

function NewCharacter({ sid, onCreated }: { sid: string; onCreated: (id: string) => void }) {
  const toast = useToast();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("procedural");
  const [file, setFile] = useState<File | null>(null);
  const [license, setLicense] = useState("");
  const [inspectJob, setInspectJob] = useState<string | null>(null);
  const [report, setReport] = useState<any>(null);
  const [uploaded, setUploaded] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  const upload = async () => {
    if (!file) return;
    setErr(null);
    const form = new FormData();
    form.append("file", file);
    form.append("license", license);
    try {
      const r = await api(`/api/series/${sid}/uploads/character`, { form });
      setUploaded(r.file);
      const j = await post(`/api/series/${sid}/characters/inspect`, { file: r.file });
      setInspectJob(j.id);
    } catch (x) {
      setErr(x);
    }
  };
  const create = async () => {
    setErr(null);
    try {
      await post(`/api/series/${sid}/cast`, { id, name, kind, file: uploaded });
      toast(`${name || id} created`);
      onCreated(id);
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <div className="card stack" style={{ marginBottom: 14 }}>
      <h3>New character</h3>
      <div className="grid cols-3">
        <Field label="Id (lowercase, used in scripts)"><input value={id} onChange={(x) => setId(x.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} placeholder="robo" /></Field>
        <Field label="Name"><input value={name} onChange={(x) => setName(x.target.value)} placeholder="Robo" /></Field>
        <Field label="Kind"><Select value={kind} options={[{ value: "procedural", label: "procedural blocky figure" }, { value: "imported", label: "my rigged character (.blend/.fbx/.glb)" }]} onChange={(v) => setKind(v || "procedural")} /></Field>
      </div>
      {kind === "imported" && (
        <div className="stack">
          <div className="grid cols-2">
            <Field label="Rigged character file"><input type="file" accept=".blend,.fbx,.glb,.gltf" onChange={(x) => setFile(x.target.files?.[0] || null)} /></Field>
            <Field label="License / source (stored in the license manifest)"><input value={license} onChange={(x) => setLicense(x.target.value)} placeholder="made by me / CC-BY 4.0 (credit …)" /></Field>
          </div>
          <div><button disabled={!file} onClick={upload}>Upload &amp; inspect</button></div>
          <JobStatus jobId={inspectJob} compact onDone={(j) => setReport(j.result?.report || null)} />
          {report && (
            <div className={`alert ${report.ok ? "ok" : "warn"}`}>
              {report.ok ? "Rig recognised: every required bone was mapped." : `Missing bones: ${(report.missing || []).join(", ")} (add them in the bone map after creating).`}
              <div className="small">Armature {report.armature}, {report.bones?.length} bones, {report.shape_keys?.length || 0} shape keys, face preset {report.face_preset || "none"}.</div>
            </div>
          )}
        </div>
      )}
      <Errors error={err} />
      <div><button className="primary" disabled={!id || (kind === "imported" && !uploaded)} onClick={create}>Create</button></div>
    </div>
  );
}
