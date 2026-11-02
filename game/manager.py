import asyncio
import json
import logging
import pathlib
import random
import re
import time
import uuid

from fastapi import WebSocket

from game.config import CHALLENGE_CONSECUTIVE_MS, CHALLENGE_GUARD_MS, DEBUG_MODE, DISCONNECT_GRACE_SECONDS, MAX_BID_QUANTITY, MAX_PLAYERS, RATE_LIMIT_MS, REVEAL_SECONDS
from game.models import Bid, Game, Player, RuleConfig
from game.rules import RuleEngine
from game.actions import CalzoAction, DudoAction, DudoBidResult, DudoPasoResult
import game.bot as bot_engine
from game.db import get_pool
from game.audio_clips import (
    build_player_clip_stream_url,
    fetch_player_audio_clip_by_id,
    get_system_audio_clip_by_id,
    normalize_anon_id,
)

log = logging.getLogger(__name__)

# Fuente de verdad: /static/quick_phrases.json (compartido con el front)
# Se usa para ALLOWED_QUICK_PHRASES y _BOT_PHRASES.
_QUICK_PHRASES_DATA = json.loads(
    (pathlib.Path(__file__).resolve().parents[1] / "static" / "quick_phrases.json").read_text(encoding="utf-8")
)

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

# Fuente de verdad compartida con el cliente: static/*.json
_STATIC = pathlib.Path(__file__).parent.parent / "static"
ALLOWED_EMOJIS: frozenset[str] = frozenset(
    item["emoji"] for item in json.loads((_STATIC / "emojis.json").read_text(encoding="utf-8"))
)
ALLOWED_AVATARS: frozenset[str] = frozenset(
    item["emoji"] for item in json.loads((_STATIC / "avatars.json").read_text(encoding="utf-8"))
)


def _clean_name(value, default: str = "") -> str:
    """Quita caracteres de marcado HTML y recorta a 20 caracteres."""
    cleaned = re.sub(r"[<>&\"'`]", "", str(value or "")).strip()[:20]
    return cleaned or default


class GameManager:
    def __init__(self):
        self.games: dict[str, Game] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.hosts: dict[str, str] = {}
        self.last_message_at: dict[str, float] = {}
        self.turn_timeout_tasks: dict[str, asyncio.Task] = {}
        self.disconnect_resolution_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.room_cleanup_tasks: dict[str, asyncio.Task] = {}
        self.turn_started_at: dict[str, float] = {}   # room_id → monotonic timestamp
        self.admin_sessions: dict[str, set[str]] = {}  # room_id → {player_id, ...} sesiones admin
        self.paused_rooms: set[str] = set()  # salas pausadas por admin
        self.client_anon_ids: dict[str, dict[str, str]] = {}  # room_id -> {connection_id: anon_id}
        # Tasks de gavilán fuera de turno: (room_id, bot_id) → Task
        # Se cancelan antes de crear uno nuevo para evitar duplicados por bid.
        self.gavilan_tasks: dict[tuple[str, str], asyncio.Task] = {}

    # ------------------------------------------------------------------ state persistence

    def _serialize_bid(self, bid: Bid | None) -> dict | None:
        if bid is None:
            return None
        return {
            "quantity": bid.quantity,
            "face": bid.face,
            "player_id": bid.player_id,
            "player_name": bid.player_name,
            "elapsed_seconds": bid.elapsed_seconds,
        }

    def _deserialize_bid(self, data: dict | None) -> Bid | None:
        if data is None:
            return None
        return Bid(
            quantity=data["quantity"],
            face=data["face"],
            player_id=data["player_id"],
            player_name=data["player_name"],
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
        )

    def _serialize_room_state(self, room_id: str) -> dict | None:
        game = self.games.get(room_id)
        if not game:
            return None

        players_serialized = {}
        for pid, p in game.players.items():
            players_serialized[pid] = {
                "id": p.id,
                "name": p.name,
                "avatar": p.avatar,
                "dice": p.dice,
                "dice_count": p.dice_count,
                "connected": p.connected,
                "ready": p.ready,
                "selected_bid": self._serialize_bid(p.selected_bid),
                "is_bot": p.is_bot,
                "bot_difficulty": p.bot_difficulty,
                "anon_id": p.anon_id,
            }

        return {
            "game": {
                "room_id": game.room_id,
                "players": players_serialized,
                "spectators": dict(game.spectators),
                "phase": game.phase,
                "player_order": list(game.player_order),
                "current_player_idx": game.current_player_idx,
                "current_bid": self._serialize_bid(game.current_bid),
                "bid_history": [self._serialize_bid(b) for b in game.bid_history],
                "round_number": game.round_number,
                "last_paso": game.last_paso,
                "passed_players": list(game.passed_players),
                "direction": game.direction,
                "round_first_player": game.round_first_player,
                "rules": game.rules.to_dict(),
                "elimination_order": list(game.elimination_order),
                "streaks": dict(game.streaks),
                "best_streaks": dict(game.best_streaks),
                "ghost_failures": dict(game.ghost_failures),
                "ghost_cooldown": dict(game.ghost_cooldown),
                "initial_total_dice": game.initial_total_dice,
            },
            "host": self.hosts.get(room_id),
            "admin_sessions": list(self.admin_sessions.get(room_id, set())),
            "paused": room_id in self.paused_rooms,
            "client_anon_ids": dict(self.client_anon_ids.get(room_id, {})),
        }

    def _restore_room_from_state(self, room_id: str, data: dict) -> None:
        gd = data["game"]

        players = {}
        for pid, pd in gd["players"].items():
            players[pid] = Player(
                id=pd["id"],
                name=pd["name"],
                avatar=pd["avatar"],
                dice=list(pd["dice"]),
                dice_count=pd["dice_count"],
                connected=pd["connected"],
                ready=pd["ready"],
                selected_bid=self._deserialize_bid(pd.get("selected_bid")),
                is_bot=pd["is_bot"],
                bot_difficulty=pd.get("bot_difficulty", "medium"),
                anon_id=pd.get("anon_id"),
            )

        game = Game(
            room_id=room_id,
            players=players,
            spectators=dict(gd.get("spectators", {})),
            phase=gd["phase"],
            player_order=list(gd["player_order"]),
            current_player_idx=gd["current_player_idx"],
            current_bid=self._deserialize_bid(gd.get("current_bid")),
            bid_history=[self._deserialize_bid(b) for b in gd.get("bid_history", [])],
            round_number=gd["round_number"],
            last_paso=gd.get("last_paso"),
            passed_players=set(gd.get("passed_players", [])),
            direction=gd["direction"],
            round_first_player=gd.get("round_first_player", ""),
            rules=RuleConfig.from_payload(gd.get("rules")),
            elimination_order=list(gd.get("elimination_order", [])),
            streaks=dict(gd.get("streaks", {})),
            best_streaks=dict(gd.get("best_streaks", {})),
            ghost_failures=dict(gd.get("ghost_failures", {})),
            ghost_cooldown=dict(gd.get("ghost_cooldown", {})),
            initial_total_dice=gd.get("initial_total_dice", 0),
        )

        self.games[room_id] = game

        host = data.get("host")
        if host:
            self.hosts[room_id] = host

        admin_list = data.get("admin_sessions", [])
        if admin_list:
            self.admin_sessions[room_id] = set(admin_list)

        if data.get("paused"):
            self.paused_rooms.add(room_id)

        anon_map = data.get("client_anon_ids", {})
        if anon_map:
            self.client_anon_ids[room_id] = dict(anon_map)

    async def _persist_room_state(self, room_id: str) -> None:
        state = self._serialize_room_state(room_id)
        if state is None:
            return
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO active_rooms (room_id, state, updated_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (room_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        updated_at = NOW()
                    """,
                    room_id,
                    json.dumps(state),
                )
        except Exception as exc:
            log.warning("[persist] failed to save room %s: %s", room_id, exc)

    async def _delete_room_state(self, room_id: str) -> None:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM active_rooms WHERE room_id = $1",
                    room_id,
                )
        except Exception as exc:
            log.warning("[persist] failed to delete room %s: %s", room_id, exc)

    async def restore_all_rooms_from_db(self) -> int:
        """Load all persisted rooms from DB into memory. Returns the count restored.
        Rooms older than DISCONNECT_GRACE_SECONDS + 60s are considered dead and deleted.
        """
        ROOM_TTL = DISCONNECT_GRACE_SECONDS + 60

        try:
            pool = await get_pool()
        except Exception as exc:
            log.warning("[persist] no DB pool for restoration: %s", exc)
            return 0

        try:
            async with pool.acquire() as conn:
                # Eliminar rooms viejas que ya no deberían restaurarse
                deleted = await conn.execute(
                    "DELETE FROM active_rooms WHERE updated_at < NOW() - make_interval(secs => $1)",
                    ROOM_TTL,
                )
                if deleted != "DELETE 0":
                    log.info("[persist] cleaned %s stale room(s)", deleted.replace("DELETE ", ""))

                rows = await conn.fetch(
                    "SELECT room_id, state FROM active_rooms ORDER BY updated_at DESC"
                )
        except Exception as exc:
            log.warning("[persist] failed to load persisted rooms: %s", exc)
            return 0

        count = 0
        for row in rows:
            try:
                data = json.loads(row["state"])
                room_id = row["room_id"]
                self._restore_room_from_state(room_id, data)
                game = self.games.get(room_id)
                if game and game.phase == "playing":
                    self._cancel_turn_timeout(room_id)
                    for pid in list(game.players.keys()):
                        self._cancel_disconnect_resolution(room_id, pid)
                count += 1
                log.info("[persist] restored room %s (phase=%s, players=%d)",
                         room_id, game.phase if game else "?", len(game.players) if game else 0)
            except Exception as exc:
                log.warning("[persist] failed to restore room %s: %s", row["room_id"], exc)
                self.games.pop(row["room_id"], None)
                self.connections.pop(row["room_id"], None)
                self.hosts.pop(row["room_id"], None)

        if count > 0:
            log.info("[persist] restored %d room(s) from DB", count)
        return count

    # ------------------------------------------------------------------ connect

    async def connect(self, websocket: WebSocket, room_id: str, player_id: str):
        await websocket.accept()
        self._cancel_room_cleanup(room_id)
        self.games.setdefault(room_id, Game(room_id=room_id))
        self.connections.setdefault(room_id, {})[player_id] = websocket
        await self._send(room_id, player_id, {
            "type": "connected",
            "player_id": player_id,
            "room_id": room_id,
            "challenge_guard_ms": CHALLENGE_GUARD_MS,
            "challenge_consecutive_ms": CHALLENGE_CONSECUTIVE_MS,
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

        # Si no quedan conexiones, programar limpieza diferida para permitir reconexión
        if not self.connections.get(room_id):
            self._schedule_room_cleanup(room_id)
            return

        if not game:
            return

        if player_id in game.spectators:
            spectator_name = game.spectators.pop(player_id, "Espectador")
            self.client_anon_ids.get(room_id, {}).pop(player_id, None)
            await self._broadcast(room_id, {
                "type": "spectator_left",
                "spectator_id": player_id,
                "spectator_name": spectator_name,
                "spectator_count": len(game.spectators),
            })
            return

        # Limpiar sesión admin si corresponde
        self.admin_sessions.get(room_id, set()).discard(player_id)

        if player_id not in game.players:
            return

        player = game.players[player_id]
        turn_changed = game.set_player_connected(player_id, False)
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
            # Backlog #4: if the player on turn left, the next one must be told right away.
            if turn_changed:
                await self._announce_turn(room_id, game)

        await self._persist_room_state(room_id)

    # ------------------------------------------------------------------ dispatch

    async def handle_message(self, room_id: str, player_id: str, msg: dict):
        game = self.games.get(room_id)
        if not game:
            return
        msg_type = msg.get("type")

        # ── Debug/admin messages (solo cuando DEBUG_MODE=true) ──
        if DEBUG_MODE and msg_type == "debug_auth":
            self.admin_sessions.setdefault(room_id, set()).add(player_id)
            await self._send_debug_full_state(room_id, player_id)
            return
        if DEBUG_MODE and msg_type == "debug_cmd" and player_id in self.admin_sessions.get(room_id, set()):
            await self._h_debug_cmd(room_id, player_id, game, msg)
            return

        # ── Sala pausada: los bots no actúan ──
        if room_id in self.paused_rooms and msg_type in {"bid", "dudo", "calzo", "paso", "direction", "ready", "start", "select_bid"}:
            player = game.players.get(player_id)
            if player and player.is_bot:
                return

        _spectator_allowed = {"join", "emoji", "quick_chat", "audio_clip", "become_player"}
        if player_id in game.spectators and game.phase == "lobby" and self._host_id(room_id, game) == player_id:
            _spectator_allowed |= {"set_rules", "kick_player", "add_bot", "remove_bot", "start"}
        if player_id in game.spectators and msg_type not in _spectator_allowed:
            return
        if player_id in self.admin_sessions.get(room_id, set()):
            return  # admin no participa en el juego normal
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
            "audio_clip": self._h_audio_clip,
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


    def _track_anon_id(self, room_id: str, player_id: str, anon_id: str | None) -> None:
        normalized = normalize_anon_id(anon_id)
        if not normalized:
            return
        self.client_anon_ids.setdefault(room_id, {})[player_id] = normalized

    def _anon_for(self, room_id: str, player_id: str, game: Game | None = None) -> str | None:
        if game:
            player = game.players.get(player_id)
            if player and player.anon_id:
                return player.anon_id
        return self.client_anon_ids.get(room_id, {}).get(player_id)

    def is_anon_present(self, room_id: str, anon_id: str | None) -> bool:
        normalized = normalize_anon_id(anon_id)
        if not normalized:
            return False
        game = self.games.get(room_id)
        if not game:
            return False

        for player in game.players.values():
            if player.connected and player.anon_id == normalized:
                return True

        room_anon = self.client_anon_ids.get(room_id, {})
        for spectator_id in game.spectators:
            if room_anon.get(spectator_id) == normalized:
                return True
        return False

    async def notify_audio_clips_updated(self, room_id: str, anon_id: str) -> None:
        if room_id not in self.games:
            return
        await self._broadcast(room_id, {
            "type": "audio_clips_updated",
            "anon_id": anon_id,
        })

    # ------------------------------------------------------------------ handlers

    async def _h_join(self, room_id, player_id, game, msg):
        # ── Intento de reconexión ─────────────────────────────────────────────
        anon_id = normalize_anon_id(msg.get("anon_id"))
        self._track_anon_id(room_id, player_id, anon_id)
        reconnect_id = msg.get("reconnect_id")
        if reconnect_id and reconnect_id in game.spectators:
            old_name = game.spectators[reconnect_id]
            ws = self.connections[room_id].pop(player_id, None)
            if ws:
                self.connections[room_id][reconnect_id] = ws
            if anon_id:
                self._track_anon_id(room_id, reconnect_id, anon_id)
            self.client_anon_ids.get(room_id, {}).pop(player_id, None)
            game.spectators[reconnect_id] = old_name
            await self._send(room_id, reconnect_id, {
                "type": "joined_spectator",
                "spectator_id": reconnect_id,
                "spectator_name": old_name,
                **self._spectator_state_payload(game),
            })
            await self._persist_room_state(room_id)
            return

        if reconnect_id and reconnect_id in game.players and game.phase in {"playing", "lobby", "reveal"}:
            old = game.players[reconnect_id]
            # Permitir takeover incluso si aún figura conectado (carrera de desconexión).
            ws = self.connections[room_id].pop(player_id, None)
            if ws:
                self.connections[room_id][reconnect_id] = ws
            if anon_id:
                old.anon_id = anon_id
                self._track_anon_id(room_id, reconnect_id, anon_id)
            self.client_anon_ids.get(room_id, {}).pop(player_id, None)
            game.set_player_connected(reconnect_id, True)
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
                "streaks": game.streaks,
                "best_streaks": game.best_streaks,
"challenge_guard_ms": CHALLENGE_GUARD_MS,
            "challenge_consecutive_ms": CHALLENGE_CONSECUTIVE_MS,
            })
            await self._broadcast_except(room_id, reconnect_id, {
                "type": "player_reconnected",
                "player_id": reconnect_id,
                "player_name": old.name,
            })

            if host_changed_msg:
                await self._broadcast(room_id, host_changed_msg)

            if game.phase in {"playing", "reveal"}:
                # Reenviar estado actual de la partida al jugador reconectado
                reconnect_players = {p: pl.to_public_dict() for p, pl in game.players.items()}
                if game.rules.allow_ghost_gavilan:
                    for pid, pl in game.players.items():
                        if pl.dice_count <= 0:
                            reconnect_players[pid]["ghost_cooldown"] = game.ghost_cooldown_for(pid)
                await self._send(room_id, reconnect_id, {
                    "type": "your_dice",
                    "dice": old.dice,
                    "round_number": game.round_number,
                    "total_dice": game.total_dice(),
                    "players": reconnect_players,
                    "has_passed": reconnect_id in game.passed_players,
                })
                await self._announce_turn(room_id, game)
            await self._persist_room_state(room_id)
            return

        if game.phase == "lobby" and player_id in game.spectators:
            game.spectators.pop(player_id, None)

        # ── Unirse nuevo ──────────────────────────────────────────────────────
        if game.phase != "lobby":
            spectator_name = _clean_name(msg.get("name"), "Espectador")
            if anon_id:
                self._track_anon_id(room_id, player_id, anon_id)
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
            await self._persist_room_state(room_id)
            return
        # Sin límite de jugadores en el join del lobby: el límite se aplica al iniciar partida.
        # Permite que espectadores pasen a jugadores libremente hasta que empiece el juego.

        # Limpiar zombies del mismo anon_id antes de crear nueva entrada
        if anon_id:
            zombies = [
                pid for pid, p in game.players.items()
                if p.anon_id == anon_id and not p.connected
            ]
            for zid in zombies:
                game.player_order[:] = [pid for pid in game.player_order if pid != zid]
                game.players.pop(zid, None)
                self.admin_sessions.get(room_id, set()).discard(zid)
                self.client_anon_ids.get(room_id, {}).pop(zid, None)

        name = _clean_name(msg.get("name"), f"Jugador {len(game.players) + 1}")
        avatar = self._normalize_avatar(msg.get("avatar"))
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
            "challenge_guard_ms": CHALLENGE_GUARD_MS,
            "challenge_consecutive_ms": CHALLENGE_CONSECUTIVE_MS,
        })
        await self._broadcast_except(room_id, player_id, {
            "type": "player_joined",
            "player": player.to_public_dict(),
        })
        await self._persist_room_state(room_id)

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
        await self._persist_room_state(room_id)

    async def _h_rename(self, room_id, player_id, game, msg):
        if player_id not in game.players or game.phase != "lobby":
            return
        player = game.players[player_id]
        new_name = _clean_name(msg.get("name"), player.name)
        new_avatar = self._normalize_avatar(msg.get("avatar")) if msg.get("avatar") else player.avatar
        player.name = new_name
        player.avatar = new_avatar
        await self._broadcast(room_id, {
            "type": "player_renamed",
            "player_id": player_id,
            "name": new_name,
            "avatar": new_avatar,
        })
        await self._persist_room_state(room_id)

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
        # Resetear estado "listo" de humanos al cambiar reglas (bots siempre listos)
        for player in game.players.values():
            if not player.is_bot:
                player.ready = False
        await self._broadcast(room_id, {
            "type": "rules_updated",
            "rules": game.rules.to_dict(),
            "players": {pid: p.to_public_dict() for pid, p in game.players.items()},
        })
        await self._persist_room_state(room_id)

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

        await self._persist_room_state(room_id)

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
        if difficulty not in {"easy", "medium", "hard", "very_hard", "expert"}:
            difficulty = "medium"

        bot_names = {
            "easy":      ["Botín", "Novato", "Pipón", "Torpe"],
            "medium":    ["Calculín", "Medio", "Astuto", "Listo"],
            "hard":      ["Maestro", "Genio", "Experto", "HAL"],
            "very_hard": ["Oráculo", "Némesis", "Profeta", "Centinela"],
            "expert":    ["Absoluto", "Nexus", "Axioma", "Sísifo"],
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
        await self._persist_room_state(room_id)

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
        await self._persist_room_state(room_id)

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
        self._track_anon_id(room_id, player_id, player.anon_id)

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
        await self._persist_room_state(room_id)

    async def _h_become_player(self, room_id, player_id, game, msg):
        """Un espectador en el lobby decide unirse como jugador."""
        if game.phase != "lobby":
            return await self._send(room_id, player_id,
                                    {"type": "error", "message": "Solo puedes cambiar de rol en el lobby"})
        if player_id not in game.spectators:
            return

        spectator_name = game.spectators.pop(player_id)
        player = Player(
            id=player_id,
            name=spectator_name,
            avatar=self._normalize_avatar(msg.get("avatar")),
            anon_id=self._anon_for(room_id, player_id, game),
        )
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
        await self._persist_room_state(room_id)

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
        self.client_anon_ids.get(room_id, {}).pop(player_id, None)
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
        await self._persist_room_state(room_id)

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
        await self._persist_room_state(room_id)

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

        if bid.quantity > MAX_BID_QUANTITY:
            return await self._send(room_id, player_id,
                                    {"type": "error",
                                     "message": f"La cantidad máxima es {MAX_BID_QUANTITY}"})

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
        await self._persist_room_state(room_id)

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

        if bid.quantity > MAX_BID_QUANTITY or not game.is_valid_bid(bid):
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
        game.pasos_count[player_id] = game.pasos_count.get(player_id, 0) + 1
        await self._announce_turn(room_id, game)
        await self._persist_room_state(room_id)

    async def _h_dudo(self, room_id, player_id, game, msg):
        if game.phase != "playing":
            return
        self._cancel_turn_timeout(room_id)

        action = DudoAction(game, player_id, self._rules_engine(game))
        error = action.validate()
        if error:
            return await self._send(room_id, player_id, {"type": "error", "message": error})

        result = action.resolve()

        # Gavilán fantasma fallido: nadie se entera
        if result.is_ghost:
            if isinstance(result, DudoPasoResult):
                challenger_won = not result.paso_valid
            else:
                challenger_won = not result.bid_holds
            if not challenger_won:
                game.record_ghost_failure(player_id)
                await self._send(room_id, player_id, {
                    "type": "ghost_failed",
                    "ghost_cooldown": game.ghost_cooldown_for(player_id),
                    "ghost_failures": game.ghost_failures.get(player_id, 0),
                })
                return
            # Fantasma exitoso: contar intento para próximo cooldown progresivo
            game.ghost_failures[player_id] = game.ghost_failures.get(player_id, 0) + 1

        action.apply(result)

        # Actualizar racha del retador
        if isinstance(result, DudoPasoResult):
            challenger_won = not result.paso_valid
        else:
            challenger_won = not result.bid_holds
        self._update_streak(game, result.challenger_id, challenger_won)
        if challenger_won and result.loser_id != result.challenger_id:
            game.streaks[result.loser_id] = 0

        # Estadísticas
        game.dudos_count[player_id] = game.dudos_count.get(player_id, 0) + 1
        if challenger_won:
            game.dudos_won[player_id] = game.dudos_won.get(player_id, 0) + 1
        if result.loser_id:
            game.dice_lost[result.loser_id] = game.dice_lost.get(result.loser_id, 0) + 1
        if challenger_won and result.loser_id and result.loser_id != result.challenger_id:
            game.dice_taken[result.challenger_id] = game.dice_taken.get(result.challenger_id, 0) + 1
        if result.is_gavilan:
            if challenger_won:
                game.gavilanes_won[player_id] = game.gavilanes_won.get(player_id, 0) + 1
            else:
                game.gavilanes_lost[player_id] = game.gavilanes_lost.get(player_id, 0) + 1
        if result.is_ghost and challenger_won:
            game.ghost_revivals[player_id] = game.ghost_revivals.get(player_id, 0) + 1
        if challenger_won and not isinstance(result, DudoPasoResult):
            diff = result.bid.quantity - result.actual_count
            prev = game.hardest_dudo.get(player_id, {"diff": -1})
            if diff > prev["diff"]:
                game.hardest_dudo[player_id] = {"qty": result.bid.quantity, "face": result.bid.face, "diff": diff}

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
                "ghost_revival": result.is_ghost,
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
                "ghost_revival": result.is_ghost,
            }
            await self._broadcast(room_id, reveal_payload)

        bot_engine.notify_reveal(game, reveal_payload)

        # Bot chat: enviar inmediatamente (sin delay) mientras el frontend aún
        # muestra la fase reveal, no esperar a que _new_round avance a la
        # siguiente ronda.
        if game.players.get(player_id, None) and game.players[player_id].is_bot:
            await self._bot_chat_immediate(room_id, player_id, "dudo")

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

        # Gavilán fantasma fallido: nadie se entera
        if result.is_ghost and not result.exact:
            game.record_ghost_failure(player_id)
            await self._send(room_id, player_id, {
                "type": "ghost_failed",
                "ghost_cooldown": game.ghost_cooldown_for(player_id),
                "ghost_failures": game.ghost_failures.get(player_id, 0),
            })
            return

        # Fantasma exitoso: contar intento para próximo cooldown progresivo
        if result.is_ghost:
            game.ghost_failures[player_id] = game.ghost_failures.get(player_id, 0) + 1

        action.apply(result)

        # Actualizar racha del retador
        self._update_streak(game, result.challenger_id, result.exact)

        # Estadísticas
        game.calzos_count[player_id] = game.calzos_count.get(player_id, 0) + 1
        if result.exact:
            game.calzos_hit[player_id] = game.calzos_hit.get(player_id, 0) + 1
        if result.loser_id:
            game.dice_lost[result.loser_id] = game.dice_lost.get(result.loser_id, 0) + 1
        if result.is_gavilan:
            if result.exact:
                game.gavilanes_won[player_id] = game.gavilanes_won.get(player_id, 0) + 1
            else:
                game.gavilanes_lost[player_id] = game.gavilanes_lost.get(player_id, 0) + 1
        if result.is_ghost and result.exact:
            game.ghost_revivals[player_id] = game.ghost_revivals.get(player_id, 0) + 1
        if result.exact and result.loser_id and result.loser_id != result.challenger_id:
            game.dice_taken[result.challenger_id] = game.dice_taken.get(result.challenger_id, 0) + 1
        if result.challenger_gained:
            game.calzo_gains[result.challenger_id] = game.calzo_gains.get(result.challenger_id, 0) + 1

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
            "ghost_revival": result.is_ghost,
        }
        await self._broadcast(room_id, calzo_payload)
        bot_engine.notify_reveal(game, calzo_payload)

        # Bot chat inmediato (misma razón que en _h_dudo)
        if game.players.get(player_id, None) and game.players[player_id].is_bot:
            await self._bot_chat_immediate(room_id, player_id, "calzo")

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

    ALLOWED_QUICK_PHRASES = {entry["text"] for entry in _QUICK_PHRASES_DATA}

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

    async def _h_audio_clip(self, room_id, player_id, game, msg):
        clip_kind = msg.get("clip_kind")
        if clip_kind not in {"system", "player"}:
            clip_kind = "player"

        sender = game.players.get(player_id)
        sender_name = sender.name if sender else game.spectators.get(player_id, "?")
        sender_avatar = sender.avatar if sender else "👁"

        if clip_kind == "system":
            clip_id = msg.get("clip_id")
            if not isinstance(clip_id, str):
                return
            clip = get_system_audio_clip_by_id(clip_id)
            if not clip:
                return
            payload = {
                "type": "audio_clip",
                "from_id": player_id,
                "from_name": sender_name,
                "from_avatar": sender_avatar,
                "clip_kind": "system",
                "clip_id": clip["id"],
                "clip_label": clip.get("label") or "Audio",
                "clip_emoji": clip.get("emoji") or "🎵",
                "clip_url": clip.get("stream_url"),
            }
            clip_color = clip.get("color")
            if isinstance(clip_color, str):
                payload["clip_color"] = clip_color
            await self._broadcast(room_id, payload)
            return

        clip_id = msg.get("clip_id")
        if not isinstance(clip_id, int):
            return

        try:
            pool = await get_pool()
            clip = await fetch_player_audio_clip_by_id(pool, clip_id)
        except Exception as exc:
            log.warning("No se pudo cargar audio %s: %s", clip_id, exc)
            return
        if not clip:
            return

        # El audio solo se puede disparar mientras el dueño del clip sigue presente
        # en la sala (igual que el endpoint de streaming). Cualquier jugador o
        # espectador presente puede disparar el audio de cualquier otro presente.
        if not self.is_anon_present(room_id, clip["anon_id"]):
            return

        payload = {
            "type": "audio_clip",
            "from_id": player_id,
            "from_name": sender_name,
            "from_avatar": sender_avatar,
            "clip_kind": "player",
            "clip_id": clip_id,
            "clip_label": clip.get("label") or "Audio",
            "clip_emoji": clip.get("emoji") or "🎵",
            "clip_url": build_player_clip_stream_url(clip_id, clip["updated_at"], room_id),
        }
        clip_color = clip.get("color")
        if isinstance(clip_color, str):
            payload["clip_color"] = clip_color
        await self._broadcast(room_id, payload)

    # ------------------------------------------------------------------ game flow

    async def _begin_game(self, room_id: str, game: Game):
        game.phase = "playing"
        game.round_number = 1
        for player in game.players.values():
            player.dice_count = 5
            player.ready = False
        game.initial_total_dice = game.total_dice()
        game.roll_all_dice()
        game.current_bid = None
        game.last_paso = None
        game.passed_players = set()
        game.bid_history = []
        game.direction = 1
        game.elimination_order = []
        game.streaks = {}
        game.best_streaks = {}
        game.ghost_failures = {}
        game.ghost_cooldown = {}
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
        await self._persist_room_state(room_id)

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
            if game.rules.allow_ghost_gavilan:
                game.init_ghost_cooldown(loser_id)
            await self._broadcast(room_id, {
                "type": "player_eliminated",
                "player_id": loser_id,
                "player_name": p.name,
            })

        await self._persist_room_state(room_id)
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
        game.tick_ghost_cooldowns()
        game.roll_all_dice()
        game.set_current_player(first_player_id)
        game.round_first_player = first_player_id

        await self._broadcast(room_id, {
            "type": "new_round",
            "round_number": game.round_number,
        })
        await self._send_dice(room_id, game)
        await self._announce_turn(room_id, game)
        await self._persist_room_state(room_id)

    async def _end_game(self, room_id: str, game: Game, outcome):
        game.phase = "lobby"
        self._cancel_turn_timeout(room_id)

        # Construir standings: ganador primero (posición 1), luego por orden de eliminación inverso
        survivors = []
        for pid in game.player_order:
            p = game.players.get(pid)
            if p and p.connected and p.dice_count > 0:
                survivors.append({
                    "id": pid,
                    "name": p.name,
                    "avatar": p.avatar,
                    "round": game.round_number,
                })
        # survivors first (winner = pos 1), then eliminated in reverse order (last eliminated = pos 2, etc.)
        standings = survivors + list(reversed(game.elimination_order))

        # Estadísticas divertidas por jugador
        player_stats = {}
        for pid, p in game.players.items():
            hd = game.hardest_dudo.get(pid)
            gav_won = game.gavilanes_won.get(pid, 0)
            gav_lost = game.gavilanes_lost.get(pid, 0)
            gho_won = game.ghost_revivals.get(pid, 0)
            gho_fail = game.ghost_failures.get(pid, 0)
            player_stats[pid] = {
                "streak":       game.best_streaks.get(pid, 0),
                "pasos":        game.pasos_count.get(pid, 0),
                "gavilanes":    f"{gav_won}/{gav_won+gav_lost}" if (gav_won+gav_lost) > 0 else None,
                "ghost":        f"{gho_won}/{gho_won+gho_fail}" if (gho_won+gho_fail) > 0 else None,
                "hardest_dudo": f"{hd['qty']}x{hd['face']}" if hd else None,
                "dice_lost":    game.dice_lost.get(pid, 0),
                "dice_taken":   game.dice_taken.get(pid, 0),
                "calzo_gains":  game.calzo_gains.get(pid, 0),
            }

        payload = {
            "type": "game_over",
            "result_mode": outcome.kind,
            "rules": game.rules.to_dict(),
            "reveal_seconds": REVEAL_SECONDS,
            "standings": standings,
            "player_stats": player_stats,
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
            if not player.is_bot:
                player.ready = False
            player.dice = []
            player.dice_count = 5
        game.current_bid = None
        game.bid_history = []
        game.round_number = 0
        game.elimination_order = []
        game.streaks = {}
        game.best_streaks = {}
        game.ghost_failures = {}
        game.ghost_cooldown = {}
        game.pasos_count = {}
        game.dudos_count = {}
        game.dudos_won = {}
        game.calzos_count = {}
        game.calzos_hit = {}
        game.gavilanes_won = {}
        game.gavilanes_lost = {}
        game.ghost_revivals = {}
        game.dice_lost = {}
        game.dice_taken = {}
        game.hardest_dudo = {}
        await self._delete_room_state(room_id)

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

        # Buscar bot activo en la partida (expert tiene prioridad sobre very_hard)
        vh      = None
        bot_pid = None
        for difficulty in ("expert", "very_hard"):
            strategy = bot_module._REGISTRY.get(difficulty)
            if not isinstance(strategy, bot_module.VeryHardBot):
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

    @staticmethod
    def _update_streak(game: Game, player_id: str, won: bool) -> None:
        if won:
            game.streaks[player_id] = game.streaks.get(player_id, 0) + 1
            game.best_streaks[player_id] = max(
                game.streaks[player_id],
                game.best_streaks.get(player_id, 0),
            )
        else:
            game.streaks[player_id] = 0

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
        players_dict = {pid: p.to_public_dict() for pid, p in game.players.items()}
        if game.rules.allow_ghost_gavilan:
            for pid, pl in game.players.items():
                if pl.dice_count <= 0:
                    players_dict[pid]["ghost_cooldown"] = game.ghost_cooldown_for(pid)
        return {
            "phase": game.phase,
            "players": players_dict,
            "player_order": game.player_order,
            "rules": game.rules.to_dict(),
            "round_number": game.round_number,
            "total_dice": game.total_dice(),
            "host_id": self._host_id(game.room_id, game),
            "turn": self._turn_payload(game) if game.phase in {"playing", "reveal"} else None,
            "spectator_count": len(game.spectators),
            "challenge_guard_ms": CHALLENGE_GUARD_MS,
            "challenge_consecutive_ms": CHALLENGE_CONSECUTIVE_MS,
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
        players_dict = {p: pl.to_public_dict() for p, pl in game.players.items()}
        if game.rules.allow_ghost_gavilan:
            for pid, pl in game.players.items():
                if pl.dice_count <= 0:
                    players_dict[pid]["ghost_cooldown"] = game.ghost_cooldown_for(pid)
        for pid, player in game.players.items():
            if player.connected:
                payload = {
                    "type": "your_dice",
                    "dice": player.dice,
                    "round_number": game.round_number,
                    "total_dice": game.total_dice(),
                    "initial_total_dice": game.initial_total_dice,
                    "players": players_dict,
                }
                if player.dice_count <= 0 and game.rules.allow_ghost_gavilan:
                    payload["ghost_cooldown"] = game.ghost_cooldown_for(pid)
                    payload["ghost_failures"] = game.ghost_failures.get(pid, 0)
                await self._send(room_id, pid, payload)
        for spectator_id in list(game.spectators.keys()):
            await self._send(room_id, spectator_id, {
                "type": "spectator_state",
                **self._spectator_state_payload(game),
            })
        # Enviar estado completo a sesiones admin
        for aid in list(self.admin_sessions.get(room_id, set())):
            await self._send_debug_full_state(room_id, aid)

    async def _announce_turn(self, room_id: str, game: Game):
        self.turn_started_at[room_id] = time.monotonic()
        await self._broadcast(room_id, self._turn_payload(game))
        self._schedule_turn_timeout(room_id, game)
        # Si el turno es de un bot, programar su acción con un pequeño delay
        current = game.current_player_id()
        if current and current in game.players and game.players[current].is_bot:
            self._schedule_bot_action(room_id, game, current)
        # Gavilán fuera de turno: bots vivos que no son el jugador activo
        if game.current_bid is not None or game.last_paso is not None:
            self._schedule_gavilan_bots(room_id, game)
        # Gavilán fantasma: bots eliminados que pueden actuar
        self._schedule_ghost_bots(room_id, game)

    def _cancel_turn_timeout(self, room_id: str):
        task = self.turn_timeout_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_disconnect_resolution(self, room_id: str, player_id: str):
        key = (room_id, player_id)
        task = self.disconnect_resolution_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    def _schedule_room_cleanup(self, room_id: str):
        self._cancel_room_cleanup(room_id)

        async def _runner():
            try:
                await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
                self._cancel_turn_timeout(room_id)
                self._cancel_disconnect_resolution_for_room(room_id)
                self.games.pop(room_id, None)
                self.connections.pop(room_id, None)
                self.hosts.pop(room_id, None)
                self.admin_sessions.pop(room_id, None)
                self.client_anon_ids.pop(room_id, None)
                self.paused_rooms.discard(room_id)
                asyncio.create_task(self._delete_room_state(room_id))
                log.info("[room] %s limpiada tras gracia de desconexión", room_id)
            except asyncio.CancelledError:
                return
            finally:
                self.room_cleanup_tasks.pop(room_id, None)

        self.room_cleanup_tasks[room_id] = asyncio.create_task(_runner())

    def _cancel_room_cleanup(self, room_id: str):
        task = self.room_cleanup_tasks.pop(room_id, None)
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
    _BOT_THINK_DELAY = {"easy": 1.8, "medium": 1.2, "hard": 0.7, "very_hard": 0.5, "expert": 0.5}
    # Delay extra cuando hay humanos en juego (para parecer más natural).
    # hard/very_hard/expert subidos para dar tiempo real a gavilanes y sentirse menos robóticos.
    _BOT_HUMAN_DELAY_EXTRA = {"easy": 3.0, "medium": 2.0, "hard": 2.5, "very_hard": 2.5, "expert": 2.0}

    # Delays para gavilán vivo fuera de turno.
    # base mínimo = 1.0s para todos; jitter asimétrico (sesgado a valores altos
    # con random.random()**0.4): bots lentos ocasionalmente reaccionan rápido.
    # Jitters reducidos vs versión anterior para que hard/medium tengan chance real
    # contra bots rápidos en turno (jugada pésima: hard ~50%, medium ~21%, easy ~13%).
    _BOT_GAVILAN_LIVE_BASE   = {"easy": 1.0, "medium": 1.0, "hard": 1.0, "very_hard": 1.0, "expert": 1.0}
    _BOT_GAVILAN_LIVE_JITTER = {"easy": 9.0, "medium": 7.0, "hard": 5.0, "very_hard": 4.5, "expert": 3.0}

    # Delays para gavilán fantasma (bot eliminado).
    # Ligeramente más lentos que el gavilán vivo — el bot "muerto" tarda más.
    _BOT_GHOST_BASE   = {"easy": 1.0, "medium": 1.0, "hard": 1.0, "very_hard": 1.0, "expert": 1.0}
    _BOT_GHOST_JITTER = {"easy": 11.0, "medium": 8.5, "hard": 6.0, "very_hard": 5.5, "expert": 3.5}

    # Rank numérico por dificultad — usado para calcular la reducción de delay
    # por probabilidad baja de apuesta (urgency).
    _BOT_LEVEL_RANK = {"easy": 0, "medium": 1, "hard": 2, "very_hard": 3, "expert": 4}

    # Frases por categoría para el chat de bots (se deriva de quick_phrases.json)
    _BOT_PHRASES: dict = {}
    for _entry in _QUICK_PHRASES_DATA:
        for _cat in _entry.get("categories", []):
            _BOT_PHRASES.setdefault(_cat, []).append(_entry["text"])
    del _entry, _cat  # no contaminar el namespace de la clase

    # Por dificultad y acción: (probabilidad, [categorías de frases disponibles])
    _BOT_CHAT_CONFIG: dict = {
        "easy":      {"bid":  (0.55, ["taunt", "confusion"]),
                      "dudo": (0.65, ["confusion"]),
                      "calzo":(0.65, ["confusion"]),
                      "paso": (0.50, ["confusion", "taunt"])},
        "medium":    {"bid":  (0.40, ["taunt", "bluff", "confusion"]),
                      "dudo": (0.50, ["taunt", "truth_dudo", "confusion"]),
                      "calzo":(0.50, ["calzo_msg", "taunt", "confusion"]),
                      "paso": (0.35, ["taunt", "confusion"])},
        "hard":      {"bid":  (0.30, ["taunt", "bluff", "truth_bid"]),
                      "dudo": (0.38, ["truth_dudo", "bluff"]),
                      "calzo":(0.38, ["calzo_msg"]),
                      "paso": (0.25, ["taunt", "bluff"])},
        "very_hard": {"bid":  (0.22, ["taunt", "bluff", "truth_bid"]),
                      "dudo": (0.30, ["truth_dudo", "bluff"]),
                      "calzo":(0.30, ["calzo_msg"]),
                      "paso": (0.18, ["taunt", "bluff"])},
        "expert":    {"bid":  (0.15, ["taunt", "bluff", "truth_bid"]),
                      "dudo": (0.22, ["truth_dudo", "bluff"]),
                      "calzo":(0.22, ["calzo_msg"]),
                      "paso": (0.12, ["taunt", "bluff"])},
    }

    def _schedule_bot_action(self, room_id: str, game: Game, bot_id: str):
        difficulty = game.players[bot_id].bot_difficulty
        humans_active = any(
            not p.is_bot and p.dice_count > 0
            for pid, p in game.players.items() if pid != bot_id
        )
        base_delay = self._BOT_THINK_DELAY.get(difficulty, 1.2)
        if humans_active:
            base_delay += self._BOT_HUMAN_DELAY_EXTRA.get(difficulty, 1.0)
        delay = base_delay + random.uniform(0, 1.5 if humans_active else 0.8)

        async def _runner():
            try:
                await asyncio.sleep(delay)
                current_game = self.games.get(room_id)
                if not current_game or current_game.phase != "playing":
                    return
                is_ghost = current_game.can_ghost_gavilan(bot_id)
                if current_game.current_player_id() != bot_id and not is_ghost:
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

    def _gavilan_delay(self, difficulty: str, prob: float, jitter_table: dict, base_table: dict) -> float:
        """
        Calcula el delay para un gavilán fuera de turno (vivo o fantasma).

        Distribución no lineal: random.random()**0.4 sesga hacia valores altos del
        rango, de modo que los delays cortos son posibles pero poco probables.
        Todos los bots comparten el mismo base mínimo (~1s) pero el jitter máximo
        crece mucho para los niveles bajos → bots lentos ocasionalmente ganan el
        timing a bots rápidos.

        Urgency con curva cóncava (prob**0.6): más agresiva en el rango bajo-medio
        (0.20–0.40) donde ocurren la mayoría de los gavilanes, sin colapsar el delay
        en los extremos. Rango: 0.35 (prob=0) → 1.0 (prob=1).
        """
        base   = base_table.get(difficulty, 1.0)
        jitter = jitter_table.get(difficulty, 7.0)
        # Sesgo: valores bajos del rango son raros (exponente < 1 acumula cerca del máximo)
        raw_jitter = jitter * (random.random() ** 0.4)
        # Urgency cóncava: reduce más agresivamente en el rango bajo-medio
        p = max(0.0, min(1.0, prob))
        urgency = 0.35 + 0.65 * (p ** 0.6)
        return base + raw_jitter * urgency

    def _schedule_gavilan_bots(self, room_id: str, game: Game):
        """
        Programa intentos de gavilán vivo para bots activos que no son el turno actual
        y tienen la mecánica habilitada (GAVILAN_LIVE_ENABLED o _gavilan_allowed).
        """
        current = game.current_player_id()
        bid = game.current_bid
        if bid is None and game.last_paso is None:
            return
        prob = 0.5  # fallback si no hay bid
        if bid is not None:
            # Estimación de prob desde el punto de vista de un bot genérico
            # (cada bot calculará la suya en decide(), este valor solo afecta el delay)
            total = game.total_dice()
            p_match = 1/6 if bid.face == 1 else 2/6
            import math
            prob = sum(
                math.comb(total, i) * (p_match ** i) * ((1 - p_match) ** (total - i))
                for i in range(bid.quantity, total + 1)
            ) if total >= bid.quantity else 0.0
            prob = max(0.0, min(1.0, prob))

        for pid, player in game.players.items():
            if not player.is_bot:
                continue
            if player.dice_count == 0:
                continue
            if pid == current:
                continue  # es su turno — ya tiene _schedule_bot_action
            if bid is not None and bid.player_id == pid:
                continue  # es su propia apuesta
            self._schedule_single_gavilan_bot(room_id, game, pid, bid, prob)

    def _schedule_single_gavilan_bot(
        self, room_id: str, game: Game, bot_id: str,
        bid_snapshot: object, prob: float
    ):
        # Cancelar task previo de este bot en esta sala para evitar duplicados
        key = (room_id, bot_id)
        old = self.gavilan_tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        difficulty = game.players[bot_id].bot_difficulty
        delay = self._gavilan_delay(
            difficulty, prob,
            self._BOT_GAVILAN_LIVE_JITTER,
            self._BOT_GAVILAN_LIVE_BASE,
        )

        async def _runner():
            try:
                await asyncio.sleep(delay)
                current_game = self.games.get(room_id)
                if not current_game or current_game.phase != "playing":
                    return
                # Si el bid cambió durante el delay → cancelar (el nuevo _announce_turn
                # ya habrá programado un nuevo intento con el bid actualizado)
                if current_game.current_bid is not bid_snapshot:
                    return
                if game.last_paso is not None and current_game.last_paso is not game.last_paso:
                    return
                # Verificar que el bot sigue vivo y fuera de turno
                player = current_game.players.get(bot_id)
                if not player or player.dice_count == 0:
                    return
                if current_game.current_player_id() == bot_id:
                    return  # ya es su turno, _schedule_bot_action lo manejará
                await self._run_bot_action(room_id, current_game, bot_id)
            except asyncio.CancelledError:
                return
            except Exception as e:
                import traceback
                print(f"[gavilan bot error] {bot_id}: {e}\n{''.join(traceback.format_exc())}")
            finally:
                self.gavilan_tasks.pop(key, None)

        self.gavilan_tasks[key] = asyncio.create_task(_runner())

    def _schedule_ghost_bots(self, room_id: str, game: Game):
        """
        Programa intentos de gavilán fantasma para bots eliminados que pueden actuar.
        """
        bid = game.current_bid
        prob = 0.5
        if bid is not None:
            import math
            total = game.total_dice()
            p_match = 1/6 if bid.face == 1 else 2/6
            prob = sum(
                math.comb(total, i) * (p_match ** i) * ((1 - p_match) ** (total - i))
                for i in range(bid.quantity, total + 1)
            ) if total >= bid.quantity else 0.0
            prob = max(0.0, min(1.0, prob))

        for pid, player in game.players.items():
            if not player.is_bot:
                continue
            if player.dice_count > 0:
                continue
            if not game.can_ghost_gavilan(pid):
                continue
            self._schedule_single_ghost_bot(room_id, game, pid, bid, prob)

    def _schedule_single_ghost_bot(
        self, room_id: str, game: Game, bot_id: str,
        bid_snapshot: object, prob: float
    ):
        # Cancelar task previo de este bot fantasma en esta sala
        key = (room_id, bot_id + ":ghost")
        old = self.gavilan_tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        difficulty = game.players[bot_id].bot_difficulty
        delay = self._gavilan_delay(
            difficulty, prob,
            self._BOT_GHOST_JITTER,
            self._BOT_GHOST_BASE,
        )

        async def _runner():
            try:
                await asyncio.sleep(delay)
                current_game = self.games.get(room_id)
                if not current_game or current_game.phase != "playing":
                    return
                # Si el bid cambió → cancelar (el siguiente _announce_turn reprogramará)
                if current_game.current_bid is not bid_snapshot:
                    return
                if not current_game.can_ghost_gavilan(bot_id):
                    return
                await self._run_bot_action(room_id, current_game, bot_id)
            except asyncio.CancelledError:
                return
            except Exception as e:
                import traceback
                print(f"[ghost bot error] {bot_id}: {e}\n{''.join(traceback.format_exc())}")
            finally:
                self.gavilan_tasks.pop(key, None)

        self.gavilan_tasks[key] = asyncio.create_task(_runner())

    async def _maybe_bot_chat(self, room_id: str, bot_id: str, action: str):
        game = self.games.get(room_id)
        if not game or not game.rules.bot_chat_enabled:
            return
        player = game.players.get(bot_id)
        if not player:
            return
        difficulty = player.bot_difficulty
        action_cfg = self._BOT_CHAT_CONFIG.get(difficulty, {}).get(action)
        if not action_cfg:
            return
        prob, categories = action_cfg
        if random.random() > prob:
            return
        phrases = self._BOT_PHRASES.get(random.choice(categories), [])
        if not phrases:
            return
        phrase = random.choice(phrases)
        await asyncio.sleep(random.uniform(0.5, 1.8))
        game = self.games.get(room_id)
        if not game or game.phase not in ("playing", "reveal"):
            return
        player = game.players.get(bot_id)
        if not player:
            return
        await self._broadcast(room_id, {
            "type": "quick_chat",
            "from_id": bot_id,
            "from_name": player.name,
            "from_avatar": player.avatar,
            "phrase": phrase,
        })

    async def _bot_chat_immediate(self, room_id: str, bot_id: str, action: str):
        """Como _maybe_bot_chat pero sin sleep ni verificación de fase —
        para usar dentro de _h_dudo / _h_calzo justo después del reveal
        y antes de _apply_loss / _new_round."""
        game = self.games.get(room_id)
        if not game or not game.rules.bot_chat_enabled:
            return
        player = game.players.get(bot_id)
        if not player:
            return
        difficulty = player.bot_difficulty
        action_cfg = self._BOT_CHAT_CONFIG.get(difficulty, {}).get(action)
        if not action_cfg:
            return
        prob, categories = action_cfg
        if random.random() > prob:
            return
        phrases = self._BOT_PHRASES.get(random.choice(categories), [])
        if not phrases:
            return
        phrase = random.choice(phrases)
        await self._broadcast(room_id, {
            "type": "quick_chat",
            "from_id": bot_id,
            "from_name": player.name,
            "from_avatar": player.avatar,
            "phrase": phrase,
        })

    async def _run_bot_action(self, room_id: str, game: Game, bot_id: str):
        if room_id in self.paused_rooms:
            return  # sala pausada, el bot no actúa
        # Cambio de sentido: solo si el bot es round_first_player y no hay acción aún
        if (game.round_first_player == bot_id
                and game.current_bid is None
                and game.last_paso is None):
            direction = bot_engine.decide_direction(game, bot_id)
            if direction is not None:
                await self._h_direction(room_id, bot_id, game, {"value": direction})

        decision = bot_engine.decide(game, bot_id)
        action = decision.get("action")
        is_gavilan = decision.get("gavilan", False)

        # Fuera de turno: solo se permiten dudo/calzo marcados explícitamente
        # como gavilán. Cualquier otra acción (incluyendo dudo por flujo normal)
        # se descarta — el bot no está en turno para actuar normalmente.
        is_off_turn = game.current_player_id() != bot_id
        if is_off_turn and not is_gavilan:
            return

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
                await self._maybe_bot_chat(room_id, bot_id, "paso")
                return
            else:
                action = "bid"  # fallback si no puede pasar

        if action == "bid":
            qty = decision.get("quantity", 1)
            face = decision.get("face", 2)
            self._cancel_turn_timeout(room_id)
            await self._h_bid(room_id, bot_id, game, {"quantity": qty, "face": face})
            await self._maybe_bot_chat(room_id, bot_id, "bid")

    # ------------------------------------------------------------------ debug / admin

    async def _send_debug_full_state(self, room_id: str, admin_pid: str):
        game = self.games.get(room_id)
        if not game:
            return
        players = []
        for pid in game.player_order:
            p = game.players.get(pid)
            if not p:
                continue
            players.append({
                "id": p.id,
                "name": p.name,
                "avatar": p.avatar,
                "dice_count": p.dice_count,
                "dice": list(p.dice) if p.dice else [],
                "connected": p.connected,
                "is_bot": p.is_bot,
            })
        bid_dict = game.current_bid.to_dict() if game.current_bid else None
        await self._send(room_id, admin_pid, {
            "type": "debug_state",
            "phase": game.phase,
            "round_number": game.round_number,
            "player_order": game.player_order,
            "players": players,
            "paused": room_id in self.paused_rooms,
            "current_bid": bid_dict,
            "passed_players": list(game.passed_players),
        })

    async def _h_debug_cmd(self, room_id: str, admin_pid: str, game, msg: dict):
        cmd = msg.get("cmd")
        if not isinstance(cmd, str):
            return

        # ── Comandos que no dependen de un jugador ──
        if cmd == "set_paused":
            paused = msg.get("paused", False)
            if paused:
                self.paused_rooms.add(room_id)
            else:
                self.paused_rooms.discard(room_id)
                if game.phase == "playing":
                    current = game.current_player_id()
                    if current and current in game.players and game.players[current].is_bot:
                        self._cancel_turn_timeout(room_id)
                        await self._announce_turn(room_id, game)
            await self._broadcast(room_id, {"type": "debug_paused", "paused": paused})
            for aid in list(self.admin_sessions.get(room_id, set())):
                await self._send_debug_full_state(room_id, aid)
            await self._persist_room_state(room_id)
            return

        if cmd == "clear_bid":
            game.current_bid = None
            game.last_paso = None
            game.passed_players.clear()
            await self._announce_turn(room_id, game)
            for aid in list(self.admin_sessions.get(room_id, set())):
                await self._send_debug_full_state(room_id, aid)
            await self._persist_room_state(room_id)
            return

        if cmd == "set_bid":
            qty = msg.get("quantity")
            face = msg.get("face")
            if isinstance(qty, int) and isinstance(face, int) and 1 <= face <= 6 and qty >= 1:
                game.current_bid = Bid(quantity=qty, face=face, player_id="admin", player_name="Admin")
                game.last_paso = None
                await self._announce_turn(room_id, game)
                for aid in list(self.admin_sessions.get(room_id, set())):
                    await self._send_debug_full_state(room_id, aid)
                await self._persist_room_state(room_id)
            return

        # ── Comandos que requieren target_id ──
        target_id = msg.get("target_id")
        if not isinstance(target_id, str):
            return
        player = game.players.get(target_id)
        if not player:
            return

        if cmd == "set_passed":
            passed = msg.get("passed", False)
            if passed:
                game.passed_players.add(target_id)
            else:
                game.passed_players.discard(target_id)
            await self._announce_turn(room_id, game)
            for aid in list(self.admin_sessions.get(room_id, set())):
                await self._send_debug_full_state(room_id, aid)
            await self._persist_room_state(room_id)
            return

        if cmd == "set_dice_count":
            delta = msg.get("delta", 0)
            if not isinstance(delta, int):
                return
            new_count = max(0, min(5, player.dice_count + delta))
            old_count = player.dice_count
            player.dice_count = new_count
            diff = new_count - old_count
            if diff > 0:
                player.dice.extend(random.randint(1, 6) for _ in range(diff))
            elif diff < 0:
                player.dice = player.dice[:new_count]
            if player.dice_count <= 0:
                player.dice = []

        elif cmd == "set_dice":
            dice = msg.get("dice")
            if not isinstance(dice, list):
                return
            dice = [int(d) for d in dice if isinstance(d, (int, float)) and 1 <= int(d) <= 6][:5]
            player.dice = dice
            player.dice_count = len(dice)

        else:
            return

        # Broadcast updated state to all regular players
        await self._send_dice(room_id, game)
        if game.phase in {"playing", "reveal"}:
            await self._announce_turn(room_id, game)

        # Send updated full state to all connected admins
        for aid in list(self.admin_sessions.get(room_id, set())):
            await self._send_debug_full_state(room_id, aid)

        await self._persist_room_state(room_id)

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
