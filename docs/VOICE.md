# STARK voice

Talk to Vision and Wanda in **English or Urdu** and hear them answer, each in their own voice.

## Turn it on

1. Create a free API key at aistudio.google.com/apikey (Google account needed).
2. Desktop app: **Settings → STARK voice**, paste the key, choose the language, **Save and restart**.
   Self-hosted: set `GEMINI_API_KEY` in `.env` (optional: `STARK_VOICE_LANGUAGE=en|ur`,
   `STARK_VOICE_URDU_SCRIPT=roman`) and restart the API.
3. In **Command**, turn on **Speak replies**, hold **Hold to talk** (or Space/Enter on the button) and speak.
   Start with a name to choose who answers: "Vision, how did yesterday's posts do?", "وانڈا، تین پوسٹس لکھو".

Use **Hear Vision / Hear Wanda** in Settings to check the voices.

## How it works

- While you hold the button, the desktop app records with your computer's microphone (a browser page records
  itself). When you let go, the recording is turned into text with your Gemini key.
- The text goes to the assistant exactly like a typed message: the same tools, approvals, modes and emergency stop.
- The reply is shortened for speaking (no code or links; "the rest is on screen") and said in the assistant's voice.
- **Voice never approves anything.** When an action needs approval, the assistant says so and the approval card
  waits on screen.
- Nothing is recorded or sent unless you hold the button. Recordings stop by themselves after 60 seconds.

## Voices and languages

| | Voice | Style |
|---|---|---|
| Vision | Charon | calm, clear, precise |
| Wanda | Sulafat | warm, lively, friendly |

Change `voice` and `style` in `agents/<id>/agent.toml` (`[voice]` section). Any Gemini prebuilt voice name works.
Urdu is written in Urdu script by default; choose Roman Urdu in Settings. Speech models are picked automatically
from what your key can use; `STARK_VOICE_STT_MODEL` and `STARK_VOICE_TTS_MODEL` override them.

## Privacy and limits

- Audio and text are sent to Google only for speech. On the free tier Google may use the data to improve its
  services; use a paid key if that matters to you.
- The free tier has per-minute and daily limits. When one is reached, STARK says so; wait a minute and try again.
- Your key is stored in the macOS Keychain / Windows Credential Manager and is never shown in logs.
- On macOS the first recording asks for microphone permission (System Settings → Privacy & Security → Microphone).
