"""Talk to Vision and Wanda: speech in, speech out.

The voice layer only turns speech into text and text into speech. What you say is sent to the assistant exactly
like a typed message, so tools, approvals, modes and the emergency stop work the same. Voice never approves
anything and never acts on its own.

* Speech-to-text and the assistants' voices use the owner's own Google Gemini API key (free tier works).
* In the desktop app the microphone and speakers are used by the engine itself; in a browser the page records
  and plays the audio.
"""

from .gemini import GeminiVoice, VoiceError, spoken  # noqa: F401
