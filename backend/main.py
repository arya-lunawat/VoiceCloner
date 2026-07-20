"""
Voice Cloning MVP - FastAPI backend.
Free stack: FastAPI + SQLite + Coqui XTTS v2 + local disk storage.

Run: uvicorn main:app --reload --port 8000
"""
import os
import json
import shutil
import threading
import logging

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import database as db
import preprocessing
import tts_engine
import watermark

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "..", "uploads"))
EMBED_DIR = os.getenv("EMBED_DIR", os.path.join(BASE_DIR, "..", "embeddings"))
GEN_DIR = os.getenv("GEN_DIR", os.path.join(BASE_DIR, "..", "generated_audio"))
for d in (UPLOAD_DIR, EMBED_DIR, GEN_DIR):
    os.makedirs(d, exist_ok=True)

PORT = int(os.getenv("PORT", 8000))

app = FastAPI(title="Voice Clone App (Free/Open-Source MVP)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


@app.on_event("startup")
def startup_checks():
    """Verify system dependencies and warm up the model on boot."""
    # Ensure ffmpeg is available (pydub depends on it for audio conversion)
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH. "
            "Install it via 'brew install ffmpeg' (macOS), "
            "'sudo apt-get install ffmpeg' (Debian/Ubuntu), "
            "or 'conda install -c conda-forge ffmpeg' (conda). "
            "The app cannot convert uploaded audio without it."
        )
    # Loads XTTS v2 once at startup instead of on first request.
    tts_engine.get_tts()


# ═══════════════════════════════════════════════════════════════════════
#  In-memory background job tracking
# ═══════════════════════════════════════════════════════════════════════
#
# A simple thread-safe dict holds all active generation jobs.  Each job
# has the following structure:
#
#   {
#       "status": "processing" | "completed" | "failed",
#       "progress": "chunk X of Y" | "done" | str(error),
#       "total_chunks": int | None,
#       "completed_chunks": int,
#       "generation_id": str | None,    # set when complete
#       "output_path": str | None,      # set when complete
#       "error": str | None,            # set on failure
#   }
#
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _generate_in_background(
    job_id: str,
    text: str,
    voice_profile_id: str,
    embedding_path: str,
    language: str,
    generation_id: str,
    out_path: str,
    created_at: str,
):
    """
    Background thread target: runs the long-form generation and updates
    the job dict with progress.
    """
    def progress_callback(current: int, total: int):
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["completed_chunks"] = current
                _jobs[job_id]["total_chunks"] = total
                _jobs[job_id]["progress"] = f"Processing chunk {current} of {total}"

    try:
        logger.info("Job %s: starting long-form generation (%d chars)", job_id, len(text))
        tts_engine.generate_speech_long(
            text=text,
            embedding_path=embedding_path,
            output_path=out_path,
            language=language,
            progress_callback=progress_callback,
        )
        # Tag the audio with metadata
        watermark.tag_generated_audio(out_path, generation_id, voice_profile_id, created_at)

        # Record in database
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO generations (id, voice_profile_id, text, audio_path, created_at, is_favorite) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (generation_id, voice_profile_id, text, out_path, created_at),
            )
            conn.commit()

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["progress"] = "done"
                _jobs[job_id]["generation_id"] = generation_id
                _jobs[job_id]["output_path"] = out_path
                _jobs[job_id]["total_chunks"] = _jobs[job_id].get("total_chunks") or 0

        logger.info("Job %s: completed successfully → %s", job_id, out_path)

    except Exception as e:
        logger.exception("Job %s failed: %s", job_id, e)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["progress"] = str(e)
                _jobs[job_id]["error"] = str(e)


# ---------- 1. Upload + preprocess ----------

@app.post("/upload-voice")
async def upload_voice(
    name: str = Form(...),
    consent_confirmed: bool = Form(...),
    files: list[UploadFile] = File(...),
):
    if not consent_confirmed:
        raise HTTPException(
            status_code=400,
            detail="You must confirm you have the right to clone this voice before uploading.",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    profile_id = db.new_id()
    profile_dir = os.path.join(UPLOAD_DIR, profile_id)
    os.makedirs(profile_dir, exist_ok=True)

    processed_paths = []
    rejections = []

    for i, f in enumerate(files):
        raw_path = os.path.join(profile_dir, f"sample_{i}{os.path.splitext(f.filename)[1]}")
        with open(raw_path, "wb") as out:
            shutil.copyfileobj(f.file, out)

        try:
            result = preprocessing.preprocess_voice_sample(raw_path, profile_dir, f"sample_{i}")
            processed_paths.append(result["processed_path"])
        except preprocessing.PreprocessingError as e:
            rejections.append({"file": f.filename, "reason": str(e)})

    if not processed_paths:
        raise HTTPException(
            status_code=422,
            detail={"message": "All uploaded files were rejected during preprocessing.", "rejections": rejections},
        )

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO voice_profiles (id, name, consent_confirmed, source_files, embedding_path, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile_id, name, 1, json.dumps(processed_paths), None, db.now(), "processing"),
        )
        conn.commit()

    return {
        "voice_profile_id": profile_id,
        "accepted_samples": len(processed_paths),
        "rejected_samples": rejections,
        "next_step": f"POST /create-voice-profile with voice_profile_id={profile_id}",
    }


# ---------- 2. Build the reusable voice embedding ----------

@app.post("/create-voice-profile")
async def create_voice_profile(voice_profile_id: str = Form(...)):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM voice_profiles WHERE id = ?", (voice_profile_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice profile not found.")

    source_files = json.loads(row["source_files"])
    embedding_path = os.path.join(EMBED_DIR, f"{voice_profile_id}.pt")

    try:
        tts_engine.compute_speaker_latents(source_files, embedding_path)
    except Exception as e:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE voice_profiles SET status = ? WHERE id = ?", ("failed", voice_profile_id)
            )
            conn.commit()
        raise HTTPException(status_code=500, detail=f"Voice profile creation failed: {e}")

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE voice_profiles SET embedding_path = ?, status = ? WHERE id = ?",
            (embedding_path, "ready", voice_profile_id),
        )
        conn.commit()

    return {"voice_profile_id": voice_profile_id, "status": "ready"}


# ---------- 3. List voices ----------

@app.get("/voices")
async def list_voices():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, status, created_at FROM voice_profiles ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- 4. Generate speech (long-form, async) ----------

@app.post("/generate-audio")
async def generate_audio(
    voice_profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("en"),
):
    """
    Start a (potentially long) text-to-speech generation job.

    Returns immediately with a ``job_id``.  Poll
    ``GET /generate-audio/{job_id}/status`` for progress updates.
    When the job status is ``"completed"``, the result audio is available
    at ``GET /generate-audio/{job_id}``.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM voice_profiles WHERE id = ?", (voice_profile_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice profile not found.")
    if row["status"] != "ready":
        raise HTTPException(status_code=400, detail="Voice profile is not ready yet.")

    # Create the job entry
    generation_id = db.new_id()
    out_path = os.path.join(GEN_DIR, f"{generation_id}.wav")
    created_at = db.now()

    job_id = db.new_id()

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "processing",
            "progress": "queued",
            "total_chunks": None,
            "completed_chunks": 0,
            "generation_id": None,
            "output_path": None,
            "error": None,
        }

    # Launch background thread
    thread = threading.Thread(
        target=_generate_in_background,
        args=(
            job_id,
            text,
            voice_profile_id,
            row["embedding_path"],
            language,
            generation_id,
            out_path,
            created_at,
        ),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "processing",
        "poll_url": f"/generate-audio/{job_id}/status",
    }


@app.get("/generate-audio/{job_id}/status")
async def get_generation_status(job_id: str):
    """Poll the progress of a generation job."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    response = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "total_chunks": job["total_chunks"],
        "completed_chunks": job["completed_chunks"],
    }

    if job["status"] == "completed":
        response["download_url"] = f"/generate-audio/{job_id}"
    if job["status"] == "failed":
        response["error"] = job.get("error")

    return response


@app.get("/generate-audio/{job_id}")
async def get_generation_result(job_id: str):
    """
    Download the result of a completed generation job.

    Returns the audio file if the job is completed, or an error if it's
    still processing or failed.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] == "processing":
        raise HTTPException(
            status_code=400,
            detail=f"Job is still processing: {job['progress']}",
        )
    if job["status"] == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {job.get('error')}",
        )

    if not job["output_path"] or not os.path.exists(job["output_path"]):
        raise HTTPException(status_code=404, detail="Generated audio file not found.")

    return FileResponse(
        job["output_path"],
        media_type="audio/wav",
        filename=f"{job['generation_id']}.wav",
    )


# ---------- 5. Download / stream generated audio (legacy lookup by generation_id) ----------

@app.get("/audio/{generation_id}")
async def get_audio(generation_id: str):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM generations WHERE id = ?", (generation_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return FileResponse(row["audio_path"], media_type="audio/wav", filename=f"{generation_id}.wav")


@app.get("/generations")
async def list_generations(voice_profile_id: str | None = None):
    with db.get_conn() as conn:
        if voice_profile_id:
            rows = conn.execute(
                "SELECT * FROM generations WHERE voice_profile_id = ? ORDER BY created_at DESC",
                (voice_profile_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM generations ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


# ---------- 6. Delete a voice profile (consent / privacy requirement) ----------

@app.delete("/voice-profile/{voice_profile_id}")
async def delete_voice_profile(voice_profile_id: str):
    profile_dir = os.path.join(UPLOAD_DIR, voice_profile_id)
    embedding_path = os.path.join(EMBED_DIR, f"{voice_profile_id}.pt")

    if os.path.isdir(profile_dir):
        shutil.rmtree(profile_dir)
    if os.path.exists(embedding_path):
        os.remove(embedding_path)

    with db.get_conn() as conn:
        conn.execute("DELETE FROM voice_profiles WHERE id = ?", (voice_profile_id,))
        conn.execute("DELETE FROM generations WHERE voice_profile_id = ?", (voice_profile_id,))
        conn.commit()

    return {"deleted": voice_profile_id}


# Serve the simple frontend
frontend_dir = os.path.join(BASE_DIR, "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
