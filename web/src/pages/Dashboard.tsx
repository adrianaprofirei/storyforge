import { useState } from "react";
import { post } from "../api";
import { Badge, Errors, Field, Kv, useToast } from "../components/ui";
import { go } from "../hooks";

export function Dashboard({ series, reload, system }: { series: any[] | null; reload: () => void; system: any }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const create = async (template: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await post<{ id: string }>("/api/series", { template, title, logline });
      toast(template === "demo" ? "Demo series ready" : `Series ${r.id} created`);
      reload();
      go(`s/${r.id}`);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>StoryForge</h1>
          <p>Story idea → multi-part vertical animated shorts, rendered in Blender. Output files only.</p>
        </div>
      </div>
      <div className="grid cols-2">
        <div className="card">
          <div className="card-head"><h2>Series</h2></div>
          {series && series.length ? (
            <div className="stack">
              {series.map((s) => (
                <a key={s.id} className="card" style={{ display: "block", boxShadow: "none" }} href={`#/s/${s.id}`}>
                  <div className="row between">
                    <b>{s.title}</b>
                    <span className="row small muted">
                      <Badge>{s.style}</Badge> bible v{s.version} · {s.arcs} arcs · {s.episodes} parts
                    </span>
                  </div>
                  <div className="small muted">{s.logline}</div>
                </a>
              ))}
            </div>
          ) : (
            <div className="alert info">No series yet. Start with the bundled demo (works without any API keys).</div>
          )}
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy} onClick={() => create("demo")}>Open the demo series</button>
          </div>
          <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "16px 0" }} />
          <h3>New series</h3>
          <div className="stack">
            <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="The Lighthouse Kids" /></Field>
            <Field label="Logline"><input value={logline} onChange={(e) => setLogline(e.target.value)} placeholder="Three friends solve tiny mysteries in a seaside town" /></Field>
            <div className="small muted">Starts from the sample bible and cast (original characters); edit both afterwards.</div>
            <Errors error={err} />
            <div><button disabled={busy || !title.trim()} onClick={() => create("blank")}>Create series</button></div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>System</h2><a href="#/system" className="small">details</a></div>
          {system ? (
            <Kv items={[
              ["LLM", <span key="l">{system.llm?.provider} {system.llm?.model && <span className="muted">({system.llm.model})</span>}
                {system.llm?.fallbacks && system.llm.fallbacks !== "off" && <Badge kind="info">fallbacks: {String(system.llm.fallbacks)}</Badge>}</span>],
              ["Voices (TTS)", (system.tts_available || []).join(", ") || "silent (captions only)"],
              ["Blender", system.blender || <Badge kind="bad">not found: set BLENDER_PATH</Badge>],
              ["Render device", system.render_device],
              ["ffmpeg", system.ffmpeg || <Badge kind="bad">missing</Badge>],
              ["Rhubarb", system.rhubarb || <span className="muted">not found (amplitude lip-sync fallback)</span>],
              ["Demo mode", system.demo_mode ? <Badge kind="warn">yes: no API keys, bundled samples</Badge> : "no"],
              ["Data folder", <code key="d">{system.data_dir}</code>],
            ]} />
          ) : "…"}
        </div>
      </div>
    </div>
  );
}
