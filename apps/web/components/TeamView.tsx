"use client";

import { MessageSquare, Volume2, X } from "lucide-react";
import { useState } from "react";
import { useStark } from "@/lib/store";
import type { Agent } from "@/lib/types";
import { speak, ttsSupported } from "@/lib/voice";
import { AgentGlyph, AvailabilityChip, RiskChip, StateBadge, timeAgo } from "./ui";

function AgentCard({ agent, onOpen, talkTo, openTask }: { agent: Agent; onOpen: () => void; talkTo: (id: string) => void; openTask: (id: string) => void }) {
  const { events, listeningAgent } = useStark();
  const recent = [...events].reverse().find((e) => (e.data.agent_id === agent.id || e.data.sender === agent.id) && ["tool.result", "tool.call", "message", "task.thought"].includes(e.type));
  const state = listeningAgent === agent.id ? "listening" : agent.live.status;
  const m = agent.metrics;
  const done = m.tasks.completed || 0;
  const failed = m.tasks.failed || 0;
  return (
    <div className="panel relative overflow-hidden p-4" style={{ borderColor: `${agent.color}33` }}>
      <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-20 blur-2xl" style={{ background: agent.color }} />
      <div className="flex items-start gap-3">
        <div className="rounded-xl border p-2" style={{ borderColor: `${agent.color}55` }}>
          <AgentGlyph icon={agent.icon} color={agent.color} size={30} active={state !== "idle"} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold tracking-wide" style={{ color: agent.color }}>
              {agent.name}
            </h3>
          </div>
          <p className="truncate text-xs text-[var(--color-mute)]">{agent.role}</p>
        </div>
        <StateBadge state={state} />
      </div>
      <div className="mt-3 space-y-1.5 text-xs">
        <Row label="Task">
          {agent.live.task_id ? (
            <button className="truncate text-left hover:underline" onClick={() => openTask(agent.live.task_id!)}>
              {agent.live.detail || agent.live.task_id}
            </button>
          ) : (
            <span className="text-[var(--color-mute)]">none</span>
          )}
        </Row>
        <Row label="Brain">
          <span className="font-mono">{agent.model.preferred?.[0] || `${agent.model.tier} tier`}</span>
          {!agent.model_in_use.model ? (
            <span className="ml-1 text-amber-300">(no key configured)</span>
          ) : agent.model_in_use.model !== agent.model.preferred?.[0] ? (
            <span className="ml-1 text-[var(--color-mute)]">· now using {agent.model_in_use.model}</span>
          ) : null}
        </Row>
        <Row label="Voice">
          <span>
            {agent.voice.muted ? "muted (text only)" : `${agent.voice.lang} · pitch ${agent.voice.pitch} · rate ${agent.voice.rate}`}
          </span>
        </Row>
        <Row label="Mode cap">
          <span className="uppercase">{agent.permission_level.replace("_", " ")}</span>
        </Row>
        <Row label="Tools">
          <span className="flex flex-wrap gap-1">
            {agent.tools.map((t) => (
              <span key={t} className="chip !px-1.5 !py-0 !text-[10px]">
                {t}
              </span>
            ))}
          </span>
        </Row>
        <Row label="Metrics">
          <span>
            {done} done · {failed} failed · {m.tokens.toLocaleString()} tok · ${m.cost_usd.toFixed(3)}
            {m.avg_seconds ? ` · avg ${m.avg_seconds}s` : ""}
          </span>
        </Row>
        <Row label="Recent">
          <span className="truncate text-[var(--color-mute)]">{recent ? `${recent.type}: ${recent.data.tool || recent.data.type || ""} ${recent.data.summary || ""}`.slice(0, 90) + ` · ${timeAgo(recent.ts)}` : "—"}</span>
        </Row>
      </div>
      <div className="mt-4 flex gap-2">
        <button className="btn" onClick={() => talkTo(agent.id)}>
          <MessageSquare size={14} /> Talk
        </button>
        <button className="btn" onClick={onOpen}>
          Details
        </button>
        {ttsSupported() && (
          <button className="btn ml-auto" title={agent.voice.muted ? "Muted: this agent never speaks" : "Preview voice"} disabled={agent.voice.muted} onClick={() => speak(`${agent.name} online. ${agent.role}.`, agent.voice)}>
            <Volume2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="hud-label w-16 shrink-0 pt-0.5 text-[var(--color-mute)]">{label}</span>
      <div className="flex min-w-0 flex-1 items-center">{children}</div>
    </div>
  );
}

function AgentDetail({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/60" onClick={onClose}>
      <aside className="panel h-full w-full max-w-2xl overflow-y-auto !rounded-none p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center gap-3">
          <AgentGlyph icon={agent.icon} color={agent.color} size={34} />
          <div className="flex-1">
            <h2 className="text-lg font-semibold" style={{ color: agent.color }}>
              {agent.name}
            </h2>
            <p className="text-xs text-[var(--color-mute)]">{agent.full_name}</p>
          </div>
          <button className="btn" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>
        <Block title="Personality">{agent.personality.join(" · ")}</Block>
        <Block title="Communication style">{agent.communication_style}</Block>
        <Block title="Responsibilities">
          <ul className="list-disc pl-5">{agent.responsibilities.map((r) => <li key={r}>{r}</li>)}</ul>
        </Block>
        <Block title="Boundaries (enforced)">
          <ul className="list-disc pl-5 text-amber-100/90">{agent.boundaries.map((r) => <li key={r}>{r}</li>)}</ul>
        </Block>
        <Block title="Reasoning workflow">
          <span className="chip">{agent.workflow}</span>
        </Block>
        <Block title="Brain (own first-choice free models)">
          <ol className="mb-2 list-decimal pl-5 font-mono text-xs">
            {(agent.model.preferred || []).map((m) => <li key={m}>{m}</li>)}
          </ol>
          <div className="font-mono text-xs">
            then the shared {agent.model.tier} tier list with failover · tier={agent.model.tier} · temp={agent.model.temperature} · max_out={agent.model.max_output_tokens}
            <br />
            in use: {agent.model_in_use.provider || "—"} / {agent.model_in_use.model || "—"} ({agent.model_in_use.reason})
          </div>
        </Block>
        <Block title="Limits">
          <div className="font-mono text-xs">
            steps={agent.limits.max_steps} · timeout={agent.limits.timeout_s}s · retries={agent.limits.max_retries} · tokens/task={agent.limits.max_tokens_per_task} · cost/task=${agent.limits.cost_limit_usd_per_task}
          </div>
        </Block>
        <Block title="Tools & permissions">
          <div className="space-y-1.5">
            {agent.tool_details.map((t) => (
              <div key={t.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono">{t.id}</span>
                <RiskChip risk={t.risk} />
                <AvailabilityChip value={t.availability} />
              </div>
            ))}
          </div>
        </Block>
        <Block title="Memory access">
          <div className="text-xs">
            read: {agent.memory.read_namespaces.join(", ")}
            <br />
            write: {agent.memory.write_namespaces.join(", ")}
          </div>
        </Block>
        <Block title="Collaboration">
          <div className="text-xs">
            can delegate to: {agent.delegation.can_delegate_to.join(", ") || "nobody"}
            <br />
            review focus: {agent.delegation.review_focus}
          </div>
        </Block>
        <Block title="Voice profile">{agent.voice.description}</Block>
        <Block title="Canon notes (labelled)">
          <ul className="list-disc pl-5 text-xs">{agent.canon_notes.map((r) => <li key={r}>{r}</li>)}</ul>
        </Block>
        <Block title="System prompt">
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-3 font-mono text-[11px]">{agent.system_prompt}</pre>
        </Block>
      </aside>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="panel-title mb-1">{title}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

export function TeamView({ talkTo, openTask }: { talkTo: (id: string) => void; openTask: (id: string) => void }) {
  const { agents } = useStark();
  const [open, setOpen] = useState<string | null>(null);
  const openAgent = agents.find((a) => a.id === open);
  return (
    <>
      <div className="grid gap-4 [&>*]:min-w-0 md:grid-cols-2 2xl:grid-cols-3">
        {agents.map((a) => (
          <AgentCard key={a.id} agent={a} onOpen={() => setOpen(a.id)} talkTo={talkTo} openTask={openTask} />
        ))}
      </div>
      {openAgent && <AgentDetail agent={openAgent} onClose={() => setOpen(null)} />}
    </>
  );
}
