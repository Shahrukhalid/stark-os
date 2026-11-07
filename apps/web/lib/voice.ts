"use client";

/**
 * Voice I/O using the browser's Web Speech API (free, no keys).
 *  - Speech-to-text: SpeechRecognition (Chrome, Edge, Safari). Not available in Firefox.
 *  - Text-to-speech: speechSynthesis with per-agent voice profiles (original system voices, no cloning).
 * STARK voice (below) uses the engine with the owner's Gemini key instead, when one is set: English and Urdu,
 * one voice per assistant, and it also works in the desktop app's window.
 */

export interface VoiceProfile {
  lang: string;
  pitch: number;
  rate: number;
  preferred_voices: string[];
  /** Muted agents (U. is mute) are never spoken aloud. */
  muted?: boolean;
}

export interface VoiceLike {
  name: string;
  lang: string;
}

/** Pick the best available system voice for a profile: preferred name > exact lang > language family > any. */
export function pickVoice<T extends VoiceLike>(voices: T[], profile: VoiceProfile): T | null {
  if (!voices.length) return null;
  for (const pref of profile.preferred_voices) {
    const v = voices.find((x) => x.name.toLowerCase().includes(pref.toLowerCase()));
    if (v) return v;
  }
  const lang = profile.lang.toLowerCase();
  const exact = voices.find((x) => x.lang.toLowerCase() === lang);
  if (exact) return exact;
  const family = voices.find((x) => x.lang.toLowerCase().startsWith(lang.split("-")[0]));
  return family || voices[0];
}

/** Strip markdown so it is read naturally. */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " (code omitted) ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "link")
    .replace(/[#*_>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1500);
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function sttSupported(): boolean {
  return typeof window !== "undefined" && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
}

/** Time the dashboard last finished speaking, so the microphone can ignore its own voice. */
let lastSpokeAt = 0;

/** True while the dashboard is speaking (and briefly after), so wake-word mode ignores its own replies. */
export function isSpeaking(): boolean {
  if (!ttsSupported()) return false;
  return window.speechSynthesis.speaking || Date.now() - lastSpokeAt < 1500;
}

export function speak(text: string, profile: VoiceProfile, onEnd?: () => void): void {
  if (profile.muted || !ttsSupported()) {
    onEnd?.();
    return;
  }
  const synth = window.speechSynthesis;
  synth.cancel(); // interrupt anything already speaking
  const u = new SpeechSynthesisUtterance(speakable(text));
  const voice = pickVoice(synth.getVoices(), profile);
  if (voice) u.voice = voice;
  u.lang = voice?.lang || profile.lang;
  u.pitch = Math.max(0, Math.min(2, profile.pitch));
  u.rate = Math.max(0.5, Math.min(2, profile.rate));
  u.onend = () => {
    lastSpokeAt = Date.now();
    onEnd?.();
  };
  u.onerror = () => {
    lastSpokeAt = Date.now();
    onEnd?.();
  };
  synth.speak(u);
}

export function stopSpeaking(): void {
  if (ttsSupported()) window.speechSynthesis.cancel();
}

export interface Recognizer {
  start(): void;
  stop(): void;
}

export function createRecognizer(opts: {
  lang?: string;
  continuous?: boolean;
  onPartial?: (text: string) => void;
  onFinal: (text: string) => void;
  onState?: (listening: boolean) => void;
  onError?: (message: string) => void;
}): Recognizer | null {
  if (!sttSupported()) return null;
  const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  const rec = new Ctor();
  rec.lang = opts.lang || "en-US";
  rec.interimResults = true;
  rec.continuous = !!opts.continuous;
  let active = false;
  rec.onstart = () => {
    active = true;
    opts.onState?.(true);
  };
  let restartDelay = 0;
  rec.onend = () => {
    opts.onState?.(false);
    if (active && opts.continuous) {
      // Restart to keep wake-word mode alive; back off after network errors instead of looping.
      setTimeout(() => {
        if (!active) return;
        try {
          rec.start();
        } catch {
          /* already started */
        }
      }, restartDelay);
    }
  };
  rec.onerror = (e: any) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") active = false;
    restartDelay = e.error === "network" ? Math.min(30000, Math.max(2000, restartDelay * 2)) : 0;
    // Silence and our own restarts are normal in continuous mode: don't flood the screen with toasts.
    if (opts.continuous && (e.error === "no-speech" || e.error === "aborted")) return;
    if (opts.continuous && e.error === "network" && restartDelay > 2000) return; // already reported once
    opts.onError?.(e.error === "not-allowed" ? "Microphone permission denied" : `Speech error: ${e.error}`);
  };
  rec.onresult = (e: any) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) opts.onFinal(r[0].transcript.trim());
      else interim += r[0].transcript;
    }
    if (interim) opts.onPartial?.(interim);
  };
  return {
    start() {
      active = true;
      try {
        rec.start();
      } catch {
        /* already running */
      }
    },
    stop() {
      active = false;
      try {
        rec.stop();
      } catch {
        /* not running */
      }
    },
  };
}

// ---------------------------------------------------------------- STARK voice (engine side, Gemini key)
/** Status of STARK voice from the engine. "browser" means the browser's own speech is used instead. */
export interface VoiceStatus {
  engine: "gemini" | "browser";
  configured: boolean;
  local_audio: boolean;
  local_reason: string;
  language: string;
  urdu_script: string;
}

interface Client {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
}

const URDU = /[؀-ۿ]/;

/** True when most letters are Urdu script. */
export function isUrdu(text: string): boolean {
  const letters = Array.from(text).filter((c) => /\p{L}/u.test(c));
  return letters.length > 0 && letters.filter((c) => URDU.test(c)).length / letters.length > 0.4;
}

let recorder: MediaRecorder | null = null;
let chunks: Blob[] = [];
let playing: HTMLAudioElement | null = null;

async function blobToBase64(blob: Blob): Promise<string> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

/** Start recording: the desktop engine uses the microphone itself; a browser page records with MediaRecorder. */
export async function voiceListenStart(client: Client, st: VoiceStatus): Promise<void> {
  voiceStopSpeaking(client, st);
  if (st.local_audio) {
    await client.post("/api/voice/listen/start");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new Error("This browser can't record audio.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start();
}

/** Stop recording and return what was said (empty when nothing was heard). */
export async function voiceListenStop(client: Client, st: VoiceStatus): Promise<string> {
  if (st.local_audio) return (await client.post<{ text: string }>("/api/voice/listen/stop")).text;
  const rec = recorder;
  recorder = null;
  if (!rec) return "";
  const done = new Promise<void>((r) => (rec.onstop = () => r()));
  rec.stop();
  await done;
  rec.stream.getTracks().forEach((t) => t.stop());
  const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
  if (blob.size < 2000) return "";
  const audio = await blobToBase64(blob);
  return (await client.post<{ text: string }>("/api/voice/transcribe", { audio, mime: blob.type || "audio/webm" })).text;
}

/** Say a reply in the assistant's own voice. */
export async function voiceSpeak(client: Client, agentId: string, text: string): Promise<void> {
  const r = await client.post<{ played: boolean; audio?: string; mime?: string }>("/api/voice/speak", { agent_id: agentId, text, play: true });
  if (r.played || !r.audio) return;
  playing?.pause();
  playing = new Audio(`data:${r.mime || "audio/wav"};base64,${r.audio}`);
  await playing.play().catch(() => undefined);
}

export function voiceStopSpeaking(client: Client, st: VoiceStatus | null): void {
  playing?.pause();
  playing = null;
  if (st?.local_audio) client.post("/api/voice/stop").catch(() => undefined);
}
