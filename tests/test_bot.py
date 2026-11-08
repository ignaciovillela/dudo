"""Regresión: toda estrategia que usa DUDO_NOISE debe definirlo."""
import inspect

from game import bot


def test_bots_con_ruido_lo_definen():
    for nombre, cls in inspect.getmembers(bot, inspect.isclass):
        if not nombre.endswith("Bot"):
            continue
        fuente = inspect.getsource(cls)
        if "self.DUDO_NOISE" in fuente:
            assert hasattr(cls, "DUDO_NOISE"), nombre


def test_medium_bot_tiene_ruido():
    assert 0 <= bot.MediumBot.DUDO_NOISE <= 1
