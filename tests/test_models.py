import pytest

from tests.helpers import bid, make_game


# ── Apuestas ────────────────────────────────────────────────────────────────

def test_first_bid_can_be_anything_valid():
    game = make_game({"a": [1, 2, 3, 4, 5], "b": [6, 6, 6, 6, 6]})
    assert game.is_valid_bid(bid(1, 2))
    assert game.is_valid_bid(bid(3, 1))


@pytest.mark.parametrize("quantity,face", [(0, 3), (2, 0), (2, 7), (-1, 4)])
def test_out_of_range_bids_are_rejected(quantity, face):
    game = make_game({"a": [1, 2, 3, 4, 5]})
    assert not game.is_valid_bid(bid(quantity, face))


@pytest.mark.parametrize("new,valid", [
    ((3, 6), True),    # misma cantidad, pinta mayor
    ((3, 4), False),   # misma cantidad, misma pinta
    ((3, 2), False),   # misma cantidad, pinta menor
    ((4, 2), True),    # más cantidad, cualquier pinta
    ((2, 6), False),   # menos cantidad
])
def test_raising_regular_bids(new, valid):
    game = make_game({"a": [2, 2, 3, 4, 5], "b": [6, 6, 6, 6, 6]})
    game.current_bid = bid(3, 4)
    assert game.is_valid_bid(bid(*new, "b")) is valid


@pytest.mark.parametrize("old_qty,min_aces", [(5, 3), (6, 3), (7, 4), (1, 1)])
def test_regular_to_aces_needs_half_rounded_up(old_qty, min_aces):
    game = make_game({"a": [2, 3, 4, 5, 6]})
    game.current_bid = bid(old_qty, 4)
    assert game.is_valid_bid(bid(min_aces, 1, "b"))
    if min_aces > 1:
        assert not game.is_valid_bid(bid(min_aces - 1, 1, "b"))


@pytest.mark.parametrize("old_qty,min_regular", [(1, 3), (2, 5), (3, 7)])
def test_aces_to_regular_needs_double_plus_one(old_qty, min_regular):
    game = make_game({"a": [2, 3, 4, 5, 6]})
    game.current_bid = bid(old_qty, 1)
    assert game.is_valid_bid(bid(min_regular, 2, "b"))
    assert not game.is_valid_bid(bid(min_regular - 1, 6, "b"))


def test_aces_to_aces_needs_more_aces():
    game = make_game({"a": [2, 3, 4, 5, 6]})
    game.current_bid = bid(2, 1)
    assert game.is_valid_bid(bid(3, 1, "b"))
    assert not game.is_valid_bid(bid(2, 1, "b"))


# ── Conteo ──────────────────────────────────────────────────────────────────

def test_aces_are_wild_for_regular_faces():
    game = make_game({"a": [4, 1, 2, 6, 6], "b": [4, 3, 1, 5, 2]})
    assert game.count_dice(4) == 4  # dos cuadras + dos ases
    assert game.count_dice(1) == 2  # los ases solo cuentan como ases


def test_disconnected_players_dice_are_not_counted():
    game = make_game({"a": [5, 5, 5], "b": [5, 5]})
    game.players["b"].connected = False
    assert game.count_dice(5) == 3
    assert game.total_dice() == 3


# ── Paso ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dice,valid", [
    ([1, 2, 3, 4, 5], True),    # todos distintos
    ([3, 3, 3, 3, 3], True),    # todos iguales
    ([2, 2, 5, 5, 5], True),    # full
    ([1, 1, 2, 2, 2], True),    # full con ases (no son comodines en el paso)
    ([2, 2, 3, 4, 5], False),   # un par
    ([2, 2, 3, 3, 5], False),   # doble par
    ([1, 2, 3, 4], False),      # solo con 5 dados
])
def test_paso_hands(dice, valid):
    game = make_game({"a": dice})
    assert game.is_valid_paso("a") is valid


# ── Turnos y desconexiones (Backlog #4) ─────────────────────────────────────

def test_disconnect_before_current_player_keeps_the_turn():
    game = make_game({"a": [1], "b": [2], "c": [3]})
    game.set_current_player("c")
    changed = game.set_player_connected("a", False)
    assert not changed
    assert game.current_player_id() == "c"


def test_disconnect_of_current_player_passes_turn_in_direction():
    game = make_game({"a": [1], "b": [2], "c": [3]})
    game.set_current_player("b")
    assert game.set_player_connected("b", False)
    assert game.current_player_id() == "c"

    game = make_game({"a": [1], "b": [2], "c": [3]})
    game.direction = -1
    game.set_current_player("b")
    assert game.set_player_connected("b", False)
    assert game.current_player_id() == "a"


def test_reconnect_does_not_steal_the_turn():
    game = make_game({"a": [1], "b": [2], "c": [3]})
    game.players["a"].connected = False
    game.set_current_player("c")
    assert not game.set_player_connected("a", True)
    assert game.current_player_id() == "c"


def test_advance_turn_skips_eliminated_players():
    game = make_game({"a": [1], "b": [], "c": [3]})
    game.players["b"].dice_count = 0
    game.set_current_player("a")
    game.advance_turn()
    assert game.current_player_id() == "c"
