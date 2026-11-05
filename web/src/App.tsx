import { useEffect, useState } from "react";
import { get, Options } from "./api";
import { useFetch, useRoute } from "./hooks";
import { Empty } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { SeriesHome } from "./pages/SeriesHome";
import { BiblePage } from "./pages/Bible";
import { CastPage } from "./pages/Cast";
import { ArcsPage } from "./pages/Arcs";
import { EpisodePage } from "./pages/Episode";
import { QueuePage } from "./pages/Queue";
import { SystemPage } from "./pages/System";

export const OptionsContext = { current: null as Options | null };

function NavLink({ href, active, children, sub }: { href: string; active: boolean; children: React.ReactNode; sub?: boolean }) {
  return <a href={href} className={`${active ? "active" : ""} ${sub ? "sub" : ""}`}>{children}</a>;
}

export default function App() {
  const route = useRoute();
  const [opts, setOpts] = useState<Options | null>(null);
  const series = useFetch<any[]>("/api/series");
  const sys = useFetch<any>("/api/system");
  const sid = route[0] === "s" ? route[1] : (localStorage.getItem("sf.series") || series.data?.[0]?.id);
  const ser = useFetch<any>(sid ? `/api/series/${sid}` : null, [route.join("/")]);

  useEffect(() => {
    get<Options>("/api/options").then((o) => {
      OptionsContext.current = o;
      setOpts(o);
    });
  }, []);
  useEffect(() => {
    if (route[0] === "s" && route[1]) localStorage.setItem("sf.series", route[1]);
  }, [route]);

  const section = route[0] === "s" ? route[2] || "home" : route[0] || "dashboard";
  let page: React.ReactNode;
  if (!opts) page = <Empty>Loading…</Empty>;
  else if (route[0] === "s" && route[1]) {
    const s = route[1];
    switch (route[2]) {
      case "bible":
        page = <BiblePage sid={s} tab={route[3] || "world"} />;
        break;
      case "cast":
        page = <CastPage sid={s} cid={route[3]} />;
        break;
      case "arcs":
        page = <ArcsPage sid={s} aid={route[3]} />;
        break;
      case "ep":
        page = <EpisodePage sid={s} eid={route[3]} tab={route[4] || "overview"} />;
        break;
      default:
        page = <SeriesHome sid={s} />;
    }
  } else if (route[0] === "queue") page = <QueuePage jobId={route[1]} />;
  else if (route[0] === "system") page = <SystemPage />;
  else page = <Dashboard series={series.data} reload={series.reload} system={sys.data} />;

  const llm = sys.data?.llm;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">SF</div>StoryForge</div>
        <nav className="nav">
          <NavLink href="#/" active={section === "dashboard"}>Dashboard</NavLink>
          {sid && (
            <>
              <div className="nav-section ellipsis" title={ser.data?.title}>{ser.data?.title || sid}</div>
              <NavLink href={`#/s/${sid}`} active={section === "home"}>Episodes</NavLink>
              <NavLink href={`#/s/${sid}/arcs`} active={section === "arcs"}>Arc planner</NavLink>
              <NavLink href={`#/s/${sid}/bible`} active={section === "bible"}>Series bible</NavLink>
              <NavLink href={`#/s/${sid}/cast`} active={section === "cast"}>Cast &amp; characters</NavLink>
              {(ser.data?.episodes || []).slice(0, 12).map((e: any) => (
                <NavLink key={e.id} sub href={`#/s/${sid}/ep/${e.id}`} active={section === "ep" && route[3] === e.id}>
                  <span className="ellipsis">{e.arc_id ? `P${e.part} · ` : ""}{e.title || e.id}</span>
                </NavLink>
              ))}
            </>
          )}
          <div className="nav-section">Production</div>
          <NavLink href="#/queue" active={section === "queue"}>Render queue</NavLink>
          <NavLink href="#/system" active={section === "system"}>System</NavLink>
        </nav>
        <div className="sidebar-foot">
          {llm ? <>LLM: <b>{llm.provider}</b>{llm.model ? ` · ${llm.model}` : ""}</> : "…"}
          {sys.data?.demo_mode && <div>Demo mode (no API keys)</div>}
        </div>
      </aside>
      <main className="main">{page}</main>
    </div>
  );
}
