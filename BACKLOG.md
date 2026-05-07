# Dudo — Backlog de mejoras

Ordenado por impacto/dificultad. Prioridad alta primero; dentro de la misma prioridad, lo más fácil primero.

## Mantenimiento del backlog

Al implementar una mejora, eliminarla de este backlog y registrarla en `CHANGELOG.md` (version/fecha correspondiente).

### Cómo agregar nuevas mejoras

- Crear el item en la sección de prioridad correspondiente (`🔴 Alta` o `🟡 Media`; si agregas baja, crear `🟢 Baja`).
- Mantener este formato mínimo por mejora:

```markdown
### N. Título corto
**Por qué:** problema o valor que resuelve en 1-2 líneas.
- Alcance técnico (backend/frontend).
- Archivos principales a tocar.
- Dificultad estimada (`Baja` / `Media` / `Alta`).
- Riesgo de implementación (`Bajo` / `Medio` / `Alto`).
- Dependencias: #X, #Y (opcional).
- Criterio de término (cómo validar que quedó listo).
```

- Ordenar dentro de cada prioridad por **impacto primero**, **dificultad después** y **riesgo como desempate**.
- Actualizar la tabla de `## Resumen` al agregar/quitar una mejora, incluyendo riesgo y dificultad.
- Cuando se implemente: 1) eliminarla del backlog, 2) registrar el cambio en `CHANGELOG.md`.

## Implementado recientemente (resumen)

Referencia completa en `CHANGELOG.md`.

- URL compartible por `?sala=codigo`.
- Transferencia automática de anfitrión.
- Reconexión automática con backoff.
- Eliminar soporte móvil (viewport fijo, sin @media queries de breakpoint).
- Fix: kick durante turno activo corrompe orden de turno.
- Fix: setTimeout del overlay de fin de partida no era cancelable.
- Fix: auto-apuesta por timeout siempre usaba cara=2.
- Fix: mejoras al sistema de notificaciones de turno.
- Fix: `S.hasPassed` no se restauraba al reconectar.
- UX: botón "Copiar sala" con confirmación visual (checkmark ~1.5s).
- UX: urgencia visual en el countdown de turno (rojo ≤10s, pulso ≤5s).
- UX: indicación previa de acción automática por timeout (aviso ≤3s).
- Contador de espectadores visible en la mesa en tiempo real.
- Vista dedicada para jugadores eliminados (panel de acciones reemplazado por mensaje de espectador).
- Clasificación final con orden de eliminación en overlay de game over.
- Chat rápido con frases predefinidas desde el popup de emojis.
- Espectadores interactivos: emojis y frases rápidas disponibles para espectadores.
- Rachas: badge 🔥N en cartas y resumen en overlay de game over.
- Sonido al recibir un emoji (SFX.emojiHit).
- Logros: catálogo de 10 logros con modal y toast de desbloqueo.
- Sonido direccional con pan estéreo basado en posición de la carta en la mesa.
- Indicador de probabilidad estimada de la apuesta actual en el bid builder.

---

## 🔴 Alta prioridad

### 4. Fix: desconexión durante el turno activo congela la partida [no aplicar aún, se debe revisar bien el alcance]
**Por qué:** cuando el jugador activo se desconecta, `active_players()` lo excluye y `current_player_id()` retorna al siguiente jugador, pero nunca se llama `_announce_turn`. Los demás jugadores no reciben anuncio de turno y la partida queda congelada visualmente hasta que el timeout expira.
- Alcance técnico: backend.
- Archivos principales: `game/manager.py` (función `disconnect`, ~línea 772).
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: al desconectarse el jugador activo durante una partida, el siguiente jugador recibe inmediatamente el mensaje `turn`.

### 18. Total de dados coincidentes visible en el reveal
**Por qué:** durante los 7 segundos de revelación no se muestra cuántos dados de la cara apostada había en total en la mesa. Esa información existe en el payload `reveal` pero no se resume en ningún lugar visible.
- Alcance técnico: frontend.
- Archivos principales: `static/app.js` (función `onReveal`), `static/index.html`, `static/style.css`.
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: durante el reveal se muestra un resumen del tipo "Había 7 🎲5 en la mesa (se apostaron 8)"; el número de dados coincidentes y el total apostado son visibles durante toda la fase de revelación.

---

## 🟡 Prioridad media

### 8. UX: indicador de carga al unirse a una sala [revisar si es necesario, podría ser que el proceso de unirse es tan rápido que no vale la pena]
**Por qué:** entre hacer click en "Unirse" y recibir la respuesta `joined` del servidor, la UI no da ningún feedback. En conexiones lentas el usuario no sabe si algo está pasando.
- Alcance técnico: frontend.
- Archivos principales: `static/app.js`, `static/index.html`, `static/style.css`.
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: el botón "Unirse" muestra un estado de carga (texto o spinner) desde el click hasta recibir `joined` o error; se deshabilita para evitar doble envío.

### 11. Fix: cap en cantidad apostada (cliente y servidor) [revisar, podría ser bueno solo limitar el máximo ej: 100]
**Por qué:** no hay límite superior en la cantidad de la apuesta. Un cliente puede enviar `quantity: 9999999`; el servidor lo acepta porque solo valida que sea ≥ 1 y mayor a la apuesta anterior.
- Alcance técnico: frontend + backend.
- Archivos principales: `static/app.js` (función `adjBid`), `game/models.py` (función `is_valid_bid`).
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: el stepper de cantidad en el cliente tiene un máximo de `total_dados`; el backend rechaza apuestas con `quantity > total_dados` con mensaje de error.

### 22. Bots
**Por qué:** permite jugar cuando no hay suficientes amigos disponibles, o para practicar.
- Alcance técnico: backend.
- Archivos principales: `game/manager.py`, `game/models.py`, nuevo `game/bot.py`.
- Dificultad estimada: `Alta`.
- Riesgo de implementación: `Medio`.
- Notas de implementación: la lógica no necesita modelar probabilidades completas. Basta con: si la apuesta actual está cerca de la estimación del bot → subir o aceptar; si la apuesta parece muy alta → dudar; agregar ruido aleatorio calibrado para que el bot sea entretenido, no óptimo. Los bots demasiado "correctos" dejan de ser divertidos.
- Criterio de término: el anfitrión puede añadir slots de bot desde el lobby (hasta completar `MAX_PLAYERS`); el bot toma decisiones basadas en sus propios dados y la apuesta actual con algo de aleatoriedad; tiene nombre, avatar y aparece como jugador normal en la UI.

### 23. Highlights de partida
**Por qué:** al terminar la partida, mostrar los momentos más destacados (el bluff más arriesgado, el dudo más preciso, la apuesta más alta) genera conversación y replayability social.
- Alcance técnico: backend + frontend.
- Archivos principales: `game/manager.py`, `static/app.js`, `static/index.html`.
- Dificultad estimada: `Alta`.
- Riesgo de implementación: `Medio`.
- Dependencias: #17 (clasificación final; comparten el overlay de game over).
- Criterio de término: el backend registra eventos destacados durante la partida (apuesta más alta, calzo exacto, dudo más ajustado, bluff más audaz); el payload `game_over` incluye una lista de highlights; el overlay de fin de partida muestra una sección "Momentos de la partida" con estos eventos.

---

## 🟢 Prioridad baja

### 24. Limpieza: eliminar CSS muerto
**Por qué:** hay reglas CSS de sistemas anteriores que ya no se usan (`.emoji-picker-popup`, `.emoji-bar`, `.lost-dice-row`), generando ruido en el archivo.
- Alcance técnico: frontend.
- Archivos principales: `static/style.css` (~líneas 1094–1100 y 1551–1568).
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: los selectores eliminados no aparecen en ningún HTML ni JS del proyecto; el CSS compila sin cambios visuales.

### 25. Modal de reglas accesible desde la partida
**Por qué:** no hay forma de consultar las reglas una vez que empieza la partida. Los jugadores nuevos quedan perdidos sin poder salir de la vista de juego.
- Alcance técnico: frontend.
- Archivos principales: `static/index.html`, `static/app.js`, `static/style.css`.
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: hay un botón `?` visible durante la partida que abre un modal con las reglas resumidas (acciones válidas, escalación de apuestas, resolución de retos); el modal se cierra sin afectar el estado del juego.

### 26. Confirmación en acción "Dudo" [no implementar, revisar como no hacerlo molesto]
**Por qué:** un click accidental en "Dudo!" resulta en perder un dado sin posibilidad de corrección. Es la acción más irreversible del juego.
- Alcance técnico: frontend.
- Archivos principales: `static/app.js`, `static/index.html`, `static/style.css`.
- Dificultad estimada: `Baja`.
- Riesgo de implementación: `Bajo`.
- Criterio de término: el botón "Dudo!" requiere doble click o una confirmación rápida (ej. mantener presionado 0.5s o un segundo click en un overlay mini); configurable por el jugador desde el lobby.

### 27. Variante: ronda Obligo (o Palifico) (1 dado, sin comodines)
**Por qué:** cuando un jugador llega a exactamente 1 dado por primera vez, en la variante clásica los Ases dejan de ser comodines esa ronda. Es una regla ampliamente conocida que cambia la estrategia en momentos críticos.
- Alcance técnico: backend + frontend.
- Archivos principales: `game/models.py` (`count_dice`), `game/rules/`, `static/app.js`, `static/index.html`.
- Dificultad estimada: `Media`.
- Riesgo de implementación: `Medio`.
- Criterio de término: existe una opción `Obligo` (o `palifico`) en `RuleConfig`; cuando está activo y un jugador tiene exactamente 1 dado (solo la primera vez de cada jugador), el backend usa un conteo sin comodines, la pinta (cara del dado) no se puede cambiar salvo por otro jugador con un dado; el frontend indica visualmente que la ronda es Obligada.

### 29. Variante: dados iniciales configurables
**Por qué:** el conteo inicial de 5 dados está hardcodeado. Partidas con 3 o 4 dados son más rápidas; con 6 son más largas. Es una variante común para controlar la duración.
- Alcance técnico: backend + frontend.
- Archivos principales: `game/models.py`, `game/manager.py` (`_begin_game`), `game/rules/`, `static/index.html`, `static/app.js`.
- Dificultad estimada: `Media`.
- Riesgo de implementación: `Medio`.
- Criterio de término: el anfitrión puede elegir entre 3, 4, 5 o 6 dados iniciales desde el panel de reglas del lobby; el backend usa ese valor al iniciar la partida y lo incluye en el payload de `game_started`.

---

## Resumen

| # | Mejora | Archivos afectados | Dificultad | Riesgo | Impacto |
|---|--------|--------------------|------------|--------|---------|
| 4 | Fix: desconexión congela turno activo | `manager.py` | Baja | Bajo | Alto |
| 18 | Total de dados coincidentes en el reveal | `app.js`, `index.html`, `style.css` | Baja | Bajo | Alto |
| 8 | UX: indicador de carga al unirse | `app.js`, `index.html`, `style.css` | Baja | Bajo | Medio |
| 11 | Fix: cap en cantidad apostada | `app.js`, `models.py` | Baja | Bajo | Bajo |
| 22 | Bots | `manager.py`, `models.py`, `bot.py` | Alta | Medio | Alto |
| 23 | Highlights de partida | `manager.py`, `app.js`, `index.html` | Alta | Medio | Medio |
| 24 | Limpieza: eliminar CSS muerto | `style.css` | Baja | Bajo | Bajo |
| 25 | Modal de reglas en partida | `index.html`, `app.js`, `style.css` | Baja | Bajo | Bajo |
| 26 | Confirmación en acción "Dudo" | `app.js`, `index.html`, `style.css` | Baja | Bajo | Bajo |
| 27 | Variante: ronda Palifico | `models.py`, `rules/`, `app.js`, `index.html` | Media | Medio | Bajo |
| 29 | Variante: dados iniciales configurables | `models.py`, `manager.py`, `index.html`, `app.js` | Media | Medio | Bajo |
