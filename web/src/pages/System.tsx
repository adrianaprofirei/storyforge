import { Badge, Empty, Kv } from "../components/ui";
import { useFetch } from "../hooks";

export function SystemPage() {
  const sys = useFetch<any>("/api/system");
  if (!sys.data) return <Empty>Loading…</Empty>;
  const s = sys.data;
  const ok = (v: any) => (v ? <Badge kind="ok">found</Badge> : <Badge kind="bad">missing</Badge>);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>System</h1>
          <p>Tools, providers and render settings resolved from your <code>.env</code>. Run <code>storyforge doctor</code> for a full Blender/GPU check.</p>
        </div>
        <button onClick={() => sys.reload()}>Refresh</button>
      </div>
      <div className="grid cols-2">
        <div className="card">
          <h3>Story (LLM)</h3>
          <Kv items={Object.entries(s.llm || {}).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)])} />
          {s.demo_mode && <div className="alert warn small" style={{ marginTop: 10 }}>Demo mode: no LLM key, so arcs/screenplays come from the bundled samples and templates. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to <code>.env</code>.</div>}
        </div>
        <div className="card">
          <h3>Voices</h3>
          <Kv items={[["Available TTS", (s.tts_available || []).join(", ") || "none (silent + captions)"], ["Preference", s.tts_provider], ["Piper voices", <code key="p">{s.piper_voices_dir}</code>], ["Piper", s.piper || "–"], ["eSpeak", s.espeak || "–"]]} />
        </div>
        <div className="card">
          <h3>Rendering</h3>
          <Kv items={[["Blender", s.blender || <Badge kind="bad">set BLENDER_PATH</Badge>], ["Device", s.render_device], ["Parallel shots", s.render_workers], ["ffmpeg", s.ffmpeg ? <code key="f">{s.ffmpeg}</code> : ok(false)], ["libass (captions)", ok(s.ffmpeg_capabilities?.libass)], ["H.264 (libx264)", ok(s.ffmpeg_capabilities?.libx264)], ["Rhubarb lip-sync", s.rhubarb || <span className="muted">not found (amplitude fallback)</span>]]} />
        </div>
        <div className="card">
          <h3>Environment</h3>
          <Kv items={[["Python", s.python], ["Platform", s.platform], ["Data folder", <code key="d">{s.data_dir}</code>], ["Running jobs", (s.jobs_running || []).length]]} />
        </div>
      </div>
    </div>
  );
}
