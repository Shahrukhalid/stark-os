"use client";

import { Plus, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { ContentItem, PostingPlan } from "@/lib/types";
import { Section } from "./ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** The posting plan: content categories with a target mix, and weekly time slots for "Add to queue". */
export function PlanEditor({ items }: { items: ContentItem[] }) {
  const { client, notify } = useStark();
  const [plan, setPlan] = useState<PostingPlan | null>(null);
  const [slot, setSlot] = useState({ weekday: 0, time: "09:00" });
  const [cat, setCat] = useState("");

  useEffect(() => {
    client.get<PostingPlan>("/api/plan").then(setPlan).catch(() => {});
  }, [client]);

  const save = (next: PostingPlan) =>
    client.put<PostingPlan>("/api/plan", next).then(
      (p) => {
        setPlan(p);
        notify("success", "Posting plan saved");
      },
      (e) => notify("error", e.message),
    );

  if (!plan) return null;
  const upcoming = items.filter((i) => i.status === "scheduled" || i.status === "draft");
  const total = upcoming.filter((i) => i.category).length || 1;

  return (
    <Section title="Posting plan">
      <div className="hud-label mb-1 text-[var(--color-mute)]">Content mix · target vs planned</div>
      <ul className="space-y-1.5 text-xs">
        {plan.categories.map((c, n) => {
          const actual = Math.round((100 * upcoming.filter((i) => i.category === c.name).length) / total);
          return (
            <li key={c.name}>
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: c.color }} />
                <span className="flex-1">{c.name}</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  aria-label={`${c.name} share`}
                  className="input !w-16 !px-2 !py-0.5 text-xs"
                  value={c.share}
                  onChange={(e) => setPlan({ ...plan, categories: plan.categories.map((x, j) => (j === n ? { ...x, share: Number(e.target.value) } : x)) })}
                />
                <span className="w-10 text-right text-[var(--color-mute)]">{actual}%</span>
                <button aria-label={`Remove ${c.name}`} className="text-[var(--color-mute)] hover:text-red-300" onClick={() => setPlan({ ...plan, categories: plan.categories.filter((_, j) => j !== n) })}>
                  <X size={12} />
                </button>
              </div>
              <div className="mt-0.5 h-1 overflow-hidden rounded bg-black/20">
                <div className="h-full" style={{ width: `${Math.min(100, actual)}%`, background: c.color, transition: "width .6s" }} />
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex gap-1.5">
        <input className="input !py-1 text-xs" aria-label="New category" placeholder="New category" value={cat} onChange={(e) => setCat(e.target.value)} />
        <button
          className="btn !py-1 text-xs"
          disabled={!cat.trim()}
          onClick={() => {
            setPlan({ ...plan, categories: [...plan.categories, { name: cat.trim(), share: 10, color: ["#22d3ee", "#a78bfa", "#f472b6", "#34d399", "#fbbf24"][plan.categories.length % 5] }] });
            setCat("");
          }}
        >
          <Plus size={12} />
        </button>
      </div>

      <div className="hud-label mb-1 mt-4 text-[var(--color-mute)]">Weekly time slots · your time</div>
      <div className="flex flex-wrap gap-1.5">
        {plan.slots.map((s, n) => (
          <span key={`${s.weekday}-${s.time}`} className="chip">
            {DAYS[s.weekday]} {s.time}
            <button aria-label={`Remove ${DAYS[s.weekday]} ${s.time}`} onClick={() => setPlan({ ...plan, slots: plan.slots.filter((_, j) => j !== n) })}>
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5">
        <select className="input !w-auto !py-1 text-xs" aria-label="Slot day" value={slot.weekday} onChange={(e) => setSlot({ ...slot, weekday: Number(e.target.value) })}>
          {DAYS.map((d, i) => (
            <option key={d} value={i}>
              {d}
            </option>
          ))}
        </select>
        <input type="time" className="input !w-auto !py-1 text-xs" aria-label="Slot time" value={slot.time} onChange={(e) => setSlot({ ...slot, time: e.target.value })} />
        <button className="btn !py-1 text-xs" onClick={() => setPlan({ ...plan, slots: [...plan.slots, slot] })} aria-label="Add time slot">
          <Plus size={12} />
        </button>
      </div>
      <button className="btn btn-primary mt-3 !py-1 text-xs" onClick={() => save(plan)}>
        <Save size={12} /> Save plan
      </button>
      <p className="mt-2 text-[11px] text-[var(--color-mute)]">“Add to queue” in Compose fills the next free slot.</p>
    </Section>
  );
}
