from game.actions import CalzoAction, DudoAction, DudoPasoResult
from game.models import RuleConfig
from game.rules import RuleEngine
from tests.helpers import bid, make_game


def engine(**rules):
    return RuleEngine.from_config(RuleConfig(**rules))


def tutorial_table():
    # Mismo escenario que el manual: hay 4 cuadras contando ases.
    game = make_game({"me": [4, 1, 2, 6, 6], "ana": [4, 3, 1, 5, 2]})
    game.set_current_player("me")
    return game


def test_dudo_wins_when_bid_is_too_high():
    game = tutorial_table()
    game.current_bid = bid(5, 4, "ana")
    result = DudoAction(game, "me", engine()).resolve()
    assert result.actual_count == 4
    assert not result.bid_holds
    assert result.loser_id == "ana"
    assert not result.is_gavilan


def test_dudo_loses_when_bid_holds():
    game = tutorial_table()
    game.current_bid = bid(4, 4, "ana")
    result = DudoAction(game, "me", engine()).resolve()
    assert result.bid_holds
    assert result.loser_id == "me"


def test_cannot_doubt_own_bid():
    game = tutorial_table()
    game.current_bid = bid(3, 4, "me")
    assert DudoAction(game, "me", engine()).validate() == "No puedes dudar tu propia apuesta"


def test_gavilan_respects_room_rule():
    game = make_game({"a": [2, 2], "b": [3, 3], "c": [4, 4]})
    game.set_current_player("b")
    game.current_bid = bid(3, 2, "a")
    assert DudoAction(game, "c", engine(allow_gavilan=False)).validate() is not None
    assert DudoAction(game, "c", engine(allow_gavilan=True)).validate() is None


def test_successful_gavilan_recovers_a_die():
    game = make_game({"a": [2, 2], "b": [3, 3], "c": [4, 4]})
    game.set_current_player("b")
    game.current_bid = bid(5, 6, "a")
    result = DudoAction(game, "c", engine()).resolve()
    assert result.is_gavilan and result.challenger_gained


def test_calzo_exact_and_missed():
    game = make_game({"me": [5, 5, 2, 3, 6], "beto": [1, 4, 4, 2, 6]})
    game.set_current_player("me")
    game.current_bid = bid(3, 5, "beto")
    exact = CalzoAction(game, "me", engine()).resolve()
    assert exact.exact and exact.loser_id is None
    # En su turno no recupera dado salvo que la regla lo permita
    assert not exact.challenger_gained

    game.current_bid = bid(4, 5, "beto")
    missed = CalzoAction(game, "me", engine()).resolve()
    assert not missed.exact and missed.loser_id == "me"


def test_calzo_on_turn_recovers_only_with_rule():
    game = make_game({"me": [5, 5, 2, 3], "beto": [1, 4, 4, 2, 6]})
    game.set_current_player("me")
    game.current_bid = bid(3, 5, "beto")
    result = CalzoAction(game, "me", engine(calzo_recovers_on_turn=True)).resolve()
    assert result.exact and result.challenger_gained


def test_cannot_calzo_a_paso():
    game = tutorial_table()
    game.current_bid = bid(2, 3, "ana")
    game.last_paso = {"player_id": "ana", "player_name": "ANA"}
    assert CalzoAction(game, "me", engine()).validate() == "No se puede calzar un paso"


def test_doubting_a_valid_paso_loses():
    game = make_game({"me": [2, 2, 3, 4, 5], "ana": [1, 2, 3, 4, 5]})
    game.set_current_player("me")
    game.current_bid = bid(2, 3, "me")
    game.last_paso = {"player_id": "ana", "player_name": "ANA"}
    result = DudoAction(game, "me", engine()).resolve()
    assert isinstance(result, DudoPasoResult)
    assert result.paso_valid and result.loser_id == "me"
