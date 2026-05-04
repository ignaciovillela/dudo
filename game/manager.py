import asyncio
import json
import random

from fastapi import WebSocket

from game.models import Bid, Game, Player, RuleConfig
from game.rules import RuleEngine


class GameManager:
    def __init__(self):
        self.games: dict[str, Game] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.hosts: dict[str, str] = {}

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

    async def disconnect(self, room_id: str, player_id: str):
        self.connections.get(room_id, {}).pop(player_id, None)
        game = self.games.get(room_id)

        # Liberar sala si no quedan conexiones activas
        if not self.connections.get(room_id):
            self.games.pop(room_id, None)
            self.connections.pop(room_id, None)
            self.hosts.pop(room_id, None)
            return

        if not game or player_id not in game.players:
            return

        player = game.players[player_id]
        player.connected = False
        previous_host_id = self._host_id(room_id, game)

        if game.phase == "lobby":
            del game.players[player_id]
            if player_id in game.player_order:
                game.player_order.remove(player_id)

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
            outcome = self._rules_engine(game).resolve_outcome(game, player_id)
            if outcome:
                await self._end_game(room_id, game, outcome)

    # ------------------------------------------------------------------ dispatch

    async def handle_message(self, room_id: str, player_id: str, msg: dict):
        game = self.games.get(room_id)
        if not game:
            return
        handlers = {
            "join":      self._h_join,
            "ready":     self._h_ready,
            "start":     self._h_start,
            "set_rules": self._h_set_rules,
            "direction": self._h_direction,
            "bid":       self._h_bid,
            "paso":      self._h_paso,
            "dudo":      self._h_dudo,
            "calzo":     self._h_calzo,
        }
        handler = handlers.get(msg.get("type"))
        if handler:
            await handler(room_id, player_id, game, msg)

    # ------------------------------------------------------------------ handlers

    async def _h_join(self, room_id, player_id, game, msg):
        # ── Intento de reconexión ─────────────────────────────────────────────
        reconnect_id = msg.get("reconnect_id")
        if reconnect_id and reconnect_id in game.players and game.phase == "playing":
            old = game.players[reconnect_id]
            if not old.connected:
                # Reasignar el websocket al player_id original
                ws = self.connections[room_id].pop(player_id, None)
                if ws:
                    self.connections[room_id][reconnect_id] = ws
                old.connected = True
                await self._send(room_id, reconnect_id, {
                    "type": "reconnected",
                    "player_id": reconnect_id,
                    "host_id": self._host_id(room_id, game),
                    "is_host": self._host_id(room_id, game) == reconnect_id,
                    "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
                    "player_order": game.player_order,
                    "phase": game.phase,
                    "rules": game.rules.to_dict(),
                })
                await self._broadcast_except(room_id, reconnect_id, {
                    "type": "player_reconnected",
                    "player_id": reconnect_id,
                    "player_name": old.name,
                })
                # Reenviar estado actual de la partida al jugador reconectado
                await self._send(room_id, reconnect_id, {
                    "type": "your_dice",
                    "dice": old.dice,
                    "round_number": game.round_number,
                    "total_dice": game.total_dice(),
                    "players": {p: pl.to_public_dict() for p, pl in game.players.items()},
                })
                await self._announce_turn(room_id, game)
                return

        # ── Unirse nuevo ──────────────────────────────────────────────────────
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Partida en curso"})
        if len(game.players) >= 6:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Sala llena (máx. 6)"})

        name = (msg.get("name") or f"Jugador {len(game.players) + 1}").strip()[:20]
        player = Player(id=player_id, name=name)
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
        is_host = self._host_id(room_id, game) == player_id
        connected = [p for p in game.players.values() if p.connected]
        if is_host and len(connected) >= 2:
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

    async def _h_paso(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        if game.current_player_id() != player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No es tu turno"})
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
        if player_id in game.players and game.players[player_id].dice_count <= 0:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Estás eliminado"})

        was_current = game.current_player_id() == player_id
        if not was_current and not self._rules_engine(game).allow_gavilan():
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Gavilán está desactivado en esta sala"})

        # ── Dudo sobre un paso activo ──────────────────────────────────────────
        if game.last_paso is not None:
            paso = game.last_paso
            game.last_paso = None  # evitar doble dudo simultáneo

            if paso["player_id"] == player_id:
                game.last_paso = paso
                return await self._send(room_id, player_id,
                                        {"type": "error", "message": "No puedes dudar tu propio paso"})

            paso_valid = game.is_valid_paso(paso["player_id"])
            loser_id = player_id if paso_valid else paso["player_id"]
            is_gavilan = not was_current

            # Gavilán correcto: solo recupera dado si NO es el jugador en turno (gavilán real)
            challenger_gained = False
            if not paso_valid and is_gavilan:
                p = game.players[player_id]
                if p.dice_count < 5:
                    p.dice_count += 1
                    challenger_gained = True

            await self._broadcast(room_id, {
                "type": "reveal",
                "action": "paso",
                "challenger_id": player_id,
                "challenger_name": game.players[player_id].name,
                "passer_id": paso["player_id"],
                "passer_name": paso["player_name"],
                "paso_valid": paso_valid,
                "is_gavilan": is_gavilan,
                "loser_id": loser_id,
                "challenger_gained": challenger_gained,
                "all_dice": game.all_dice_reveal(),
            })
            await self._apply_loss(room_id, game, loser_id)
            return

        # ── Dudo sobre una apuesta ─────────────────────────────────────────────
        if game.current_bid is None:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No hay acción activa que dudar"})

        bid = game.current_bid
        game.current_bid = None  # evitar doble dudo simultáneo

        if bid.player_id == player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No puedes dudar tu propia apuesta"})

        actual = game.count_dice(bid.face)
        bid_holds = actual >= bid.quantity
        loser_id = player_id if bid_holds else bid.player_id

        await self._broadcast(room_id, {
            "type": "reveal",
            "action": "dudo",
            "challenger_id": player_id,
            "challenger_name": game.players[player_id].name,
            "bid": bid.to_dict(),
            "actual_count": actual,
            "bid_holds": bid_holds,
            "loser_id": loser_id,
            "all_dice": game.all_dice_reveal(),
        })
        await self._apply_loss(room_id, game, loser_id)

    async def _h_calzo(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        if player_id in game.players and game.players[player_id].dice_count <= 0:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Estás eliminado"})
        if game.last_paso is not None:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No se puede calzar un paso"})
        if game.current_bid is None:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No hay apuesta"})

        was_current = game.current_player_id() == player_id
        if not was_current and not self._rules_engine(game).allow_gavilan():
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Gavilán está desactivado en esta sala"})

        bid = game.current_bid
        game.current_bid = None  # evitar doble calzo simultánea

        if bid.player_id == player_id:
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "No puedes calzar tu propia apuesta"})

        actual = game.count_dice(bid.face)
        exact = actual == bid.quantity

        # Recuperación de dado definida por plugin de reglas.
        challenger_gained = False
        can_recover_on_turn = self._rules_engine(game).calzo_recovers_on_turn()
        if exact and (not was_current or can_recover_on_turn):
            p = game.players[player_id]
            if p.dice_count < 5:
                p.dice_count += 1
                challenger_gained = True

        await self._broadcast(room_id, {
            "type": "reveal",
            "action": "calzo",
            "challenger_id": player_id,
            "challenger_name": game.players[player_id].name,
            "bid": bid.to_dict(),
            "actual_count": actual,
            "bid_holds": exact,
            "loser_id": None if exact else player_id,
            "calzo_success": exact,
            "challenger_gained": challenger_gained,
            "all_dice": game.all_dice_reveal(),
        })

        if exact:
            await self._new_round(room_id, game, player_id)
        else:
            await self._apply_loss(room_id, game, player_id)

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
            await self._broadcast(room_id, {
                "type": "player_eliminated",
                "player_id": loser_id,
                "player_name": game.players[loser_id].name,
            })

        outcome = self._rules_engine(game).resolve_outcome(game, loser_id)
        if outcome:
            return await self._end_game(room_id, game, outcome)

        active = game.active_players()
        next_first = loser_id if game.players[loser_id].dice_count > 0 else active[0]
        await self._new_round(room_id, game, next_first)

    async def _new_round(self, room_id: str, game: Game, first_player_id: str):
        game.phase = "reveal"
        await asyncio.sleep(7)

        game.phase = "playing"
        game.round_number += 1
        game.current_bid = None
        game.last_paso = None
        game.passed_players = set()
        game.bid_history = []
        game.direction = 1
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
        payload = {"type": "game_over", "result_mode": outcome.kind, "rules": game.rules.to_dict()}
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

    def _rules_engine(self, game: Game) -> RuleEngine:
        return RuleEngine.from_config(game.rules)

    def _pick_connected_host(self, game: Game) -> str | None:
        for pid in game.player_order:
            player = game.players.get(pid)
            if player and player.connected:
                return pid
        return None

    def _host_id(self, room_id: str, game: Game) -> str | None:
        host_id = self.hosts.get(room_id)
        if host_id in game.players and game.players[host_id].connected:
            return host_id
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

    async def _announce_turn(self, room_id: str, game: Game):
        current = game.current_player_id()
        await self._broadcast(room_id, {
            "type": "turn",
            "player_id": current,
            "player_name": game.players[current].name if current in game.players else "?",
            "current_bid": game.current_bid.to_dict() if game.current_bid else None,
            "active_paso": game.last_paso,
            "direction": game.direction,
            "round_first_player": game.round_first_player,
            "has_first_action": game.current_bid is not None or game.last_paso is not None,
        })

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
