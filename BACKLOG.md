# Dudo — Backlog de mejoras

Ordenado por impacto/dificultad. Prioridad alta primero; dentro de la misma prioridad, lo más fácil primero.

## Mantenimiento del backlog

Al implementar una mejora, eliminarla de este backlog y registrarla en `CHANGELOG.md` (version/fecha correspondiente).

## Implementado recientemente (resumen)

Referencia completa en `CHANGELOG.md`.

- URL compartible por `?sala=codigo`.
- Transferencia automática de anfitrión.
- Reconexión automática con backoff.

---

## 🔴 Alta prioridad

### 3. Rate limiting de mensajes WS
**Por qué:** un cliente malicioso o buggy podría saturar el servidor.
- En `GameManager`, mantener un `dict[str, float]` con el timestamp del último mensaje por `player_id`.
- Rechazar silenciosamente mensajes si llegan más de 1 por 200 ms (configurable via env var).
- Excepción: mensajes `join` y `connected` no tienen límite.


## 🟡 Prioridad media

### 5. Avatar de jugador (emoji)
**Por qué:** humaniza la partida, visualmente diferenciador.
- Selector de emoji en el formulario (~20 opciones: 🎲 🦅 🐺 🦁 🐯 🦊 💀 👑 🎭 🃏 🏹 ⚔️ 🛡️ 🌙 ⚡ 🔥 💎 🎯 🍀 🎪).
- El emoji se envía en `join` como campo `avatar`.
- Backend: añadir `avatar: str = "🎲"` al dataclass `Player`; incluirlo en `to_public_dict()`.
- Frontend: mostrar emoji en la carta del jugador y en el lobby en lugar de la inicial.
- Guardar la elección en localStorage junto al nombre.

---

### 6. Historial / estadísticas de jugador
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

### 7. Límite de tiempo por turno
**Por qué:** evita partidas muertas. Requiere diseño cuidadoso de la acción automática.
- Regla configurable por anfitrión: `turn_timeout_seconds` (0 = sin límite; opciones: 30/60/90 s).
- Cuando expira, el servidor ejecuta la acción más conservadora:
    - Si hay apuesta activa y el jugador no ha pasado → **pasar** (neutral).
    - Si es la primera acción de la ronda → **apostar la mínima válida con cara 2**.
- Backend: `asyncio.Task` por turno, cancelada al recibir cualquier acción del jugador.
- Frontend: countdown numérico junto al banner de turno.

---

### 8. Espectadores
**Por qué:** permite unirse tarde a observar o que eliminados sigan viendo con info completa.
- Al unirse a una sala en curso sin `reconnect_id` válido → entrar como espectador.
- Backend: lista separada `spectators: dict[str, str]` en `Game`.
- Los espectadores reciben todos los broadcasts incluyendo `all_dice` en `reveal`, pero no pueden enviar acciones.
- Frontend: pantalla de espectador muestra la mesa y el log sin panel de acciones; badge "ESPECTADOR".

---

### 9. Animación de revelación mejorada
**Propuesta concreta (reutiliza infraestructura existente):**
- Flip de dados uno por uno con delay escalonado (la clase `revealed` + `flip-in` ya existe, solo orquestar delays).
- Dados con `.match` añaden un segundo keyframe `bounce-match` (rebote dorado).
- El dado perdido usa `animateDieCup exit` con filtro rojo progresivo en los frames finales.
- El contador numérico en la carta del perdedor cae animado al actualizarse.

---

### 10. Sonidos adicionales
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
| 3 | Rate limiting | `manager.py` | ⭐⭐ | 🔥🔥 |
| 5 | Avatar de jugador | `models.py`, `manager.py`, `app.js`, `index.html`, `style.css` | ⭐⭐ | 🔥🔥 |
| 6 | Estadísticas de jugador | `app.js`, `index.html`, `style.css` | ⭐⭐ | 🔥 |
| 7 | Límite de tiempo por turno | `models.py`, `manager.py`, `app.js`, `index.html`, `style.css` | ⭐⭐⭐ | 🔥🔥 |
| 8 | Espectadores | `models.py`, `manager.py`, `app.js`, `index.html` | ⭐⭐⭐ | 🔥🔥 |
| 9 | Animación revelación | `app.js`, `style.css` | ⭐⭐ | 🔥 |
| 10 | Sonidos adicionales | `app.js` | ⭐⭐ | 🔥 |
