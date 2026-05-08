"""
Lógica de decisión para bots del juego Dudo.

Arquitectura: patrón plugin.
  - BotStrategy  — clase base abstracta con utilidades compartidas
  - EasyBot       — usa sus dados pero con umbrales relajados y algo de ruido
  - MediumBot     — bayesiano con umbrales razonables, sin Calzo
  - HardBot       — bayesiano completo: prioriza caras propias, Calzo selectivo, duda precisa

Punto de entrada público: decide(game, bot_id) -> dict
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.models import Bid, Game


# ---------------------------------------------------------------------------
# Clase base: utilidades compartidas
# ---------------------------------------------------------------------------

class BotStrategy(ABC):

    # -- Probabilidad --------------------------------------------------------

    @staticmethod
    def prob_at_least(n: int, k: int, p: float) -> float:
        """P(X >= k) donde X ~ Binomial(n, p)."""
        if k <= 0:
            return 1.0
        if k > n:
            return 0.0
        total = 0.0
        for i in range(k, n + 1):
            coef = math.comb(n, i)
            total += coef * (p ** i) * ((1 - p) ** (n - i))
        return total

    def prob_bid_holds_bayesian(self, game: "Game", bid: "Bid", bot_id: str) -> float:
        """
        P(apuesta se sostiene) condicionada a los dados propios del bot.
        Estima la incertidumbre solo sobre los dados desconocidos (los de los demás).
        """
        own_dice = game.players[bot_id].dice
        face = bid.face

        if face == 1:
            own_matching = sum(1 for d in own_dice if d == 1)
        else:
            own_matching = sum(1 for d in own_dice if d == face or d == 1)

        unknown_dice = game.total_dice() - len(own_dice)
        still_need = bid.quantity - own_matching

        if still_need <= 0:
            return 1.0
        if unknown_dice <= 0:
            return 0.0

        p_match = 1 / 6 if face == 1 else 2 / 6
        return self.prob_at_least(unknown_dice, still_need, p_match)

    def own_matching(self, game: "Game", bot_id: str, face: int) -> int:
        """Cuántos dados propios contribuyen a la cara (con comodines)."""
        dice = game.players[bot_id].dice
        if face == 1:
            return sum(1 for d in dice if d == 1)
        return sum(1 for d in dice if d == face or d == 1)

    # -- Generación de candidatos --------------------------------------------

    def candidate_bids(
        self,
        game: "Game",
        bot_id: str,
        max_candidates: int = 20,
        prefer_faces: list[int] | None = None,
    ) -> list["Bid"]:
        """
        Genera apuestas válidas por encima de la apuesta actual.
        - Nunca propone una cantidad > total_dice (sería imposible).
        - Si prefer_faces está dado, esas caras van primero en la exploración.
        - Para cada cara explora cantidades contiguas desde el mínimo válido.
        """
        from game.models import Bid

        candidates: list[Bid] = []
        bot_name = game.players[bot_id].name
        total = game.total_dice()
        all_faces = list(range(2, 7)) + [1]

        # Ordenar caras: primero las preferidas, luego el resto
        if prefer_faces:
            ordered_faces = prefer_faces + [f for f in all_faces if f not in prefer_faces]
        else:
            ordered_faces = all_faces

        for face in ordered_faces:
            # Encontrar la cantidad mínima válida para esta cara
            qty = 1
            while True:
                bid = Bid(quantity=qty, face=face, player_id=bot_id, player_name=bot_name)
                if game.is_valid_bid(bid):
                    break
                qty += 1
                if qty > total + 1:
                    break

            # Generar cantidades crecientes para esta cara mientras sean posibles
            while qty <= total:
                bid = Bid(quantity=qty, face=face, player_id=bot_id, player_name=bot_name)
                if game.is_valid_bid(bid):
                    candidates.append(bid)
                    if len(candidates) >= max_candidates:
                        return candidates
                qty += 1

        return candidates

    @staticmethod
    def can_paso(game: "Game", bot_id: str) -> bool:
        return (
            game.current_bid is not None
            and bot_id not in game.passed_players
            and game.is_valid_paso(bot_id)
        )

    # -- Interfaz pública ----------------------------------------------------

    @abstractmethod
    def decide(self, game: "Game", bot_id: str) -> dict:
        """
        Retorna la acción a ejecutar.
        Formato: {"action": str} con campos adicionales según la acción:
          bid   → + "quantity": int, "face": int
          paso  → (sin campos extra)
          dudo  → (sin campos extra)
          calzo → (sin campos extra)
        """


# ---------------------------------------------------------------------------
# EasyBot — usa sus dados pero con umbrales relajados y ruido
# ---------------------------------------------------------------------------

class EasyBot(BotStrategy):
    """
    Bot fácil: conoce sus dados y los usa para decidir, pero con umbrales
    permisivos y algo de aleatoriedad que lo hace cometer errores frecuentes.
    - Duda solo cuando la probabilidad bayesiana es muy baja (< 20%)
    - A veces no duda aunque debería (ruido del 40%)
    - Apuesta priorizando sus caras más fuertes pero elige cantidades sin afinar
    - Pasa ocasionalmente
    """

    DUDO_THRESHOLD = 0.20      # duda si P < 20%
    DUDO_NOISE     = 0.40      # 40% de las veces ignora una señal de dudo válida

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        # -- Evaluar dudo --
        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob < self.DUDO_THRESHOLD and random.random() > self.DUDO_NOISE:
                return {"action": "dudo"}

        # -- Paso ocasional --
        if self.can_paso(game, bot_id) and random.random() < 0.12:
            return {"action": "paso"}

        # -- Apuesta: priorizar caras que tenga en sus dados --
        strong_faces = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=12, prefer_faces=strong_faces)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        # Elige al azar entre las primeras candidatas (no la óptima)
        pool = candidates[:max(1, len(candidates) // 2)]
        bid = random.choice(pool)
        return {"action": "bid", "quantity": bid.quantity, "face": bid.face}

    @staticmethod
    def _strong_faces(dice: list[int]) -> list[int]:
        """Caras con mayor frecuencia en los dados propios (sin considerar comodines)."""
        if not dice:
            return []
        from collections import Counter
        counts = Counter(dice)
        return [face for face, _ in counts.most_common()]


# ---------------------------------------------------------------------------
# MediumBot — bayesiano con umbrales razonables, sin Calzo
# ---------------------------------------------------------------------------

class MediumBot(BotStrategy):
    """
    Bot medio: usa sus dados como evidencia bayesiana para todas las decisiones.
    - Duda cuando P(bid holds) < 30%
    - Pasa cuando la apuesta activa ya es probable y tiene dados válidos
    - Apuesta la opción con mejor probabilidad bayesiana >= 45%
    - No intenta Calzo (demasiado arriesgado para su nivel)
    """

    DUDO_THRESHOLD = 0.30
    BID_MIN_PROB   = 0.45

    def decide(self, game: "Game", bot_id: str) -> dict:
        # -- Evaluar dudo sobre apuesta activa --
        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob < self.DUDO_THRESHOLD:
                return {"action": "dudo"}

        # -- Evaluar dudo sobre paso activo --
        if game.last_paso is not None and game.current_bid is None:
            if random.random() < 0.20:
                return {"action": "dudo"}

        # -- Paso: si la apuesta actual es probable y tenemos dados válidos --
        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > 0.60 and random.random() < 0.35:
                return {"action": "paso"}

        # -- Apuesta: priorizar caras fuertes propias, elegir la de mejor prob --
        own_dice = game.players[bot_id].dice
        strong = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=20, prefer_faces=strong)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]
        good = [(b, p) for b, p in scored if p >= self.BID_MIN_PROB]

        if good:
            # Entre las buenas: la que mayor cantidad apuesta (más presión) con buena prob
            good.sort(key=lambda x: (x[0].quantity, x[1]), reverse=True)
            chosen = good[0][0]
        else:
            # Ninguna es buena: la menos mala
            scored.sort(key=lambda x: -x[1])
            chosen = scored[0][0]

        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    @staticmethod
    def _strong_faces(dice: list[int]) -> list[int]:
        """
        Caras con mayor conteo efectivo (cara + ases como comodines).
        Devuelve caras 2-6 ordenadas por conteo efectivo, luego ases.
        """
        if not dice:
            return []
        aces = sum(1 for d in dice if d == 1)
        face_counts = {}
        for f in range(2, 7):
            face_counts[f] = sum(1 for d in dice if d == f) + aces
        sorted_faces = sorted(face_counts, key=lambda f: -face_counts[f])
        return sorted_faces + [1]


# ---------------------------------------------------------------------------
# HardBot — bayesiano completo con Calzo selectivo
# ---------------------------------------------------------------------------

class HardBot(BotStrategy):
    """
    Bot difícil: máxima información propia, decisiones precisas.
    - Prioriza siempre las caras donde tiene más dados propios
    - Duda agresivamente cuando P < 22%
    - Calzo solo cuando la expectativa está muy cerca de la apuesta (diff < 0.5)
      y la probabilidad bayesiana es alta (> 80%)
    - Apuesta la opción con mejor relación prob/presión usando toda la información
    - Pasa cuando la apuesta activa es segura y tiene dados válidos
    """

    DUDO_THRESHOLD  = 0.22
    CALZO_PROB_MIN  = 0.80   # prob bayesiana mínima para considerar Calzo
    CALZO_DIFF_MAX  = 0.5    # diferencia máxima entre expectativa y cantidad apostada
    CALZO_RAND      = 0.60   # probabilidad aleatoria de ejecutar el Calzo si se cumplen condiciones
    BID_MIN_PROB    = 0.50

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        # -- Evaluar apuesta activa --
        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)

            # Calzo: solo si la estimación puntual está muy cerca de la cantidad apostada
            if (prob >= self.CALZO_PROB_MIN
                    and game.current_bid.player_id != bot_id
                    and self._calzo_makes_sense(game, bot_id, own_dice)):
                return {"action": "calzo"}

            # Dudo
            if prob < self.DUDO_THRESHOLD:
                return {"action": "dudo"}

        # -- Evaluar paso activo --
        if game.last_paso is not None and game.current_bid is None:
            # Dudar un paso sin ver sus dados: solo si nuestros dados son malos para pasar
            if random.random() < 0.30:
                return {"action": "dudo"}

        # -- Paso: si la apuesta activa ya es prácticamente segura --
        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > 0.70 and random.random() < 0.45:
                return {"action": "paso"}

        # -- Apuesta: priorizar caras fuertes, elegir la de mejor prob/presión --
        strong = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=30, prefer_faces=strong)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]
        good = [(b, p) for b, p in scored if p >= self.BID_MIN_PROB]

        if good:
            # Maximizar presión: mayor cantidad apostada con prob aceptable
            # Desempate: mayor probabilidad
            good.sort(key=lambda x: (x[0].quantity, x[1]), reverse=True)
            chosen = good[0][0]
        else:
            scored.sort(key=lambda x: -x[1])
            chosen = scored[0][0]

        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    def _calzo_makes_sense(self, game: "Game", bot_id: str, own_dice: list) -> bool:
        """
        Verifica que la expectativa del conteo total esté muy cerca de la cantidad apostada.
        Solo así vale la pena arriesgar el Calzo.
        """
        bid = game.current_bid
        face = bid.face
        unknown_dice = game.total_dice() - len(own_dice)

        if face == 1:
            own_m = sum(1 for d in own_dice if d == 1)
            expected_others = unknown_dice / 6
        else:
            own_m = sum(1 for d in own_dice if d == face or d == 1)
            expected_others = unknown_dice * 2 / 6

        expected_total = own_m + expected_others
        diff = abs(expected_total - bid.quantity)
        return diff <= self.CALZO_DIFF_MAX and random.random() < self.CALZO_RAND

    @staticmethod
    def _strong_faces(dice: list[int]) -> list[int]:
        """
        Ordena caras 2-6 por conteo efectivo (propios + ases como comodín).
        Los ases van al final ya que son la cara más difícil de apostar.
        """
        if not dice:
            return list(range(2, 7)) + [1]
        aces = sum(1 for d in dice if d == 1)
        face_counts = {f: sum(1 for d in dice if d == f) + aces for f in range(2, 7)}
        sorted_faces = sorted(face_counts, key=lambda f: -face_counts[f])
        return sorted_faces + [1]


# ---------------------------------------------------------------------------
# Registro de estrategias
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, BotStrategy] = {
    "easy":   EasyBot(),
    "medium": MediumBot(),
    "hard":   HardBot(),
}


def decide(game: "Game", bot_id: str) -> dict:
    """
    Punto de entrada público.
    Despacha la decisión a la estrategia correspondiente según bot_difficulty.
    """
    player = game.players.get(bot_id)
    if not player or not player.is_bot:
        return {"action": "bid", "quantity": 1, "face": 2}

    strategy = _REGISTRY.get(player.bot_difficulty, _REGISTRY["medium"])
    return strategy.decide(game, bot_id)
