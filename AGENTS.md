# AGENTS Memory

## Proyecto
- Stack principal: FastAPI (`main.py`) + lógica de juego en `game/manager.py` + frontend vanilla en `static/app.js`.
- Archivos estáticos servidos desde `/static`.

## Verificación rápida
- Sintaxis Python: `python -m compileall main.py game`
- Sintaxis frontend: `node -e "const fs=require('fs'); new Function(fs.readFileSync('static/app.js','utf8'));"`

## Audio clips cortos (lanzador)
- Persistencia en DB con migración `v4`:
  - tabla `player_audio_clips` (máximo 2 slots por `anon_id`, duración <= 7s, `label`/`emoji`/`color` + `audio_data`).
- Endpoints backend:
  - `GET /api/player/{anon_id}/audio_clips?room_id=...` (solo si el jugador está presente en la sala)
  - `POST /api/player/{anon_id}/audio_clips` (multipart, sube/reemplaza por `slot`)
  - `GET /api/audio_clips/{clip_id}/stream?room_id=...` (sirve audio solo mientras el dueño está presente)
- WebSocket:
  - envío `{"type":"audio_clip","clip_id":<int>}`
  - broadcast incluye `clip_label`, `clip_emoji`, `clip_color`, `clip_url`.
- Frontend:
  - Botones de audio se construyen desde los clips del jugador (`QUICK_AUDIO_CLIPS`) y se muestran en popup propio + panel de espectador.
  - Panel de lobby `#custom-audio-panel` para subir/reemplazar slots 1..2 y parametrizar nombre/emoji/color.
