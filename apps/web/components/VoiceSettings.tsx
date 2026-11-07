"use client";

import { useEffect, useState } from "react";
import { isDesktop } from "@/lib/api";
import { useStark } from "@/lib/store";
import { voiceSpeak, type VoiceChoices, type VoiceStatus } from "@/lib/voice";
import { AgentGlyph } from "./ui";
import { Section } from "./ui";

const KEEP = "__keep__";
const sample = (name: string) => `Hello, I'm ${name}. السلام علیکم، آپ کی آج کی پوسٹس تیار ہیں۔`;
const STYLE_LABEL: Record<string, string> = { "": "Assistant's own", calm: "Calm", warm: "Warm", energetic: "Energetic", professional: "Professional", gentle: "Gentle", natural: "Natural" };

/** STARK voice: talk to Vision and Wanda in English or Urdu with your own Gemini key. */
export function VoiceSettings() {
  const { client, notify, agents } = useStark();
  const [choices, setChoices] = useState<VoiceChoices | null>(null);
  const [st, setSt] = useState<VoiceStatus | null>(null);
  const [key, setKey] = useState("");
  const [engine, setEngine] = useState("gemini");
  const [language, setLanguage] = useState("auto");
  const [script, setScript] = useState("urdu");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    client
      .get<VoiceStatus>("/api/voice/status")
      .then((s) => {
        setSt(s);
        setLanguage(s.language || "auto");
        setScript(s.urdu_script || "urdu");
      })
      .catch(() => setSt(null));
    client.get<VoiceChoices>("/api/voice/voices").then(setChoices).catch(() => setChoices(null));
    if (isDesktop())
      client
        .get<{ secrets: Record<string, boolean>; settings: Record<string, string> }>("/api/desktop/status")
        .then((d) => {
          if (d.secrets.GEMINI_API_KEY) setKey(KEEP);
          setEngine(d.settings.STARK_VOICE_ENGINE || "gemini");
        })
        .catch(() => undefined);
  }, [client]);

  async function save() {
    setBusy("save");
    try {
      await client.put("/api/desktop/settings", {
        values: { GEMINI_API_KEY: key, STARK_VOICE_ENGINE: engine === "gemini" ? "" : engine, STARK_VOICE_LANGUAGE: language === "auto" ? "" : language, STARK_VOICE_URDU_SCRIPT: script === "urdu" ? "" : script },
        restart: true,
      });
      notify("success", "Saved. STARK AI is restarting with the new voice settings.");
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  async function choose(agentId: string, voice: string, style: string) {
    try {
      await client.put("/api/voice/prefs", { agent_id: agentId, voice, style });
      setChoices((c) => (c ? { ...c, agents: { ...c.agents, [agentId]: { ...c.agents[agentId], voice: voice || c.agents[agentId].default, style } } } : c));
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function test(agentId: string, name: string) {
    const pick = choices?.agents[agentId];
    setBusy(agentId);
    try {
      await voiceSpeak(client, agentId, sample(name), pick ? { voice: pick.voice, style: pick.style } : undefined);
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <Section title="STARK voice">
      <p className="mb-3 text-sm text-[var(--color-mute)]">
        Talk to Vision and Wanda in English or Urdu, each in their own voice. Uses your own Google Gemini API key (the free tier works).
        Recordings are sent to Google only while you hold the talk button; free-tier data may be used by Google to improve its services.
        Approvals always stay on screen.
      </p>
      <p className="mb-3 text-xs">
        Status:{" "}
        {st?.engine === "gemini" ? (
          <span className="text-emerald-400">on{st.local_audio ? " (this computer's microphone and speakers)" : " (this browser records and plays)"}</span>
        ) : (
          <span className="text-[var(--color-mute)]">off: the browser&apos;s own speech is used</span>
        )}
      </p>
      {isDesktop() ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="hud-label text-[var(--color-mute)]">Gemini API key (aistudio.google.com/apikey)</span>
            <input className="input mt-1 w-full font-mono" type="password" autoComplete="off" value={key === KEEP ? "" : key}
              placeholder={key === KEEP ? "saved (leave empty to keep)" : "paste your key"}
              onChange={(e) => setKey(e.target.value || (key === KEEP ? KEEP : ""))} />
          </label>
          <label className="block">
            <span className="hud-label text-[var(--color-mute)]">Voice</span>
            <select className="input mt-1 w-full" value={engine} onChange={(e) => setEngine(e.target.value)}>
              <option value="gemini">STARK voice (Gemini)</option>
              <option value="browser">Browser speech</option>
            </select>
          </label>
          <label className="block">
            <span className="hud-label text-[var(--color-mute)]">Language I speak</span>
            <select className="input mt-1 w-full" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="auto">English and Urdu (automatic)</option>
              <option value="en">English</option>
              <option value="ur">اردو Urdu</option>
            </select>
          </label>
          <label className="block">
            <span className="hud-label text-[var(--color-mute)]">Write Urdu as</span>
            <select className="input mt-1 w-full" value={script} onChange={(e) => setScript(e.target.value)}>
              <option value="urdu">اردو (Urdu script)</option>
              <option value="roman">Roman Urdu</option>
            </select>
          </label>
          <div className="flex items-end">
            <button type="button" className="btn btn-primary" disabled={busy === "save" || !key} onClick={save}>
              {busy === "save" ? "Saving…" : "Save and restart"}
            </button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-[var(--color-mute)]">
          Set <code className="font-mono">GEMINI_API_KEY</code> (and optionally <code className="font-mono">STARK_VOICE_LANGUAGE=ur</code>) in .env and restart the API.
        </p>
      )}
      {st?.engine === "gemini" && choices && (
        <div className="mt-4 space-y-2">
          <p className="hud-label text-[var(--color-mute)]">Voices: pick one for each assistant and press Hear</p>
          {agents
            .filter((a) => choices.agents[a.id])
            .map((a) => {
              const pick = choices.agents[a.id];
              return (
                <div key={a.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <AgentGlyph icon={a.icon} color={a.color} size={16} />
                  <span className="w-24 truncate" style={{ color: a.color }}>{a.name}</span>
                  <select className="input min-w-0 flex-1" aria-label={`${a.name} voice`} value={pick.voice}
                    onChange={(e) => choose(a.id, e.target.value === pick.default ? "" : e.target.value, pick.style)}>
                    {choices.voices.map((v) => (
                      <option key={v.name} value={v.name}>{v.name} · {v.character}{v.name === pick.default ? " (default)" : ""}</option>
                    ))}
                  </select>
                  <select className="input w-36" aria-label={`${a.name} speaking style`} value={pick.style}
                    onChange={(e) => choose(a.id, pick.voice === pick.default ? "" : pick.voice, e.target.value)}>
                    {["", ...choices.styles].map((s) => (
                      <option key={s} value={s}>{STYLE_LABEL[s] ?? s}</option>
                    ))}
                  </select>
                  <button type="button" className="btn" disabled={!!busy} onClick={() => test(a.id, a.name)}>
                    {busy === a.id ? "Speaking…" : "Hear"}
                  </button>
                </div>
              );
            })}
        </div>
      )}
    </Section>
  );
}
