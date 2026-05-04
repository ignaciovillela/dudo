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

## 🟡 Prioridad media

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
| 6 | Estadísticas de jugador | `app.js`, `index.html`, `style.css` | ⭐⭐ | 🔥 |
| 9 | Animación revelación | `app.js`, `style.css` | ⭐⭐ | 🔥 |
| 10 | Sonidos adicionales | `app.js` | ⭐⭐ | 🔥 |
