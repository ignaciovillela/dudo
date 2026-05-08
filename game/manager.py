import asyncio
import json
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
        if msg_type not in {"join", "connected", "select_bid", "become_spectator", "become_player", "add_bot", "remove_bot"} and not self._allow_message(player_id):
            return
        handlers = {
            "join":      self._h_join,
            "ready":     self._h_ready,
            "start":     self._h_start,
            "set_rules": self._h_set_rules,
            "kick_player": self._h_kick_player,
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
        player = Player(id=player_id, name=name, avatar=avatar)
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
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"

        bot_names = {
            "easy":   ["Botín", "Novato", "Pipón", "Torpe"],
            "medium": ["Calculín", "Medio", "Astuto", "Listo"],
            "hard":   ["Maestro", "Genio", "Experto", "HAL"],
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
        self._cancel_turn_timeout(room_id)
        try:
            bid = Bid(
                quantity=int(msg["quantity"]),
                face=int(msg["face"]),
                player_id=player_id,
                player_name=game.players[player_id].name,
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
            await self._broadcast(room_id, {
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
            })
        else:
            await self._broadcast(room_id, {
                "type": "reveal",
                "action": "dudo",
                "challenger_id": result.challenger_id,
                "challenger_name": result.challenger_name,
                "bid": result.bid.to_dict(),
                "actual_count": result.actual_count,
                "bid_holds": result.bid_holds,
                "is_gavilan": result.is_gavilan,
                "loser_id": result.loser_id,
                "all_dice": game.all_dice_reveal(),
                "reveal_seconds": REVEAL_SECONDS,
            })

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

        await self._broadcast(room_id, {
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
        })

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

        # Construir standings: eliminados en orden + ganador/sobreviviente al final
        standings = list(game.elimination_order)
        # El/los jugadores con dados > 0 van al final (ganadores/sobrevivientes)
        for pid in game.player_order:
            p = game.players.get(pid)
            if p and p.dice_count > 0:
                standings.append({
                    "id": pid,
                    "name": p.name,
                    "avatar": p.avatar,
                    "round": game.round_number,
                })

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
        for player in game.players.values():
            player.ready = False
            player.dice = []
            player.dice_count = 5
        game.current_bid = None
        game.bid_history = []
        game.round_number = 0
        game.elimination_order = []

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

        # Si el jugador tiene una apuesta seleccionada, ejecutarla
        if player.selected_bid is not None:
            bid = player.selected_bid
            player.selected_bid = None  # limpiar la selección después de usarla
            game.current_bid = bid
            game.last_paso = None
            game.bid_history.append(bid)
            game.advance_turn()
            await self._broadcast(room_id, {"type": "bid_made", "bid": bid.to_dict()})
            await self._announce_turn(room_id, game)
            return

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
            await self._announce_turn(room_id, game)
            return

        bid = self._min_timeout_bid(game, player_id)
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
