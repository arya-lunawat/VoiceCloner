"""
Voice Cloning MVP - FastAPI backend.
Free stack: FastAPI + SQLite + Coqui XTTS v2 + local disk storage.

Run: uvicorn main:app --reload --port 8000
"""
import os
import json
import shutil

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import database as db
import preprocessing
import tts_engine
import watermark

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "..", "uploads")
EMBED_DIR = os.path.join(BASE_DIR, "..", "embeddings")
GEN_DIR = os.path.join(BASE_DIR, "..", "generated_audio")
for d in (UPLOAD_DIR, EMBED_DIR, GEN_DIR):
    os.makedirs(d, exist_ok=True)

app = FastAPI(title="Voice Clone App (Free/Open-Source MVP)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


@app.on_event("startup")
def warm_up_model():
    # Loads XTTS v2 once at startup instead of on first request.
    tts_engine.get_tts()


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


# ---------- 4. Generate speech ----------

@app.post("/generate-audio")
async def generate_audio(
    voice_profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("en"),
):
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

    generation_id = db.new_id()
    out_path = os.path.join(GEN_DIR, f"{generation_id}.wav")
    created_at = db.now()

    try:
        tts_engine.generate_speech(text, row["embedding_path"], out_path, language=language)
        watermark.tag_generated_audio(out_path, generation_id, voice_profile_id, created_at)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO generations (id, voice_profile_id, text, audio_path, created_at, is_favorite) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (generation_id, voice_profile_id, text, out_path, created_at),
        )
        conn.commit()

    return {"generation_id": generation_id, "download_url": f"/audio/{generation_id}"}


# ---------- 5. Download / stream generated audio ----------

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
