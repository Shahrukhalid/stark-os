import { describe, expect, it } from "vitest";
import { detectWake, parseAddress } from "../lib/addressing";
import { pickVoice, speak, speakable } from "../lib/voice";

// Same cases as services/api/tests/test_policy_memory.py::test_addressing - front and back end must agree.
const CASES: [string, string | null, string][] = [
  ["Hey JARVIS, I need you to plan our launch week", "jarvis", "I need you to plan our launch week"],
  ["Friday, check our mentions.", "friday", "check our mentions."],
  ["EDITH draft a poll for Friday night", "edith", "draft a poll for Friday night"],
  ["Ultron: analyze this strategy", "ultron", "analyze this strategy"],
  ["Jocasta, research this topic", "jocasta", "research this topic"],
  ["DUM-E, publish the next post", "dum_e", "publish the next post"],
  ["Dummy check the fan", "dum_e", "check the fan"],
  ["U, let's plan my day", "u", "let's plan my day"],
  ["use the tool", null, "use the tool"],
  ["Edit my document", null, "Edit my document"],
  ["Fridays are busy", null, "Fridays are busy"],
];

describe("agent addressing", () => {
  it.each(CASES)("%s", (utterance, agent, rest) => {
    expect(parseAddress(utterance)).toEqual({ agent, rest });
  });
  it("wake word only triggers on a leading agent name", () => {
    expect(detectWake("hey jarvis what's the time")).toBe("jarvis");
    expect(detectWake("I told jarvis yesterday")).toBeNull();
  });
});

describe("voice selection", () => {
  const voices = [
    { name: "Samantha", lang: "en-US" },
    { name: "Daniel", lang: "en-GB" },
    { name: "Moira", lang: "en-IE" },
    { name: "Thomas", lang: "fr-FR" },
  ];
  it("prefers a named voice, then exact language, then language family", () => {
    expect(pickVoice(voices, { lang: "en-GB", pitch: 1, rate: 1, preferred_voices: ["Daniel"] })?.name).toBe("Daniel");
    expect(pickVoice(voices, { lang: "en-IE", pitch: 1, rate: 1, preferred_voices: ["NotInstalled"] })?.name).toBe("Moira");
    expect(pickVoice(voices, { lang: "en-AU", pitch: 1, rate: 1, preferred_voices: [] })?.lang.startsWith("en")).toBe(true);
    expect(pickVoice([], { lang: "en-US", pitch: 1, rate: 1, preferred_voices: [] })).toBeNull();
  });
  it("strips markdown and code before speaking", () => {
    expect(speakable("**Done.** See `fs.move` and [docs](https://x.y) ```py\nprint(1)\n```")).toBe("Done. See fs.move and docs (code omitted)");
  });
});

describe("muted agents", () => {
  it("never speaks a muted profile (U. is mute) but still calls onEnd", () => {
    let ended = false;
    speak("hello", { lang: "en-US", pitch: 1, rate: 1, preferred_voices: [], muted: true }, () => (ended = true));
    expect(ended).toBe(true);
  });
});
