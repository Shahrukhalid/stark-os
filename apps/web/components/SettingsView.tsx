"use client";

import { Trash2, Sun, Moon, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { pickVoice, ttsSupported } from "@/lib/voice";
import { AgentGlyph, Section } from "./ui";

const MODES = [
  {
    id: "observe",
    title: "Observe",
    text: "Read-only. Every write, publish or memory-write action is denied.",
  },
  {
    id: "assist",
    title: "Assist (default)",
    text: "Agents read freely and draft changes; every change waits in the approval queue.",
  },
  {
    id: "execute_approved",
    title: "Execute approved",
    text: "Reversible file changes inside scopes you grant below run without asking. Publishing, sensitive and destructive actions still always need approval.",
  },
  {
    id: "scheduled",
    title: "Scheduled automation (planned)",
    text: "The scheduler is not implemented yet; selecting it behaves like Assist.",
  },
] as const;

type ThemePreference = "light" | "dark" | "system";

function applyTheme(theme: ThemePreference) {
  const resolvedTheme =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: light)").matches
        ? "light"
        : "dark"
      : theme;

  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.style.colorScheme = resolvedTheme;
}

export function SettingsView({
  onSignOut,
}: {
  onSignOut: () => void;
}) {
  const { status, client, notify, agents, refresh } = useStark();

  const [grants, setGrants] = useState<any[]>([]);
  const [g, setG] = useState({
    agent_id: "jarvis",
    tool_id: "fs.move",
    scope: "",
    hours: 24,
  });
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [theme, setTheme] = useState<ThemePreference>("system");

  const loadGrants = () =>
    client.get<any[]>("/api/grants").then(setGrants).catch(() => {});

  // Load the saved theme and follow system preference when selected.
  useEffect(() => {
    const savedTheme = localStorage.getItem("stark-theme");

    const initialTheme: ThemePreference =
      savedTheme === "light" || savedTheme === "dark" || savedTheme === "system"
        ? savedTheme
        : "system";

    setTheme(initialTheme);
    applyTheme(initialTheme);

    const media = window.matchMedia("(prefers-color-scheme: light)");

    const handleSystemThemeChange = () => {
      if ((localStorage.getItem("stark-theme") || "system") === "system") {
        applyTheme("system");
      }
    };

    media.addEventListener("change", handleSystemThemeChange);

    return () => {
      media.removeEventListener("change", handleSystemThemeChange);
    };
  }, []);

  const changeTheme = (nextTheme: ThemePreference) => {
    setTheme(nextTheme);
    localStorage.setItem("stark-theme", nextTheme);
    applyTheme(nextTheme);
  };

  useEffect(() => {
    loadGrants();

    if (ttsSupported()) {
      const load = () => setVoices(window.speechSynthesis.getVoices());

      load();
      window.speechSynthesis.addEventListener("voiceschanged", load);

      return () =>
        window.speechSynthesis.removeEventListener("voiceschanged", load);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const writeTools =
    agents.find((a) => a.id === g.agent_id)?.tool_details.filter(
      (t) => t.risk === "write",
    ) || [];

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-2">
      <Section title="Appearance">
        <div className="space-y-3">
          <p className="text-sm text-[var(--color-mute)]">
            Choose how STARK OS looks. Your preference is saved in this browser.
          </p>

          <div
            className="grid grid-cols-3 gap-2"
            role="group"
            aria-label="Color theme"
          >
            <button
              type="button"
              onClick={() => changeTheme("light")}
              aria-pressed={theme === "light"}
              className={`flex items-center justify-center gap-2 rounded-lg border p-3 text-sm transition ${
                theme === "light"
                  ? "border-cyan-500 bg-cyan-500/10 text-[var(--color-ink)]"
                  : "border-[var(--color-line)]"
              }`}
            >
              <Sun size={16} />
              Light
            </button>

            <button
              type="button"
              onClick={() => changeTheme("dark")}
              aria-pressed={theme === "dark"}
              className={`flex items-center justify-center gap-2 rounded-lg border p-3 text-sm transition ${
                theme === "dark"
                  ? "border-cyan-500 bg-cyan-500/10 text-[var(--color-ink)]"
                  : "border-[var(--color-line)]"
              }`}
            >
              <Moon size={16} />
              Dark
            </button>

            <button
              type="button"
              onClick={() => changeTheme("system")}
              aria-pressed={theme === "system"}
              className={`flex items-center justify-center gap-2 rounded-lg border p-3 text-sm transition ${
                theme === "system"
                  ? "border-cyan-500 bg-cyan-500/10 text-[var(--color-ink)]"
                  : "border-[var(--color-line)]"
              }`}
            >
              <Monitor size={16} />
              System
            </button>
          </div>

          <p className="text-xs text-[var(--color-mute)]">
            {theme === "system"
              ? "Following your device's appearance setting."
              : `The ${theme} theme is selected.`}
          </p>
        </div>
      </Section>

      <Section title="Execution mode">
        <div className="space-y-2">
          {MODES.map((m) => (
            <label
              key={m.id}
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${
                status?.mode === m.id
                  ? "border-cyan-400/60 bg-cyan-400/5"
                  : "border-[var(--color-line)]"
              }`}
            >
              <input
                type="radio"
                name="mode"
                checked={status?.mode === m.id}
                onChange={() =>
                  client
                    .post("/api/settings/mode", { mode: m.id })
                    .then(refresh)
                    .catch((e) => notify("error", e.message))
                }
              />
              <span>
                <span className="font-medium">{m.title}</span>
                <span className="block text-xs text-[var(--color-mute)]">
                  {m.text}
                </span>
              </span>
            </label>
          ))}

          <p className="text-xs text-[var(--color-mute)]">
            Each agent also has its own ceiling (Ultron is capped at Observe).
            No agent has a tool to change modes, grants or its own configuration.
          </p>
        </div>
      </Section>

      <Section title="Standing grants (Execute-approved mode)">
        <form
          className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_80px_auto]"
          onSubmit={(e) => {
            e.preventDefault();

            client
              .post("/api/grants", g)
              .then(() => {
                notify("success", "Grant created");
                loadGrants();
              })
              .catch((err) => notify("error", err.message));
          }}
        >
          <select
            className="input"
            value={g.agent_id}
            onChange={(e) =>
              setG({ ...g, agent_id: e.target.value, tool_id: "" })
            }
            aria-label="Agent"
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>

          <select
            className="input"
            value={g.tool_id}
            onChange={(e) => setG({ ...g, tool_id: e.target.value })}
            aria-label="Tool"
          >
            <option value="">
              {writeTools.length ? "Tool…" : "no write tools"}
            </option>
            {writeTools.map((t) => (
              <option key={t.id} value={t.id}>
                {t.id}
              </option>
            ))}
          </select>

          <input
            className="input"
            aria-label="Grant scope (path prefix)"
            placeholder="scope (path prefix)"
            value={g.scope}
            onChange={(e) => setG({ ...g, scope: e.target.value })}
          />

          <input
            className="input"
            type="number"
            min={1}
            max={720}
            value={g.hours}
            onChange={(e) =>
              setG({ ...g, hours: Number(e.target.value) })
            }
            aria-label="Hours"
          />

          <button className="btn btn-primary" disabled={!g.tool_id}>
            Grant
          </button>
        </form>

        <div className="mt-3 space-y-1.5">
          {grants.length === 0 && (
            <p className="text-xs text-[var(--color-mute)]">
              No standing grants. Only reversible “write” tools can be
              granted; grants expire.
            </p>
          )}

          {grants.map((x) => (
            <div
              key={x.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--color-line)] px-3 py-1.5 text-xs"
            >
              <span className="font-medium">{x.agent_id}</span>
              <span className="break-anywhere min-w-0 font-mono">
                {x.tool_id}
              </span>
              <span className="chip">{x.scope || "any path"}</span>
              <span className="text-[var(--color-mute)]">
                until{" "}
                {x.expires_at
                  ? new Date(x.expires_at).toLocaleString()
                  : "∞"}
              </span>

              <button
                type="button"
                className="btn btn-danger ml-auto !px-2 !py-1"
                onClick={() =>
                  client
                    .del(`/api/grants/${x.id}`)
                    .then(loadGrants)
                    .catch((e) => notify("error", e.message))
                }
                aria-label="Revoke grant"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Model configuration">
        <p className="mb-2 text-xs text-[var(--color-mute)]">
          All agents run on free OpenRouter models. Each agent has a tier
          (deep / balanced / fast); the Models panel shows which free models
          serve each tier and lets you ping them. Pin a model with{" "}
          <code className="font-mono">OPENROUTER_MODEL</code> in{" "}
          <code className="font-mono">.env</code> or{" "}
          <code className="font-mono">[model] model</code> in{" "}
          <code className="font-mono">agents/&lt;id&gt;/agent.toml</code>.
        </p>

        <table className="w-full table-fixed text-left text-xs">
          <tbody>
            {agents.map((a) => (
              <tr
                key={a.id}
                className="border-t border-[var(--color-line)]"
              >
                <td className="py-1.5" style={{ color: a.color }}>
                  {a.name}
                </td>
                <td>{a.model.tier}</td>
                <td className="break-anywhere font-mono">
                  {a.model_in_use.model || "—"}
                </td>
                <td className="break-anywhere text-[var(--color-mute)]">
                  {a.model_in_use.reason}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Voice profiles (browser speech)">
        {!ttsSupported() ? (
          <p className="text-sm text-[var(--color-mute)]">
            This browser has no speech synthesis.
          </p>
        ) : (
          <div className="space-y-1.5 text-xs">
            <p className="mb-2 text-[var(--color-mute)]">
              {voices.length} system voices found. Each agent picks the closest
              original system voice; no actor voices are cloned.
            </p>

            {agents.map((a) => {
              const v = pickVoice(voices, a.voice);

              return (
                <div
                  key={a.id}
                  className="flex flex-wrap items-center gap-x-2"
                >
                  <AgentGlyph icon={a.icon} color={a.color} size={16} />
                  <span className="w-24">{a.name}</span>
                  <span className="break-anywhere min-w-0 font-mono">
                    {v ? `${v.name} (${v.lang})` : "default voice"}
                  </span>
                  <span className="ml-auto text-[var(--color-mute)]">
                    pitch {a.voice.pitch} · rate {a.voice.rate}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      <Section title="Connection">
        <p className="mb-3 text-sm text-[var(--color-mute)]">
          Memory is {status?.memory_enabled ? "enabled" : "disabled"} ·
          database {status?.database}
        </p>

        <button
          type="button"
          className="btn btn-danger"
          onClick={onSignOut}
        >
          Disconnect this browser
        </button>
      </Section>
    </div>
  );
}
