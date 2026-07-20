"""
Voice cloning + speech generation using Coqui XTTS v2.

XTTS v2 is free to download and run. License: Coqui Public Model License (CPML) -
free for personal / research / non-commercial use. Commercial use requires a
separate license from Coqui. Since this MVP is built to run "for free", it uses
the model as-is; check CPML terms before shipping this commercially.

XTTS v2 is zero-shot: no per-user training run. It computes a "speaker latent"
from your reference audio once, then reuses it for every generation - this is
the "reusable voice profile" the spec asks for.
"""
import os
import torch
from TTS.api import TTS

_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
_device = "cuda" if torch.cuda.is_available() else "cpu"

_tts_instance = None


def get_tts():
    """Lazy-load the model once (it's a few GB - don't reload per request)."""
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTS(_MODEL_NAME).to(_device)
    return _tts_instance


def compute_speaker_latents(reference_wav_paths: list[str], save_path: str) -> str:
    """
    Compute and cache the speaker embedding/latents from one or more clean
    reference clips. Saving this means we never need to reprocess the raw
    audio again for future generations - this IS the "voice profile".
    """
    tts = get_tts()
    gpt_cond_latent, speaker_embedding = tts.synthesizer.tts_model.get_conditioning_latents(
        audio_path=reference_wav_paths
    )
    torch.save(
        {"gpt_cond_latent": gpt_cond_latent, "speaker_embedding": speaker_embedding},
        save_path,
    )
    return save_path


def generate_speech(
    text: str,
    embedding_path: str,
    output_path: str,
    language: str = "en",
) -> str:
    """
    Generate speech in the cloned voice using cached latents (fast - no
    re-encoding of reference audio needed on every call).
    """
    tts = get_tts()
    cached = torch.load(embedding_path)

    wav = tts.synthesizer.tts_model.inference(
        text=text,
        language=language,
        gpt_cond_latent=cached["gpt_cond_latent"],
        speaker_embedding=cached["speaker_embedding"],
    )["wav"]

    import soundfile as sf
    sf.write(output_path, wav, 24000)
    return output_path
