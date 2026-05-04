# Dudo — Backlog de mejoras

Ordenado por impacto/dificultad. Prioridad alta primero; dentro de la misma prioridad, lo más fácil primero.

---

## 🔴 Alta prioridad

### 1. Compartir sala por URL (`?sala=codigo`)
**Por qué primero:** una línea en el cliente, impacto de usabilidad enorme.
- Al entrar con `?sala=codigo` en la URL, pre-rellenar el campo de sala automáticamente.
- El botón "Copiar" del lobby también copia el link completo (`origin + ?sala=codigo`).
- No requiere cambios de backend.

---

### 2. Transferencia de anfitrión
**Por qué:** sin esto, si el host se va la sala queda sin control.
- Cuando el jugador en `player_order[0]` se desconecta, el backend promueve al siguiente jugador conectado.
- Backend emite `{"type": "host_changed", "new_host_id": "...", "new_host_name": "..."}`.
- Frontend actualiza `S.isHost`, muestra/oculta `btn-start`, muestra toast `"Ahora eres el anfitrión"`.
- En lobby: el nuevo host puede cambiar reglas e iniciar.
- En partida: solo notificación, el juego continúa sin cambios.

---

### 3. Reconexión automática con backoff
**Por qué:** actualmente si el WS cae, el usuario tiene que refrescar manualmente.
- En `S.ws.onclose`, si el cierre no fue voluntario, lanzar un timer de reconexión.
- Intentos: 1 s → 2 s → 4 s → 8 s → 16 s → desistir y mostrar mensaje.
- Al reconectar, reutilizar `connect(S.roomId)` con el `reconnect_id` almacenado en sesión.
- Mostrar banner "Reconectando…" durante los intentos.

---

### 4. Reconexión en lobby
**Por qué:** actualmente solo funciona durante partida; si el host se va del lobby y vuelve, pierde su rol.
- Backend: en `_h_join`, si `reconnect_id` existe y la sala está en `lobby`, reincorporar al jugador con el mismo ID y nombre sin añadirlo como nuevo jugador.
- Si el reconectado era el host (`player_order[0]`), mantener esa posición.
- Emitir `reconnected` con `phase: "lobby"`.
- Frontend: `onReconnected` ya maneja `phase: "lobby"`.

---

### 5. Notificación de turno (pestaña en segundo plano)
**Por qué:** los jugadores a menudo tienen otras pestañas abiertas; sin esto el juego se detiene.
- Pedir permiso con `Notification.requestPermission()` en la primera interacción.
- En `onTurn`, si `isMe && document.hidden`, disparar `new Notification("¡Tu turno en Dudo!", { icon: "/static/favicon.svg" })`.
- Hacer parpadear `document.title` alternando `"⚡ ¡TU TURNO! — Dudo"` / `"Dudo"` hasta que el usuario enfoque la pestaña.

---

### 6. Rate limiting de mensajes WS
**Por qué:** un cliente malicioso o buggy podría saturar el servidor.
- En `GameManager`, mantener un `dict[str, float]` con el timestamp del último mensaje por `player_id`.
- Rechazar silenciosamente mensajes si llegan más de 1 por 200 ms (configurable via env var).
- Excepción: mensajes `join` y `connected` no tienen límite.

---

### 7. Variables de entorno
**Por qué:** valores como `MAX_PLAYERS`, `REVEAL_SECONDS`, `RATE_LIMIT_MS` están hardcodeados.
- Crear `config.py` con valores leídos de `os.environ`:
    - `REVEAL_SECONDS = int(os.getenv("REVEAL_SECONDS", 7))`
    - `MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", 6))`
    - `RATE_LIMIT_MS = int(os.getenv("RATE_LIMIT_MS", 200))`
- Referenciar desde `manager.py` y eliminar literales hardcodeados.
- Documentar en `README.md`.

---

## 🟡 Prioridad media

### 8. Avatar de jugador (emoji)
**Por qué:** humaniza la partida, visualmente diferenciador.
- Selector de emoji en el formulario (~20 opciones: 🎲 🦅 🐺 🦁 🐯 🦊 💀 👑 🎭 🃏 🏹 ⚔️ 🛡️ 🌙 ⚡ 🔥 💎 🎯 🍀 🎪).
- El emoji se envía en `join` como campo `avatar`.
- Backend: añadir `avatar: str = "🎲"` al dataclass `Player`; incluirlo en `to_public_dict()`.
- Frontend: mostrar emoji en la carta del jugador y en el lobby en lugar de la inicial.
- Guardar la elección en localStorage junto al nombre.

---

### 9. Historial / estadísticas de jugador
**Por qué:** da contexto de rendimiento. Solo lado cliente, sin backend.
- Al terminar cada partida (`game_over`), guardar en `dudoStats` en localStorage:
    - Partidas jugadas / ganadas (o no-perdedor en modo loser).
    - Rondas totales jugadas.
    - Dudos acertados / fallados.
    - Calzos acertados / fallados.
    - El frontend contabiliza los eventos `reveal` donde el jugador fue `challenger_id`.
- Modal accesible desde el lobby (`📊 Mis stats`).
- Formato: tabla con totales y porcentajes.

---

### 10. Límite de tiempo por turno
**Por qué:** evita partidas muertas. Requiere diseño cuidadoso de la acción automática.
- Regla configurable por anfitrión: `turn_timeout_seconds` (0 = sin límite; opciones: 30/60/90 s).
- Cuando expira, el servidor ejecuta la acción más conservadora:
    - Si hay apuesta activa y el jugador no ha pasado → **pasar** (neutral).
    - Si es la primera acción de la ronda → **apostar la mínima válida con cara 2**.
- Backend: `asyncio.Task` por turno, cancelada al recibir cualquier acción del jugador.
- Frontend: countdown numérico junto al banner de turno.

---

### 11. Espectadores
**Por qué:** permite unirse tarde a observar o que eliminados sigan viendo con info completa.
- Al unirse a una sala en curso sin `reconnect_id` válido → entrar como espectador.
- Backend: lista separada `spectators: dict[str, str]` en `Game`.
- Los espectadores reciben todos los broadcasts incluyendo `all_dice` en `reveal`, pero no pueden enviar acciones.
- Frontend: pantalla de espectador muestra la mesa y el log sin panel de acciones; badge "ESPECTADOR".

---

### 12. Animación de revelación mejorada
**Propuesta concreta (reutiliza infraestructura existente):**
- Flip de dados uno por uno con delay escalonado (la clase `revealed` + `flip-in` ya existe, solo orquestar delays).
- Dados con `.match` añaden un segundo keyframe `bounce-match` (rebote dorado).
- El dado perdido usa `animateDieCup exit` con filtro rojo progresivo en los frames finales.
- El contador numérico en la carta del perdedor cae animado al actualizarse.

---

### 13. Sonidos adicionales
**Por qué:** los tonos sintéticos actuales son funcionales pero no temáticos.
- Añadir a `SFX` usando Web Audio API (ya instanciada):
    - `roll`: ruido blanco filtrado corto al iniciar ronda.
    - `gavilan`: glissando agudo al actuar fuera de turno.
    - `eliminated`: 3 notas descendentes lentas ("sad trombone").
    - `reconnect`: ping suave al reconectarse.
    - `tick`: click seco para los últimos 3 s del countdown de reveal.
- Alternativa: archivos `.ogg` < 20 KB c/u en `/static/sfx/`.

---

## Resumen

| # | Mejora | Archivos afectados | Dificultad | Impacto |
|---|--------|-------------------|------------|---------|
| 1 | URL compartible | `app.js` | ⭐ | 🔥🔥🔥 |
| 2 | Transferencia de anfitrión | `manager.py`, `app.js` | ⭐⭐ | 🔥🔥🔥 |
| 3 | Reconexión backoff | `app.js` | ⭐⭐ | 🔥🔥🔥 |
| 4 | Reconexión en lobby | `manager.py`, `app.js` | ⭐⭐ | 🔥🔥 |
| 5 | Notificación de turno | `app.js` | ⭐ | 🔥🔥 |
| 6 | Rate limiting | `manager.py` | ⭐⭐ | 🔥🔥 |
| 7 | Variables de entorno | `config.py`, `manager.py` | ⭐ | 🔥 |
| 8 | Avatar de jugador | `models.py`, `manager.py`, `app.js`, `index.html`, `style.css` | ⭐⭐ | 🔥🔥 |
| 9 | Estadísticas de jugador | `app.js`, `index.html`, `style.css` | ⭐⭐ | 🔥 |
| 10 | Límite de tiempo por turno | `models.py`, `manager.py`, `app.js`, `index.html`, `style.css` | ⭐⭐⭐ | 🔥🔥 |
| 11 | Espectadores | `models.py`, `manager.py`, `app.js`, `index.html` | ⭐⭐⭐ | 🔥🔥 |
| 12 | Animación revelación | `app.js`, `style.css` | ⭐⭐ | 🔥 |
| 13 | Sonidos adicionales | `app.js` | ⭐⭐ | 🔥 |