import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Player:
    id: str
    name: str
    avatar: str = "🎲"
    dice: list = field(default_factory=list)
    dice_count: int = 5
    connected: bool = True
    ready: bool = False
    selected_bid: Optional["Bid"] = None  # apuesta seleccionada para timeout
    is_bot: bool = False
    bot_difficulty: str = "medium"  # easy | medium | hard
    anon_id: Optional[str] = None   # ID anónimo persistente del cliente (para memoria entre partidas)

    def to_public_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "avatar": self.avatar,
            "dice_count": self.dice_count,
            "connected": self.connected,
            "ready": self.ready,
            "is_bot": self.is_bot,
            "bot_difficulty": self.bot_difficulty if self.is_bot else None,
        }


@dataclass
class Bid:
    quantity: int
    face: int
    player_id: str
    player_name: str
    elapsed_seconds: float = 0.0   # tiempo desde que era su turno hasta que apostó

    def to_dict(self):
        return {
            "quantity": self.quantity,
            "face": self.face,
            "player_id": self.player_id,
            "player_name": self.player_name,
        }


@dataclass
class RuleConfig:
    elimination_mode: str = "winner"  # winner | loser
    allow_gavilan: bool = True
    calzo_recovers_on_turn: bool = False
    turn_timeout_seconds: int = 0
    allow_throwable_emojis: bool = True
    bot_chat_enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "elimination_mode": self.elimination_mode,
            "allow_gavilan": self.allow_gavilan,
            "calzo_recovers_on_turn": self.calzo_recovers_on_turn,
            "turn_timeout_seconds": self.turn_timeout_seconds,
            "allow_throwable_emojis": self.allow_throwable_emojis,
            "bot_chat_enabled": self.bot_chat_enabled,
        }

    @classmethod
    def from_payload(cls, payload: Optional[dict], current: Optional["RuleConfig"] = None) -> "RuleConfig":
        base = current or cls()
        if not isinstance(payload, dict):
            return cls(
                elimination_mode=base.elimination_mode,
                allow_gavilan=base.allow_gavilan,
                calzo_recovers_on_turn=base.calzo_recovers_on_turn,
                turn_timeout_seconds=base.turn_timeout_seconds,
                allow_throwable_emojis=base.allow_throwable_emojis,
                bot_chat_enabled=base.bot_chat_enabled,
            )

        elimination_mode = payload.get("elimination_mode", base.elimination_mode)
        if elimination_mode not in {"winner", "loser"}:
            elimination_mode = base.elimination_mode

        timeout_seconds = payload.get("turn_timeout_seconds", base.turn_timeout_seconds)
        try:
            timeout_seconds = int(timeout_seconds)
        except (TypeError, ValueError):
            timeout_seconds = base.turn_timeout_seconds
        if timeout_seconds not in {0, 30, 60, 90}:
            timeout_seconds = base.turn_timeout_seconds

        return cls(
            elimination_mode=elimination_mode,
            allow_gavilan=bool(payload.get("allow_gavilan", base.allow_gavilan)),
            calzo_recovers_on_turn=bool(
                payload.get("calzo_recovers_on_turn", base.calzo_recovers_on_turn)
            ),
            turn_timeout_seconds=timeout_seconds,
            allow_throwable_emojis=bool(
                payload.get("allow_throwable_emojis", base.allow_throwable_emojis)
            ),
            bot_chat_enabled=bool(
                payload.get("bot_chat_enabled", base.bot_chat_enabled)
            ),
        )


@dataclass
class Game:
    room_id: str
    players: dict = field(default_factory=dict)
    spectators: dict = field(default_factory=dict)  # spectator_id -> nombre
    phase: str = "lobby"  # lobby | playing | reveal
    player_order: list = field(default_factory=list)
    current_player_idx: int = 0
    current_bid: Optional[Bid] = None
    bid_history: list = field(default_factory=list)
    round_number: int = 0
    last_paso: Optional[dict] = None   # {'player_id', 'player_name'} si la acción activa es un paso
    passed_players: set = field(default_factory=set)  # jugadores que ya pasaron esta ronda
    direction: int = 1              # 1 = horario, -1 = antihorario
    round_first_player: str = ""    # jugador que inicia la ronda (puede cambiar sentido)
    rules: RuleConfig = field(default_factory=RuleConfig)
    elimination_order: list = field(default_factory=list)  # [{"id", "name", "avatar", "round"}] orden de eliminación

    def active_players(self) -> list[str]:
        return [
            pid for pid in self.player_order
            if pid in self.players
            and self.players[pid].dice_count > 0
            and self.players[pid].connected
        ]

    def current_player_id(self) -> str:
        active = self.active_players()
        if not active:
            return ""
        return active[self.current_player_idx % len(active)]

    def set_current_player(self, player_id: str):
        active = self.active_players()
        if player_id in active:
            self.current_player_idx = active.index(player_id)
        elif active:
            self.current_player_idx = 0

    def advance_turn(self):
        active = self.active_players()
        if not active:
            return
        current = self.current_player_id()
        idx = active.index(current) if current in active else 0
        self.current_player_idx = (idx + self.direction) % len(active)

    def roll_all_dice(self):
        for player in self.players.values():
            if player.connected and player.dice_count > 0:
                player.dice = [random.randint(1, 6) for _ in range(player.dice_count)]
            elif player.dice_count == 0:
                player.dice = []

    def count_dice(self, face: int) -> int:
        """Count dice matching face. Ones are wild for faces 2-6."""
        total = 0
        for player in self.players.values():
            if player.connected:
                for d in player.dice:
                    if face == 1:
                        total += d == 1
                    else:
                        total += d == face or d == 1
        return total

    def is_valid_bid(self, bid: "Bid") -> bool:
        if not (1 <= bid.face <= 6 and bid.quantity >= 1):
            return False
        if self.current_bid is None:
            return True
        old = self.current_bid

        # Regular → Ases: mínimo ceil(old_quantity / 2)
        if old.face != 1 and bid.face == 1:
            return bid.quantity >= math.ceil(old.quantity / 2)

        # Ases → Regular: mínimo old_quantity * 2 + 1
        if old.face == 1 and bid.face != 1:
            return bid.quantity >= old.quantity * 2 + 1

        # Dentro de la misma categoría (ambos ases o ambos regular)
        return bid.quantity > old.quantity or (
            bid.quantity == old.quantity and bid.face > old.face
        )

    def is_valid_paso(self, player_id: str) -> bool:
        """Valida si los dados del jugador cumplen las condiciones de paso (sin comodines)."""
        dice = self.players[player_id].dice
        if not dice:
            return False
        counts = Counter(dice)
        if len(dice) != 5:
            return False
        # Todos distintos
        if len(counts) == len(dice):
            return True
        # Todos iguales
        if len(counts) == 1:
            return True
        # Full: exactamente 3 de un valor y 2 de otro (requiere 5 dados)
        if sorted(counts.values()) == [2, 3]:
            return True
        return False

    def total_dice(self) -> int:
        return sum(p.dice_count for p in self.players.values() if p.connected)

    def get_winner(self) -> Optional[str]:
        active = self.active_players()
        return active[0] if len(active) == 1 else None

    def all_ready(self) -> bool:
        human_connected = [p for p in self.players.values() if p.connected and not p.is_bot]
        bots = [p for p in self.players.values() if p.is_bot]
        active = human_connected + bots
        return len(active) >= 2 and all(p.ready for p in human_connected)

    def all_dice_reveal(self) -> dict:
        return {
            pid: player.dice
            for pid, player in self.players.items()
            if player.connected
        }
