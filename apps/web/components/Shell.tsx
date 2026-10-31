"use client";

import { Activity, BarChart3, Brain, CalendarClock, CalendarDays, Command, Cpu, Home, Gauge, LogOut, MessageSquare, Moon, Network, OctagonX, Radar, Rocket, ScrollText, Settings, ShieldCheck, Sparkles, Sun, Users, Wrench, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { saveFx, useFx, type FxLevel } from "@/lib/fx";
import { applyTheme, saveTheme } from "@/lib/theme";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";
import { CommandPalette, type PaletteAction } from "./CommandPalette";
import { BootOverlay } from "./fx/BootOverlay";
import { ParticleField } from "./fx/ParticleField";
import { LiveView } from "./LiveView";
import { useStark } from "@/lib/store";
import { ActivityView } from "./ActivityView";
import { ApprovalsView } from "./ApprovalsView";
import { AutopilotView } from "./AutopilotView";
import { CommandView } from "./CommandView";
import { ContentView } from "./ContentView";
import { HomeView } from "./HomeView";
import { DiagnosticsView } from "./DiagnosticsView";
import { MemoryView } from "./MemoryView";
import { ModelsView } from "./ModelsView";
import { SettingsView } from "./SettingsView";
import { TasksView } from "./TasksView";
import { TeamView } from "./TeamView";
import { ToolsView } from "./ToolsView";
import { UsageView } from "./UsageView";
import { AgentGlyph } from "./ui";

export type View = "home" | "live" | "calendar" | "analytics" | "command" | "content" | "autopilot" | "team" | "tasks" | "approvals" | "memory" | "models" | "tools" | "diagnostics" | "usage" | "activity" | "settings";

const NAV: { id: View; label: string; icon: React.ElementType }[] = [
  { id: "home", label: "Start", icon: Home },
  { id: "live", label: "Live", icon: Radar },
  { id: "command", label: "Command", icon: MessageSquare },
  { id: "content", label: "Content", icon: CalendarClock },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "autopilot", label: "Autopilot", icon: Rocket },
  { id: "team", label: "Agents", icon: Users },
  { id: "tasks", label: "Tasks", icon: Network },
  { id: "approvals", label: "Approvals", icon: ShieldCheck },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "models", label: "Models", icon: Cpu },
  { id: "tools", label: "Tools", icon: Wrench },
  { id: "diagnostics", label: "Diagnostics", icon: Activity },
  { id: "usage", label: "Usage", icon: Gauge },
  { id: "activity", label: "Activity", icon: ScrollText },
  { id: "settings", label: "Settings", icon: Settings },
];

const MODES = [
  { id: "observe", label: "Observe" },
  { id: "assist", label: "Assist" },
  { id: "execute_approved", label: "Execute approved" },
];

export function Shell({ onSignOut }: { onSignOut: () => void }) {
  const { status, approvals, sseConnected, client, notify, toasts, dismiss, error, agents } = useStark();
  const [view, setViewRaw] = useState<View>("home");
  const [boot, setBoot] = useState(0);
  const [palette, setPalette] = useState(false);
  const fx = useFx();
  const setView = useCallback((v: View) => {
    setViewRaw(v);
    setBoot((b) => b + 1);
  }, []);
  const activity = agents.length ? agents.filter((a) => ["thinking", "executing", "collaborating", "listening", "waiting_approval"].includes(a.live?.status)).length / agents.length : 0;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const cycleFx = () => saveFx(({ max: "calm", calm: "off", off: "max" } as Record<FxLevel, FxLevel>)[fx]);
  const [focusAgent, setFocusAgent] = useState<string>("jarvis");
  const [focusTask, setFocusTask] = useState<string | null>(null);
  const estop = status?.emergency_stop;

  async function toggleEstop() {
    try {
      if (estop) await client.post("/api/estop/reset");
      else await client.post("/api/estop");
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function setMode(mode: string) {
    try {
      await client.post("/api/settings/mode", { mode });
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  const openTask = (id: string) => {
    setFocusTask(id);
    setView("tasks");
  };
  const [prefill, setPrefill] = useState<string>("");
  const talkTo = (id: string, text?: string) => {
    setFocusAgent(id);
    setPrefill(text || "");
    setView("command");
  };

  const noModel = status && status.active_providers.length === 0;

  const actions = useMemo<PaletteAction[]>(() => {
    const out: PaletteAction[] = NAV.map((n) => ({ id: `go-${n.id}`, label: n.label, group: "Go to", icon: n.icon, color: "#22d3ee", run: () => setView(n.id) }));
    for (const a of agents) out.push({ id: `talk-${a.id}`, label: `Talk to ${a.name}`, hint: a.role, group: "Agent", icon: Sparkles, color: a.color, run: () => talkTo(a.id) });
    out.push(
      { id: "estop", label: estop ? "Reset emergency stop" : "Emergency stop", group: "Action", icon: OctagonX, color: "#f87171", run: toggleEstop },
      { id: "theme-dark", label: "Dark theme", group: "Appearance", icon: Moon, run: () => (saveTheme("dark"), applyTheme("dark")) },
      { id: "theme-light", label: "Light theme", group: "Appearance", icon: Sun, run: () => (saveTheme("light"), applyTheme("light")) },
      { id: "fx-max", label: "Effects: maximum", group: "Appearance", icon: Sparkles, run: () => saveFx("max") },
      { id: "fx-calm", label: "Effects: calm", group: "Appearance", icon: Sparkles, run: () => saveFx("calm") },
      { id: "fx-off", label: "Effects: off", group: "Appearance", icon: Sparkles, run: () => saveFx("off") },
    );
    for (const m of MODES) out.push({ id: `mode-${m.id}`, label: `Mode: ${m.label}`, group: "Action", icon: ShieldCheck, run: () => setMode(m.id) });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, estop, setView]);

  return (
    <>
    {fx === "max" && <ParticleField activity={activity} />}
    <div className="relative z-[1] flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 flex flex-wrap items-center gap-3 border-b border-[var(--color-line)] bg-[color-mix(in_srgb,var(--color-bg)_80%,transparent)] px-4 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <span className="relative inline-flex h-[30px] w-[30px] items-center justify-center">
            <svg viewBox="0 0 30 30" className="absolute inset-0" aria-hidden>
              <circle cx="15" cy="15" r="14" fill="none" stroke="#a78bfa" strokeOpacity={0.7} strokeDasharray="6 4 1 4" className="orbit" />
              <circle cx="15" cy="15" r="11.5" fill="none" stroke="#f472b6" strokeOpacity={0.5} strokeDasharray="2 5" className="orbit-rev" />
            </svg>
            <AgentGlyph icon="core" color="#22d3ee" size={20} active={activity > 0} />
          </span>
          <div className="leading-tight">
            <div className="holo-text text-sm font-semibold tracking-[0.3em]">STARK OS</div>
            <div className="hud-label text-[var(--color-mute)]">Project Genesis</div>
          </div>
        </div>
        <div className="ml-2 flex items-center gap-2 text-xs text-[var(--color-mute)]">
          <span className={`inline-block h-2 w-2 rounded-full ${sseConnected ? "bg-emerald-400" : "bg-red-400 anim-pulse"}`} />
          <span>{sseConnected ? "Live" : "Reconnecting"}</span>
          {status && (
            <span className="chip hidden sm:inline-flex">
              {status.active_providers.length
                ? `Free models${status.quota ? ` · ${status.quota.remaining}/${status.quota.limit} requests left today` : ""}`
                : "No model configured"}
            </span>
          )}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn !py-1.5 text-xs" onClick={() => setPalette(true)} title="Command palette (Ctrl/⌘ K)" aria-label="Command palette">
            <Command size={13} />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden rounded border border-[var(--color-line-strong)] px-1 font-mono text-[10px] sm:inline">⌘K</kbd>
          </button>
          <button className="btn !py-1.5 text-xs" onClick={cycleFx} title="Visual effects: maximum, calm or off" aria-label={`Visual effects: ${fx}`}>
            <Sparkles size={13} className={fx === "max" ? "text-fuchsia-300" : fx === "calm" ? "text-cyan-300" : "text-[var(--color-mute)]"} />
            <span className="hidden capitalize sm:inline">FX {fx === "max" ? "Max" : fx}</span>
          </button>
          <select
            aria-label="Execution mode"
            className="input !w-auto !py-1.5 text-xs"
            value={status?.mode || "assist"}
            onChange={(e) => setMode(e.target.value)}
          >
            {MODES.map((m) => (
              <option key={m.id} value={m.id}>
                Mode: {m.label}
              </option>
            ))}
          </select>
          <button onClick={toggleEstop} className={`btn ${estop ? "btn-primary" : "btn-danger"} font-semibold`} title="Global emergency stop">
            <OctagonX size={16} />
            {estop ? "Reset E-Stop" : "E-STOP"}
          </button>
          <button className="btn" onClick={onSignOut} title="Sign out" aria-label="Sign out">
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {estop && (
        <div className="border-b border-red-400/40 bg-red-500/15 px-4 py-2 text-center text-sm text-red-200">
          Emergency stop engaged: all tasks were cancelled, approvals voided and the content queue paused (fire suppression). New work is blocked until reset; the queue stays paused until D.U.M.-E. resumes it with your approval.
        </div>
      )}
      {noModel && (
        <div className="border-b border-amber-300/30 bg-amber-300/10 px-4 py-2 text-center text-sm text-amber-100">
          No model is configured. Agents cannot reason until you add a free <code className="font-mono">OPENROUTER_API_KEY</code> (openrouter.ai/keys) to{" "}
          <code className="font-mono">.env</code> and restart the API. Tools still work from the Tools panel.
        </div>
      )}
      {error && <div className="border-b border-red-400/30 bg-red-400/10 px-4 py-1.5 text-center text-xs text-red-200">API error: {error}</div>}

      <div className="flex flex-1 flex-col md:flex-row">
        <nav className="flex gap-1 overflow-x-auto border-b border-[var(--color-line)] p-2 md:w-52 md:flex-col md:border-b-0 md:border-r md:p-3">
          {NAV.map((n) => {
            const Icon = n.icon;
            const badge = n.id === "approvals" ? approvals.length : 0;
            return (
              <button
                key={n.id}
                onClick={() => setView(n.id)}
                aria-current={view === n.id ? "page" : undefined}
                className={`nav-item flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                  view === n.id ? "bg-cyan-400/10 text-cyan-200 ring-1 ring-cyan-400/30" : "text-[var(--color-mute)] hover:bg-white/5 hover:text-[var(--color-ink)]"
                }`}
              >
                <Icon size={16} />
                <span>{n.label}</span>
                {badge > 0 && <span className="ml-auto rounded-full bg-amber-400 px-1.5 text-[11px] font-bold text-black">{badge}</span>}
              </button>
            );
          })}
        </nav>
        <main className="grid-bg relative min-w-0 flex-1 p-3 md:p-5">
          {fx === "max" && <BootOverlay label={NAV.find((n) => n.id === view)?.label || view} run={boot} />}
          <div key={`${view}-${boot}`} className="view-enter">
          {view === "command" && <CommandView agentId={focusAgent} setAgentId={setFocusAgent} openTask={openTask} prefill={prefill} />}
          {view === "home" && <HomeView talkTo={talkTo} go={setView} />}
          {view === "live" && <LiveView openTask={openTask} />}
          {view === "calendar" && <CalendarView />}
          {view === "analytics" && <AnalyticsView />}
          {view === "content" && <ContentView talkTo={talkTo} />}
          {view === "autopilot" && <AutopilotView />}
          {view === "team" && <TeamView talkTo={talkTo} openTask={openTask} />}
          {view === "tasks" && <TasksView focus={focusTask} setFocus={setFocusTask} />}
          {view === "approvals" && <ApprovalsView openTask={openTask} />}
          {view === "memory" && <MemoryView />}
          {view === "models" && <ModelsView />}
          {view === "tools" && <ToolsView />}
          {view === "diagnostics" && <DiagnosticsView />}
          {view === "usage" && <UsageView />}
          {view === "activity" && <ActivityView openTask={openTask} />}
          {view === "settings" && <SettingsView onSignOut={onSignOut} />}
          </div>
        </main>
      </div>

      <div className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`panel flex items-start gap-2 p-3 text-sm ${
              t.kind === "error" ? "!border-red-400/50" : t.kind === "warn" ? "!border-amber-300/50" : t.kind === "success" ? "!border-emerald-400/50" : ""
            }`}
          >
            <span className="break-anywhere min-w-0 flex-1">{t.text}</span>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-[var(--color-mute)] hover:text-white">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} actions={actions} onAsk={(t) => talkTo("jarvis", t)} />
    </div>
    </>
  );
}
