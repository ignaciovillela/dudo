"""
Lógica de resolución de acciones de reto: Dudo y Calzo.

Cada acción encapsula:
  - validate()  — precondiciones; devuelve str con el error o None si es válido
  - resolve()   — calcula el resultado sin tocar el estado del juego
  - apply()     — aplica los efectos secundarios al estado (recuperación de dado)

El handler en manager.py solo orquesta:
    1. validate()  → rechazar si hay error
    2. resolve()   → obtener DudoResult / CalzoResult
    3. apply()     → mutar el estado
    4. broadcast   → emitir reveal con los datos del resultado
    5. _apply_loss / _new_round según corresponda
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.models import Bid, Game
    from game.rules import RuleEngine


# ---------------------------------------------------------------------------
# Resultados (value objects, sin lógica)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DudoBidResult:
    """Resultado de dudar una apuesta (bid)."""
    bid: "Bid"
    challenger_id: str
    challenger_name: str
    actual_count: int
    bid_holds: bool        # True → la apuesta se sostuvo → pierde el challenger
    loser_id: str
    is_gavilan: bool       # el challenger actuó fuera de turno
    challenger_gained: bool  # el gavilán ganó un dado por dudar bien fuera de turno
    is_ghost: bool = False   # el challenger estaba eliminado (gavilán fantasma)


@dataclass(frozen=True)
class DudoPasoResult:
    """Resultado de dudar un paso."""
    passer_id: str
    passer_name: str
    challenger_id: str
    challenger_name: str
    paso_valid: bool       # True → el paso era válido → pierde el challenger
    loser_id: str
    is_gavilan: bool
    challenger_gained: bool  # el gavilán ganó un dado por dudar bien fuera de turno
    is_ghost: bool = False


@dataclass(frozen=True)
class CalzoResult:
    """Resultado de un calzo."""
    bid: "Bid"
    challenger_id: str
    challenger_name: str
    actual_count: int
    exact: bool            # True → calzo correcto → el challenger gana o no pierde
    loser_id: str | None   # None si el calzo fue correcto
    challenger_gained: bool
    is_gavilan: bool
    is_ghost: bool = False


# ---------------------------------------------------------------------------
# DudoAction
# ---------------------------------------------------------------------------

class DudoAction:
    """
    Encapsula la validación y resolución de un Dudo.
    No distingue gavilan vs. turno normal hasta resolve(): primero verifica
    que la acción sea posible, luego calcula el resultado.
    """

    def __init__(self, game: "Game", challenger_id: str, engine: "RuleEngine"):
        self._game = game
        self._challenger_id = challenger_id
        self._engine = engine

    # -- Validación ----------------------------------------------------------

    def validate(self) -> str | None:
        """
        Devuelve el mensaje de error si la acción no es válida, None si puede ejecutarse.
        Orden: primero condiciones propias del jugador, luego si hay algo que dudar,
        finalmente si tiene permiso de actuar fuera de turno.
        """
        game = self._game
        pid = self._challenger_id

        player = game.players.get(pid)
        if not player:
            return "No estás en la partida"
        if player.dice_count <= 0 and not game.can_ghost_gavilan(pid):
            return "Estás eliminado"

        if game.current_bid is None and game.last_paso is None:
            return "No hay acción activa que dudar"

        if game.last_paso is not None and game.last_paso["player_id"] == pid:
            return "No puedes dudar tu propio paso"

        if game.last_paso is None and game.current_bid is not None and game.current_bid.player_id == pid:
            return "No puedes dudar tu propia apuesta"

        # Gavilán: verificar permiso solo si es fuera de turno
        if game.current_player_id() != pid and not self._engine.allow_gavilan():
            return "Gavilán está desactivado en esta sala"

        return None

    # -- Resolución ----------------------------------------------------------

    def resolve(self) -> DudoBidResult | DudoPasoResult:
        """
        Calcula el resultado del dudo sin modificar el estado del juego.
        Determina gavilan, quién pierde y si el challenger recupera dado.
        """
        game = self._game
        pid = self._challenger_id
        is_gavilan = game.current_player_id() != pid
        is_ghost = game.players[pid].dice_count <= 0

        if game.last_paso is not None:
            return self._resolve_paso(is_gavilan, is_ghost)
        return self._resolve_bid(is_gavilan, is_ghost)

    def _resolve_bid(self, is_gavilan: bool, is_ghost: bool = False) -> DudoBidResult:
        game = self._game
        pid = self._challenger_id
        bid = game.current_bid

        actual = game.count_dice(bid.face)
        bid_holds = actual >= bid.quantity
        loser_id = pid if bid_holds else bid.player_id

        # Gavilán exitoso (dudó bien fuera de turno y la apuesta no se sostiene)
        challenger_gained = False
        if is_gavilan and not bid_holds:
            p = game.players[pid]
            if p.dice_count < 5:
                challenger_gained = True

        return DudoBidResult(
            bid=bid,
            challenger_id=pid,
            challenger_name=game.players[pid].name,
            actual_count=actual,
            bid_holds=bid_holds,
            loser_id=loser_id,
            is_gavilan=is_gavilan,
            challenger_gained=challenger_gained,
            is_ghost=is_ghost,
        )

    def _resolve_paso(self, is_gavilan: bool, is_ghost: bool = False) -> DudoPasoResult:
        game = self._game
        pid = self._challenger_id
        paso = game.last_paso

        paso_valid = game.is_valid_paso(paso["player_id"])
        loser_id = pid if paso_valid else paso["player_id"]

        # Gavilán exitoso (dudó bien fuera de turno) → recupera dado
        challenger_gained = False
        if not paso_valid and is_gavilan:
            p = game.players[pid]
            if p.dice_count < 5:
                challenger_gained = True

        return DudoPasoResult(
            passer_id=paso["player_id"],
            passer_name=paso["player_name"],
            challenger_id=pid,
            challenger_name=game.players[pid].name,
            paso_valid=paso_valid,
            loser_id=loser_id,
            is_gavilan=is_gavilan,
            challenger_gained=challenger_gained,
            is_ghost=is_ghost,
        )

    # -- Aplicación de efectos secundarios -----------------------------------

    def apply(self, result: DudoBidResult | DudoPasoResult) -> None:
        """
        Aplica los efectos que no son pérdida de dado (eso lo hace _apply_loss en manager).
        Actualmente: recuperación de dado por gavilán en paso.
        También limpia el estado del juego (current_bid / last_paso) para
        evitar doble resolución si llegan mensajes simultáneos.
        """
        game = self._game

        if isinstance(result, DudoPasoResult):
            game.last_paso = None
            if result.challenger_gained:
                game.players[result.challenger_id].dice_count += 1
                if result.is_ghost:
                    game.elimination_order = [
                        e for e in game.elimination_order
                        if e["id"] != result.challenger_id
                    ]
        else:
            game.current_bid = None
            if result.challenger_gained:
                game.players[result.challenger_id].dice_count += 1
                if result.is_ghost:
                    game.elimination_order = [
                        e for e in game.elimination_order
                        if e["id"] != result.challenger_id
                    ]


# ---------------------------------------------------------------------------
# CalzoAction
# ---------------------------------------------------------------------------

class CalzoAction:
    """
    Encapsula la validación y resolución de un Calzo.
    Solo aplica sobre apuestas (no sobre pasos).
    """

    def __init__(self, game: "Game", challenger_id: str, engine: "RuleEngine"):
        self._game = game
        self._challenger_id = challenger_id
        self._engine = engine

    # -- Validación ----------------------------------------------------------

    def validate(self) -> str | None:
        """
        Devuelve el mensaje de error si la acción no es válida, None si puede ejecutarse.
        """
        game = self._game
        pid = self._challenger_id

        player = game.players.get(pid)
        if not player:
            return "No estás en la partida"
        if player.dice_count <= 0 and not game.can_ghost_gavilan(pid):
            return "Estás eliminado"

        if game.last_paso is not None:
            return "No se puede calzar un paso"

        if game.current_bid is None:
            return "No hay apuesta"

        if game.current_bid.player_id == pid:
            return "No puedes calzar tu propia apuesta"

        # Gavilán: verificar permiso solo si es fuera de turno
        if game.current_player_id() != pid and not self._engine.allow_gavilan():
            return "Gavilán está desactivado en esta sala"

        return None

    # -- Resolución ----------------------------------------------------------

    def resolve(self) -> CalzoResult:
        """
        Calcula el resultado del calzo sin modificar el estado del juego.
        """
        game = self._game
        pid = self._challenger_id
        bid = game.current_bid
        is_gavilan = game.current_player_id() != pid
        is_ghost = game.players[pid].dice_count <= 0

        actual = game.count_dice(bid.face)
        exact = actual == bid.quantity
        loser_id = None if exact else pid

        # Recuperación de dado: si el calzo fue correcto y las reglas lo permiten
        challenger_gained = False
        can_recover_on_turn = self._engine.calzo_recovers_on_turn()
        if exact and (is_gavilan or can_recover_on_turn):
            p = game.players[pid]
            if p.dice_count < 5:
                challenger_gained = True

        return CalzoResult(
            bid=bid,
            challenger_id=pid,
            challenger_name=game.players[pid].name,
            actual_count=actual,
            exact=exact,
            loser_id=loser_id,
            challenger_gained=challenger_gained,
            is_gavilan=is_gavilan,
            is_ghost=is_ghost,
        )

    # -- Aplicación de efectos secundarios -----------------------------------

    def apply(self, result: CalzoResult) -> None:
        """
        Aplica recuperación de dado si corresponde y limpia la apuesta activa.
        """
        game = self._game
        game.current_bid = None  # limpiar antes de cualquier otro efecto

        if result.challenger_gained:
            game.players[result.challenger_id].dice_count += 1
            if result.is_ghost:
                game.elimination_order = [
                    e for e in game.elimination_order
                    if e["id"] != result.challenger_id
                ]
