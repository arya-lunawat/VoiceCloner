# End-to-End Voice Clone System - Implementation Plan

## Overview
Transform the current single-page tabbed interface into a **multi-page end-to-end voice cloning system** with:
1. **Recording Page** - Record voice → "Save Created Voice" → saves to My Voices
2. **Voice Creator Page** - Select saved voice → enter text → "Generate Voice" → "Download Voice"
3. **My Voices Page** - List all saved voice profiles (with delete)
4. **My Library Page** - List all generated audio (play, download MP3, delete)

All data persisted in SQLite (swappable to PostgreSQL).

---

## Current Architecture Summary

**Backend (FastAPI + SQLite):**
- `voice_profiles` table: id, name, consent_confirmed, source_files (JSON), embedding_path, created_at, status
- `generations` table: id, voice_profile_id, text, audio_path, created_at, is_favorite, is_saved
- `voice_recordings` table: id, audio_path, created_at (legacy, can be merged)

**Frontend (Vanilla JS modules):**
- Single-page app with 3 tabs: My Voices, Voice Creator, My Library
- Shared `voiceApp` global for cross-tab communication
- API client in `api.js` with `fetch` wrappers

---

## Phase 1: Database Schema Updates

### 1.1 Update `voice-clone-app/backend/database.py`

**Changes:**
1. Add `voice_recordings` table merge into `voice_profiles` (store recording path directly on profile)
2. Add `is_saved` column to `voice_profiles` (user-saved voices vs temp profiles)
3. Add `recording_path` column to `voice_profiles` for direct recordings
4. Add indexes for common queries
5. Add migration for existing databases

```python
# database.py - Schema additions
conn.execute("""
    CREATE TABLE IF NOT EXISTS voice_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        consent_confirmed INTEGER NOT NULL DEFAULT 0,
        source_files TEXT NOT NULL,          -- JSON list of processed sample paths
        embedding_path TEXT,                  -- path to saved speaker latents (.pt)
        recording_path TEXT,                  -- NEW: path to direct browser recording
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'processing',
        is_saved INTEGER NOT NULL DEFAULT 0   -- NEW: user-saved "My Voices"
    )
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_saved ON voice_profiles(is_saved)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_status ON voice_profiles(status)")
```

### 1.2 Backend API Endpoints to Add/Modify

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/voice-profiles` | GET | List all voice profiles (filter by `is_saved`) |
| `/voice-profiles` | POST | Create voice profile from recording (merge upload-recording + create-profile) |
| `/voice-profiles/{id}/save` | POST | Toggle `is_saved` flag (Save/Unsave to My Voices) |
| `/voice-profiles/{id}` | DELETE | Delete voice profile + files + embedding |
| `/voice-profiles/{id}/recording` | GET | Download original recording |
| `/generations` | POST | Generate speech (async, returns job_id) |
| `/generations/{job_id}/status` | GET | Poll generation status |
| `/generations/{job_id}/audio` | GET | Download generated audio (WAV/MP3) |
| `/generations/{id}/save` | POST | Toggle save to library (`is_saved`) |
| `/library` | GET | List saved generations (`is_saved=1`) |
| `/library/{id}` | DELETE | Remove from library |

---

## Phase 2: Backend Implementation

### 2.1 Update `voice-clone-app/backend/main.py`

**New/Modified Endpoints:**

```python
# 1. Unified voice profile creation from recording (replaces /upload-recording)
@app.post("/voice-profiles")
async def create_voice_profile(
    name: str = Form(...),
    consent_confirmed: bool = Form(...),
    audio: UploadFile = File(...),  # browser recording (webm/ogg/wav)
):
    # 1. Save recording
    # 2. Preprocess
    # 3. Compute embedding
    # 4. Save to DB with status="ready", is_saved=0 (temp)
    # Returns: {voice_profile_id, status: "ready"}

# 2. Save voice profile to "My Voices"
@app.post("/voice-profiles/{voice_profile_id}/save")
async def save_voice_profile(voice_profile_id: str):
    # Toggle is_saved flag
    # Return: {voice_profile_id, saved: bool}

# 3. List voice profiles (filter by saved status)
@app.get("/voice-profiles")
async def list_voice_profiles(saved: bool = None):
    # If saved=true -> only is_saved=1
    # If saved=false -> only is_saved=0 (temp)
    # If None -> all

# 4. Delete voice profile (cascades to generations)
@app.delete("/voice-profiles/{voice_profile_id}")
async def delete_voice_profile(voice_profile_id: str):
    # Delete files, embedding, DB rows

# 5. Generate speech (async job) - rename /generate-audio to /generations
@app.post("/generations")
async def generate_speech(
    voice_profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("en"),
):
    # Returns {job_id, poll_url, status: "processing"}

# 6. Poll generation status
@app.get("/generations/{job_id}/status")
async def get_generation_status(job_id: str):
    # Returns {status, progress, total_chunks, completed_chunks, generation_id}

# 7. Download generated audio (WAV or MP3)
@app.get("/generations/{job_id}/audio")
async def download_generation(job_id: str, format: str = "wav"):
    # Returns audio file

# 8. Save generation to library
@app.post("/generations/{generation_id}/save")
async def save_generation(generation_id: str):
    # Toggle is_saved on generations table

# 9. List library (saved generations)
@app.get("/library")
async def list_library():
    # Join generations + voice_profiles, filter is_saved=1

# 10. Remove from library
@app.delete("/library/{generation_id}")
async def remove_from_library(generation_id: str):
    # Set is_saved=0
```

### 2.2 Update `voice-clone-app/backend/tts_engine.py`
- No changes needed, existing `generate_speech_long` works

### 2.3 Update `voice-clone-app/backend/preprocessing.py`
- Add `preprocess_recording()` for browser recordings (webm/ogg → wav 24kHz mono)

---

## Phase 3: Frontend - Multi-Page Architecture

### 3.1 Create Page Structure

```
voice-clone-app/frontend/
├── index.html              # Landing page / router entry
├── pages/
│   ├── record.html         # Page 1: Record Voice
│   ├── create.html         # Page 2: Voice Creator (Generate)
│   ├── voices.html         # Page 3: My Voices
│   └── library.html        # Page 4: My Library
├── app.js                  # Router + shared state
├── api.js                  # Updated API client
├── components/
│   ├── voiceRecorder.js    # Existing recorder modal
│   ├── audioPlayer.js      # Existing audio player
│   ├── toast.js            # Existing toast
│   ├── progressBar.js      # Existing progress
│   └── nav.js              # NEW: Navigation bar component
├── styles.css              # Updated for multi-page
└── utils/
    └── router.js           # NEW: Simple hash-based router
```

### 3.2 Create `utils/router.js` (Hash-based SPA Router)

```javascript
// Simple hash-based router for multi-page feel
export class Router {
  constructor() {
    this.routes = {};
    window.addEventListener('hashchange', () => this.navigate());
    window.addEventListener('load', () => this.navigate());
  }

  add(path, handler) {
    this.routes[path] = handler;
  }

  navigate() {
    const hash = window.location.hash.slice(1) || 'record';
    const [path, ...params] = hash.split('?');
    const handler = this.routes[path] || this.routes['record'];
    handler(params);
  }

  go(path) {
    window.location.hash = path;
  }
}
```

### 3.3 Create `components/nav.js` (Persistent Navigation)

```javascript
export function createNav(currentPage) {
  const nav = document.createElement('nav');
  nav.className = 'main-nav';
  nav.innerHTML = `
    <a href="#record" class="${currentPage === 'record' ? 'active' : ''}" data-page="record">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
        <line x1="12" y1="19" x2="12" y2="23"/>
        <line x1="8" y1="23" x2="16" y2="23"/>
      </svg>
      <span>Record</span>
    </a>
    <a href="#create" class="${currentPage === 'create' ? 'active' : ''}" data-page="create">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
      </svg>
      <span>Create</span>
    </a>
    <a href="#voices" class="${currentPage === 'voices' ? 'active' : ''}" data-page="voices">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
        <circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
        <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
      <span>My Voices</span>
    </a>
    <a href="#library" class="${currentPage === 'library' ? 'active' : ''}" data-page="library">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
      </svg>
      <span>Library</span>
    </a>
  `;
  return nav;
}
```

---

## Phase 4: Page Implementations

### 4.1 Page 1: Record Voice (`pages/record.html`)

**Features:**
- Full-screen recording interface
- Visual waveform/timer during recording
- "Save Created Voice" button after recording
- Shows saved confirmation → navigates to My Voices

**Flow:**
1. User lands on `/#record`
2. Clicks "Start Recording" → MediaRecorder starts
3. Speaks for 30+ seconds → Clicks "Stop"
4. Preview playback → "Save Voice" button appears
5. Enters voice name → "Save Created Voice" 
6. POST `/voice-profiles` → returns voice_profile_id
7. Toast "Voice saved to My Voices!" → navigate to `#voices`

**UI Components:**
- Large mic button with pulse animation
- Timer display (MM:SS)
- Audio preview player (after recording)
- Name input field
- "Save Created Voice" primary button
- "Re-record" secondary button

### 4.2 Page 2: Voice Creator (`pages/create.html`)

**Features:**
- Voice selector dropdown (loads from `/voice-profiles?saved=true`)
- Large text area for script input
- "Generate Voice" button (shows progress)
- Audio player with "Download Voice" (MP3) button
- Auto-saves to library option

**Flow:**
1. User lands on `/#create`
2. Loads saved voices via `GET /voice-profiles?saved=true`
3. Selects voice, enters text
4. Clicks "Generate Voice" → POST `/generations`
5. Polls `GET /generations/{job_id}/status` → shows progress bar
6. On complete: shows audio player with "Download Voice (MP3)" button
7. Optional: "Save to Library" checkbox auto-saves

**UI Components:**
- Voice selector (shows name, duration of recording)
- Script textarea (char count, estimated duration)
- Generate button with loading state
- Progress bar with chunk counter
- Audio player with download button

### 4.3 Page 3: My Voices (`pages/voices.html`)

**Features:**
- Grid/list of saved voice profiles
- Each card: name, recording preview, "Use in Creator" button, "Delete" button
- Empty state: "Record your first voice" → links to `#record`

**Flow:**
1. Loads `GET /voice-profiles?saved=true`
2. Renders cards with playable recording preview
3. "Use in Creator" → navigates to `#create?voice={id}`
4. "Delete" → DELETE `/voice-profiles/{id}` → refresh

### 4.4 Page 4: My Library (`pages/library.html`)

**Features:**
- Grid of saved generations
- Each card: voice name, text preview, date, play button, download MP3, remove
- Empty state: "Generate your first voice" → links to `#create`

**Flow:**
1. Loads `GET /library`
2. Renders cards with audio players
3. Play → streams audio
4. Download MP3 → `GET /generations/{id}/audio?format=mp3`
5. Remove → DELETE `/library/{id}` → refresh

---

## Phase 5: API Client Updates (`api.js`)

```javascript
// New API functions
export async function createVoiceProfile(name, audioBlob) {
  const form = new FormData();
  form.append('name', name);
  form.append('consent_confirmed', 'true');
  form.append('audio', audioBlob, 'recording.webm');
  return apiFetch('/voice-profiles', { method: 'POST', body: form });
}

export async function listVoiceProfiles(saved = null) {
  const url = saved !== null ? `/voice-profiles?saved=${saved}` : '/voice-profiles';
  return apiFetch(url);
}

export async function saveVoiceProfile(id) {
  return apiFetch(`/voice-profiles/${id}/save`, { method: 'POST' });
}

export async function deleteVoiceProfile(id) {
  return apiFetch(`/voice-profiles/${id}`, { method: 'DELETE' });
}

export async function generateSpeech(voiceProfileId, text, language = 'en') {
  const form = new FormData();
  form.append('voice_profile_id', voiceProfileId);
  form.append('text', text);
  form.append('language', language);
  return apiFetch('/generations', { method: 'POST', body: form });
}

export async function pollGeneration(jobId) {
  return apiFetch(`/generations/${jobId}/status`);
}

export async function downloadGeneration(jobId, format = 'wav') {
  const res = await fetch(`${API}/generations/${jobId}/audio?format=${format}`);
  if (!res.ok) throw new Error('Download failed');
  return res.blob();
}

export async function saveGeneration(generationId) {
  return apiFetch(`/generations/${generationId}/save`, { method: 'POST' });
}

export async function fetchLibrary() {
  return apiFetch('/library');
}

export async function removeFromLibrary(generationId) {
  return apiFetch(`/library/${generationId}`, { method: 'DELETE' });
}
```

---

## Phase 6: Database Migration Strategy

### 6.1 Create Migration Script (`backend/migrate.py`)

```python
# Run once to migrate existing DB
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "voice_clone.db")

with sqlite3.connect(DB_PATH) as conn:
    # Add new columns to voice_profiles
    for col, ddl in [
        ("recording_path", "TEXT"),
        ("is_saved", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE voice_profiles ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass
    
    # Add index
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_saved ON voice_profiles(is_saved)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_profiles_status ON voice_profiles(status)")
    
    # Migrate existing voice_recordings to voice_profiles
    conn.execute("""
        UPDATE voice_profiles 
        SET recording_path = (
            SELECT audio_path FROM voice_recordings 
            WHERE voice_recordings.id = voice_profiles.id
            LIMIT 1
        )
        WHERE recording_path IS NULL
    """)
    
    conn.commit()
print("Migration complete")
```

---

## Phase 7: Styling Updates (`styles.css`)

Add page-specific styles:
- `.page-record` - full-screen recording UI
- `.page-create` - split layout (voice selector + script + result)
- `.page-voices` - card grid
- `.page-library` - card grid with audio players
- `.main-nav` - fixed bottom/top navigation
- Responsive breakpoints for mobile

---

## Phase 8: Testing Checklist

| Feature | Test Case |
|---------|-----------|
| Record Page | Record 30s audio → preview plays → save → appears in My Voices |
| Record Page | Re-record works, clears previous |
| Create Page | Voice selector loads saved voices only |
| Create Page | Generate long text (>500 chars) → chunked progress works |
| Create Page | Download MP3 works, file plays |
| Create Page | Auto-save to library works |
| My Voices | Delete voice removes profile + embedding + generations |
| My Voices | "Use in Creator" navigates with voice pre-selected |
| Library | Play, download MP3, remove all work |
| DB | Migration runs cleanly on existing DB |
| Mobile | All pages responsive, recording works on mobile browser |

---

## Implementation Order

1. **Database migration** (`migrate.py` + `database.py` schema updates)
2. **Backend API** (new endpoints in `main.py`)
3. **Router + Nav** (`utils/router.js`, `components/nav.js`)
4. **API Client** (update `api.js`)
5. **Record Page** (`pages/record.html` + JS module)
6. **Create Page** (`pages/create.html` + JS module)
7. **My Voices Page** (`pages/voices.html` + JS module)
8. **My Library Page** (`pages/library.html` + JS module)
9. **Styling** (update `styles.css`)
10. **Entry point** (update `index.html` + `app.js` for router)
11. **Test end-to-end**

---

## Database Connection for External Access

To connect external tools (DBeaver, Python scripts, etc.):

```python
# SQLite (local file)
import sqlite3
conn = sqlite3.connect("voice-clone-app/backend/voice_clone.db")

# PostgreSQL (future)
import psycopg2
conn = psycopg2.connect(
    host="localhost",
    database="voice_clone",
    user="postgres",
    password="password"
)
```

Schema is identical - just swap connection logic in `database.py`.

---

## File Summary (New/Modified)

| File | Status | Description |
|------|--------|-------------|
| `backend/database.py` | MODIFY | Add columns, indexes |
| `backend/main.py` | MODIFY | New REST endpoints |
| `backend/migrate.py` | NEW | Migration script |
| `frontend/utils/router.js` | NEW | Hash router |
| `frontend/components/nav.js` | NEW | Navigation bar |
| `frontend/api.js` | MODIFY | New API functions |
| `frontend/pages/record.html` | NEW | Recording page |
| `frontend/pages/create.html` | NEW | Voice creator page |
| `frontend/pages/voices.html` | NEW | My Voices page |
| `frontend/pages/library.html` | NEW | My Library page |
| `frontend/app.js` | MODIFY | Router init |
| `frontend/index.html` | MODIFY | Mount point for pages |
| `frontend/styles.css` | MODIFY | Page styles |

---

## Prompt for Implementation

> **Implement the end-to-end voice clone system as specified in E2E_VOICE_CLONE_PLAN.md. Follow the phased approach:**
> 
> 1. Run database migration (`backend/migrate.py`)
> 2. Update `database.py` schema + `main.py` with new REST endpoints
> 3. Create `utils/router.js` and `components/nav.js`
> 4. Update `api.js` with new API functions
> 5. Build 4 pages: `record.html`, `create.html`, `voices.html`, `library.html` with their JS modules
> 6. Update `app.js` to initialize router + nav
> 7. Update `index.html` as SPA shell
> 8. Update `styles.css` for multi-page layout
> 9. Test full flow: Record → Save → Create → Generate → Download → Library
> 
> **Key requirements:**
> - Recording page: browser MediaRecorder, preview, "Save Created Voice" button
> - Create page: voice selector (saved voices only), text input, generate with progress, MP3 download
> - My Voices: grid of saved voices with preview, delete, "Use in Creator"
> - My Library: grid of saved generations with play, download MP3, remove
> - All data in SQLite (swappable to PostgreSQL via `database.py`)
> - Hash-based routing (`#record`, `#create`, `#voices`, `#library`)
> - Persistent navigation bar across pages