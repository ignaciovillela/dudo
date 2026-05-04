from game.models import Game, RuleConfig
from game.rules.base import GameOutcome, RulePlugin


class LastStandingOutcomePlugin(RulePlugin):
    def resolve_outcome(self, game: Game, loser_id: str):
        winner_id = game.get_winner()
        if not winner_id:
            return None
        winner = game.players.get(winner_id)
        return GameOutcome(
            kind="winner",
            player_id=winner_id,
            player_name=winner.name if winner else "?",
        )


class FirstEliminatedOutcomePlugin(RulePlugin):
    def resolve_outcome(self, game: Game, loser_id: str):
        loser = game.players.get(loser_id)
        if not loser or loser.dice_count > 0:
            return None
        return GameOutcome(kind="loser", player_id=loser_id, player_name=loser.name)


class GavilanEnabledPlugin(RulePlugin):
    def allow_gavilan(self):
        return True


class GavilanDisabledPlugin(RulePlugin):
    def allow_gavilan(self):
        return False


class CalzoRecoverOffTurnPlugin(RulePlugin):
    def calzo_recovers_on_turn(self):
        return False


class CalzoRecoverOnTurnPlugin(RulePlugin):
    def calzo_recovers_on_turn(self):
        return True


class RuleEngine:
    def __init__(self, plugins: list[RulePlugin]):
        self.plugins = plugins

    @classmethod
    def from_config(cls, config: RuleConfig):
        plugins: list[RulePlugin] = []

        if config.elimination_mode == "loser":
            plugins.append(FirstEliminatedOutcomePlugin())
        else:
            plugins.append(LastStandingOutcomePlugin())

        plugins.append(GavilanEnabledPlugin() if config.allow_gavilan else GavilanDisabledPlugin())
        plugins.append(
            CalzoRecoverOnTurnPlugin() if config.calzo_recovers_on_turn else CalzoRecoverOffTurnPlugin()
        )
        return cls(plugins)

    def allow_gavilan(self) -> bool:
        for plugin in self.plugins:
            value = plugin.allow_gavilan()
            if value is not None:
                return value
        return True

    def calzo_recovers_on_turn(self) -> bool:
        for plugin in self.plugins:
            value = plugin.calzo_recovers_on_turn()
            if value is not None:
                return value
        return False

    def resolve_outcome(self, game: Game, loser_id: str):
        for plugin in self.plugins:
            outcome = plugin.resolve_outcome(game, loser_id)
            if outcome is not None:
                return outcome
        return None

