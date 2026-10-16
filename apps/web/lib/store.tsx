"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { StarkClient, type Connection } from "./api";
import type { Agent, Approval, StarkEvent, SystemStatus, Task } from "./types";

export interface Toast {
  id: number;
  kind: "info" | "success" | "warn" | "error";
  text: string;
}

interface StarkState {
  client: StarkClient;
  sseConnected: boolean;
  status: SystemStatus | null;
  agents: Agent[];
  approvals: Approval[];
  tasks: Task[];
  events: StarkEvent[];
  toasts: Toast[];
  error: string | null;
  listeningAgent: string | null;
  setListeningAgent: (id: string | null) => void;
  refresh: () => Promise<void>;
  notify: (kind: Toast["kind"], text: string) => void;
  dismiss: (id: number) => void;
  agentById: (id: string) => Agent | undefined;
}

const Ctx = createContext<StarkState | null>(null);

export function useStark(): StarkState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStark outside StarkProvider");
  return v;
}

export function StarkProvider({ conn, children, onAuthError }: { conn: Connection; children: React.ReactNode; onAuthError: () => void }) {
  const client = useMemo(() => new StarkClient(conn), [conn]);
  const [sseConnected, setSse] = useState(false);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<StarkEvent[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [listeningAgent, setListeningAgent] = useState<string | null>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const toastId = useRef(1);

  const notify = useCallback((kind: Toast["kind"], text: string) => {
    const id = toastId.current++;
    setToasts((t) => [...t.slice(-4), { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 9000 : 5000);
  }, []);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const guard = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      try {
        const v = await fn();
        setError(null);
        return v;
      } catch (e: any) {
        if (e?.status === 401) onAuthError();
        setError(e?.message || "Cannot reach the STARK OS API");
        return undefined;
      }
    },
    [onAuthError],
  );

  const loadStatus = useCallback(() => guard(() => client.get<SystemStatus>("/api/system/status")).then((s) => s && setStatus(s)), [client, guard]);
  const loadAgents = useCallback(() => guard(() => client.get<Agent[]>("/api/agents")).then((a) => a && setAgents(a)), [client, guard]);
  const loadApprovals = useCallback(() => guard(() => client.get<Approval[]>("/api/approvals?status=pending")).then((a) => a && setApprovals(a)), [client, guard]);
  const loadTasks = useCallback(() => guard(() => client.get<Task[]>("/api/tasks?limit=150")).then((t) => t && setTasks(t)), [client, guard]);

  const refresh = useCallback(async () => {
    await Promise.all([loadStatus(), loadAgents(), loadApprovals(), loadTasks()]);
  }, [loadStatus, loadAgents, loadApprovals, loadTasks]);

  const debounce = useCallback((key: string, fn: () => void, ms = 250) => {
    clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(fn, ms);
  }, []);

  useEffect(() => {
    refresh();
    const stop = client.events(
      (ev) => {
        setEvents((prev) => [...prev.slice(-299), ev]);
        switch (ev.type) {
          case "agent.status":
            setAgents((prev) => prev.map((a) => (a.id === ev.data.agent_id ? { ...a, live: { ...a.live, ...ev.data } as Agent["live"] } : a)));
            debounce("agents", loadAgents, 1500);
            break;
          case "task.created":
          case "task.updated":
            debounce("tasks", loadTasks);
            if (ev.type === "task.updated" && !ev.data.parent_id && ev.data.kind === "chat") {
              if (ev.data.status === "failed") notify("error", `${ev.data.agent_id.toUpperCase()} task failed: ${String(ev.data.error).slice(0, 140)}`);
            }
            break;
          case "approval.created":
            notify("warn", `Approval needed: ${ev.data.action}`.slice(0, 160));
            debounce("approvals", loadApprovals, 50);
            debounce("status", loadStatus);
            break;
          case "approval.decided":
            debounce("approvals", loadApprovals, 50);
            debounce("status", loadStatus);
            break;
          case "estop":
            notify(ev.data.engaged ? "error" : "info", ev.data.engaged ? "EMERGENCY STOP ENGAGED" : "Emergency stop reset");
            debounce("status", loadStatus, 50);
            break;
          case "mode":
            debounce("status", loadStatus, 50);
            break;
          case "usage":
            debounce("status", loadStatus, 2000);
            break;
        }
      },
      (ok) => setSse(ok),
    );
    const poll = setInterval(loadStatus, 20000);
    return () => {
      stop();
      clearInterval(poll);
    };
  }, [client, refresh, debounce, loadAgents, loadTasks, loadApprovals, loadStatus, notify]);

  const agentById = useCallback((id: string) => agents.find((a) => a.id === id), [agents]);

  const value: StarkState = {
    client, sseConnected, status, agents, approvals, tasks, events, toasts, error,
    listeningAgent, setListeningAgent, refresh, notify, dismiss, agentById,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
