"""
Voice cloning + speech generation using Coqui XTTS v2.

XTTS v2 is free to download and run. License: Coqui Public Model License (CPML) -
free for personal / research / non-commercial use. Commercial use requires a
separate license from Coqui. Since this MVP is built to run "for free", it uses
the model as-is; check CPML terms before shipping this commercially.

XTTS v2 is zero-shot: no per-user training run. It computes a "speaker latent"
from your reference audio once, then reuses it for every generation - this is
the "reusable voice profile" the spec asks for.

Long-form support:
    Long text is automatically chunked into segments that respect sentence
    and clause boundaries (see chunking.py). Each chunk is generated
    sequentially reusing the same speaker latents (no recomputation needed).
    Chunks are concatenated with a brief silence gap for natural pacing.
    If a chunk fails, it is retried once, then skipped with a warning.
"""
import os
import logging
import torch
from TTS.api import TTS
from pydub import AudioSegment
import numpy as np

from chunking import chunk_text

logger = logging.getLogger(__name__)

_MODEL_NAME = os.getenv("MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
_device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

_tts_instance = None

# Silence gap to insert between chunks (milliseconds).
# 300ms sounds natural for most prose; adjust per taste.
CHUNK_SILENCE_MS = 300

# Maximum retry attempts per chunk before giving up.
MAX_RETRIES_PER_CHUNK = 1


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

    For short text, this works as a single call. For long text, it
    delegates to `generate_speech_long` which chunks and concatenates.
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


# ═══════════════════════════════════════════════════════════════════════
#  Long-form generation with chunking + stitching
# ═══════════════════════════════════════════════════════════════════════

def generate_speech_long(
    text: str,
    embedding_path: str,
    output_path: str,
    language: str = "en",
    progress_callback=None,
) -> str:
    """
    Generate speech for potentially very long text by:
      1. Chunking the text into XTTS-safe segments (see chunking.py).
      2. Generating audio for each chunk sequentially using the SAME
         cached speaker latents (no re-computation per chunk).
      3. Concatenating all chunk WAVs with a short silence gap.
      4. Handling per-chunk failures gracefully (retry once, skip).

    Args:
        text: The full text to speak (unlimited length).
        embedding_path: Path to cached speaker latents (.pt file).
        output_path: Where to write the final concatenated WAV.
        language: Language code (default "en").
        progress_callback: Optional callable(current_chunk, total_chunks)
                           called after each successful chunk generation.

    Returns:
        output_path on success.

    Raises:
        RuntimeError: If ALL chunks fail generation (no audio produced).
    """
    import soundfile as sf
    from io import BytesIO

    tts = get_tts()
    cached = torch.load(embedding_path)

    # 1. Chunk the text
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Input text produced no chunks after splitting.")

    total = len(chunks)
    logger.info("Long-form generation: %d chunks to process", total)

    # 2. Generate each chunk, collecting audio segments
    segments: list[AudioSegment] = []
    successful_chunks = 0
    failed_chunks = 0

    for idx, chunk in enumerate(chunks, start=1):
        logger.info("Generating chunk %d/%d (%d chars)", idx, total, len(chunk))

        success = False
        for attempt in range(1 + MAX_RETRIES_PER_CHUNK):
            try:
                wav_out = tts.synthesizer.tts_model.inference(
                    text=chunk,
                    language=language,
                    gpt_cond_latent=cached["gpt_cond_latent"],
                    speaker_embedding=cached["speaker_embedding"],
                )["wav"]
                success = True
                break
            except Exception as e:
                logger.warning(
                    "Chunk %d/%d attempt %d failed: %s",
                    idx, total, attempt + 1, e,
                )
                if attempt < MAX_RETRIES_PER_CHUNK:
                    logger.info("Retrying chunk %d/%d...", idx, total)

        if not success:
            logger.error("Skipping chunk %d/%d after %d failed attempt(s).",
                         idx, total, 1 + MAX_RETRIES_PER_CHUNK)
            failed_chunks += 1
            if progress_callback:
                progress_callback(idx, total)
            continue

        # Convert the numpy audio array to pydub AudioSegment
        # XTTS v2 outputs audio at 24kHz.
        wav_np = (wav_out * 32767).astype(np.int16)
        # Wrap in BytesIO so pydub can read it without writing to disk
        buf = BytesIO()
        sf.write(buf, wav_np, 24000, format="wav")
        buf.seek(0)
        segment = AudioSegment.from_wav(buf)
        segments.append(segment)
        successful_chunks += 1

        if progress_callback:
            progress_callback(idx, total)

    # 3. No successful chunks? Error out.
    if not segments:
        raise RuntimeError(
            f"All {total} chunks failed generation. No audio produced."
        )

    # 4. Concatenate with silence gaps
    logger.info(
        "Concatenating %d successful chunks (%.1f seconds total raw audio)...",
        successful_chunks,
        sum(len(s) for s in segments) / 1000.0,
    )

    silence_gap = AudioSegment.silent(duration=CHUNK_SILENCE_MS)
    final_audio = segments[0]
    for seg in segments[1:]:
        final_audio += silence_gap + seg

    # 5. Export final audio
    final_audio.export(output_path, format="wav")
    logger.info(
        "Long-form generation complete: %d successful, %d failed → %s",
        successful_chunks,
        failed_chunks,
        output_path,
    )
    return output_path

