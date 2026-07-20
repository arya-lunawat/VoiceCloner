"""
Lightweight, free traceability measures (per the ethical-safeguards requirement).

This is intentionally simple for the MVP:
1. Embeds metadata tags into the generated audio file (source profile id,
   generation id, timestamp) so any exported file can be traced back to its
   generation record.
2. Every generation is also logged in the database (see database.py).

For stronger tamper-resistant watermarking later, look at Meta's open-source
AudioSeal (free, research license) - noted here as a future upgrade, not
included by default to keep the MVP dependency-light.
"""
from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TXXX


def tag_generated_audio(wav_path: str, generation_id: str, voice_profile_id: str, created_at: str):
    audio = WAVE(wav_path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(TXXX(desc="generation_id", text=generation_id))
    audio.tags.add(TXXX(desc="voice_profile_id", text=voice_profile_id))
    audio.tags.add(TXXX(desc="created_at", text=created_at))
    audio.tags.add(TXXX(desc="generator", text="voice-clone-app (AI-generated speech)"))
    audio.save()
