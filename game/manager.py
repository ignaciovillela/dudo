import asyncio
import json
import logging
import pathlib
import random
import time
import uuid

from fastapi import WebSocket

from game.config import DISCONNECT_GRACE_SECONDS, MAX_PLAYERS, RATE_LIMIT_MS, REVEAL_SECONDS
from game.models import Bid, Game, Player, RuleConfig
from game.rules import RuleEngine
from game.actions import CalzoAction, DudoAction, DudoBidResult, DudoPasoResult
import game.bot as bot_engine
from game.db import get_pool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XP constants
# ---------------------------------------------------------------------------
_XP_WIN = 50
_XP_PARTICIPATION = 10
_XP_PER_POSITION = 5   # extra XP for finishing higher (2nd gets 1×, 3rd gets 0×…)


async def _retrain_model(pool) -> None:
    """Re-entrena el BluffModel con todos los datos actuales de la DB."""
    from game.player_model import bluff_model
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT anon_id, face, qty_bucket, bids_total, bids_bluff "
                "FROM player_bid_stats"
            )
        bluff_model.retrain([dict(r) for r in rows])
    except Exception as exc:
        log.warning("[db] retrain failed: %s", exc)

# Fuente de verdad compartida con el cliente: static/emojis.json
_EMOJIS_PATH = pathlib.Path(__file__).parent.parent / "static" / "emojis.json"
ALLOWED_EMOJIS: frozenset[str] = frozenset(
    item["emoji"] for item in json.loads(_EMOJIS_PATH.read_text(encoding="utf-8"))
)

ALLOWED_AVATARS = {
    "🎲", "🦅", "🐺", "🦁", "🐯", "🦊", "💀", "👑", "🎭", "🃏",
    "🏹", "⚔️", "🛡️", "🌙", "⚡", "🔥", "💎", "🎯", "🍀", "🎪",
}


class GameManager:
    def __init__(self):
        self.games: dict[str, Game] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.hosts: dict[str, str] = {}
        self.last_message_at: dict[str, float] = {}
        self.turn_timeout_tasks: dict[str, asyncio.Task] = {}
        self.disconnect_resolution_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.turn_started_at: dict[str, float] = {}   # room_id → monotonic timestamp

    # ------------------------------------------------------------------ connect

    async def connect(self, websocket: WebSocket, room_id: str, player_id: str):
        await websocket.accept()
        self.games.setdefault(room_id, Game(room_id=room_id))
        self.connections.setdefault(room_id, {})[player_id] = websocket
        await self._send(room_id, player_id, {
            "type": "connected",
            "player_id": player_id,
            "room_id": room_id,
        })

    def resolve_player_id(self, room_id: str, websocket: WebSocket) -> str | None:
        for pid, ws in self.connections.get(room_id, {}).items():
            if ws is websocket:
                return pid
        return None

    async def disconnect(self, room_id: str, player_id: str):
        self.connections.get(room_id, {}).pop(player_id, None)
        self.last_message_at.pop(player_id, None)
        game = self.games.get(room_id)

        # Liberar sala si no quedan conexiones activas
        if not self.connections.get(room_id):
            self._cancel_turn_timeout(room_id)
            self._cancel_disconnect_resolution_for_room(room_id)
            self.games.pop(room_id, None)
            self.connections.pop(room_id, None)
            self.hosts.pop(room_id, None)
            return

        if not game:
            return

        if player_id in game.spectators:
            spectator_name = game.spectators.pop(player_id, "Espectador")
            await self._broadcast(room_id, {
                "type": "spectator_left",
                "spectator_id": player_id,
                "spectator_name": spectator_name,
                "spectator_count": len(game.spectators),
            })
            return

        if player_id not in game.players:
            return

        player = game.players[player_id]
        player.connected = False
        previous_host_id = self._host_id(room_id, game)

        host_changed_msg = None
        if previous_host_id == player_id:
            new_host_id = self._pick_connected_host(game)
            if new_host_id:
                self.hosts[room_id] = new_host_id
                host_changed_msg = {
                    "type": "host_changed",
                    "new_host_id": new_host_id,
                    "new_host_name": game.players[new_host_id].name,
                }
            else:
                self.hosts.pop(room_id, None)

        await self._broadcast(room_id, {
            "type": "player_disconnected",
            "player_id": player_id,
            "player_name": player.name,
        })

        if host_changed_msg:
            await self._broadcast(room_id, host_changed_msg)

        if game.phase == "playing":
            self._schedule_disconnect_resolution(room_id, player_id)

    # ------------------------------------------------------------------ dispatch

    async def handle_message(self, room_id: str, player_id: str, msg: dict):
        game = self.games.get(room_id)
        if not game:
            return
        msg_type = msg.get("type")
        _spectator_allowed = {"join", "emoji", "quick_chat", "become_player"}
        # El host conserva privilegios aunque sea espectador en el lobby
        if player_id in game.spectators and game.phase == "lobby" and self._host_id(room_id, game) == player_id:
            _spectator_allowed |= {"set_rules", "kick_player", "add_bot", "remove_bot", "start"}
        if player_id in game.spectators and msg_type not in _spectator_allowed:
            return
        if msg_type not in {"join", "connected", "select_bid", "become_spectator", "become_player", "add_bot", "remove_bot", "leave", "reorder"} and not self._allow_message(player_id):
            return
        handlers = {
            "join":      self._h_join,
            "ready":     self._h_ready,
            "start":     self._h_start,
            "set_rules": self._h_set_rules,
            "kick_player": self._h_kick_player,
            "leave":     self._h_leave,
            "reorder":   self._h_reorder,
            "rename":    self._h_rename,
            "add_bot":   self._h_add_bot,
            "remove_bot": self._h_remove_bot,
            "become_spectator": self._h_become_spectator,
            "become_player":    self._h_become_player,
            "direction": self._h_direction,
            "bid":       self._h_bid,
            "select_bid": self._h_select_bid,
            "paso":      self._h_paso,
            "dudo":      self._h_dudo,
            "calzo":     self._h_calzo,
            "emoji":     self._h_emoji,
            "quick_chat": self._h_quick_chat,
        }
        handler = handlers.get(msg_type)
        if handler:
            await handler(room_id, player_id, game, msg)

    def _allow_message(self, player_id: str) -> bool:
        if RATE_LIMIT_MS <= 0:
            return True
        now = time.monotonic()
        min_interval = RATE_LIMIT_MS / 1000
        last = self.last_message_at.get(player_id)
        if last is not None and (now - last) < min_interval:
            return False
        self.last_message_at[player_id] = now
        return True

    @staticmethod
    def _normalize_avatar(value) -> str:
        if isinstance(value, str) and value in ALLOWED_AVATARS:
            return value
        return "🎲"

    # ------------------------------------------------------------------ handlers

    async def _h_join(self, room_id, player_id, game, msg):
        # ── Intento de reconexión ─────────────────────────────────────────────
        reconnect_id = msg.get("reconnect_id")
        if reconnect_id and reconnect_id in game.spectators:
            old_name = game.spectators[reconnect_id]
            ws = self.connections[room_id].pop(player_id, None)
            if ws:
                self.connections[room_id][reconnect_id] = ws
            game.spectators[reconnect_id] = old_name
            await self._send(room_id, reconnect_id, {
                "type": "joined_spectator",
                "spectator_id": reconnect_id,
                "spectator_name": old_name,
                **self._spectator_state_payload(game),
            })
            return

        if reconnect_id and reconnect_id in game.players and game.phase in {"playing", "lobby"}:
            old = game.players[reconnect_id]
            # Permitir takeover incluso si aún figura conectado (carrera de desconexión).
            ws = self.connections[room_id].pop(player_id, None)
            if ws:
                self.connections[room_id][reconnect_id] = ws
            old.connected = True
            self._cancel_disconnect_resolution(room_id, reconnect_id)

            host_changed_msg = None
            if game.phase == "lobby" and game.player_order and game.player_order[0] == reconnect_id:
                if self.hosts.get(room_id) != reconnect_id:
                    self.hosts[room_id] = reconnect_id
                    host_changed_msg = {
                        "type": "host_changed",
                        "new_host_id": reconnect_id,
                        "new_host_name": old.name,
                    }

            await self._send(room_id, reconnect_id, {
                "type": "reconnected",
                "player_id": reconnect_id,
                "host_id": self._host_id(room_id, game),
                "is_host": self._host_id(room_id, game) == reconnect_id,
                "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
                "player_order": game.player_order,
                "phase": game.phase,
                "rules": game.rules.to_dict(),
                "spectator_count": len(game.spectators),
            })
            await self._broadcast_except(room_id, reconnect_id, {
                "type": "player_reconnected",
                "player_id": reconnect_id,
                "player_name": old.name,
            })

            if host_changed_msg:
                await self._broadcast(room_id, host_changed_msg)

            if game.phase == "playing":
                # Reenviar estado actual de la partida al jugador reconectado
                await self._send(room_id, reconnect_id, {
                    "type": "your_dice",
                    "dice": old.dice,
                    "round_number": game.round_number,
                    "total_dice": game.total_dice(),
                    "players": {p: pl.to_public_dict() for p, pl in game.players.items()},
                    "has_passed": reconnect_id in game.passed_players,
                })
                await self._announce_turn(room_id, game)
            return

        if game.phase == "lobby" and player_id in game.spectators:
            game.spectators.pop(player_id, None)

        # ── Unirse nuevo ──────────────────────────────────────────────────────
        if game.phase != "lobby":
            spectator_name = (msg.get("name") or "Espectador").strip()[:20] or "Espectador"
            game.spectators[player_id] = spectator_name
            await self._send(room_id, player_id, {
                "type": "joined_spectator",
                "spectator_id": player_id,
                "spectator_name": spectator_name,
                **self._spectator_state_payload(game),
            })
            await self._broadcast_except(room_id, player_id, {
                "type": "spectator_joined",
                "spectator_id": player_id,
                "spectator_name": spectator_name,
                "spectator_count": len(game.spectators),
            })
            return
        # Sin límite de jugadores en el join del lobby: el límite se aplica al iniciar partida.
        # Permite que espectadores pasen a jugadores libremente hasta que empiece el juego.

        name = (msg.get("name") or f"Jugador {len(game.players) + 1}").strip()[:20]
        avatar = self._normalize_avatar(msg.get("avatar"))
        anon_id = msg.get("anon_id") or None
        player = Player(id=player_id, name=name, avatar=avatar, anon_id=anon_id)
        game.players[player_id] = player
        game.player_order.append(player_id)
        if room_id not in self.hosts or self.hosts[room_id] not in game.players:
            self.hosts[room_id] = game.player_order[0]

        await self._send(room_id, player_id, {
            "type": "joined",
            "player_id": player_id,
            "host_id": self._host_id(room_id, game),
            "is_host": self._host_id(room_id, game) == player_id,
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
            "player_order": game.player_order,
            "rules": game.rules.to_dict(),
            "spectator_count": len(game.spectators),
        })
        await self._broadcast_except(room_id, player_id, {
            "type": "player_joined",
            "player": player.to_public_dict(),
        })

    async def _h_ready(self, room_id, player_id, game, msg):
        if player_id not in game.players:
            return
        game.players[player_id].ready = not game.players[player_id].ready
        await self._broadcast(room_id, {
            "type": "player_ready",
            "player_id": player_id,
            "ready": game.players[player_id].ready,
        })
        if game.all_ready():
            await self._broadcast(room_id, {
                "type": "all_ready",
            })

    async def _h_rename(self, room_id, player_id, game, msg):
        if player_id not in game.players or game.phase != "lobby":
            return
        player = game.players[player_id]
        new_name = (msg.get("name") or player.name).strip()[:20] or player.name
        new_avatar = self._normalize_avatar(msg.get("avatar")) if msg.get("avatar") else player.avatar
        player.name = new_name
        player.avatar = new_avatar
        await self._broadcast(room_id, {
            "type": "player_renamed",
            "player_id": player_id,
            "name": new_name,
            "avatar": new_avatar,
        })

    async def _h_start(self, room_id, player_id, game, msg):
        if self._host_id(room_id, game) != player_id:
            return
        connected = [p for p in game.players.values() if p.connected and not p.is_bot]
        bots = [p for p in game.players.values() if p.is_bot]
        active = connected + bots
        if len(active) < 2:
            return
        if len(active) > MAX_PLAYERS:
            return await self._send(room_id, player_id, {
                "type": "error",
                "message": f"Demasiados jugadores para iniciar (máx. {MAX_PLAYERS}). Algunos deben pasarse a espectadores.",
            })
        await self._begin_game(room_id, game)

    async def _h_set_rules(self, room_id, player_id, game, msg):
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo puedes cambiar reglas en el lobby"})
        is_host = self._host_id(room_id, game) == player_id
        if not is_host:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo el anfitrión puede cambiar reglas"})

        if game.players.get(player_id) and game.players[player_id].ready:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Cancela tu listo antes de cambiar reglas"})

        game.rules = RuleConfig.from_payload(msg.get("rules"), game.rules)
        # Resetear estado "listo" de todos al cambiar reglas
        for player in game.players.values():
            player.ready = False
        await self._broadcast(room_id, {
            "type": "rules_updated",
            "rules": game.rules.to_dict(),
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
        })

    async def _h_kick_player(self, room_id, player_id, game, msg):
        is_host = self._host_id(room_id, game) == player_id
        if not is_host:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo el anfitrión puede expulsar jugadores"})

        target_id = msg.get("target_id")
        if not isinstance(target_id, str):
            return
        if target_id == player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No puedes expulsarte a ti mismo"})

        target = game.players.get(target_id)
        if not target:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Jugador no encontrado"})

        self._cancel_disconnect_resolution(room_id, target_id)

        # Calcular antes de eliminar si el kickeado tiene el turno activo
        was_current = game.phase == "playing" and game.current_player_id() == target_id
        if was_current:
            game.advance_turn()
            next_player_id = game.current_player_id()
            # Restaurar idx para que apunte al kickeado mientras aún existe (se corregirá tras el del)
            game.set_current_player(target_id)

        await self._send(room_id, target_id, {
            "type": "kicked",
            "message": "El anfitrión te expulsó de la sala",
        })
        ws = self.connections.get(room_id, {}).pop(target_id, None)
        if ws:
            try:
                await ws.close(code=1000)
            except Exception:
                pass

        del game.players[target_id]
        if target_id in game.player_order:
            game.player_order.remove(target_id)

        await self._broadcast(room_id, {
            "type": "player_kicked",
            "player_id": target_id,
            "player_name": target.name,
            "kicked_by_id": player_id,
            "kicked_by_name": (game.players[player_id].name if player_id in game.players
                               else game.spectators.get(player_id, "Anfitrión")),
        })

        if game.phase == "playing":
            outcome = self._rules_engine(game).resolve_outcome(game, target_id)
            if outcome:
                return await self._end_game(room_id, game, outcome)
            # Si el kickeado era el jugador activo, ajustar el índice al siguiente jugador
            if was_current:
                game.set_current_player(next_player_id)
            await self._announce_turn(room_id, game)

    async def _h_add_bot(self, room_id, player_id, game, msg):
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo se pueden agregar bots en el lobby"})
        if self._host_id(room_id, game) != player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo el anfitrión puede agregar bots"})
        if len(game.players) >= MAX_PLAYERS:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": f"Sala llena (máx. {MAX_PLAYERS})"})

        difficulty = msg.get("difficulty", "medium")
        if difficulty not in {"easy", "medium", "hard", "expert"}:
            difficulty = "medium"

        bot_names = {
            "easy":      ["Botín", "Novato", "Pipón", "Torpe"],
            "medium":    ["Calculín", "Medio", "Astuto", "Listo"],
            "hard":      ["Maestro", "Genio", "Experto", "HAL"],
            "expert": ["Oráculo", "Némesis", "Profeta", "Centinela"],
        }
        existing_bot_names = {p.name for p in game.players.values() if p.is_bot}
        candidates = [n for n in bot_names[difficulty] if n not in existing_bot_names]
        name = random.choice(candidates) if candidates else f"Bot-{difficulty[:1].upper()}{len(game.players)}"

        bot_avatars = ["🤖", "👾", "🎮", "🧠", "⚙️"]
        used_avatars = {p.avatar for p in game.players.values() if p.is_bot}
        free_avatars = [a for a in bot_avatars if a not in used_avatars]
        avatar = random.choice(free_avatars) if free_avatars else "🤖"

        bot_id = f"bot-{uuid.uuid4().hex[:8]}"
        bot_player = Player(
            id=bot_id,
            name=name,
            avatar=avatar,
            is_bot=True,
            bot_difficulty=difficulty,
            ready=True,  # los bots siempre están listos
        )
        game.players[bot_id] = bot_player
        game.player_order.append(bot_id)

        await self._broadcast(room_id, {
            "type": "player_joined",
            "player": bot_player.to_public_dict(),
        })
        await self._broadcast(room_id, {
            "type": "player_ready",
            "player_id": bot_id,
            "ready": True,
        })
        if game.all_ready():
            await self._broadcast(room_id, {"type": "all_ready"})

    async def _h_remove_bot(self, room_id, player_id, game, msg):
        if game.phase != "lobby":
            return
        if self._host_id(room_id, game) != player_id:
            return

        target_id = msg.get("target_id")
        if not isinstance(target_id, str):
            return
        target = game.players.get(target_id)
        if not target or not target.is_bot:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Ese jugador no es un bot"})

        del game.players[target_id]
        if target_id in game.player_order:
            game.player_order.remove(target_id)

        await self._broadcast(room_id, {
            "type": "player_kicked",
            "player_id": target_id,
            "player_name": target.name,
            "kicked_by_id": player_id,
            "kicked_by_name": (game.players[player_id].name if player_id in game.players
                               else game.spectators.get(player_id, "Anfitrión")),
        })

    async def _h_become_spectator(self, room_id, player_id, game, msg):
        """Un jugador en el lobby decide pasarse a espectador.
        El host conserva su liderazgo aunque pase a espectador."""
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo puedes cambiar de rol en el lobby"})
        if player_id not in game.players:
            return

        player = game.players[player_id]
        spectator_name = player.name

        # Eliminar de jugadores sin tocar self.hosts: el host conserva el liderazgo
        del game.players[player_id]
        if player_id in game.player_order:
            game.player_order.remove(player_id)
        game.spectators[player_id] = spectator_name

        # Notificar al propio jugador su nuevo estado
        await self._send(room_id, player_id, {
            "type": "became_spectator",
            "spectator_id": player_id,
            "spectator_name": spectator_name,
            "host_id": self._host_id(room_id, game),
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
            "player_order": game.player_order,
            "spectator_count": len(game.spectators),
        })
        # Notificar al resto
        await self._broadcast_except(room_id, player_id, {
            "type": "player_kicked",
            "player_id": player_id,
            "player_name": spectator_name,
            "became_spectator": True,
            "kicked_by_id": player_id,
            "kicked_by_name": spectator_name,
        })
        await self._broadcast(room_id, {
            "type": "spectator_joined",
            "spectator_id": player_id,
            "spectator_name": spectator_name,
            "spectator_count": len(game.spectators),
        })

    async def _h_become_player(self, room_id, player_id, game, msg):
        """Un espectador en el lobby decide unirse como jugador."""
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo puedes cambiar de rol en el lobby"})
        if player_id not in game.spectators:
            return

        spectator_name = game.spectators.pop(player_id)
        player = Player(id=player_id, name=spectator_name, avatar=self._normalize_avatar(msg.get("avatar")))
        game.players[player_id] = player
        game.player_order.append(player_id)

        if room_id not in self.hosts or self.hosts[room_id] not in game.players:
            self.hosts[room_id] = game.player_order[0]

        await self._send(room_id, player_id, {
            "type": "became_player",
            "player_id": player_id,
            "host_id": self._host_id(room_id, game),
            "is_host": self._host_id(room_id, game) == player_id,
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
            "player_order": game.player_order,
            "rules": game.rules.to_dict(),
            "spectator_count": len(game.spectators),
        })
        await self._broadcast_except(room_id, player_id, {
            "type": "player_joined",
            "player": player.to_public_dict(),
        })
        await self._broadcast(room_id, {
            "type": "spectator_left",
            "spectator_id": player_id,
            "spectator_name": spectator_name,
            "spectator_count": len(game.spectators),
        })

    async def _h_leave(self, room_id, player_id, game, msg):
        """El jugador abandona la sala voluntariamente (solo en lobby)."""
        if game.phase != "lobby":
            return
        if player_id not in game.players:
            return

        player = game.players[player_id]
        was_host = self._host_id(room_id, game) == player_id

        # Limpiar conexión y datos del jugador
        ws = self.connections.get(room_id, {}).pop(player_id, None)
        del game.players[player_id]
        if player_id in game.player_order:
            game.player_order.remove(player_id)

        # Notificar al jugador que salió
        if ws:
            try:
                await ws.close(code=1000)
            except Exception:
                pass

        # Si era el host, reasignar
        new_host_msg = None
        if was_host and game.player_order:
            new_host_id = game.player_order[0]
            self.hosts[room_id] = new_host_id
            new_host_msg = {
                "type": "new_host",
                "new_host_id": new_host_id,
                "new_host_name": game.players[new_host_id].name,
            }

        await self._broadcast(room_id, {
            "type": "player_left",
            "player_id": player_id,
            "player_name": player.name,
            "player_order": game.player_order,
        })
        if new_host_msg:
            await self._broadcast(room_id, new_host_msg)

    async def _h_reorder(self, room_id, player_id, game, msg):
        """Reordena jugadores en el lobby via drag & drop."""
        if game.phase != "lobby":
            return
        if player_id not in game.players:
            return

        new_order = msg.get("order")
        if not isinstance(new_order, list):
            return

        is_host = self._host_id(room_id, game) == player_id

        if is_host:
            # El líder puede reordenar a todos: validar que sea permutación exacta
            if set(new_order) != set(game.player_order) or len(new_order) != len(game.player_order):
                return
            game.player_order = new_order
        else:
            # No-líder: solo puede mover su propia posición
            # new_order debe contener exactamente a player_id en una posición diferente
            # y el resto en el mismo orden relativo
            current = game.player_order
            if set(new_order) != set(current) or len(new_order) != len(current):
                return
            # Verificar que solo player_id cambió de posición (los demás mantienen orden relativo)
            others_current = [p for p in current if p != player_id]
            others_new = [p for p in new_order if p != player_id]
            if others_current != others_new:
                return
            game.player_order = new_order

        await self._broadcast(room_id, {
            "type": "reordered",
            "player_order": game.player_order,
        })

    async def _h_direction(self, room_id, player_id, game, msg):
        """Solo el primer jugador de la ronda puede cambiar sentido, y solo antes de su primera acción."""
        if game.phase != "playing":
            return
        if player_id != game.round_first_player:
            return
        if game.current_bid is not None or game.last_paso is not None:
            return  # ya se hizo alguna acción, sentido bloqueado
        value = msg.get("value")
        if value not in ("cw", "ccw"):
            return
        game.direction = 1 if value == "cw" else -1
        await self._broadcast(room_id, {
            "type": "direction_set",
            "direction": value,
            "player_id": player_id,
            "player_name": game.players[player_id].name,
        })

    async def _h_bid(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        if game.current_player_id() != player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No es tu turno"})
        elapsed = time.monotonic() - self.turn_started_at.get(room_id, time.monotonic())
        self._cancel_turn_timeout(room_id)
        try:
            bid = Bid(
                quantity=int(msg["quantity"]),
                face=int(msg["face"]),
                player_id=player_id,
                player_name=game.players[player_id].name,
                elapsed_seconds=round(elapsed, 3),
            )
        except (KeyError, ValueError, TypeError):
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Apuesta inválida"})

        if not game.is_valid_bid(bid):
            return await self._send(room_id, player_id,
                                    {"type": "error",
                                     "message": "La apuesta debe ser mayor a la anterior"})

        game.current_bid = bid
        game.last_paso = None  # la apuesta reemplaza al paso como acción activa
        game.bid_history.append(bid)
        game.advance_turn()

        await self._broadcast(room_id, {"type": "bid_made", "bid": bid.to_dict()})
        await self._announce_turn(room_id, game)

    async def _h_select_bid(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        if game.current_player_id() != player_id:
            return
        try:
            bid = Bid(
                quantity=int(msg["quantity"]),
                face=int(msg["face"]),
                player_id=player_id,
                player_name=game.players[player_id].name,
            )
        except (KeyError, ValueError, TypeError):
            return

        if not game.is_valid_bid(bid):
            return

        # Guardar la apuesta seleccionada sin ejecutarla
        game.players[player_id].selected_bid = bid

    async def _h_paso(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        if game.current_player_id() != player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No es tu turno"})
        self._cancel_turn_timeout(room_id)
        if player_id in game.passed_players:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Ya pasaste en esta ronda"})

        game.passed_players.add(player_id)
        game.last_paso = {"player_id": player_id, "player_name": game.players[player_id].name}
        game.advance_turn()

        await self._broadcast(room_id, {
            "type": "paso_made",
            "passer_id": player_id,
            "passer_name": game.players[player_id].name,
        })
        bot_engine.notify_paso(game, player_id)
        await self._announce_turn(room_id, game)

    async def _h_dudo(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        self._cancel_turn_timeout(room_id)

        action = DudoAction(game, player_id, self._rules_engine(game))
        error = action.validate()
        if error:
            return await self._send(room_id, player_id, {"type": "error", "message": error})

        result = action.resolve()
        action.apply(result)

        if isinstance(result, DudoPasoResult):
            reveal_payload = {
                "type": "reveal",
                "action": "paso",
                "challenger_id": result.challenger_id,
                "challenger_name": result.challenger_name,
                "passer_id": result.passer_id,
                "passer_name": result.passer_name,
                "paso_valid": result.paso_valid,
                "is_gavilan": result.is_gavilan,
                "loser_id": result.loser_id,
                "challenger_gained": result.challenger_gained,
                "all_dice": game.all_dice_reveal(),
                "reveal_seconds": REVEAL_SECONDS,
            }
            await self._broadcast(room_id, reveal_payload)
        else:
            reveal_payload = {
                "type": "reveal",
                "action": "dudo",
                "challenger_id": result.challenger_id,
                "challenger_name": result.challenger_name,
                "bid": result.bid.to_dict(),
                "actual_count": result.actual_count,
                "bid_holds": result.bid_holds,
                "is_gavilan": result.is_gavilan,
                "loser_id": result.loser_id,
                "challenger_gained": result.challenger_gained,
                "all_dice": game.all_dice_reveal(),
                "reveal_seconds": REVEAL_SECONDS,
            }
            await self._broadcast(room_id, reveal_payload)

        bot_engine.notify_reveal(game, reveal_payload)
        await self._apply_loss(room_id, game, result.loser_id)

    async def _h_calzo(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        self._cancel_turn_timeout(room_id)

        action = CalzoAction(game, player_id, self._rules_engine(game))
        error = action.validate()
        if error:
            return await self._send(room_id, player_id, {"type": "error", "message": error})

        result = action.resolve()
        action.apply(result)

        calzo_payload = {
            "type": "reveal",
            "action": "calzo",
            "challenger_id": result.challenger_id,
            "challenger_name": result.challenger_name,
            "bid": result.bid.to_dict(),
            "actual_count": result.actual_count,
            "bid_holds": result.exact,
            "loser_id": result.loser_id,
            "calzo_success": result.exact,
            "challenger_gained": result.challenger_gained,
            "is_gavilan": result.is_gavilan,
            "all_dice": game.all_dice_reveal(),
            "reveal_seconds": REVEAL_SECONDS,
        }
        await self._broadcast(room_id, calzo_payload)
        bot_engine.notify_reveal(game, calzo_payload)

        if result.exact:
            await self._new_round(room_id, game, result.challenger_id)
        else:
            await self._apply_loss(room_id, game, result.loser_id)

    async def _h_emoji(self, room_id, player_id, game, msg):
        if not game.rules.allow_throwable_emojis:
            return
        emoji = msg.get("emoji")
        target_id = msg.get("target_id")
        if not isinstance(emoji, str) or emoji not in ALLOWED_EMOJIS:
            return
        if not isinstance(target_id, str):
            return
        if target_id not in game.players and target_id not in game.spectators:
            return
        sender = game.players.get(player_id)
        sender_name = sender.name if sender else game.spectators.get(player_id, "?")
        await self._broadcast(room_id, {
            "type": "emoji_thrown",
            "from_id": player_id,
            "from_name": sender_name,
            "target_id": target_id,
            "emoji": emoji,
        })

    ALLOWED_QUICK_PHRASES = {
        "¡Mentira!", "¡Suerte!", "Buen bluff", "No te creo",
        "¡Calzo!", "Vamos", "😅", "🤔", "Eso era mentira",
        "¡Bien jugado!", "Mala suerte", "Ups",
    }

    async def _h_quick_chat(self, room_id, player_id, game, msg):
        phrase = msg.get("phrase")
        if not isinstance(phrase, str) or phrase not in self.ALLOWED_QUICK_PHRASES:
            return
        sender = game.players.get(player_id)
        sender_name = sender.name if sender else game.spectators.get(player_id, "?")
        sender_avatar = sender.avatar if sender else "👁"
        await self._broadcast(room_id, {
            "type": "quick_chat",
            "from_id": player_id,
            "from_name": sender_name,
            "from_avatar": sender_avatar,
            "phrase": phrase,
        })

    # ------------------------------------------------------------------ game flow

    async def _begin_game(self, room_id: str, game: Game):
        game.phase = "playing"
        game.round_number = 1
        for player in game.players.values():
            player.dice_count = 5
            player.ready = False
        game.roll_all_dice()
        game.current_bid = None
        game.last_paso = None
        game.passed_players = set()
        game.bid_history = []
        game.direction = 1
        game.elimination_order = []
        active = game.active_players()
        game.current_player_idx = random.randint(0, len(active) - 1) if active else 0
        game.round_first_player = game.current_player_id()

        await self._broadcast(room_id, {
            "type": "game_started",
            "player_order": game.player_order,
            "rules": game.rules.to_dict(),
        })
        await self._send_dice(room_id, game)
        await self._announce_turn(room_id, game)

    async def _apply_loss(self, room_id: str, game: Game, loser_id: str):
        game.players[loser_id].dice_count -= 1

        if game.players[loser_id].dice_count <= 0:
            game.players[loser_id].dice_count = 0
            p = game.players[loser_id]
            game.elimination_order.append({
                "id": loser_id,
                "name": p.name,
                "avatar": p.avatar,
                "round": game.round_number,
            })
            await self._broadcast(room_id, {
                "type": "player_eliminated",
                "player_id": loser_id,
                "player_name": p.name,
            })

        outcome = self._rules_engine(game).resolve_outcome(game, loser_id)
        if outcome:
            return await self._end_game(room_id, game, outcome)

        active = game.active_players()
        next_first = loser_id if game.players[loser_id].dice_count > 0 else active[0]
        await self._new_round(room_id, game, next_first)

    async def _new_round(self, room_id: str, game: Game, first_player_id: str):
        game.phase = "reveal"
        self._cancel_turn_timeout(room_id)
        await asyncio.sleep(REVEAL_SECONDS)

        game.phase = "playing"
        game.round_number += 1
        game.current_bid = None
        game.last_paso = None
        game.passed_players = set()
        game.bid_history = []
        for p in game.players.values():
            p.selected_bid = None
        game.roll_all_dice()
        game.set_current_player(first_player_id)
        game.round_first_player = first_player_id

        await self._broadcast(room_id, {
            "type": "new_round",
            "round_number": game.round_number,
        })
        await self._send_dice(room_id, game)
        await self._announce_turn(room_id, game)

    async def _end_game(self, room_id: str, game: Game, outcome):
        game.phase = "lobby"
        self._cancel_turn_timeout(room_id)

        # Construir standings: ganador primero (posición 1), luego por orden de eliminación inverso
        survivors = []
        for pid in game.player_order:
            p = game.players.get(pid)
            if p and p.dice_count > 0:
                survivors.append({
                    "id": pid,
                    "name": p.name,
                    "avatar": p.avatar,
                    "round": game.round_number,
                })
        # survivors first (winner = pos 1), then eliminated in reverse order (last eliminated = pos 2, etc.)
        standings = survivors + list(reversed(game.elimination_order))

        payload = {
            "type": "game_over",
            "result_mode": outcome.kind,
            "rules": game.rules.to_dict(),
            "reveal_seconds": REVEAL_SECONDS,
            "standings": standings,
        }
        if outcome.kind == "winner":
            payload.update({"winner_id": outcome.player_id, "winner_name": outcome.player_name})
        else:
            payload.update({"loser_id": outcome.player_id, "loser_name": outcome.player_name})
        await self._broadcast(room_id, payload)

        # Persist to DB (non-blocking: errors are logged, never crash the game)
        asyncio.create_task(
            self._persist_game_result(room_id, game, outcome, standings)
        )

        for player in game.players.values():
            player.ready = False
            player.dice = []
            player.dice_count = 5
        game.current_bid = None
        game.bid_history = []
        game.round_number = 0
        game.elimination_order = []

    async def _persist_game_result(
        self, room_id: str, game: Game, outcome, standings: list[dict]
    ) -> None:
        """Save session, participants, and update player stats in PostgreSQL."""
        try:
            pool = await get_pool()
        except Exception as exc:
            log.warning("[db] could not get pool: %s", exc)
            return

        # standings[0] is winner → position 1; standings[-1] is 1st eliminated → last place
        n = len(standings)
        winner_anon_id: str | None = None
        if outcome.kind == "winner":
            winner_pid = outcome.player_id
            winner_player = game.players.get(winner_pid)
            if winner_player:
                winner_anon_id = winner_player.anon_id

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # 0. Ensure all human players exist in players table first
                    #    (required before game_sessions FK on winner_anon_id)
                    for entry in standings:
                        pid = entry["id"]
                        player = game.players.get(pid)
                        if player is None:
                            continue
                        if player.anon_id and not getattr(player, "is_bot", False):
                            await conn.execute(
                                """
                                INSERT INTO players (anon_id, display_name)
                                VALUES ($1, $2)
                                ON CONFLICT (anon_id) DO UPDATE SET
                                    display_name = EXCLUDED.display_name,
                                    updated_at   = NOW()
                                """,
                                player.anon_id,
                                player.name,
                            )

                    # 1. Insert session
                    session_id: int = await conn.fetchval(
                        """
                        INSERT INTO game_sessions
                            (room_id, player_count, winner_anon_id, rules)
                        VALUES ($1, $2, $3, $4::jsonb)
                        RETURNING id
                        """,
                        room_id,
                        n,
                        winner_anon_id,
                        json.dumps(game.rules.to_dict()),
                    )

                    for finish_pos, entry in enumerate(standings, start=1):
                        pid = entry["id"]
                        player = game.players.get(pid)
                        if player is None:
                            continue
                        is_bot = getattr(player, "is_bot", False)
                        anon_id = player.anon_id

                        # XP: winner gets full, others get participation + position bonus
                        if finish_pos == 1:
                            xp_earned = _XP_WIN
                        else:
                            xp_earned = _XP_PARTICIPATION + max(0, n - finish_pos) * _XP_PER_POSITION

                        # 2. Insert participant
                        await conn.execute(
                            """
                            INSERT INTO game_participants
                                (session_id, anon_id, display_name, finish_position, is_bot, xp_earned)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            session_id,
                            anon_id,
                            player.name,
                            finish_pos,
                            is_bot,
                            xp_earned,
                        )

                        # 3. Upsert player stats (human players only)
                        if anon_id and not is_bot:
                            await conn.execute(
                                """
                                INSERT INTO players
                                    (anon_id, display_name, xp, level, games_played, games_won)
                                VALUES ($1, $2, $3, 1, 1, $4)
                                ON CONFLICT (anon_id) DO UPDATE SET
                                    display_name  = EXCLUDED.display_name,
                                    xp            = players.xp + EXCLUDED.xp,
                                    level         = (players.xp + EXCLUDED.xp) / 100 + 1,
                                    games_played  = players.games_played + 1,
                                    games_won     = players.games_won + EXCLUDED.games_won,
                                    updated_at    = NOW()
                                """,
                                anon_id,
                                player.name,
                                xp_earned,
                                1 if finish_pos == 1 else 0,
                            )

            log.info("[db] persisted session %s for room %s", session_id, room_id)

        except Exception as exc:
            log.exception("[db] failed to persist game result: %s", exc)
            return

        # Persist bid/paso stats for all human players from Expert memory
        asyncio.create_task(self._persist_bid_stats(room_id, game))

    async def _persist_bid_stats(self, room_id: str, game: Game) -> None:
        """
        Persiste las estadísticas de apuesta (bid_stats y paso_stats) acumuladas
        por el ExpertBot durante esta partida para cada jugador humano.
        Usa UPSERT incremental: suma sobre lo que ya había en DB.
        """
        import game.bot as bot_module
        from game.player_model import bluff_model

        # Buscar bot activo en la partida (expert tiene prioridad sobre expert)
        vh      = None
        bot_pid = None
        for difficulty in ("expert", "expert"):
            strategy = bot_module._REGISTRY.get(difficulty)
            if not isinstance(strategy, bot_module.ExpertBot):
                continue
            candidate = next(
                (pid for pid, p in game.players.items()
                 if p.is_bot and p.bot_difficulty == difficulty),
                None,
            )
            if candidate:
                vh      = strategy
                bot_pid = candidate
                break

        if bot_pid is None:
            return

        mem = vh._memory.get(bot_pid)
        # Para ExpertBot: si no tiene global_mem propio, usar el de ExpertBot
        global_mem = vh._memory.get("__global__")
        if global_mem is None:
            vh_fallback = bot_module._REGISTRY.get("expert")
            if isinstance(vh_fallback, bot_module.ExpertBot) and vh_fallback is not vh:
                global_mem = vh_fallback._memory.get("__global__")
        if mem is None:
            return

        try:
            pool = await get_pool()
        except Exception as exc:
            log.warning("[db] could not get pool for bid_stats: %s", exc)
            return

        # Para cada jugador humano con anon_id en esta partida,
        # calcular el delta (mem - global_mem) y persistirlo
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for pid, player in game.players.items():
                        anon_id = player.anon_id
                        if not anon_id or getattr(player, "is_bot", False):
                            continue

                        # Asegurar que el jugador exista en players
                        await conn.execute(
                            """
                            INSERT INTO players (anon_id, display_name)
                            VALUES ($1, $2)
                            ON CONFLICT (anon_id) DO UPDATE SET
                                display_name = EXCLUDED.display_name,
                                updated_at   = NOW()
                            """,
                            anon_id, player.name,
                        )

                        current = mem.player_stats.get(anon_id)
                        baseline = global_mem.player_stats.get(anon_id) if global_mem else None

                        if current is None:
                            continue

                        # -- bid stats delta --
                        for face in range(1, 7):
                            for bucket in range(1, 4):
                                cur_t  = current.face_bid_counts.get(face, 0)
                                cur_b  = current.face_bluff_counts.get(face, 0)
                                bas_t  = baseline.face_bid_counts.get(face, 0) if baseline else 0
                                bas_b  = baseline.face_bluff_counts.get(face, 0) if baseline else 0
                                delta_t = max(0, cur_t - bas_t)
                                delta_b = max(0, cur_b - bas_b)

                                if delta_t == 0:
                                    continue

                                # Distribute face counts evenly across buckets;
                                # time stats are stored per face (bucket=2 as representative)
                                frac_t = delta_t // 3 + (1 if face % 3 < bucket else 0)
                                frac_b = int(delta_b * frac_t / max(delta_t, 1))
                                if frac_t == 0:
                                    continue

                                # Time deltas (only meaningful for bucket=2 representative row)
                                if bucket == 2:
                                    bas_bts = baseline.bid_time_bluff_sum if baseline else 0.0
                                    bas_btn = baseline.bid_time_bluff_n   if baseline else 0
                                    bas_tts = baseline.bid_time_truth_sum if baseline else 0.0
                                    bas_ttn = baseline.bid_time_truth_n   if baseline else 0
                                    d_bts = max(0.0, current.bid_time_bluff_sum - bas_bts)
                                    d_btn = max(0,   current.bid_time_bluff_n   - bas_btn)
                                    d_tts = max(0.0, current.bid_time_truth_sum - bas_tts)
                                    d_ttn = max(0,   current.bid_time_truth_n   - bas_ttn)
                                else:
                                    d_bts = d_btn = d_tts = d_ttn = 0

                                await conn.execute(
                                    """
                                    INSERT INTO player_bid_stats
                                        (anon_id, face, qty_bucket, bids_total, bids_bluff,
                                         bid_time_bluff_sum, bid_time_bluff_n,
                                         bid_time_truth_sum, bid_time_truth_n)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                                    ON CONFLICT (anon_id, face, qty_bucket) DO UPDATE SET
                                        bids_total         = player_bid_stats.bids_total         + EXCLUDED.bids_total,
                                        bids_bluff         = player_bid_stats.bids_bluff         + EXCLUDED.bids_bluff,
                                        bid_time_bluff_sum = player_bid_stats.bid_time_bluff_sum + EXCLUDED.bid_time_bluff_sum,
                                        bid_time_bluff_n   = player_bid_stats.bid_time_bluff_n   + EXCLUDED.bid_time_bluff_n,
                                        bid_time_truth_sum = player_bid_stats.bid_time_truth_sum + EXCLUDED.bid_time_truth_sum,
                                        bid_time_truth_n   = player_bid_stats.bid_time_truth_n   + EXCLUDED.bid_time_truth_n
                                    """,
                                    anon_id, face, bucket, frac_t, frac_b,
                                    d_bts, d_btn, d_tts, d_ttn,
                                )

                        # -- paso stats delta --
                        bas_pc  = baseline.paso_count       if baseline else 0
                        bas_pb  = baseline.paso_bluff_count if baseline else 0
                        bas_pds = baseline.paso_dice_sum    if baseline else 0
                        delta_pc  = max(0, current.paso_count       - bas_pc)
                        delta_pb  = max(0, current.paso_bluff_count - bas_pb)
                        delta_pds = max(0, current.paso_dice_sum    - bas_pds)
                        if delta_pc > 0:
                            await conn.execute(
                                """
                                INSERT INTO player_paso_stats
                                    (anon_id, pasos_total, pasos_bluff, paso_dice_sum)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (anon_id) DO UPDATE SET
                                    pasos_total   = player_paso_stats.pasos_total   + EXCLUDED.pasos_total,
                                    pasos_bluff   = player_paso_stats.pasos_bluff   + EXCLUDED.pasos_bluff,
                                    paso_dice_sum = player_paso_stats.paso_dice_sum + EXCLUDED.paso_dice_sum
                                """,
                                anon_id, delta_pc, delta_pb, delta_pds,
                            )

            # Re-entrenar el modelo con los nuevos datos (en background)
            asyncio.create_task(_retrain_model(pool))
            log.info("[db] persisted bid_stats for room %s", room_id)
        except Exception as exc:
            log.warning("[db] failed to persist bid_stats: %s", exc)

    def _rules_engine(self, game: Game) -> RuleEngine:
        return RuleEngine.from_config(game.rules)

    @staticmethod
    def _turn_payload(game: Game) -> dict:
        current = game.current_player_id()
        return {
            "type": "turn",
            "player_id": current,
            "player_name": game.players[current].name if current in game.players else "?",
            "current_bid": game.current_bid.to_dict() if game.current_bid else None,
            "active_paso": game.last_paso,
            "direction": game.direction,
            "round_first_player": game.round_first_player,
            "has_first_action": game.current_bid is not None or game.last_paso is not None,
            "turn_timeout_seconds": game.rules.turn_timeout_seconds,
        }

    def _spectator_state_payload(self, game: Game) -> dict:
        return {
            "phase": game.phase,
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
            "player_order": game.player_order,
            "rules": game.rules.to_dict(),
            "round_number": game.round_number,
            "total_dice": game.total_dice(),
            "host_id": self._host_id(game.room_id, game),
            "turn": self._turn_payload(game) if game.phase in {"playing", "reveal"} else None,
            "spectator_count": len(game.spectators),
        }

    def _pick_connected_host(self, game: Game) -> str | None:
        """Devuelve el primer jugador humano conectado como candidato a host. Los bots nunca son host."""
        for pid in game.player_order:
            player = game.players.get(pid)
            if player and player.connected and not player.is_bot:
                return pid
        return None

    def _host_id(self, room_id: str, game: Game) -> str | None:
        """
        Devuelve el host actual.
        El host puede estar en players O en spectators (si se hizo espectador en el lobby).
        Los bots nunca son host. Si el host registrado ya no existe en ninguno de los dos,
        se asigna automáticamente el primer jugador humano conectado.
        """
        host_id = self.hosts.get(room_id)
        if host_id:
            in_players = host_id in game.players and game.players[host_id].connected and not game.players[host_id].is_bot
            in_spectators = host_id in game.spectators
            if in_players or in_spectators:
                return host_id
        # Fallback: primer jugador humano conectado
        fallback = self._pick_connected_host(game)
        if fallback:
            self.hosts[room_id] = fallback
            return fallback
        self.hosts.pop(room_id, None)
        return None

    async def _send_dice(self, room_id: str, game: Game):
        for pid, player in game.players.items():
            if player.connected:
                await self._send(room_id, pid, {
                    "type": "your_dice",
                    "dice": player.dice,
                    "round_number": game.round_number,
                    "total_dice": game.total_dice(),
                    "players": {p: pl.to_public_dict() for p, pl in game.players.items()},
                })
        for spectator_id in list(game.spectators.keys()):
            await self._send(room_id, spectator_id, {
                "type": "spectator_state",
                **self._spectator_state_payload(game),
            })

    async def _announce_turn(self, room_id: str, game: Game):
        self.turn_started_at[room_id] = time.monotonic()
        await self._broadcast(room_id, self._turn_payload(game))
        self._schedule_turn_timeout(room_id, game)
        # Si el turno es de un bot, programar su acción con un pequeño delay
        current = game.current_player_id()
        if current and current in game.players and game.players[current].is_bot:
            self._schedule_bot_action(room_id, game, current)

    def _cancel_turn_timeout(self, room_id: str):
        task = self.turn_timeout_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_disconnect_resolution(self, room_id: str, player_id: str):
        key = (room_id, player_id)
        task = self.disconnect_resolution_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    def _cancel_disconnect_resolution_for_room(self, room_id: str):
        keys = [key for key in self.disconnect_resolution_tasks if key[0] == room_id]
        for key in keys:
            task = self.disconnect_resolution_tasks.pop(key, None)
            if task and not task.done():
                task.cancel()

    def _schedule_disconnect_resolution(self, room_id: str, player_id: str):
        self._cancel_disconnect_resolution(room_id, player_id)
        if DISCONNECT_GRACE_SECONDS < 0:
            return

        async def _runner():
            try:
                await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
                game = self.games.get(room_id)
                if not game or game.phase != "playing":
                    return
                player = game.players.get(player_id)
                if not player or player.connected:
                    return
                outcome = self._rules_engine(game).resolve_outcome(game, player_id)
                if outcome:
                    await self._end_game(room_id, game, outcome)
            except asyncio.CancelledError:
                return
            finally:
                self.disconnect_resolution_tasks.pop((room_id, player_id), None)

        self.disconnect_resolution_tasks[(room_id, player_id)] = asyncio.create_task(_runner())

    def _schedule_turn_timeout(self, room_id: str, game: Game):
        self._cancel_turn_timeout(room_id)
        seconds = game.rules.turn_timeout_seconds
        if game.phase != "playing" or seconds <= 0:
            return
        current = game.current_player_id()
        if not current:
            return

        async def _runner():
            try:
                await asyncio.sleep(seconds)
                current_game = self.games.get(room_id)
                if not current_game or current_game.phase != "playing":
                    return
                if current_game.current_player_id() != current:
                    return
                await self._run_timeout_action(room_id, current_game, current)
            except asyncio.CancelledError:
                return

        self.turn_timeout_tasks[room_id] = asyncio.create_task(_runner())

    async def _run_timeout_action(self, room_id: str, game: Game, player_id: str):
        player = game.players.get(player_id)
        if not player:
            return

        # Si el jugador tiene una apuesta seleccionada y es válida, ejecutarla
        if player.selected_bid is not None and game.is_valid_bid(player.selected_bid):
            bid = player.selected_bid
            bid.elapsed_seconds = round(time.monotonic() - self.turn_started_at.get(room_id, time.monotonic()), 3)
            player.selected_bid = None
            game.current_bid = bid
            game.last_paso = None
            game.bid_history.append(bid)
            game.advance_turn()
            await self._broadcast(room_id, {"type": "bid_made", "bid": bid.to_dict()})
            await self._announce_turn(room_id, game)
            return
        player.selected_bid = None

        # Comportamiento original si no hay apuesta seleccionada
        if game.current_bid is not None and player_id not in game.passed_players:
            game.passed_players.add(player_id)
            game.last_paso = {"player_id": player_id, "player_name": player.name}
            game.advance_turn()
            await self._broadcast(room_id, {
                "type": "paso_made",
                "passer_id": player_id,
                "passer_name": player.name,
            })
            bot_engine.notify_paso(game, player_id)
            await self._announce_turn(room_id, game)
            return

        bid = self._min_timeout_bid(game, player_id)
        bid.elapsed_seconds = round(time.monotonic() - self.turn_started_at.get(room_id, time.monotonic()), 3)
        game.current_bid = bid
        game.last_paso = None
        game.bid_history.append(bid)
        game.advance_turn()
        await self._broadcast(room_id, {"type": "bid_made", "bid": bid.to_dict()})
        await self._announce_turn(room_id, game)

    @staticmethod
    def _min_timeout_bid(game: Game, player_id: str) -> Bid:
        current = game.current_bid
        face = current.face if current else 2
        qty = 1
        if current:
            if current.face == 1:
                # subir ases: mínimo quantity + 1
                qty = current.quantity + 1
            elif face == current.face:
                qty = current.quantity + 1
            else:
                qty = current.quantity

        while True:
            bid = Bid(
                quantity=qty,
                face=face,
                player_id=player_id,
                player_name=game.players[player_id].name,
            )
            if game.is_valid_bid(bid):
                return bid
            qty += 1

    # ------------------------------------------------------------------ bot actions

    # Delay de pensamiento por dificultad (segundos)
    _BOT_THINK_DELAY = {"easy": 1.8, "medium": 1.2, "hard": 0.7}

    def _schedule_bot_action(self, room_id: str, game: Game, bot_id: str):
        difficulty = game.players[bot_id].bot_difficulty
        delay = self._BOT_THINK_DELAY.get(difficulty, 1.2) + random.uniform(0, 0.8)

        async def _runner():
            try:
                await asyncio.sleep(delay)
                current_game = self.games.get(room_id)
                if not current_game or current_game.phase != "playing":
                    return
                if current_game.current_player_id() != bot_id:
                    return
                await self._run_bot_action(room_id, current_game, bot_id)
            except asyncio.CancelledError:
                return
            except Exception as e:
                import traceback
                print(f"[bot error] {bot_id}: {e}\n{''.join(traceback.format_exc())}")
                current_game = self.games.get(room_id)
                if (current_game and current_game.phase == "playing"
                        and current_game.current_player_id() == bot_id):
                    fallback = self._min_timeout_bid(current_game, bot_id)
                    self._cancel_turn_timeout(room_id)
                    await self._h_bid(room_id, bot_id, current_game,
                                      {"quantity": fallback.quantity, "face": fallback.face})

        asyncio.create_task(_runner())

    async def _run_bot_action(self, room_id: str, game: Game, bot_id: str):
        decision = bot_engine.decide(game, bot_id)
        action = decision.get("action")

        if action == "dudo":
            # Verificar que haya algo que dudar
            if game.current_bid is None and game.last_paso is None:
                action = "bid"  # fallback
            else:
                self._cancel_turn_timeout(room_id)
                await self._h_dudo(room_id, bot_id, game, {})
                return

        if action == "calzo":
            if game.current_bid is None or game.current_bid.player_id == bot_id:
                action = "bid"  # fallback
            else:
                self._cancel_turn_timeout(room_id)
                await self._h_calzo(room_id, bot_id, game, {})
                return

        if action == "paso":
            if game.current_bid is not None and bot_id not in game.passed_players:
                self._cancel_turn_timeout(room_id)
                await self._h_paso(room_id, bot_id, game, {})
                return
            else:
                action = "bid"  # fallback si no puede pasar

        if action == "bid":
            qty = decision.get("quantity", 1)
            face = decision.get("face", 2)
            self._cancel_turn_timeout(room_id)
            await self._h_bid(room_id, bot_id, game, {"quantity": qty, "face": face})

    # ------------------------------------------------------------------ transport

    async def _send(self, room_id: str, player_id: str, msg: dict):
        ws = self.connections.get(room_id, {}).get(player_id)
        if ws:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                pass

    async def _broadcast(self, room_id: str, msg: dict):
        text = json.dumps(msg)
        for ws in list(self.connections.get(room_id, {}).values()):
            try:
                await ws.send_text(text)
            except Exception:
                pass

    async def _broadcast_except(self, room_id: str, exclude: str, msg: dict):
        text = json.dumps(msg)
        for pid, ws in list(self.connections.get(room_id, {}).items()):
            if pid != exclude:
                try:
                    await ws.send_text(text)
                except Exception:
                    pass
