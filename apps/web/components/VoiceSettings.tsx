"use client";

import { useEffect, useState } from "react";
import { isDesktop } from "@/lib/api";
import { useStark } from "@/lib/store";
import { voiceSpeak, type VoiceStatus } from "@/lib/voice";
import { Section } from "./ui";

const KEEP = "__keep__";
const SAMPLES: Record<string, string> = {
  vision: "Hello, I'm Vision. السلام علیکم، میں وژن ہوں۔",
  wanda: "Hi, I'm Wanda. السلام علیکم، میں وانڈا ہوں۔",
};

/** STARK voice: talk to Vision and Wanda in English or Urdu with your own Gemini key. */
export function VoiceSettings() {
  const { client, notify } = useStark();
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

  async function test(agentId: string) {
    setBusy(agentId);
    try {
      await voiceSpeak(client, agentId, SAMPLES[agentId]);
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
      {st?.engine === "gemini" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.keys(SAMPLES).map((id) => (
            <button key={id} type="button" className="btn" disabled={!!busy} onClick={() => test(id)}>
              {busy === id ? "Speaking…" : `Hear ${id === "vision" ? "Vision" : "Wanda"}`}
            </button>
          ))}
        </div>
      )}
    </Section>
  );
}
