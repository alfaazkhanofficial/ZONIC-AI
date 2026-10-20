import { useEffect, useRef, type ReactNode } from "react";
import { getBridge } from "../lib/bridge";
import { PROFILES } from "../lib/avatar";
import { useMedia } from "../lib/hooks";
import { useCoreState } from "../lib/useCoreState";
import { useStore, type View } from "../lib/store";
import { Activity } from "../views/Activity";
import { HomeDashboard } from "../views/Home";
import { MemoryView } from "../views/Memory";
import { Permissions, Projects } from "../views/Projects";
import { SettingsView } from "../views/Settings";
import { Skills } from "../views/Skills";
import { Tasks } from "../views/Tasks";
import { ConversationPanel } from "./ConversationPanel";
import { IconActivity, IconChat, IconHome, IconMemory, IconMenu, IconFolder, IconSettings, IconShield, IconSidebar, IconTasks, IconTools, IconLogs, IconRefresh } from "./icons";
import { Btn, IconButton } from "./ui";

interface NavItem { key: string; view: View; label: string; icon: ReactNode; tab?: string }
const WORKSPACE: NavItem[] = [
  { key: "home", view: "home", label: "Home", icon: <IconHome /> },
  { key: "tasks", view: "tasks", label: "Tasks", icon: <IconTasks /> },
  { key: "memory", view: "memory", label: "Memory", icon: <IconMemory /> },
  { key: "skills", view: "skills", label: "Skills & Tools", icon: <IconTools /> },
  { key: "projects", view: "projects", label: "Projects", icon: <IconFolder /> },
];
const SYSTEM: NavItem[] = [
  { key: "permissions", view: "permissions", label: "Permissions", icon: <IconShield /> },
  { key: "activity", view: "activity", label: "Activity", icon: <IconActivity /> },
  { key: "diagnostics", view: "settings", label: "Diagnostics", icon: <IconLogs />, tab: "diag" },
  { key: "settings", view: "settings", label: "Settings", icon: <IconSettings /> },
];

/** TopStatusBar: identity + live status derived from real state. */
function TopStatusBar() {
  const { state } = useCoreState();
  const link = useStore((s) => s.link);
  const status = useStore((s) => s.status);
  const chatCollapsed = useStore((s) => s.chatCollapsed);
  const navCollapsed = useStore((s) => s.navCollapsed);
  const drawer = useStore((s) => s.drawer);
  const toggleNav = useStore((s) => s.toggleNav);
  const toggleChat = useStore((s) => s.toggleChat);
  const setDrawer = useStore((s) => s.setDrawer);
  const p = PROFILES[state];
  const ok = link === "live";
  return (
    <header className="topbar">
      <IconButton label="Open navigation" className="only-narrow" pressed={drawer === "nav"} onClick={() => setDrawer(drawer === "nav" ? null : "nav")}><IconMenu /></IconButton>
      <IconButton label={navCollapsed ? "Expand navigation" : "Collapse navigation"} className="btn-navtoggle only-wide" onClick={toggleNav}><IconMenu /></IconButton>
      <div className="brand"><img src="./zonic-mark.png" alt="" width={30} height={30} /><span className="wordmark">ZONIC <b>M4</b></span></div>
      <div className="top-status" role="status" aria-label="Assistant status">
        <span className="pill state"><span className="dot" style={{ background: p.color, boxShadow: `0 0 6px ${p.color}` }} aria-hidden />{p.label}</span>
        <span className="pill optional"><span className={`dot ${ok ? "live" : link === "connecting" ? "wait" : "bad"}`} aria-hidden />{ok ? `Backend ready${status ? ` · v${status.backend.version}` : ""}` : link === "connecting" ? "Connecting…" : "Backend unreachable"}</span>
        {status && <span className="pill model optional" title={`${status.model.provider} · ${status.model.model}`}>{status.model.state === "ready" ? status.model.model : `Model: ${status.model.state.replace("_", " ")}`}</span>}
        {status?.limited_mode && <span className="pill warn optional"><span aria-hidden>◐</span>Limited mode</span>}
      </div>
      <span className="grow" />
      <IconButton label="Open conversation" className="only-narrow" pressed={drawer === "chat"} onClick={() => setDrawer(drawer === "chat" ? null : "chat")}><IconChat /></IconButton>
      {chatCollapsed && <IconButton label="Show conversation panel" className="only-wide" onClick={toggleChat}><IconSidebar /></IconButton>}
    </header>
  );
}

/** WorkspaceNavigation: real view switches; the active destination is marked with aria-current. */
function WorkspaceNavigation() {
  const view = useStore((s) => s.view);
  const tab = useStore((s) => s.settingsTab);
  const setView = useStore((s) => s.setView);
  const setTab = useStore((s) => s.setSettingsTab);
  const pending = useStore((s) => s.approvals.length);
  const version = useStore((s) => s.conn?.version);
  const go = (n: NavItem) => { if (n.view === "settings") setTab(n.tab ?? (tab === "diag" ? "model" : tab)); setView(n.view); };
  const active = (n: NavItem) => (n.view !== "settings" ? view === n.view : view === "settings" && (n.tab === "diag" ? tab === "diag" : tab !== "diag"));
  const item = (n: NavItem) => (
    <button key={n.key} type="button" className="item" aria-current={active(n) ? "page" : undefined} onClick={() => go(n)} title={n.label} aria-label={n.label}>
      <span className="ico">{n.icon}</span><span className="label">{n.label}</span>
      {n.key === "tasks" && pending > 0 && <span className="badge" aria-label={`${pending} approvals waiting`}>{pending}</span>}
    </button>
  );
  return (
    <>
      <nav className="nav" aria-label="Workspace">
        <div className="group-label">Workspace</div>{WORKSPACE.map(item)}
        <div className="group-label">System</div>{SYSTEM.map(item)}
      </nav>
      <div className="nav-foot"><span className="ver">ZONIC M4{version ? ` · v${version}` : ""}</span></div>
    </>
  );
}

/** WorkspaceViewRouter: the centre column. Home is the default. */
function WorkspaceViewRouter() {
  const view = useStore((s) => s.view);
  const screens: Record<View, ReactNode> = { home: <HomeDashboard />, tasks: <Tasks />, memory: <MemoryView />, skills: <Skills />, projects: <Projects />, permissions: <Permissions />, activity: <Activity />, settings: <SettingsView /> };
  return <main className="main" id="main" tabIndex={-1} aria-label="Workspace view" key={view}>{screens[view]}</main>;
}

export function AppShell() {
  const link = useStore((s) => s.link);
  const navCollapsed = useStore((s) => s.navCollapsed);
  const chatCollapsed = useStore((s) => s.chatCollapsed);
  const drawer = useStore((s) => s.drawer);
  const setDrawer = useStore((s) => s.setDrawer);
  const refreshAll = useStore((s) => s.refreshAll);
  const narrow = useMedia("(max-width: 899px)");
  const main = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!narrow && drawer) setDrawer(null); }, [narrow, drawer, setDrawer]);
  useEffect(() => {
    if (!drawer) return;
    const f = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(null); };
    document.addEventListener("keydown", f);
    return () => document.removeEventListener("keydown", f);
  }, [drawer, setDrawer]);
  const banner = link === "reconnecting";
  return (
    <div className="app" ref={main} style={{ ["--banner-h" as string]: banner ? "35px" : "0px" }}>
      <TopStatusBar />
      {banner ? <div className="banner" role="alert">Lost contact with the local backend. Retrying automatically… <Btn small onClick={() => { void getBridge().retryBackend(); void refreshAll(); }}><IconRefresh size={13} />Retry now</Btn></div> : <div />}
      <div className={`workspace shell ${navCollapsed ? "nav-rail" : ""} ${chatCollapsed ? "chat-hidden" : ""}`}>
        <aside className="panel-left" data-open={drawer === "nav"} aria-label="Navigation"><WorkspaceNavigation /></aside>
        <WorkspaceViewRouter />
        <aside className="panel-right" data-open={drawer === "chat"} aria-label="Conversation"><ConversationPanel drawer={narrow} /></aside>
        {drawer && <button type="button" className="scrim-drawer" aria-label="Close panel" onClick={() => setDrawer(null)} />}
      </div>
    </div>
  );
}
