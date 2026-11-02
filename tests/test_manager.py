import asyncio
import json

import pytest

from game.config import MAX_BID_QUANTITY
from game.manager import GameManager
from tests.helpers import make_game


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    def of_type(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


@pytest.fixture
def manager(monkeypatch):
    async def no_persist(self, room_id):
        return None
    # Sin base de datos en los tests
    monkeypatch.setattr(GameManager, "_persist_room_state", no_persist)
    return GameManager()


def seat(manager, hands, current):
    game = make_game(hands)
    game.set_current_player(current)
    game.round_first_player = current
    manager.games["test"] = game
    sockets = {pid: FakeWebSocket() for pid in hands}
    manager.connections["test"] = dict(sockets)
    manager.hosts["test"] = next(iter(hands))
    return game, sockets


def run(coro):
    async def wrapper():
        try:
            return await coro
        finally:
            # Cancelar timers (resolución de desconexión, etc.) para cerrar limpio
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
    return asyncio.run(wrapper())


def test_disconnect_of_player_on_turn_announces_next_turn(manager):
    """Backlog #4: la partida no puede quedar congelada esperando a quien se fue."""
    game, ws = seat(manager, {"a": [2, 3], "b": [4, 5], "c": [6, 1]}, current="b")
    run(manager.disconnect("test", "b"))
    turns = ws["c"].of_type("turn")
    assert turns, "el siguiente jugador debe recibir el turno de inmediato"
    assert turns[-1]["player_id"] == "c"
    assert game.current_player_id() == "c"


def test_disconnect_of_other_player_keeps_turn_and_does_not_reannounce(manager):
    game, ws = seat(manager, {"a": [2, 3], "b": [4, 5], "c": [6, 1]}, current="c")
    run(manager.disconnect("test", "a"))
    assert game.current_player_id() == "c"
    assert not ws["b"].of_type("turn")


def test_bid_quantity_is_capped(manager):
    """Backlog #11: el servidor no acepta cantidades absurdas."""
    game, ws = seat(manager, {"a": [2, 3], "b": [4, 5]}, current="a")
    run(manager.handle_message("test", "a", {"type": "bid", "quantity": MAX_BID_QUANTITY + 1, "face": 3}))
    assert game.current_bid is None
    assert ws["a"].of_type("error")

    manager.last_message_at.clear()  # saltar el rate limit entre mensajes
    run(manager.handle_message("test", "a", {"type": "bid", "quantity": 2, "face": 3}))
    assert game.current_bid is not None and game.current_bid.quantity == 2
    assert ws["b"].of_type("turn")[-1]["player_id"] == "b"
