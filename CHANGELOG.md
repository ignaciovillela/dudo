# Changelog

Todos los cambios importantes de este proyecto se documentan aqui.

Este archivo sigue una estructura inspirada en Keep a Changelog.
Como aun no hay tags de version en git, se usan versiones internas por fecha para resumir la evolucion real del proyecto.

## [0.3.1] - 2026-05-04

### Added
- Nuevo modulo `game/config.py` para centralizar configuraciones por entorno (`REVEAL_SECONDS`, `MAX_PLAYERS`, `RATE_LIMIT_MS`).
- Notificacion de turno en segundo plano en frontend, con `Notification` y parpadeo de `document.title` hasta recuperar foco.
- Reconexion de jugador en fase `lobby` usando `reconnect_id`, conservando identidad y orden original en sala.
- Rate limiting de mensajes WebSocket por jugador en backend (1 mensaje cada `RATE_LIMIT_MS`), con excepcion para `join` y `connected`.
- Avatar de jugador por emoji, con selector en lobby, persistencia local y sincronizacion en payload publico de `Player`.
- Modo espectador para entradas tardias a partidas en curso, con vista completa de mesa y bloqueo de acciones.

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

