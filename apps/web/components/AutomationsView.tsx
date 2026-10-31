"use client";

import { Bolt, CalendarClock, CheckCircle2, Copy, FlaskConical, History, Pencil, Play, Plus, Puzzle, Trash2, Webhook, XCircle, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Empty, timeAgo } from "./ui";

type Trigger = { type: "event" | "schedule" | "webhook"; event?: string; every?: "day" | "week"; weekday?: number; time?: string };
type Cond = { field: string; op: string; value: string };
type Action = { type: string; agent?: string; message?: string; platform?: string; text?: string; label?: string; url?: string; category?: string };
type Automation = { id: string; name: string; enabled: boolean; trigger: Trigger; conditions: Cond[]; actions: Action[]; recipe: string; runs: number; last_run_at: string | null; hook_path: string | null };
type Recipe = { recipe: string; name: string; description: string; trigger: Trigger; conditions: Cond[]; actions: Action[] };
type Run = { id: string; automation_id: string; at: string; event: string; ok: boolean; steps: (Action & { result?: string; error?: string })[] };
type Meta = { events: string[]; ops: string[]; actions: string[]; agents: string[]; platforms: string[] };

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const OP_LABEL: Record<string, string> = {
  equals: "is", not_equals: "is not", contains: "contains any of", not_contains: "contains none of", matches: "matches pattern",
  greater_than: "is more than", less_than: "is less than", is_empty: "is empty", not_empty: "is not empty",
};
const ACTION_LABEL: Record<string, string> = {
  ask_agent: "Ask an agent", create_draft: "Create a draft", label_mention: "Label the mention", add_utm: "Add UTM tags to the post",
  notify: "Message my phone", webhook: "Send to a webhook (another app)",
};
const EVENT_LABEL: Record<string, string> = {
  "post.drafted": "A draft is created", "post.scheduled": "A post is scheduled", "post.published": "A post is published",
  "post.failed": "A post fails", "mention.found": "Listening finds a mention", "approval.needed": "An agent needs approval",
  "autopilot.alert": "Autopilot raises an alert",
};
const FIELDS = ["data.platform", "data.text", "data.category", "data.author", "data.likes", "data.kind", "data.campaign", "data.watch", "data.agent_id"];

const blank = (): Omit<Automation, "id" | "runs" | "last_run_at" | "hook_path"> => ({
  name: "", enabled: true, recipe: "", trigger: { type: "event", event: "post.published" }, conditions: [], actions: [{ type: "notify", text: "{{event}}: {{data.text}}" }],
});

function describe(t: Trigger) {
  if (t.type === "event") return EVENT_LABEL[t.event || ""] || t.event;
  if (t.type === "schedule") return t.every === "week" ? `Every ${DAYS[t.weekday ?? 0]} at ${t.time}` : `Every day at ${t.time}`;
  return "Another app calls its webhook address";
}

function TriggerIcon({ t }: { t: Trigger }) {
  const I = t.type === "schedule" ? CalendarClock : t.type === "webhook" ? Webhook : Bolt;
  return <I size={14} className="text-cyan-300" />;
}

/** Automations: "when this happens, do that" recipes, built in and approval-safe. */
export function AutomationsView() {
  const { client, notify } = useStark();
  const [tab, setTab] = useState<"mine" | "gallery" | "history" | "connect">("mine");
  const [list, setList] = useState<Automation[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [edit, setEdit] = useState<(ReturnType<typeof blank> & { id?: string }) | null>(null);
  const [testing, setTesting] = useState<{ id: string; sample: string; out?: any } | null>(null);

  const load = useCallback(() => {
    client.get<Meta & { automations: Automation[] }>("/api/automations").then((r) => { setList(r.automations); setMeta(r); }).catch(() => {});
    client.get<{ recipes: Recipe[] }>("/api/automations/recipes").then((r) => setRecipes(r.recipes)).catch(() => {});
    client.get<{ runs: Run[] }>("/api/automations/runs?limit=60").then((r) => setRuns(r.runs)).catch(() => {});
  }, [client]);
  useEffect(load, [load]);

  const body = (a: ReturnType<typeof blank>) => ({ name: a.name, enabled: a.enabled, recipe: a.recipe, trigger: a.trigger, conditions: a.conditions, actions: a.actions });

  async function save() {
    if (!edit) return;
    try {
      if (edit.id) await client.put(`/api/automations/${edit.id}`, body(edit));
      else await client.post("/api/automations", body(edit));
      notify("success", `Saved “${edit.name}”`);
      setEdit(null);
      load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function toggle(a: Automation) {
    try {
      await client.put(`/api/automations/${a.id}`, { ...body(a), enabled: !a.enabled });
      load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function addRecipe(r: Recipe) {
    try {
      await client.post("/api/automations/from-recipe", { recipe: r.recipe });
      notify("success", `“${r.name}” added, switched off. Check it, then switch it on.`);
      setTab("mine");
      load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function runTest(run: boolean) {
    if (!testing) return;
    let data: any = {};
    try {
      data = testing.sample.trim() ? JSON.parse(testing.sample) : {};
    } catch {
      notify("error", "Sample data must be JSON, e.g. {\"text\": \"Hello\"}");
      return;
    }
    try {
      const out = await client.post(`/api/automations/${testing.id}/test`, { data, run });
      setTesting({ ...testing, out });
      if (run) load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  const hookUrl = (p: string) => `${client.url}${p}`;
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => notify("success", "Copied"), () => {});
  const names = Object.fromEntries(list.map((a) => [a.id, a.name]));
  const TABS = [
    { id: "mine", label: "My automations", icon: Zap, n: list.length },
    { id: "gallery", label: "Recipe gallery", icon: Puzzle, n: recipes.length },
    { id: "history", label: "Run history", icon: History, n: runs.length },
    { id: "connect", label: "Connect other apps", icon: Webhook, n: null },
  ] as const;

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel p-4">
        <div className="hud-label text-cyan-300">Workflow engine</div>
        <h1 className="holo-text text-xl font-semibold">Automations</h1>
        <p className="max-w-3xl text-xs text-[var(--color-mute)]">
          “When this happens, do that.” Pick a trigger (an event, a schedule or another app), add conditions, and chain actions. Automations can draft, label,
          tag and notify, but never publish: every post still waits for your approval.
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs">
          <span className="rounded-full border border-cyan-400/25 bg-cyan-400/5 px-2.5 py-0.5 text-cyan-200">{list.filter((a) => a.enabled).length} on</span>
          <span className="rounded-full border border-cyan-400/25 bg-cyan-400/5 px-2.5 py-0.5 text-cyan-200">{runs.filter((r) => Date.now() - new Date(r.at).getTime() < 86400000).length} runs today</span>
          <span className="rounded-full border border-cyan-400/25 bg-cyan-400/5 px-2.5 py-0.5 text-cyan-200">{runs.filter((r) => !r.ok).length} with errors</span>
        </div>
      </section>

      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => { setTab(t.id); load(); }} className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs ${tab === t.id ? "bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-400/30" : "text-[var(--color-mute)] hover:bg-white/5"}`}>
            <t.icon size={13} /> {t.label} {t.n !== null && <span className="opacity-60">{t.n}</span>}
          </button>
        ))}
      </div>

      {tab === "mine" && (
        <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_1.1fr]">
          <section className="panel p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="hud-label">Your automations</div>
              <button className="btn btn-primary" onClick={() => { setEdit(blank()); setTesting(null); }}>
                <Plus size={14} /> New automation
              </button>
            </div>
            {list.length === 0 ? (
              <Empty>No automations yet. Start from the recipe gallery or build your own.</Empty>
            ) : (
              <ul className="space-y-2">
                {list.map((a) => (
                  <li key={a.id} className={`rounded-lg border p-3 text-sm transition ${a.enabled ? "border-cyan-400/30 bg-cyan-400/[0.04]" : "border-[var(--color-line)] opacity-80"}`}>
                    <div className="flex items-start gap-2">
                      <TriggerIcon t={a.trigger} />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">{a.name}</div>
                        <div className="text-xs text-[var(--color-mute)]">
                          {describe(a.trigger)}
                          {a.conditions.length > 0 && ` · ${a.conditions.length} condition${a.conditions.length > 1 ? "s" : ""}`} → {a.actions.map((x) => ACTION_LABEL[x.type] || x.type).join(", ")}
                        </div>
                        <div className="mt-1 text-[11px] text-[var(--color-mute)]">{a.runs} run{a.runs === 1 ? "" : "s"}{a.last_run_at && ` · last ${timeAgo(a.last_run_at)}`}</div>
                      </div>
                      <label className="flex cursor-pointer items-center gap-1 text-xs">
                        <input type="checkbox" role="switch" checked={a.enabled} onChange={() => toggle(a)} aria-label={`Switch ${a.name} ${a.enabled ? "off" : "on"}`} />
                        {a.enabled ? "On" : "Off"}
                      </label>
                    </div>
                    {a.hook_path && (
                      <div className="mt-2 flex items-center gap-2 rounded-md bg-black/20 p-1.5 font-mono text-[11px]">
                        <span className="break-anywhere min-w-0 flex-1">{hookUrl(a.hook_path)}</span>
                        <button onClick={() => copy(hookUrl(a.hook_path!))} aria-label={`Copy webhook address of ${a.name}`} className="text-[var(--color-mute)] hover:text-cyan-300">
                          <Copy size={12} />
                        </button>
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button className="btn" onClick={() => { setEdit({ ...a }); setTesting(null); }}><Pencil size={12} /> Edit</button>
                      <button className="btn" onClick={() => { setTesting({ id: a.id, sample: sampleFor(a) }); setEdit(null); }}><FlaskConical size={12} /> Test</button>
                      <button className="btn" onClick={() => client.del(`/api/automations/${a.id}`).then(() => { setTesting(null); setEdit(null); load(); })} aria-label={`Delete ${a.name}`}><Trash2 size={12} /> Delete</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {edit && meta && <Builder value={edit} meta={meta} onChange={setEdit} onSave={save} onCancel={() => setEdit(null)} />}
          {testing && (
            <section className="panel p-4">
              <div className="hud-label mb-2">Test run · {names[testing.id]}</div>
              <p className="mb-2 text-xs text-[var(--color-mute)]">Sample event data (JSON). A dry run shows what would happen; “Run for real” performs the actions.</p>
              <textarea className="input h-28 w-full font-mono text-xs" aria-label="Sample data" value={testing.sample} onChange={(e) => setTesting({ ...testing, sample: e.target.value })} />
              <div className="mt-2 flex gap-2">
                <button className="btn btn-primary" onClick={() => runTest(false)}><FlaskConical size={13} /> Dry run</button>
                <button className="btn" onClick={() => runTest(true)}><Play size={13} /> Run for real</button>
              </div>
              {testing.out && (
                <div className="mt-3 space-y-2 text-xs">
                  <div className={testing.out.would_run ? "text-emerald-300" : "text-amber-300"}>
                    {testing.out.would_run ? "All conditions match: these steps run." : `Would not run: ${testing.out.failed_conditions.map((c: Cond) => `${c.field} ${OP_LABEL[c.op]} ${c.value}`).join("; ")}`}
                  </div>
                  <ol className="space-y-1.5">
                    {(testing.out.result?.steps || testing.out.steps).map((s: any, i: number) => (
                      <li key={i} className="rounded-md border border-[var(--color-line)] p-2">
                        <b>{i + 1}. {ACTION_LABEL[s.type]}</b>
                        {(s.message || s.text) && <div className="break-anywhere mt-1 whitespace-pre-wrap text-[var(--color-mute)]">{s.message || s.text}</div>}
                        {s.result && <div className="mt-1 text-emerald-300">✓ {s.result}</div>}
                        {s.error && <div className="mt-1 text-red-300">✗ {s.error}</div>}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </section>
          )}
          {!edit && !testing && (
            <section className="panel p-4 text-xs text-[var(--color-mute)]">
              <div className="hud-label mb-2 text-cyan-300">How it works</div>
              <ol className="list-decimal space-y-1.5 pl-4">
                <li><b>Trigger:</b> an event in STARK OS, a daily/weekly schedule, or a webhook another app calls.</li>
                <li><b>Conditions:</b> all must match. Use fields like <code>data.platform</code>, <code>data.category</code>, <code>data.likes</code>.</li>
                <li><b>Actions:</b> run in order. Use <code>{"{{data.text}}"}</code> to insert event fields into messages.</li>
                <li><b>Safety:</b> at most 20 runs per automation per hour, and what an automation creates never triggers automations again.</li>
              </ol>
            </section>
          )}
        </div>
      )}

      {tab === "gallery" && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {recipes.map((r) => (
            <section key={r.recipe} className="panel flex flex-col p-4">
              <div className="mb-1 flex items-center gap-2 text-sm font-medium"><TriggerIcon t={r.trigger} /> {r.name}</div>
              <p className="flex-1 text-xs text-[var(--color-mute)]">{r.description}</p>
              <div className="mt-2 text-[11px] text-[var(--color-mute)]">{describe(r.trigger)} → {r.actions.map((x) => ACTION_LABEL[x.type]).join(", ")}</div>
              <button className="btn btn-primary mt-3 justify-center" onClick={() => addRecipe(r)} aria-label={`Use recipe ${r.name}`}>
                <Plus size={13} /> Use recipe
              </button>
            </section>
          ))}
        </div>
      )}

      {tab === "history" && (
        <section className="panel p-4">
          {runs.length === 0 ? (
            <Empty>No runs yet.</Empty>
          ) : (
            <ul className="space-y-2">
              {runs.map((r) => (
                <li key={r.id} className="rounded-lg border border-[var(--color-line)] p-2.5 text-xs">
                  <div className="flex items-center gap-2">
                    {r.ok ? <CheckCircle2 size={14} className="text-emerald-300" /> : <XCircle size={14} className="text-red-300" />}
                    <b className="text-sm">{names[r.automation_id] || r.automation_id}</b>
                    <span className="text-[var(--color-mute)]">{r.event} · {timeAgo(r.at)}</span>
                  </div>
                  <ul className="mt-1 space-y-0.5 pl-6 text-[var(--color-mute)]">
                    {r.steps.map((s, i) => (
                      <li key={i} className="break-anywhere">{ACTION_LABEL[s.type] || s.type}: {s.error ? <span className="text-red-300">{s.error}</span> : s.result}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === "connect" && <ConnectApps />}
    </div>
  );
}

function sampleFor(a: Automation) {
  if (a.trigger.type === "webhook") return JSON.stringify({ platform: "bluesky", text: "Hello from Make" }, null, 2);
  if (a.trigger.event === "mention.found") return JSON.stringify({ platform: "bluesky", author: "@someone.example", text: "Love this tool!", category: "praise", likes: 12, kind: "keyword" }, null, 2);
  return JSON.stringify({ platform: "bluesky", text: "We just shipped Automations https://example.com/blog", campaign: "launch" }, null, 2);
}

function Builder({ value, meta, onChange, onSave, onCancel }: { value: ReturnType<typeof blank> & { id?: string }; meta: Meta; onChange: (v: any) => void; onSave: () => void; onCancel: () => void }) {
  const set = (patch: Partial<typeof value>) => onChange({ ...value, ...patch });
  const t = value.trigger;
  const setT = (patch: Partial<Trigger>) => set({ trigger: { ...t, ...patch } });
  const setCond = (i: number, patch: Partial<Cond>) => set({ conditions: value.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const setAct = (i: number, patch: Partial<Action>) => set({ actions: value.actions.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const newAction = (type: string): Action =>
    type === "ask_agent" ? { type, agent: "jarvis", message: "" } : type === "create_draft" ? { type, platform: "bluesky", text: "{{data.text}}" }
      : type === "label_mention" ? { type, label: "Urgent" } : type === "webhook" ? { type, url: "https://" }
        : type === "notify" ? { type, text: "{{event}}: {{data.text}}" } : { type };

  return (
    <section className="panel p-4">
      <div className="hud-label mb-3">{value.id ? "Edit automation" : "New automation"}</div>
      <form onSubmit={(e) => { e.preventDefault(); onSave(); }} className="space-y-4 text-sm">
        <input className="input w-full" aria-label="Automation name" placeholder="Name, e.g. Thank people who praise us" value={value.name} onChange={(e) => set({ name: e.target.value })} />

        <fieldset className="space-y-2 rounded-lg border border-[var(--color-line)] p-3">
          <legend className="px-1 text-xs text-cyan-300">1 · When</legend>
          <select className="input w-full" aria-label="Trigger type" value={t.type} onChange={(e) => {
            const type = e.target.value as Trigger["type"];
            set({ trigger: type === "event" ? { type, event: "post.published" } : type === "schedule" ? { type, every: "day", time: "09:00", weekday: 0 } : { type } });
          }}>
            <option value="event">Something happens in STARK OS</option>
            <option value="schedule">On a schedule</option>
            <option value="webhook">Another app calls a webhook</option>
          </select>
          {t.type === "event" && (
            <select className="input w-full" aria-label="Event" value={t.event} onChange={(e) => setT({ event: e.target.value })}>
              {meta.events.map((ev) => <option key={ev} value={ev}>{EVENT_LABEL[ev] || ev}</option>)}
            </select>
          )}
          {t.type === "schedule" && (
            <div className="flex flex-wrap gap-2">
              <select className="input" aria-label="Repeat" value={t.every} onChange={(e) => setT({ every: e.target.value as "day" | "week" })}>
                <option value="day">Every day</option>
                <option value="week">Every week</option>
              </select>
              {t.every === "week" && (
                <select className="input" aria-label="Weekday" value={t.weekday ?? 0} onChange={(e) => setT({ weekday: Number(e.target.value) })}>
                  {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                </select>
              )}
              <input type="time" className="input" aria-label="Time" value={t.time} onChange={(e) => setT({ time: e.target.value })} />
            </div>
          )}
          {t.type === "webhook" && <p className="text-xs text-[var(--color-mute)]">After saving, a secret address appears on the automation. Paste it into your automation app; the JSON they send is available as <code>{"{{data.…}}"}</code>.</p>}
        </fieldset>

        <fieldset className="space-y-2 rounded-lg border border-[var(--color-line)] p-3">
          <legend className="px-1 text-xs text-cyan-300">2 · Only if (all match)</legend>
          {value.conditions.map((c, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
              <input className="input" list="automation-fields" aria-label={`Condition ${i + 1} field`} value={c.field} onChange={(e) => setCond(i, { field: e.target.value })} />
              <select className="input" aria-label={`Condition ${i + 1} comparison`} value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}>
                {meta.ops.map((o) => <option key={o} value={o}>{OP_LABEL[o] || o}</option>)}
              </select>
              <input className="input" aria-label={`Condition ${i + 1} value`} value={c.value} disabled={c.op === "is_empty" || c.op === "not_empty"} onChange={(e) => setCond(i, { value: e.target.value })} />
              <button type="button" className="text-[var(--color-mute)] hover:text-red-300" aria-label={`Remove condition ${i + 1}`} onClick={() => set({ conditions: value.conditions.filter((_, j) => j !== i) })}><Trash2 size={13} /></button>
            </div>
          ))}
          <datalist id="automation-fields">{FIELDS.map((f) => <option key={f} value={f} />)}</datalist>
          <button type="button" className="btn" disabled={value.conditions.length >= 10} onClick={() => set({ conditions: [...value.conditions, { field: "data.platform", op: "equals", value: "bluesky" }] })}>
            <Plus size={12} /> Add condition
          </button>
        </fieldset>

        <fieldset className="space-y-2 rounded-lg border border-[var(--color-line)] p-3">
          <legend className="px-1 text-xs text-cyan-300">3 · Then do</legend>
          {value.actions.map((a, i) => (
            <div key={i} className="space-y-2 rounded-md bg-black/10 p-2">
              <div className="flex gap-2">
                <select className="input flex-1" aria-label={`Action ${i + 1}`} value={a.type} onChange={(e) => set({ actions: value.actions.map((x, j) => (j === i ? newAction(e.target.value) : x)) })}>
                  {meta.actions.map((x) => <option key={x} value={x}>{ACTION_LABEL[x] || x}</option>)}
                </select>
                <button type="button" className="text-[var(--color-mute)] hover:text-red-300" aria-label={`Remove action ${i + 1}`} onClick={() => set({ actions: value.actions.filter((_, j) => j !== i) })}><Trash2 size={13} /></button>
              </div>
              {a.type === "ask_agent" && (
                <>
                  <select className="input w-full" aria-label={`Action ${i + 1} agent`} value={a.agent} onChange={(e) => setAct(i, { agent: e.target.value })}>
                    {meta.agents.map((x) => <option key={x} value={x}>{x.toUpperCase()}</option>)}
                  </select>
                  <textarea className="input h-20 w-full text-xs" aria-label={`Action ${i + 1} message`} placeholder="Friday, draft a thank-you reply to {{data.author}} for: {{data.text}}" value={a.message} onChange={(e) => setAct(i, { message: e.target.value })} />
                </>
              )}
              {a.type === "create_draft" && (
                <>
                  <select className="input w-full" aria-label={`Action ${i + 1} platform`} value={a.platform} onChange={(e) => setAct(i, { platform: e.target.value })}>
                    {meta.platforms.map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                  <textarea className="input h-20 w-full text-xs" aria-label={`Action ${i + 1} text`} value={a.text} onChange={(e) => setAct(i, { text: e.target.value })} />
                </>
              )}
              {a.type === "label_mention" && <input className="input w-full" aria-label={`Action ${i + 1} label`} value={a.label} onChange={(e) => setAct(i, { label: e.target.value })} />}
              {a.type === "notify" && <textarea className="input h-16 w-full text-xs" aria-label={`Action ${i + 1} text`} value={a.text} onChange={(e) => setAct(i, { text: e.target.value })} />}
              {a.type === "webhook" && <input className="input w-full font-mono text-xs" aria-label={`Action ${i + 1} address`} value={a.url} onChange={(e) => setAct(i, { url: e.target.value })} />}
              {a.type === "add_utm" && <p className="text-xs text-[var(--color-mute)]">Adds utm_source / utm_medium / utm_campaign to links to your own site in the post from this event.</p>}
            </div>
          ))}
          <button type="button" className="btn" disabled={value.actions.length >= 6} onClick={() => set({ actions: [...value.actions, newAction("notify")] })}>
            <Plus size={12} /> Add action
          </button>
        </fieldset>

        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={value.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> Switched on
        </label>
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={!value.name.trim() || value.actions.length === 0}>Save automation</button>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </section>
  );
}

function ConnectApps() {
  return (
    <div className="grid gap-4 [&>*]:min-w-0 lg:grid-cols-2">
      <section className="panel p-4 text-xs text-[var(--color-mute)]">
        <div className="hud-label mb-2 text-cyan-300">Other apps → STARK OS</div>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>Use the recipe <b>Drafts from other apps</b> (or build an automation with the trigger “Another app calls a webhook”).</li>
          <li>Copy its secret address. Make it reachable from the internet with a tunnel, exposing only <code>/api/hooks/</code>.</li>
          <li>In Make add an <b>HTTP → Make a request</b> module: method POST, body type Raw, content type JSON, body like <code>{"{\"platform\":\"bluesky\",\"text\":\"…\"}"}</code>.</li>
          <li>Drafts appear in Content for you to approve. Nothing is published without you.</li>
        </ol>
      </section>
      <section className="panel p-4 text-xs text-[var(--color-mute)]">
        <div className="hud-label mb-2 text-cyan-300">STARK OS → other apps</div>
        <ol className="list-decimal space-y-1.5 pl-4">
          <li>In Make add a <b>Webhooks → Custom webhook</b> trigger and copy its address.</li>
          <li>Here, add an action <b>Send to a webhook</b> with that address (or use the recipe <b>Log every published post</b>).</li>
          <li>Each run sends <code>{"{automation, event, at, data}"}</code>, so the other app can write it to a spreadsheet, a notes database, email or anything else it supports.</li>
          <li>For every event at once, set <code>STARK_WEBHOOK_URLS</code> in <code>.env</code> (signed with <code>STARK_WEBHOOK_SECRET</code>).</li>
        </ol>
        <p className="mt-3">Step-by-step scenarios: <code>docs/AUTOMATIONS.md</code> in the repository.</p>
      </section>
    </div>
  );
}
