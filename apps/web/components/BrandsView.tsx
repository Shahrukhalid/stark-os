"use client";

import { Check, Plus, Tag, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Brand } from "@/lib/types";
import { Empty, Section } from "./ui";

const EMPTY = { name: "", voice: "", audience: "", guidelines: "", hashtags: "", blocked_terms: "", platforms: "", color: "#22d3ee" };
type Form = typeof EMPTY;
const toForm = (b: Brand): Form => ({
  name: b.name, voice: b.voice, audience: b.audience, guidelines: b.guidelines, color: b.color,
  hashtags: b.hashtags.join(", "), blocked_terms: b.blocked_terms.join(", "), platforms: b.platforms.join(", "),
});

/** Several brands or clients in one STARK OS: the active brand steers every agent and tags new content. */
export function BrandsView() {
  const { client, notify } = useStark();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);

  const load = useCallback(() => {
    client.get<{ brands: Brand[] }>("/api/brands").then((r) => (setBrands(r.brands), window.dispatchEvent(new Event("stark:brands-changed")))).catch((e) => notify("error", e.message));
  }, [client, notify]);
  useEffect(load, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      if (editing === "new") await client.post("/api/brands", form);
      else await client.put(`/api/brands/${editing}`, form);
      notify("success", "Brand saved");
      setEditing(null);
      load();
    } catch (err: any) {
      notify("error", err.message);
    }
  }
  const activate = (id: string | null) =>
    client.post("/api/brands/active", { id }).then(() => (notify("success", id ? "Brand switched" : "No brand active"), load())).catch((e) => notify("error", e.message));
  const remove = (b: Brand) => {
    if (!window.confirm(`Delete the brand "${b.name}"? Its content stays, just without a brand.`)) return;
    client.del(`/api/brands/${b.id}`).then(load).catch((e) => notify("error", e.message));
  };
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const active = brands.find((b) => b.active);

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_1.2fr]">
      <Section
        title={`Brands · ${brands.length}`}
        right={
          <button className="btn !py-1 text-xs" onClick={() => (setForm(EMPTY), setEditing("new"))}>
            <Plus size={13} className="mr-1 inline" /> New brand
          </button>
        }
      >
        <p className="mb-3 text-sm text-[var(--color-mute)]">
          {active ? <>Agents are writing as <b style={{ color: active.color }}>{active.name}</b>. New drafts are tagged with it.</> : "No brand active: agents use your general guidelines."}
        </p>
        {brands.length === 0 ? (
          <Empty>Add a brand for each business or client you post for: its voice, audience, hashtags and words to avoid.</Empty>
        ) : (
          <ul className="space-y-2">
            {brands.map((b) => (
              <li key={b.id} className={`rounded-lg border p-3 text-sm ${b.active ? "border-cyan-400/50" : "border-[var(--color-line)]"}`}>
                <div className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full" style={{ background: b.color }} aria-hidden />
                  <span className="font-semibold">{b.name}</span>
                  <span className="text-xs text-[var(--color-mute)]">{b.items ?? 0} posts</span>
                  <div className="ml-auto flex gap-1">
                    {b.active ? (
                      <button className="btn !py-1 text-xs" onClick={() => activate(null)}>Stop using</button>
                    ) : (
                      <button className="btn btn-primary !py-1 text-xs" onClick={() => activate(b.id)}>
                        <Check size={12} className="mr-1 inline" /> Use
                      </button>
                    )}
                    <button className="btn !py-1 text-xs" onClick={() => (setForm(toForm(b)), setEditing(b.id))}>Edit</button>
                    <button className="btn !py-1 text-xs" aria-label={`Delete ${b.name}`} onClick={() => remove(b)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                {b.voice && <p className="mt-1 line-clamp-2 text-xs text-[var(--color-mute)]">{b.voice}</p>}
                {b.hashtags.length > 0 && <p className="mt-1 text-xs text-cyan-300">{b.hashtags.join(" ")}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {editing && (
        <Section title={editing === "new" ? "New brand" : `Edit ${form.name}`} right={<Tag size={15} className="text-cyan-300" />}>
          <form onSubmit={save} className="space-y-3 text-sm">
            <div className="flex gap-2">
              <label className="flex-1">
                <span className="hud-label text-[var(--color-mute)]">Name</span>
                <input className="input mt-1 w-full" value={form.name} onChange={set("name")} required maxLength={80} />
              </label>
              <label>
                <span className="hud-label text-[var(--color-mute)]">Colour</span>
                <input className="input mt-1 h-[38px] w-16 p-1" type="color" value={form.color} onChange={set("color")} />
              </label>
            </div>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Voice and tone</span>
              <textarea className="input mt-1 w-full" rows={2} value={form.voice} onChange={set("voice")} placeholder="Warm, short sentences, a little playful, no jargon" />
            </label>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Audience</span>
              <textarea className="input mt-1 w-full" rows={2} value={form.audience} onChange={set("audience")} placeholder="Small online shop owners who want more customers" />
            </label>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Hashtags it uses (comma separated)</span>
              <input className="input mt-1 w-full" value={form.hashtags} onChange={set("hashtags")} placeholder="#smallbusiness, #shoplocal" />
            </label>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Never use these words (the post checker blocks them)</span>
              <input className="input mt-1 w-full" value={form.blocked_terms} onChange={set("blocked_terms")} placeholder="cheap, guaranteed" />
            </label>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Platforms (comma separated)</span>
              <input className="input mt-1 w-full" value={form.platforms} onChange={set("platforms")} placeholder="bluesky, mastodon, threads" />
            </label>
            <label className="block">
              <span className="hud-label text-[var(--color-mute)]">Guidelines</span>
              <textarea className="input mt-1 w-full" rows={5} value={form.guidelines} onChange={set("guidelines")} placeholder="What we talk about, what we never say, how we answer complaints, our links…" />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn btn-primary">Save</button>
            </div>
          </form>
        </Section>
      )}
    </div>
  );
}
