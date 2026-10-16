"use client";

import { Mic, MicOff, Plus, Send, Square, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { detectWake, parseAddress } from "@/lib/addressing";
import { useStark } from "@/lib/store";
import type { Agent, Task, Turn } from "@/lib/types";
import { Markdown } from "./Markdown";
import { createRecognizer, speak, stopSpeaking, sttSupported, ttsSupported, type Recognizer } from "@/lib/voice";
import { ApprovalCard } from "./ApprovalCard";
import { AgentGlyph, StateBadge, STATE_META, TaskStatus } from "./ui";

const ACTIVE = new Set(["thinking", "executing", "waiting_approval", "collaborating", "listening"]);
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function readPref(key: string, fallback: boolean) {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}
function writePref(key: string, v: boolean) {
  try {
    window.localStorage.setItem(key, v ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function CoreOrb({ agent, state }: { agent?: Agent; state: string }) {
  const active = ACTIVE.has(state);
  const color = agent?.color || "#22d3ee";
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[260px]">
      <svg viewBox="0 0 200 200" className="absolute inset-0 h-full w-full">
        <defs>
          <radialGradient id="orb" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={color} stopOpacity={active ? 0.35 : 0.15} />
            <stop offset="70%" stopColor={color} stopOpacity="0.03" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="100" cy="100" r="96" fill="url(#orb)" />
        <g className={active ? "anim-spin" : ""} style={{ transformOrigin: "100px 100px" }}>
          <circle cx="100" cy="100" r="86" fill="none" stroke={color} strokeOpacity="0.35" strokeWidth="1" strokeDasharray="2 6" />
          {[0, 60, 120, 180, 240, 300].map((a) => (
            <rect key={a} x="99" y="10" width="2" height="9" fill={color} opacity="0.6" transform={`rotate(${a} 100 100)`} />
          ))}
        </g>
        <g className={active ? "anim-spin-fast" : ""} style={{ transformOrigin: "100px 100px", animationDirection: "reverse" }}>
          <circle cx="100" cy="100" r="68" fill="none" stroke={color} strokeOpacity="0.55" strokeWidth="1.5" strokeDasharray="70 30 10 30" />
        </g>
        <circle cx="100" cy="100" r="50" fill="none" stroke={color} strokeOpacity="0.25" strokeWidth="8" />
      </svg>
      <div className={`absolute inset-[30%] flex flex-col items-center justify-center rounded-full border ${active ? "anim-breathe" : ""}`} style={{ borderColor: `${color}66` }}>
        {agent && <AgentGlyph icon={agent.icon} color={color} size={40} active={active} />}
        <div className="mt-1 text-[11px] font-semibold tracking-[0.2em]" style={{ color }}>
          {agent?.name || "—"}
        </div>
      </div>
      <div className="absolute -bottom-1 left-1/2 -translate-x-1/2">
        <StateBadge state={state} />
      </div>
    </div>
  );
}

export function CommandView({ agentId, setAgentId, openTask, prefill = "" }: { agentId: string; setAgentId: (id: string) => void; openTask: (id: string) => void; prefill?: string }) {
  const { agents, client, notify, events, tasks, approvals, status, listeningAgent, setListeningAgent } = useStark();
  const agent = agents.find((a) => a.id === agentId);
  const [conversations, setConversations] = useState<Record<string, string | null>>({});
  const conversationId = conversations[agentId] ?? null;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState(prefill);
  const [partial, setPartial] = useState("");
  const [activeTask, setActiveTask] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const [wakeMode, setWakeMode] = useState(false);
  const [pttActive, setPttActive] = useState(false);
  const recRef = useRef<Recognizer | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const spokenFor = useRef<string | null>(null);

  useEffect(() => {
    setSpeakReplies(readPref("stark.speak", false));
  }, []);

  const loadTurns = useCallback(
    async (conv: string | null) => {
      if (!conv) return setTurns([]);
      try {
        setTurns(await client.get<Turn[]>(`/api/conversations/${conv}/turns`));
      } catch (e: any) {
        notify("error", e.message);
      }
    },
    [client, notify],
  );

  useEffect(() => {
    loadTurns(conversationId);
  }, [conversationId, loadTurns]);

  // the live task and its delegated sub-tasks (real backend state)
  const tree = useMemo(() => (activeTask ? tasks.filter((t) => t.root_id === activeTask) : []), [tasks, activeTask]);
  const rootTask: Task | undefined = tree.find((t) => t.id === activeTask);
  const treeIds = useMemo(() => new Set([activeTask, ...tree.map((t) => t.id)]), [tree, activeTask]);
  const trace = useMemo(
    () =>
      events.filter(
        (e) =>
          (["tool.call", "tool.result", "task.thought", "task.retry"].includes(e.type) && treeIds.has(e.data.task_id)) ||
          (e.type === "message" && e.data.root_id === activeTask) ||
          (e.type === "task.created" && e.data.root_id === activeTask && e.data.id !== activeTask),
      ),
    [events, treeIds, activeTask],
  );
  const taskApprovals = approvals.filter((a) => treeIds.has(a.task_id));

  // when the active task finishes: reload the conversation, optionally speak the reply
  useEffect(() => {
    if (!rootTask || !TERMINAL.has(rootTask.status)) return;
    if (rootTask.conversation_id === conversationId) loadTurns(rootTask.conversation_id);
    if (speakReplies && spokenFor.current !== rootTask.id && rootTask.status === "completed" && rootTask.result) {
      spokenFor.current = rootTask.id;
      const a = agents.find((x) => x.id === rootTask.agent_id);
      if (a) speak(rootTask.result, a.voice);
    }
  }, [rootTask?.status, rootTask?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, trace.length, taskApprovals.length]);

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      setSending(true);
      stopSpeaking();
      try {
        const { agent: addressed } = parseAddress(text);
        const target = addressed || agentId;
        const conv = addressed && addressed !== agentId ? conversations[addressed] ?? null : conversationId;
        const task = await client.post<Task>("/api/chat", { message: text, agent_id: target, conversation_id: conv });
        if (task.agent_id !== agentId) setAgentId(task.agent_id);
        setConversations((c) => ({ ...c, [task.agent_id]: task.conversation_id }));
        setActiveTask(task.id);
        setTurns((t) => (task.agent_id === agentId ? [...t, { id: -Date.now(), conversation_id: task.conversation_id!, role: "user", agent_id: task.agent_id, content: task.instruction, task_id: task.id, created_at: new Date().toISOString() }] : t));
        setInput("");
      } catch (e: any) {
        notify("error", e.message);
      } finally {
        setSending(false);
      }
    },
    [agentId, client, conversationId, conversations, notify, setAgentId],
  );

  // always call the latest send (with the current agent and conversation) from long-lived recognizers
  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  // ---------------- voice ----------------
  const startPtt = useCallback(() => {
    if (!sttSupported()) return notify("warn", "Speech recognition is not supported in this browser (try Chrome, Edge or Safari).");
    stopSpeaking();
    recRef.current?.stop();
    const rec = createRecognizer({
      lang: agent?.voice.lang?.startsWith("en") ? "en-US" : agent?.voice.lang,
      onPartial: setPartial,
      onFinal: (t) => {
        setPartial("");
        send(t);
      },
      onState: (on) => {
        setPttActive(on);
        setListeningAgent(on ? agentId : null);
      },
      onError: (m) => notify("error", m),
    });
    recRef.current = rec;
    rec?.start();
  }, [agent, agentId, notify, send, setListeningAgent]);

  const stopPtt = useCallback(() => recRef.current?.stop(), []);

  useEffect(() => {
    if (!wakeMode) return;
    if (!sttSupported()) {
      setWakeMode(false);
      notify("warn", "Wake-word mode needs browser speech recognition.");
      return;
    }
    const rec = createRecognizer({
      continuous: true,
      onPartial: (t) => detectWake(t) && setPartial(t),
      onFinal: (t) => {
        setPartial("");
        if (detectWake(t)) sendRef.current(t); // only utterances that start with an agent name are sent
      },
      onState: (on) => setListeningAgent(on ? "wake" : null),
      onError: (m) => notify("error", m),
    });
    rec?.start();
    return () => {
      rec?.stop();
      setListeningAgent(null);
    };
  }, [wakeMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const liveState = listeningAgent === agentId || (listeningAgent === "wake" && !ACTIVE.has(agent?.live.status || "idle")) ? "listening" : agent?.live.status || "idle";

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[340px_1fr]">
      <div className="flex flex-col gap-4">
        <div className="panel p-5">
          <CoreOrb agent={agent} state={liveState} />
          <p className="mt-6 text-center text-xs text-[var(--color-mute)]">{agent?.role}</p>
          {agent && (
            <p className="mt-1 text-center font-mono text-[11px] text-[var(--color-mute)]">
              {agent.model_in_use.model ? `${agent.model_in_use.provider} · ${agent.model_in_use.model}` : "no model available"}
            </p>
          )}
        </div>
        <div className="panel p-3">
          <div className="panel-title mb-2 px-1">Agents</div>
          <div className="grid grid-cols-2 gap-1.5">
            {agents.map((a) => {
              const st = a.live.status;
              return (
                <button
                  key={a.id}
                  onClick={() => setAgentId(a.id)}
                  className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-left text-xs transition ${a.id === agentId ? "bg-white/5" : "border-transparent hover:bg-white/5"}`}
                  style={{ borderColor: a.id === agentId ? `${a.color}88` : undefined }}
                >
                  <AgentGlyph icon={a.icon} color={a.color} size={18} />
                  <span className="flex-1 truncate font-medium">{a.name}</span>
                  <span className={`h-1.5 w-1.5 rounded-full ${STATE_META[st]?.animated ? "anim-pulse" : ""}`} style={{ background: STATE_META[st]?.color }} title={st} />
                </button>
              );
            })}
          </div>
        </div>
        <div className="panel p-3">
          <div className="panel-title mb-2 px-1">Voice</div>
          <div className="flex flex-wrap gap-2">
            <button
              className={`btn ${pttActive ? "btn-primary" : ""}`}
              onMouseDown={startPtt}
              onMouseUp={stopPtt}
              onMouseLeave={() => pttActive && stopPtt()}
              onTouchStart={startPtt}
              onTouchEnd={stopPtt}
              onKeyDown={(e) => {
                if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                  e.preventDefault();
                  startPtt();
                }
              }}
              onKeyUp={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  stopPtt();
                }
              }}
              onBlur={() => pttActive && stopPtt()}
              disabled={!sttSupported()}
              title="Hold to talk (mouse, touch, or hold Space/Enter)"
              aria-pressed={pttActive}
            >
              <Mic size={14} /> {pttActive ? "Listening…" : "Hold to talk"}
            </button>
            <button className={`btn ${wakeMode ? "btn-primary" : ""}`} onClick={() => setWakeMode(!wakeMode)} disabled={!sttSupported()} title='Always listen for "Hey JARVIS", "Friday, …"' aria-pressed={wakeMode}>
              {wakeMode ? <Mic size={14} /> : <MicOff size={14} />} Wake word
            </button>
            <button
              className={`btn ${speakReplies ? "btn-primary" : ""}`}
              disabled={!ttsSupported()}
              aria-pressed={speakReplies}
              onClick={() => {
                writePref("stark.speak", !speakReplies);
                setSpeakReplies(!speakReplies);
              }}
            >
              {speakReplies ? <Volume2 size={14} /> : <VolumeX size={14} />} Speak replies
            </button>
            <button className="btn" onClick={stopSpeaking} title="Interrupt speech">
              <Square size={12} /> Stop
            </button>
          </div>
          {!sttSupported() && <p className="mt-2 text-xs text-[var(--color-mute)]">Speech input needs Chrome, Edge or Safari. Text works everywhere.</p>}
          {partial && <p className="mt-2 rounded-md bg-cyan-400/10 p-2 text-xs text-cyan-100">“{partial}”</p>}
        </div>
      </div>

      <div className="panel flex min-h-[70vh] flex-col">
        <div className="flex items-center gap-3 border-b border-[var(--color-line)] px-4 py-3">
          {agent && <AgentGlyph icon={agent.icon} color={agent.color} size={22} />}
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{agent?.name}</div>
            <div className="truncate text-xs text-[var(--color-mute)]">{agent?.communication_style}</div>
          </div>
          {rootTask && <TaskStatus status={rootTask.status} />}
          <button
            className="btn"
            onClick={() => {
              setConversations((c) => ({ ...c, [agentId]: null }));
              setActiveTask(null);
            }}
          >
            <Plus size={14} /> New
          </button>
        </div>

        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
          {turns.length === 0 && !activeTask && (
            <div className="mx-auto max-w-md py-12 text-center text-sm text-[var(--color-mute)]">
              <p className="mb-3">Address any agent by name, or pick one on the left.</p>
              <div className="flex flex-wrap justify-center gap-2">
                {["JARVIS, plan a one-week launch campaign for Bluesky and LinkedIn", "EDITH, draft a launch post for Bluesky with a poll idea", "Friday, check our mentions and draft replies", "Jocasta, what is trending in our niche this week? Cite sources", "U, turn our launch post into a 30-second vertical video storyboard", "Ultron, how could our launch post backfire?", "DUM-E, show me the content queue", "JARVIS, remember our brand voice is warm, plain-spoken, no slang"].map((s) => (
                  <button key={s} className="chip hover:text-white" onClick={() => setInput(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t) => {
            const a = agents.find((x) => x.id === t.agent_id);
            return t.role === "user" ? (
              <div key={t.id} className="break-anywhere ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-cyan-400/10 px-4 py-2.5 text-sm ring-1 ring-cyan-400/20">
                {t.content}
              </div>
            ) : (
              <div key={t.id} className="max-w-[92%]">
                <div className="hud-label mb-1 flex items-center gap-2" style={{ color: a?.color }}>
                  {a && <AgentGlyph icon={a.icon} color={a.color} size={14} />} {a?.name}
                  {t.task_id && (
                    <button className="text-[var(--color-mute)] underline-offset-2 hover:underline" onClick={() => openTask(t.task_id!)}>
                      trace
                    </button>
                  )}
                  {a && ttsSupported() && (
                    <button className="text-[var(--color-mute)] hover:text-white" onClick={() => speak(t.content, a.voice)} title="Read aloud" aria-label={`Read ${a.name}'s reply aloud`}>
                      <Volume2 size={12} />
                    </button>
                  )}
                </div>
                <div className={`rounded-2xl rounded-tl-sm px-4 py-2.5 ${t.content.startsWith("[task failed]") ? "bg-red-400/10 text-red-100 ring-1 ring-red-400/30" : "bg-white/[0.03] ring-1 ring-white/5"}`}>
                  <Markdown text={t.content} />
                </div>
              </div>
            );
          })}

          {rootTask && !TERMINAL.has(rootTask.status) && (
            <div className="rounded-xl border border-dashed border-[var(--color-line-strong)] p-3">
              <div className="hud-label mb-2 flex items-center gap-2 text-[var(--color-mute)]">
                Live trace · {rootTask.id}
                <button className="ml-auto text-red-300 hover:underline" onClick={() => client.post(`/api/tasks/${rootTask.id}/cancel`).catch((e) => notify("error", e.message))}>
                  cancel
                </button>
              </div>
              <ol className="space-y-1.5 font-mono text-[11.5px]">
                {trace.length === 0 && <li className="text-[var(--color-mute)]">waiting for the model…</li>}
                {trace.map((e, i) => {
                  const who = agents.find((a) => a.id === (e.data.agent_id || e.data.sender));
                  const tag = (
                    <span style={{ color: who?.color }} className="mr-1.5">
                      {who?.name || e.data.agent_id || e.data.sender}
                    </span>
                  );
                  if (e.type === "tool.call")
                    return (
                      <li key={i}>
                        {tag}→ {e.data.tool} <span className="text-[var(--color-mute)]">[{e.data.verdict}]</span>
                      </li>
                    );
                  if (e.type === "tool.result")
                    return (
                      <li key={i} className={e.data.ok ? "text-emerald-300/80" : "text-red-300/80"}>
                        {tag}← {e.data.summary} {e.data.simulated && <span className="chip !text-amber-300">SIMULATED</span>}
                      </li>
                    );
                  if (e.type === "task.thought")
                    return (
                      <li key={i} className="text-[var(--color-ink)]/80">
                        {tag}
                        {String(e.data.text).slice(0, 220)}
                      </li>
                    );
                  if (e.type === "message")
                    return (
                      <li key={i} className="text-fuchsia-300/80">
                        ✉ {e.data.sender} → {e.data.recipient}: {e.data.type}
                      </li>
                    );
                  if (e.type === "task.retry")
                    return (
                      <li key={i} className="text-amber-300/80">
                        retry #{e.data.attempt}: {e.data.error}
                      </li>
                    );
                  return null;
                })}
              </ol>
            </div>
          )}
          {taskApprovals.map((a) => (
            <ApprovalCard key={a.id} approval={a} />
          ))}
        </div>

        <form
          className="flex gap-2 border-t border-[var(--color-line)] p-3"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            className="input min-w-0"
            placeholder={status?.emergency_stop ? "Emergency stop engaged" : `Message ${agent?.name || "an agent"}…  (e.g. "Friday, check our mentions")`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={status?.emergency_stop}
            aria-label="Message"
          />
          <button className="btn btn-primary" disabled={sending || !input.trim() || status?.emergency_stop}>
            <Send size={14} /> Send
          </button>
        </form>
      </div>
    </div>
  );
}
