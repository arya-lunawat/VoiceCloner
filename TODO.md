# TODO: Consolidate API Surface

## Steps
- [x] 1. Plan and confirm with user
- [x] 2. Edit `backend/main.py`:
  - [x] 2a. Add `_start_generation_job()` helper
  - [x] 2b. Remove all legacy routes (upload-voice, create-voice-profile, /voices, generate-audio, /audio/{id}, /generations (old), /voice-profile/{id})
  - [x] 2c. Refactor `POST /generations` to use `_start_generation_job()`
  - [x] 2d. Rename `delete_voice_profile_new` → `delete_voice_profile`, `get_generation_status_new` → `get_generation_status`
- [x] 3. Update `tests/test_api_endpoints.py` to target new API
- [x] 4. Update `README.md` with user-provided content
- [x] 5. Run tests — all 23 passed

