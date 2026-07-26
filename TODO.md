# Library Rename & Custom Download Filename

## Backend
- [x] Add `name` column to `generations` table in `database.py`
- [x] Update `_generate_in_background` in `main.py` to auto-generate a name from text
- [x] Add `PATCH /library/{generation_id}` rename endpoint
- [x] Update `GET /library` to return `name` field
- [x] Update `_generation_audio_response()` to accept `display_name` for custom filename
- [x] Update `GET /generations/{id}/audio` to pass `name` as download filename

## Frontend
- [x] Update `renderLibrary()` to show editable name with Rename button (inline input)
- [x] Download MP3 button uses server-provided filename via Content-Disposition
- [x] Rename API call (Save/Cancel) with PATCH request

