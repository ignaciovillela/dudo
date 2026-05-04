from dataclasses import dataclass
from typing import Optional

from game.models import Game


@dataclass
class GameOutcome:
    kind: str  # winner | loser
    player_id: str
    player_name: str


class RulePlugin:
    """Plugin base: cada plugin puede sobreescribir hooks específicos."""

    def allow_gavilan(self) -> Optional[bool]:
        return None

    def calzo_recovers_on_turn(self) -> Optional[bool]:
        return None

    def resolve_outcome(self, game: Game, loser_id: str) -> Optional[GameOutcome]:
        return None

