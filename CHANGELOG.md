# Changelog

Todos los cambios importantes de este proyecto se documentan aqui.

Este archivo sigue una estructura inspirada en Keep a Changelog.
Como aun no hay tags de version en git, se usan versiones internas por fecha para resumir la evolucion real del proyecto.

## [0.3.6] - 2026-05-07

### Added
- Clasificación final con orden de eliminación: el backend registra en qué ronda fue eliminado cada jugador; el payload `game_over` incluye `standings` (lista ordenada); el overlay de fin de partida muestra la tabla de posiciones completa con avatar y nombre de cada jugador, resaltando al jugador local.
- Chat rápido con frases predefinidas: al pasar el cursor sobre cualquier carta de jugador (incluyendo la propia) aparece una sección de frases rápidas en el popup de emojis (¡Mentira!, Buen bluff, No te creo, etc.); al seleccionar una, aparece como burbuja temporal sobre la carta del emisor y se registra en el log de partida; los espectadores también pueden usarlas.

## [0.3.5] - 2026-05-06

### Fixed
- Kick durante turno activo: si el anfitrión expulsaba al jugador con el turno, `current_player_idx` quedaba desincronizado. Ahora se calcula el siguiente jugador antes de eliminar al kickeado y se aplica `set_current_player` tras la eliminación.
- `setTimeout` del overlay de fin de partida: el ID se guarda en `S.gameOverTimer` y se cancela al iniciar una nueva partida (`onGameStarted`) o al cerrar manualmente el overlay (`closeGameOver`), evitando que aparezca encima de una partida ya iniciada.
- Auto-apuesta por timeout: `_min_timeout_bid` ahora usa la misma cara que la apuesta actual (`current.face`) en lugar de siempre usar cara=2; si no hay apuesta activa sigue usando cara=2.
- Notificaciones de turno: (a) el modal de consentimiento ya no aparece al primer `pointerdown`/`keydown`, solo al hacer click en el ícono de campana; (b) `notification.onclick` llama `window.focus()` para traer la pestaña al frente; (c) `notification.close()` se llama en `visibilitychange` cuando la pestaña recupera el foco.
- `S.hasPassed` no se restauraba al reconectar: el payload `your_dice` enviado al reconectar ahora incluye `has_passed` calculado desde `game.passed_players`; el frontend lo aplica en `onYourDice`.
- Botón "Copiar sala": al copiar exitosamente el ícono cambia a ✓ y el texto a "Copiado" durante ~1.5s antes de volver al estado original.
- Urgencia visual en countdown de turno: con ≤10s el temporizador se vuelve rojo; con ≤5s agrega animación de pulso.
- Indicación previa de acción automática: en los últimos 3s del turno propio aparece un aviso animado ("Paso automático…" o "Apuesta automática (Cara)…") que desaparece al recibir `bid_made` o `paso_made` del servidor.
- Contador de espectadores visible en la mesa (👁 N): se actualiza en tiempo real con `spectator_joined`/`spectator_left`; el backend incluye `spectator_count` en esos eventos y en los payloads `joined`, `reconnected` y `spectator_state`.
- Vista dedicada para jugadores eliminados: al ser eliminado el jugador local, el panel de apuesta se oculta y aparece un panel "Eliminado" con aviso de espectador; se restaura al comenzar una nueva partida.

### Changed
- Eliminado soporte móvil: removidas todas las `@media` queries de breakpoint del CSS, el viewport meta usa ancho fijo `width=1280`, y los fallbacks a `window.innerWidth/Height` en animaciones reemplazados por valores fijos de desktop (1280×800).

## [0.3.4] - 2026-05-05

### Added
- Sistema de emojis lanzables entre jugadores: al pasar el cursor sobre la carta de un oponente aparece un popup con emojis seleccionables que se lanzan con una animación parabólica y rebote entre cartas.
- 23 emojis lanzables desbloqueables progresivamente por nivel (niveles 1–10), mostrados con candado y tooltip del nivel requerido si aún no están disponibles.
- Regla de sala configurable `allowEmojis` (activado por defecto) que el anfitrión puede desactivar para deshabilitar los lanzamientos de emojis en la partida.
- El backend propaga el evento `emoji` a todos los jugadores de la sala con origen, destino y el emoji elegido.
- Los modelos de `Player` y `Game` incluyen la configuración de emojis en el estado compartido.

### Changed
- El payload de `rule_config` en el backend ahora incluye el campo `allow_emojis`, sincronizado con el frontend al unirse o actualizar reglas.

## [0.3.3] - 2026-05-05

### Added
- Sistema de niveles persistido en `localStorage` (`dudoLevel`): el jugador acumula XP durante las partidas y sube de nivel progresivamente.
- Los 20 emojis del avatar picker ahora se desbloquean por nivel (del 1 al 10), ordenados de mas aburridos a mas llamativos. Los emojis bloqueados se muestran con candado, deshabilitados y con tooltip del nivel requerido.
- XP otorgado de forma incremental e inmediata (nunca se pierde si la partida no termina):
  - +1 XP por sobrevivir cada ronda.
  - +5 XP por dudo, calzo o paso correcto.
  - +1 XP por dudo, calzo o paso fallado (siempre positivo, nunca resta).
  - +10 XP al terminar una partida.
  - +20 XP adicional al ganar.
- Badge de nivel con barra de progreso XP visible en el lobby.
- El overlay de fin de partida muestra el XP ganado, si se subio de nivel y los emojis recien desbloqueados.
- Toast en partida al desbloquear un emoji nuevo sin interrumpir el flujo de juego.

## [0.3.2] - 2026-05-04

### Added
- Flujo de consentimiento para notificaciones de turno con modal explicativo previo, preferencia persistida en `localStorage` y boton de reactivacion junto al control de volumen.
- Modal de confirmacion para expulsar jugadores y accion de moderacion disponible para el anfitrion.
- Indicadores visuales mas notorios para jugadores inactivos/desconectados en lobby y mesa.
- Nueva variable `DISCONNECT_GRACE_SECONDS` para dar margen a reconexiones temporales antes de resolver una salida definitiva.
- Metadata Open Graph/Twitter dinamica por `?sala=...`, incluyendo datos de jugadores de la sala para previsualizacion al compartir en WhatsApp.

### Changed
- Selector de avatar reemplazado por un picker horizontal de emojis, expandible/contraible, sin nombres visibles y priorizando el avatar seleccionado al inicio.
- Selector de tiempo por turno cambiado de `select` a opciones inline tipo texto seleccionable.
- El sentido de ronda elegido (horario/anti-horario) ahora persiste entre rondas hasta que el primer jugador de una ronda lo cambie otra vez.
- El boton de expulsar se reubico a la izquierda del nombre del jugador y se elimino el texto visible `Dados: N` en las cartas de oponentes.

### Fixed
- Reconexion robustecida en lobby y partida usando takeover seguro del websocket aunque la desconexion anterior aun no se haya procesado completamente.
- El endpoint WebSocket ahora resuelve el `player_id` real asociado al socket para evitar desincronizacion de identidad despues de reconectar.
- En partidas de 2 jugadores (o cuando queda uno conectado), una desconexion breve ya no declara ganador inmediatamente: se espera la ventana de gracia antes de cerrar la partida.
- El countdown de reveal y la aparicion del overlay de victoria/derrota ahora respetan el `REVEAL_SECONDS` real enviado por backend.

## [0.3.1] - 2026-05-04

### Added
- Nuevo modulo `game/config.py` para centralizar configuraciones por entorno (`REVEAL_SECONDS`, `MAX_PLAYERS`, `RATE_LIMIT_MS`).
- Notificacion de turno en segundo plano en frontend, con `Notification` y parpadeo de `document.title` hasta recuperar foco.
- Reconexion de jugador en fase `lobby` usando `reconnect_id`, conservando identidad y orden original en sala.
- Rate limiting de mensajes WebSocket por jugador en backend (1 mensaje cada `RATE_LIMIT_MS`), con excepcion para `join` y `connected`.
- Avatar de jugador por emoji, con selector en lobby, persistencia local y sincronizacion en payload publico de `Player`.
- Modo espectador para entradas tardias a partidas en curso, con vista completa de mesa y bloqueo de acciones.
- Timeout de turno configurable (0/30/60/90s) con countdown en UI y acción automática conservadora en backend al expirar.
- Historial local de jugador (`dudoStats`) con modal de stats en lobby y métricas de dudo/calzo/partidas.
- Reveal mejorado con rebote para dados `.match`, salida roja progresiva en dado perdido y caída animada del contador del perdedor.
- Nuevos SFX temáticos (`roll`, `gavilan`, `eliminated`, `reconnect`, `tick`) conectados a eventos de ronda/reveal/reconexion.

### Changed
- `game/manager.py` ahora usa `MAX_PLAYERS` para validar cupo de sala y `REVEAL_SECONDS` para la espera entre rondas.
- Si el jugador reconectado en lobby corresponde al primer lugar de `player_order`, recupera el rol de anfitrion y se notifica `host_changed`.

### Docs
- `README.md` documenta las variables de entorno disponibles y sus valores por defecto.

## [0.3.0] - 2026-05-04

### Added
- Reconexion de jugadores en partidas en curso usando `reconnect_id`, con recuperacion de estado y dados al volver.
- Persistencia de sesion en frontend (`room`, `name`, `playerId`) y pre-relleno automatico del formulario de lobby.
- Guardado del nombre del jugador en tiempo real mientras se escribe.
- Soporte de URL compartible de sala (`?sala=codigo`) con pre-relleno automatico al abrir el lobby.
- Boton `Copiar` del lobby actualizado para copiar el enlace completo de invitacion (`origin + ?sala=codigo`).
- Reconexion automatica del WebSocket con backoff (1s, 2s, 4s, 8s, 16s) y banner de estado durante reintentos.
- Reglas de sala configurables desde lobby:
  - modo de resultado (`winner` o `loser`)
  - habilitar/deshabilitar Gavilan
  - permitir recuperacion de dado por Calzo en turno
- Motor de reglas por plugins (`game/rules`) para resolver comportamiento configurable sin acoplar la logica principal.
- Selector de sentido de ronda (horario/anti-horario) controlado por el primer jugador antes de su primera accion.
- Animaciones de cubiletes y visualizacion de dados perdidos en la mesa.
- Activos de marca y social sharing: `favicon.svg`, `og-cover.svg` y `og-cover.png`.
- Tooling para regenerar la portada OG (`npm run og:cover`) con `@resvg/resvg-js`.
- Mejoras visuales del lobby y mesa con iconos de Font Awesome y ayudas contextuales de reglas.

### Changed
- Flujo de estado de partida en backend para incluir reglas en eventos clave (`joined`, `game_started`, `game_over`).
- Transferencia automatica de anfitrion al desconectarse el host, promoviendo al siguiente jugador conectado y notificando `host_changed`.
- Al actualizar reglas en lobby, se reinicia el estado `ready` de todos los jugadores para evitar inicios con configuracion desincronizada.
- Se reforzo la resolucion de desafios (`dudo`/`calzo`) y el anuncio de turno con metadatos de accion activa y direccion.
- Documento de reglas (`REGLAS.md`) ampliado para cubrir personalizacion de sala, sentido de ronda y casos de desafio.

## [0.2.0] - 2026-05-02

### Added
- Sistema de sonido en frontend para eventos del juego.
- Boton de mute/unmute con estado persistido en `localStorage`.
- Badges de accion para destacar jugadas de tipo DUDO y CALZO.

### Changed
- Ajustes de estado de juego para soportar feedback visual y flujo de acciones con mayor claridad durante la ronda.

## [0.1.0] - 2026-04-06

### Added
- Base del proyecto Dudo con backend en FastAPI y comunicacion en tiempo real por WebSocket.
- Servicio de frontend estatico (`index.html`, `style.css`, `app.js`) desde FastAPI.
- Modelo de juego inicial con sala, jugadores, turnos, apuestas, paso, dudo y calzo.
- Logica de dados, validacion de apuestas y resolucion de rondas en backend.
- Reglas iniciales del juego documentadas en `REGLAS.md`.
- Archivo de pruebas manuales HTTP (`test_main.http`) y dependencias base en `requirements.txt`.

### Docs
- Se agrego `README.md` con stack, instalacion, ejecucion y uso del proyecto.

