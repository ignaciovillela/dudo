"""
Lógica de decisión para bots del juego Dudo.

Arquitectura: patrón plugin.
  - BotStrategy  — clase base abstracta con utilidades compartidas
  - EasyBot       — usa sus dados pero con umbrales relajados y algo de ruido
  - MediumBot     — bayesiano con umbrales razonables, sin Calzo
  - HardBot       — bayesiano completo: prioriza caras propias, Calzo selectivo, duda precisa
  - VeryHardBot   — memoria de rondas, modelado de rivales, bluff, Gavilán adaptativo
  - ExpertBot     — VeryHardBot + comportamiento in-game, contexto multi-jugador, Nash-aware

Punto de entrada público: decide(game, bot_id) -> dict
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
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

    @staticmethod
    def _pick_bid(
        scored: list,
        min_prob: float,
        aggression: float = 0.15,
    ):
        """
        Elige una apuesta de la lista scored = [(bid, prob), ...].

        Estrategia:
        - Filtra candidatos con prob >= min_prob.
        - La mayoría de las veces (1 - aggression) elige en el tercio inferior
          de cantidad entre los válidos — apuesta moderada, da espacio a la ronda.
        - Con probabilidad aggression escala alto (tercio superior de cantidad).
        - Si no hay candidatos válidos, elige el de mayor prob disponible.

        aggression ∈ [0, 1]: qué tan seguido escala al máximo.
        """
        good = [(b, p) for b, p in scored if p >= min_prob]
        if not good:
            # fallback: mejor prob disponible
            scored_copy = sorted(scored, key=lambda x: -x[1])
            return scored_copy[0][0]

        # Ordenar por cantidad ascendente
        good.sort(key=lambda x: x[0].quantity)
        n = len(good)
        third      = max(1, n // 3)
        low_third  = good[:third]
        high_third = good[-third:]  # siempre al menos 1 elemento

        if random.random() < aggression:
            # Escala agresivo: elige del tercio superior de cantidades
            chosen = random.choice(high_third)[0]
        else:
            # Apuesta moderada: elige del tercio inferior de cantidades
            # pero dentro de ese tercio prefiere la de mayor prob
            low_third.sort(key=lambda x: -x[1])
            chosen = low_third[0][0]

        return chosen

    @staticmethod
    def prob_paso_is_bluff(game: "Game", passer_id: str) -> float:
        """
        Estima la probabilidad de que el paso sea MENTIRA (el pasador no tiene
        una mano válida) desde el punto de vista de un bot observador.

        Un paso es válido si los dados del pasador son:
          - todos distintos  (escalera)
          - todos iguales    (generala)
          - full house       (3+2)
        Requiere exactamente 5 dados.

        Si el pasador tiene < 5 dados → el paso es SIEMPRE mentira (imposible).
        Si el pasador tiene 5 dados el bot no conoce esos dados, pero puede
        estimar la probabilidad de mano válida combinatoriamente:
          P(escalera)   ≈ 6!/(6^5) * 1   = 720/7776  ≈ 0.0926
          P(generala)   ≈ 6/6^5          = 6/7776     ≈ 0.0008
          P(full house) ≈ C(6,2)*2*10/6^5 = 1800/7776 ≈ 0.2315
          Total válido  ≈ 0.3248  →  P(bluff) ≈ 0.675

        Retorna P(mentira) ∈ [0, 1].
        """
        passer = game.players.get(passer_id)
        if passer is None:
            return 0.5  # desconocido

        dice_count = passer.dice_count
        if dice_count < 5:
            # Con menos de 5 dados es imposible pasar legítimamente
            return 1.0

        # Con exactamente 5 dados: probabilidad combinatoria de mano válida
        # (sin información adicional sobre los dados del pasador)
        # escalera: 5! * C(6,5) maneras de tener 5 valores distintos de 6
        # = 120 * 6 = 720 de 6^5 = 7776 outcomes ordenados
        p_escalera   = 720  / 7776   # ≈ 0.0926
        # generala: 6 valores posibles × 1 cada uno
        p_generala   = 6    / 7776   # ≈ 0.0008
        # full house: elegir cuál valor es el trío (6) × elegir el par (5)
        # × formas de repartir las posiciones = 6*5 * C(5,3) = 30*10 = 300 * 6 orderingsbase
        # En outcomes ordenados: 6 * 5 * C(5,2) * 1 = 6*5*10 * (numero orderings)
        # Fórmula correcta: C(6,1)*C(5,1) * (5!/(3!*2!)) = 6*5*10 = 300 outcomes distintos
        # de valores; × 1 (ya ordenados internamente): 300*1 = 300... recompute:
        # Manos full house como multisets: C(6,1) elegir trío × C(5,1) elegir par = 30
        # Por mano → número de arreglos = 5!/(3!*2!) = 10
        # Total outcomes ordenados = 30 * 10 = 300... pero eso da 300/7776 ≈ 3.8%
        # Revisión: 6^5 = 7776 outcomes. Full house: 6 opciones para trío, 5 para par,
        # C(5,3)=10 posiciones → 6*5*10 = 300. Correcto.
        p_full_house = 300  / 7776   # ≈ 0.0386
        # NOTA: en la práctica los jugadores humanos no pasan a menos que tengan
        # la mano — el paso "mentira" es raro pero posible como bluff puro.
        p_valid = p_escalera + p_generala + p_full_house   # ≈ 0.132
        return 1.0 - p_valid  # P(bluff) ≈ 0.868

    # -- Sentido (dirección) --------------------------------------------------

    @staticmethod
    def _next_player_in_dir(game: "Game", bot_id: str, direction: int) -> str | None:
        """Retorna el jugador que seguiría si el sentido fuese `direction` (1 o -1)."""
        active = game.active_players()
        if not active:
            return None
        try:
            idx = active.index(bot_id)
        except ValueError:
            return None
        return active[(idx + direction) % len(active)]

    def _player_threat_score(self, game: "Game", bot_id: str, target_id: str) -> float:
        """
        Puntaje de amenaza de target_id para el bot.
        A mayor puntaje, más problemático tenerlo cerca en el orden de turno.
        Sobrescribir en subclases para mayor sofisticación.
        """
        return float(game.players[target_id].dice_count) if target_id in game.players else 0.0

    def decide_direction(self, game: "Game", bot_id: str) -> str | None:
        """
        Decide si cambiar el sentido del juego basado en quién quedaría
        como siguiente jugador en cada dirección.
        Retorna "cw", "ccw" o None (mantener sentido actual).
        """
        return None

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
    Bot fácil: comete errores pero no es completamente aleatorio.
    - Duda cuando la probabilidad es baja (< 25%), con un 25% de ruido
    - Ocasionalmente sobreapuesta (bluff ingenuo) o pasa sin razón
    - Usa sus caras más fuertes pero no optimiza la cantidad
    - No usa comodines para evaluar caras propias (error de novato)
    """

    DUDO_THRESHOLD = 0.25
    DUDO_NOISE     = 0.25   # ignora la señal el 25% de las veces (antes 40%)

    def decide_direction(self, game: "Game", bot_id: str) -> str | None:
        next_cw = self._next_player_in_dir(game, bot_id, game.direction)
        next_ccw = self._next_player_in_dir(game, bot_id, -game.direction)
        if not next_cw or not next_ccw or next_cw == next_ccw:
            return None
        tc = self._player_threat_score(game, bot_id, next_cw)
        to = self._player_threat_score(game, bot_id, next_ccw)
        if to < tc - 0.5:
            return "ccw" if game.direction == 1 else "cw"
        if random.random() < 0.25:
            return "ccw" if game.direction == 1 else "cw"
        return None

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        # -- Evaluar dudo --
        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob < self.DUDO_THRESHOLD and random.random() > self.DUDO_NOISE:
                return {"action": "dudo"}

        # -- Dudo de paso activo --
        # Solo duda si la probabilidad de que sea mentira es alta.
        # Con < 5 dados del pasador: prob_bluff = 1.0 → siempre duda (con ruido).
        if game.last_paso is not None:
            p_bluff = self.prob_paso_is_bluff(game, game.last_paso["player_id"])
            # EasyBot duda el paso solo si es claramente mentira (< 5 dados)
            # y con su propio umbral relajado + ruido
            if p_bluff >= 0.90 and random.random() > self.DUDO_NOISE:
                return {"action": "dudo"}

        # -- Paso ocasional --
        if self.can_paso(game, bot_id) and random.random() < 0.10:
            return {"action": "paso"}

        # -- Apuesta --
        strong_faces = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=15, prefer_faces=strong_faces)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]

        # Bluff ingenuo: 15% de las veces apuesta algo que no tiene bien respaldado
        if random.random() < 0.15:
            weak = [(b, p) for b, p in scored if p < 0.50]
            if weak:
                chosen = random.choice(weak)[0]
                return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

        # Elige entre las primeras con prob ≥ 30%, o la menos mala si no hay
        decent = [(b, p) for b, p in scored if p >= 0.30]
        pool = decent if decent else scored
        # No optimiza — elige al azar entre el primer tercio
        pool_top = pool[:max(1, len(pool) // 3 * 2)]
        chosen = random.choice(pool_top)[0]
        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

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
    Bot medio: bayesiano competente con algo de variedad táctica.
    - Duda cuando P < 32%; también duda pasos activos con mayor frecuencia
    - Pasa con criterio cuando la apuesta es segura
    - Apuesta la opción con mejor probabilidad ≥ 42%, con sesgo hacia presión moderada
    - Bluff ocasional (8%) para no ser totalmente predecible
    - Sin Calzo
    """

    DUDO_THRESHOLD = 0.32
    BID_MIN_PROB   = 0.42
    BLUFF_PROB     = 0.08

    def _player_threat_score(self, game: "Game", bot_id: str, target_id: str) -> float:
        return float(game.players[target_id].dice_count) if target_id in game.players else 0.0

    def decide_direction(self, game: "Game", bot_id: str) -> str | None:
        next_cw = self._next_player_in_dir(game, bot_id, game.direction)
        next_ccw = self._next_player_in_dir(game, bot_id, -game.direction)
        if not next_cw or not next_ccw or next_cw == next_ccw:
            return None
        tc = self._player_threat_score(game, bot_id, next_cw)
        to = self._player_threat_score(game, bot_id, next_ccw)
        if to < tc - 0.5:
            return "ccw" if game.direction == 1 else "cw"
        if random.random() < 0.15:
            return "ccw" if game.direction == 1 else "cw"
        return None

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob < self.DUDO_THRESHOLD and random.random() > self.DUDO_NOISE:
                return {"action": "dudo"}

        if game.last_paso is not None:
            p_bluff = self.prob_paso_is_bluff(game, game.last_paso["player_id"])
            # Duda si el paso es claramente imposible (< 5 dados: p_bluff=1.0)
            # o si la probabilidad de mentira supera su umbral propio
            if p_bluff >= 0.90:
                return {"action": "dudo"}
            # Con 5 dados del pasador: p_bluff ≈ 0.87, duda con 28% de frecuencia base
            if random.random() < 0.28:
                return {"action": "dudo"}

        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > 0.65 and random.random() < 0.30:
                return {"action": "paso"}

        strong = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=20, prefer_faces=strong)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]

        # Bluff ocasional: apuesta algo que no tiene bien respaldado
        if random.random() < self.BLUFF_PROB:
            weak = [(b, p) for b, p in scored if 0.30 <= p < 0.42]
            if weak:
                weak.sort(key=lambda x: x[1], reverse=True)
                chosen = weak[0][0]
                return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

        chosen = self._pick_bid(scored, self.BID_MIN_PROB, aggression=0.15)

        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    @staticmethod
    def _strong_faces(dice: list[int]) -> list[int]:
        if not dice:
            return []
        aces = sum(1 for d in dice if d == 1)
        face_counts = {f: sum(1 for d in dice if d == f) + aces for f in range(2, 7)}
        return sorted(face_counts, key=lambda f: -face_counts[f]) + [1]


# ---------------------------------------------------------------------------
# HardBot — bayesiano completo con Calzo selectivo
# ---------------------------------------------------------------------------

class HardBot(BotStrategy):
    """
    Bot difícil: bayesiano preciso con Calzo, bluff controlado y paso táctico.
    - Duda cuando P < 25% (antes 22% — ligeramente más humano)
    - Calzo con gate 75% cuando las condiciones se cumplen (antes 60%)
    - Bluff deliberado ~8%: apuesta una cara que no tiene bien respaldada
    - Paso táctico: pasa con más frecuencia cuando la apuesta ya es muy segura
    - Duda pasos activos con 35%
    """

    DUDO_THRESHOLD = 0.25
    CALZO_PROB_MIN = 0.78
    CALZO_DIFF_MAX = 0.45
    CALZO_RAND     = 0.75   # antes 0.60 — más decidido cuando las condiciones se dan
    BID_MIN_PROB   = 0.48
    BLUFF_PROB     = 0.08

    def _player_threat_score(self, game: "Game", bot_id: str, target_id: str) -> float:
        return float(game.players[target_id].dice_count) if target_id in game.players else 0.0

    def decide_direction(self, game: "Game", bot_id: str) -> str | None:
        next_cw = self._next_player_in_dir(game, bot_id, game.direction)
        next_ccw = self._next_player_in_dir(game, bot_id, -game.direction)
        if not next_cw or not next_ccw or next_cw == next_ccw:
            return None
        tc = self._player_threat_score(game, bot_id, next_cw)
        to = self._player_threat_score(game, bot_id, next_ccw)
        if to < tc - 0.5:
            return "ccw" if game.direction == 1 else "cw"
        if random.random() < 0.15:
            return "ccw" if game.direction == 1 else "cw"
        return None

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)

            if (prob >= self.CALZO_PROB_MIN
                    and game.current_bid.player_id != bot_id
                    and self._calzo_makes_sense(game, bot_id, own_dice)):
                return {"action": "calzo"}

            if prob < self.DUDO_THRESHOLD:
                return {"action": "dudo"}

        if game.last_paso is not None:
            p_bluff = self.prob_paso_is_bluff(game, game.last_paso["player_id"])
            if p_bluff >= 0.90:
                return {"action": "dudo"}
            if random.random() < 0.35:
                return {"action": "dudo"}

        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > 0.68 and random.random() < 0.42:
                return {"action": "paso"}

        strong = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=30, prefer_faces=strong)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]

        # Bluff controlado: apuesta algo con prob moderada-baja deliberadamente
        if random.random() < self.BLUFF_PROB:
            weak = [(b, p) for b, p in scored if 0.32 <= p < 0.48]
            if weak:
                weak.sort(key=lambda x: x[1], reverse=True)
                chosen = weak[0][0]
                return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

        chosen = self._pick_bid(scored, self.BID_MIN_PROB, aggression=0.15)

        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    def _calzo_makes_sense(self, game: "Game", bot_id: str, own_dice: list) -> bool:
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
        return abs(expected_total - bid.quantity) <= self.CALZO_DIFF_MAX and random.random() < self.CALZO_RAND

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
# ExpertBot — memoria de rondas, modelado de rivales, bluff, Gavilán
# ---------------------------------------------------------------------------

@dataclass
class _PlayerStats:
    """
    Historial de comportamiento de un rival, alimentado retroactivamente.

    Estrategia de aprendizaje
    -------------------------
    Cada vez que se resuelve un dudo/calzo se conocen TODOS los dados de la mesa
    (campo all_dice del payload). Con eso se recorre bid_history de la ronda y
    para cada apuesta se calcula si era verdad o mentira. Así acumulamos datos
    de TODAS las jugadas, no solo de las que fueron dudadas.

    Campos de bid
    -------------
    face_bid_counts[cara]    — total de apuestas con esa cara
    face_bluff_counts[cara]  — cuántas eran mentira (retroactivo por all_dice)
    qty_bucket_counts[b]     — total de apuestas por bucket de cantidad (1=baja,2=media,3=alta)
    qty_bucket_bluff[b]      — cuántas de esas eran mentira
    bids_total               — total de apuestas vistas
    bids_bluff               — total de apuestas que eran mentira
    copy_count               — veces que copió la apuesta anterior (+0/+1 misma cara)

    Campos de paso
    --------------
    paso_count               — veces que hizo paso
    paso_bluff_count         — pasos que eran mentira (dudados con éxito)
    paso_dice_sum            — suma de dados al pasar (para avg_dice_when_paso)

    Notas
    -----
    - bluff_rate = bids_bluff / bids_total  (global, retroactivo)
    - face_bluff_rate(cara) = face_bluff_counts[cara] / face_bid_counts[cara]
    - qty_bluff_rate(bucket) = qty_bucket_bluff[b] / qty_bucket_counts[b]
    - paso_bluff_rate = paso_bluff_count / paso_count
    - avg_dice_when_paso = paso_dice_sum / paso_count
    """
    # Apuestas (retroactivas)
    bids_total:          int = 0
    bids_bluff:          int = 0
    face_bid_counts:     dict = field(default_factory=lambda: defaultdict(int))
    face_bluff_counts:   dict = field(default_factory=lambda: defaultdict(int))
    qty_bucket_counts:   dict = field(default_factory=lambda: defaultdict(int))
    qty_bucket_bluff:    dict = field(default_factory=lambda: defaultdict(int))
    copy_count:          int = 0
    total_rounds:        int = 0

    # Paso
    paso_count:          int = 0
    paso_bluff_count:    int = 0
    paso_dice_sum:       int = 0

    # Tiempo de decisión al apostar (solo apuestas, no dudo/calzo/paso)
    bid_time_bluff_sum:  float = 0.0   # suma de elapsed cuando la apuesta era mentira
    bid_time_bluff_n:    int   = 0
    bid_time_truth_sum:  float = 0.0   # suma de elapsed cuando la apuesta era verdad
    bid_time_truth_n:    int   = 0

    @property
    def bluff_rate(self) -> float:
        return self.bids_bluff / max(self.bids_total, 1)

    def face_bluff_rate(self, face: int) -> float:
        total = self.face_bid_counts.get(face, 0)
        if total < 3:
            return self.bluff_rate
        return self.face_bluff_counts.get(face, 0) / total

    def qty_bluff_rate(self, bucket: int) -> float:
        total = self.qty_bucket_counts.get(bucket, 0)
        if total < 3:
            return self.bluff_rate
        return self.qty_bucket_bluff.get(bucket, 0) / total

    @property
    def paso_bluff_rate(self) -> float:
        return self.paso_bluff_count / max(self.paso_count, 1)

    @property
    def avg_dice_when_paso(self) -> float:
        return self.paso_dice_sum / max(self.paso_count, 1)

    @property
    def copy_rate(self) -> float:
        return self.copy_count / max(self.bids_total, 1)

    @property
    def avg_decision_time(self) -> float:
        """Promedio de tiempo de decisión sobre todas las apuestas con tiempo registrado."""
        n = self.bid_time_bluff_n + self.bid_time_truth_n
        s = self.bid_time_bluff_sum + self.bid_time_truth_sum
        return s / max(n, 1)

    @property
    def avg_bluff_time(self) -> float:
        return self.bid_time_bluff_sum / max(self.bid_time_bluff_n, 1)

    @property
    def avg_truth_time(self) -> float:
        return self.bid_time_truth_sum / max(self.bid_time_truth_n, 1)

    @property
    def time_sample_count(self) -> int:
        return self.bid_time_bluff_n + self.bid_time_truth_n

    def merge_from_db(self, row: dict) -> None:
        """Fusiona una fila de player_bid_stats desde la DB (acumula, no reemplaza)."""
        face   = row["face"]
        bucket = row["qty_bucket"]
        bt     = row["bids_total"]
        bb     = row["bids_bluff"]
        self.bids_total                    += bt
        self.bids_bluff                    += bb
        self.face_bid_counts[face]         += bt
        self.face_bluff_counts[face]       += bb
        self.qty_bucket_counts[bucket]     += bt
        self.qty_bucket_bluff[bucket]      += bb
        self.bid_time_bluff_sum            += row.get("bid_time_bluff_sum", 0.0)
        self.bid_time_bluff_n              += row.get("bid_time_bluff_n", 0)
        self.bid_time_truth_sum            += row.get("bid_time_truth_sum", 0.0)
        self.bid_time_truth_n              += row.get("bid_time_truth_n", 0)

    def merge_paso_from_db(self, row: dict) -> None:
        """Fusiona una fila de player_paso_stats desde la DB."""
        self.paso_count      += row["pasos_total"]
        self.paso_bluff_count += row["pasos_bluff"]
        self.paso_dice_sum   += row["paso_dice_sum"]


@dataclass
class _BotMemory:
    """Estado persistente entre rondas para un bot Expert concreto."""
    last_round:   int  = -1
    player_stats: dict = field(default_factory=lambda: defaultdict(_PlayerStats))
    # Historial de bids de la ronda en curso: list[Bid] (caché local para detectar copiado)
    round_bids:   list = field(default_factory=list)
    # Pasos hechos en la ronda: {player_id: dice_count_at_time}
    round_pasos:  dict = field(default_factory=dict)
    # Flag: ya se fusionaron los stats de DB para esta instancia de bot
    _db_merged:   bool = False


class VeryHardBot(BotStrategy):
    """
    Bot muy difícil.

    Características:
    - Memoria persistente por bot_id con historial real de rivales.
    - Modelado de rivales:
        · bluff_rate global y por cara (ej: "suele mentir con quinas")
        · copy_rate: con qué frecuencia copia la cantidad anterior (+0/+1 misma cara)
          en lugar de apostar de verdad
    - on_reveal(): alimentado por el servidor tras cada dudo/calzo; actualiza
      times_caught_bluffing y face_bluff_counts con datos reales.
    - Ajuste de umbral de dudo:
        · global: bluff_rate alto → umbral sube; conservador → baja
        · por cara: si apostó una cara con la que suele mentir → umbral sube aún más
        · copia: si detecta copiado en esta ronda → +0.04 al umbral
    - Gavilán adaptativo: espera ≥1 bid ajeno; conservador con 5 dados.
    - Calzo perfecto: sin gate aleatorio.
    - Bluff deliberado: ~12% de las veces apuesta intencionalmente débil.
    - Agresividad adaptativa: con ≤3 dados acepta bids con menor umbral y pasa menos.
    """

    # Umbrales de dudo
    DUDO_THRESHOLD_BASE    = 0.18
    DUDO_THRESHOLD_LOW     = 0.14   # apostador muy conservador
    DUDO_THRESHOLD_HIGH    = 0.30   # apostador con alta tasa de bluff global
    DUDO_FACE_BONUS        = 0.06   # bonus si la cara tiene bluff_rate alto
    DUDO_COPY_BONUS        = 0.04   # bonus si el jugador copió en esta ronda

    # Calzo
    CALZO_PROB_MIN         = 0.75
    CALZO_PROB_MIN_RECOVER = 0.68   # umbral más bajo cuando la regla permite recuperar dado
    CALZO_DIFF_MAX         = 0.35
    SAFE_BID_THRESHOLD     = 0.82  # si existe apuesta con prob >= esto, preferir sobre calzo

    # Gavilán
    GAVILAN_PROB_MIN          = 0.85   # sin recuperación
    GAVILAN_PROB_MIN_RECOVER  = 0.78   # con recuperación posible (< 5 dados)
    GAVILAN_PROB_MIN_5DICE    = 0.98
    GAVILAN_RAND              = 0.55
    GAVILAN_RAND_RECOVER      = 0.68   # gate más alto cuando puede recuperar
    GAVILAN_RAND_5DICE        = 0.20
    GAVILAN_MIN_BIDS_IN_ROUND = 1

    # Bid
    BID_MIN_PROB          = 0.55
    BID_MIN_PROB_LOW_DICE = 0.45
    AGGRESSION_LOW_DICE   = 3

    # Bluff
    BLUFF_PROB = 0.12

    # Paso
    PASO_PROB_THRESHOLD          = 0.75
    PASO_PROB_THRESHOLD_LOW_DICE = 0.85
    PASO_RAND                    = 0.50

    # Dudo de paso activo — base; ajustado por _dudo_paso_threshold
    DUDO_PASO_PROB_BASE      = 0.40
    DUDO_PASO_PROB_MAX       = 0.90   # si sabemos que siempre miente
    DUDO_PASO_PROB_MIN       = 0.15   # si sabemos que casi nunca miente

    def _player_threat_score(self, game: "Game", bot_id: str, target_id: str) -> float:
        mem = self._memory.get(bot_id)
        key = self._stable_id(game, target_id)
        stats = mem.player_stats.get(key) if mem else None
        score = float(game.players[target_id].dice_count) if target_id in game.players else 0.0
        if stats and stats.bids_total >= 5:
            if stats.bluff_rate > 0.45:
                score *= 1.3
            elif stats.bluff_rate < 0.15:
                score *= 1.2
        return score

    def decide_direction(self, game: "Game", bot_id: str) -> str | None:
        next_cw = self._next_player_in_dir(game, bot_id, game.direction)
        next_ccw = self._next_player_in_dir(game, bot_id, -game.direction)
        if not next_cw or not next_ccw or next_cw == next_ccw:
            return None
        tc = self._player_threat_score(game, bot_id, next_cw)
        to = self._player_threat_score(game, bot_id, next_ccw)
        own_dice = len(game.players[bot_id].dice)
        threshold = 0.3 if own_dice <= 2 else 0.5
        if to < tc - threshold:
            return "ccw" if game.direction == 1 else "cw"
        return None

    def __init__(self):
        self._memory: dict[str, _BotMemory] = defaultdict(_BotMemory)

    # ------------------------------------------------------------------ helpers de identidad

    @staticmethod
    def _stable_id(game: "Game", player_id: str) -> str:
        """
        Retorna un identificador estable para el jugador entre partidas.
        Usa anon_id si está disponible (jugadores humanos con localStorage),
        o player_id como fallback (bots y jugadores sin ID anónimo).
        """
        p = game.players.get(player_id)
        if p and p.anon_id:
            return p.anon_id
        return player_id

    # ------------------------------------------------------------------ decide

    def _get_mem(self, bot_id: str, game: "Game") -> "_BotMemory":
        """
        Retorna la memoria de este bot, fusionando stats globales (de DB) si
        es la primera vez que este bot_id participa en una partida.
        """
        mem = self._memory[bot_id]
        global_mem = self._memory.get("__global__")
        if global_mem and not mem._db_merged:
            # Copiar stats de jugadores humanos que están en esta partida
            for pid, player in game.players.items():
                if player.anon_id and player.anon_id in global_mem.player_stats:
                    key = player.anon_id
                    if key not in mem.player_stats:
                        # Shallow-copy del objeto de stats global
                        src = global_mem.player_stats[key]
                        dst = mem.player_stats[key]
                        dst.bids_total        = src.bids_total
                        dst.bids_bluff        = src.bids_bluff
                        dst.face_bid_counts   = defaultdict(int, src.face_bid_counts)
                        dst.face_bluff_counts = defaultdict(int, src.face_bluff_counts)
                        dst.qty_bucket_counts = defaultdict(int, src.qty_bucket_counts)
                        dst.qty_bucket_bluff  = defaultdict(int, src.qty_bucket_bluff)
                        dst.copy_count        = src.copy_count
                        dst.total_rounds      = src.total_rounds
                        dst.paso_count        = src.paso_count
                        dst.paso_bluff_count  = src.paso_bluff_count
                        dst.paso_dice_sum     = src.paso_dice_sum
            mem._db_merged = True
        return mem

    def decide(self, game: "Game", bot_id: str) -> dict:
        mem = self._get_mem(bot_id, game)
        self._sync_round_bids(game, bot_id, mem)

        own_dice   = game.players[bot_id].dice
        dice_count = len(own_dice)
        low_dice   = dice_count <= self.AGGRESSION_LOW_DICE

        if game.current_bid is not None:
            bid  = game.current_bid
            prob = self.prob_bid_holds_bayesian(game, bid, bot_id)

            # Gavilán: fuera de turno
            if (bid.player_id != bot_id
                    and game.current_player_id() != bot_id
                    and self._gavilan_allowed(game, bot_id)):
                if self._try_gavilan(game, bot_id, own_dice, dice_count, prob):
                    return {"action": "dudo"}

            # Calzo — umbral más bajo si puede recuperar dado
            is_off_turn   = game.current_player_id() != bot_id
            can_recover   = dice_count < 5 and (
                game.rules.calzo_recovers_on_turn
                or (is_off_turn and game.rules.allow_gavilan)
            )
            calzo_min = self.CALZO_PROB_MIN_RECOVER if can_recover else self.CALZO_PROB_MIN
            if (prob >= calzo_min
                    and bid.player_id != bot_id
                    and self._calzo_makes_sense(game, own_dice)
                    and not self._has_safe_bid_alternative(
                        game, bot_id, own_dice, self.SAFE_BID_THRESHOLD)):
                return {"action": "calzo"}

            # Dudo — umbral enriquecido con modelado
            threshold = self._dudo_threshold(mem, bid, game)
            if prob < threshold:
                return {"action": "dudo"}

        if game.last_paso is not None:
            passer_id  = game.last_paso["player_id"]
            dudo_prob  = self._dudo_paso_threshold(mem, passer_id, game)
            p_bluff    = self.prob_paso_is_bluff(game, passer_id)
            # Si es imposible físicamente (< 5 dados) → siempre duda
            if p_bluff >= 1.0:
                return {"action": "dudo"}
            if random.random() < dudo_prob:
                return {"action": "dudo"}

        paso_threshold = self.PASO_PROB_THRESHOLD_LOW_DICE if low_dice else self.PASO_PROB_THRESHOLD
        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > paso_threshold and random.random() < self.PASO_RAND:
                return {"action": "paso"}

        return self._choose_bid(game, bot_id, own_dice, low_dice)

    # ------------------------------------------------------------------ feedback del servidor

    @staticmethod
    def _qty_bucket(qty: int, total_dice: int) -> int:
        """Clasifica una cantidad de apuesta en bucket 1=baja, 2=media, 3=alta."""
        expected = total_dice / 6  # valor esperado de cualquier cara sin comodines
        if qty <= expected * 0.7:
            return 1
        if qty >= expected * 1.3:
            return 3
        return 2

    def on_round_reveal(self, bot_id: str, game: "Game", all_dice: dict[str, list[int]]) -> None:
        """
        Llamado tras cada dudo/calzo cuando se conocen todos los dados de la mesa.
        Recorre TODA la bid_history de la ronda y para cada apuesta calcula
        retroactivamente si era verdad o mentira usando los dados reales.

        Esto permite aprender de TODAS las jugadas, no solo de las dudadas.

        all_dice: {player_id: [d1, d2, ...]}  — dados reales de todos
        """
        mem        = self._get_mem(bot_id, game)
        total_dice = sum(len(v) for v in all_dice.values())
        if total_dice == 0:
            return

        # Construir conteo global de dados por cara (con comodines solo para caras != 1)
        # Los comodines (1) cuentan para todas las caras excepto cuando la cara bid es 1
        aces = sum(1 for dice in all_dice.values() for d in dice if d == 1)

        def count_face(face: int) -> int:
            if face == 1:
                return sum(1 for dice in all_dice.values() for d in dice if d == 1)
            return sum(1 for dice in all_dice.values() for d in dice if d == face) + aces

        for bid in mem.round_bids:
            pid     = getattr(bid, "player_id", None)
            face    = getattr(bid, "face", None)
            qty     = getattr(bid, "quantity", None)
            elapsed = getattr(bid, "elapsed_seconds", 0.0)
            if pid is None or face is None or qty is None:
                continue

            key    = self._stable_id(game, pid)
            stats  = mem.player_stats[key]
            bucket = self._qty_bucket(qty, total_dice)
            is_bluff = count_face(face) < qty

            stats.bids_total += 1
            stats.face_bid_counts[face]     += 1
            stats.qty_bucket_counts[bucket] += 1
            if is_bluff:
                stats.bids_bluff += 1
                stats.face_bluff_counts[face]   += 1
                stats.qty_bucket_bluff[bucket]  += 1

            # Acumular tiempo de decisión si hay dato válido (>0 = fue registrado)
            if elapsed > 0:
                if is_bluff:
                    stats.bid_time_bluff_sum += elapsed
                    stats.bid_time_bluff_n   += 1
                else:
                    stats.bid_time_truth_sum += elapsed
                    stats.bid_time_truth_n   += 1

        self._detect_copy_patterns(mem)

    def on_reveal(self, bot_id: str, result: dict, game: "Game | None" = None):
        """
        Llamado por el manager tras cada dudo/calzo resuelto.
        Delega el aprendizaje retroactivo a on_round_reveal() que usa all_dice.
        Aquí solo maneja el caso de paso (que no tiene all_dice completo).
        """
        action = result.get("action")
        if action not in ("dudo", "calzo", "paso"):
            return

        mem = self._get_mem(bot_id, game) if game else self._memory[bot_id]

        def stable(pid: str) -> str:
            return self._stable_id(game, pid) if game else pid

        if action in ("dudo", "calzo"):
            # El aprendizaje retroactivo de bids se hace en on_round_reveal().
            # Solo queda procesar all_dice si está disponible aquí también
            # (on_round_reveal se llama desde notify_reveal en el manager).
            pass

        elif action == "paso":
            passer_id  = result.get("passer_id")
            paso_valid = result.get("paso_valid", True)
            if passer_id and passer_id != bot_id:
                key   = stable(passer_id)
                stats = mem.player_stats[key]
                if passer_id not in mem.round_pasos:
                    stats.paso_count    += 1
                    stats.paso_dice_sum += 5
                    mem.round_pasos[passer_id] = 5
                if not paso_valid:
                    stats.paso_bluff_count += 1

    def on_paso_made(self, bot_id: str, passer_id: str, passer_dice_count: int, stable_passer_id: str | None = None):
        """
        Llamado por el manager cuando alguien hace un paso (antes de ser dudado).
        Registra dados al momento del paso para avg_dice_when_paso.
        """
        if passer_id == bot_id:
            return
        mem   = self._memory[bot_id]  # no necesita game aquí
        key   = stable_passer_id or passer_id
        stats = mem.player_stats[key]
        if passer_id not in mem.round_pasos:
            stats.paso_count    += 1
            stats.paso_dice_sum += passer_dice_count
            mem.round_pasos[passer_id] = passer_dice_count

    # ------------------------------------------------------------------ helpers internos

    def _sync_round_bids(self, game: "Game", bot_id: str, mem: _BotMemory):
        """
        Mantiene mem.round_bids sincronizado con game.bid_history.
        No registra bids propios. Detecta inicio de ronda nueva para limpiar.
        Los conteos de bids se actualizan retroactivamente en on_round_reveal().
        """
        current_round = game.round_number
        if current_round != mem.last_round:
            mem.round_bids  = []
            mem.round_pasos = {}
            mem.last_round  = current_round

        # Añadir bids nuevos que game.bid_history tenga y round_bids no
        known = len(mem.round_bids)
        for bid in game.bid_history[known:]:
            if getattr(bid, "player_id", None) != bot_id:
                mem.round_bids.append(bid)

    def _detect_copy_patterns(self, mem: _BotMemory):
        """
        Analiza mem.round_bids para detectar si un jugador "copió" la apuesta
        anterior: subió la cantidad en 0 o 1 con la misma cara.
        Incrementa copy_count para ese jugador.
        """
        bids = mem.round_bids
        for i in range(1, len(bids)):
            prev = bids[i - 1]
            curr = bids[i]
            pid  = getattr(curr, "player_id", None)
            if not pid:
                continue
            same_face   = getattr(curr, "face", None) == getattr(prev, "face", None)
            qty_diff    = getattr(curr, "quantity", 0) - getattr(prev, "quantity", 0)
            if same_face and 0 <= qty_diff <= 1:
                mem.player_stats[pid].copy_count += 1

    def _dudo_paso_threshold(self, mem: _BotMemory, passer_id: str, game: "Game") -> float:
        """
        Probabilidad de dudar el paso activo, ajustada por el historial del pasador.

        Factores:
        1. Si el pasador tiene < 5 dados → siempre mentira (retorna 1.0).
        2. paso_bluff_rate histórico: si suele mentir al paso → más probable dudar.
        3. avg_dice_when_paso: si suele pasar con pocos dados → más probable dudar.
        4. Sin historial suficiente → usa la base.
        """
        passer = game.players.get(passer_id)
        if passer and passer.dice_count < 5:
            return 1.0  # físicamente imposible → siempre duda

        key   = self._stable_id(game, passer_id)
        stats = mem.player_stats.get(key)
        if stats is None or stats.paso_count < 2:
            return self.DUDO_PASO_PROB_BASE

        prob = self.DUDO_PASO_PROB_BASE

        br = stats.paso_bluff_rate
        if br > 0.60:
            prob = min(prob + 0.30, self.DUDO_PASO_PROB_MAX)
        elif br > 0.40:
            prob = min(prob + 0.15, self.DUDO_PASO_PROB_MAX)
        elif br < 0.10:
            prob = max(prob - 0.20, self.DUDO_PASO_PROB_MIN)

        avg = stats.avg_dice_when_paso
        if avg < 4.0:
            prob = min(prob + 0.15, self.DUDO_PASO_PROB_MAX)

        return prob

    def _dudo_threshold(self, mem: _BotMemory, bid: "Bid", game: "Game") -> float:
        """
        Umbral de dudo enriquecido con modelado de rivales y ML.

        Señales usadas:
        1. bluff_rate global retroactivo (todas las apuestas, no solo dudadas).
        2. face_bluff_rate para la cara concreta apostada.
        3. qty_bluff_rate para el bucket de cantidad (baja/media/alta).
        4. copy_rate en esta ronda: copiador = señal de juego débil.
        5. Tiempo de decisión: comparado contra promedio histórico del jugador,
           y contra su patrón diferenciado bluff-vs-verdad.
        6. BluffModel ML: si hay suficientes datos, ajusta el umbral con P(bluff).
        """
        from game.player_model import bluff_model  # import local para evitar circular

        bidder_id = bid.player_id
        key       = self._stable_id(game, bidder_id)
        stats     = mem.player_stats.get(key)

        if stats is None:
            return self.DUDO_THRESHOLD_BASE

        total_dice = game.total_dice()
        bucket     = self._qty_bucket(bid.quantity, total_dice)
        elapsed    = getattr(bid, "elapsed_seconds", 0.0)

        # 1. Base global retroactiva
        br = stats.bluff_rate
        if br > 0.40:
            threshold = self.DUDO_THRESHOLD_HIGH
        elif br < 0.10 and stats.bids_total >= 5:
            threshold = self.DUDO_THRESHOLD_LOW
        else:
            threshold = self.DUDO_THRESHOLD_BASE

        # 2. Cara específica
        face_br = stats.face_bluff_rate(bid.face)
        if face_br > 0.50 and stats.face_bid_counts.get(bid.face, 0) >= 2:
            threshold += self.DUDO_FACE_BONUS

        # 3. Bucket de cantidad
        qty_br = stats.qty_bluff_rate(bucket)
        if qty_br > 0.55 and stats.qty_bucket_counts.get(bucket, 0) >= 3:
            threshold += 0.04

        # 4. Copiado en esta ronda
        bids = mem.round_bids
        if len(bids) >= 2:
            prev = bids[-2]
            curr = bids[-1]
            if (getattr(curr, "player_id", None) == bidder_id
                    and getattr(curr, "face", None) == getattr(prev, "face", None)
                    and 0 <= getattr(curr, "quantity", 0) - getattr(prev, "quantity", 0) <= 1):
                threshold += self.DUDO_COPY_BONUS

        # 5. Tiempo de decisión
        if elapsed > 0 and stats.time_sample_count >= 5:
            own_avg = stats.avg_decision_time
            ratio   = elapsed / max(own_avg, 0.5)

            # Anomalía: mucho más rápido o mucho más lento que su propio promedio
            if ratio < 0.40 or ratio > 2.5:
                threshold += 0.03

            # Comparar contra patrones diferenciados bluff vs verdad
            if stats.bid_time_bluff_n >= 3 and stats.bid_time_truth_n >= 3:
                bluff_avg = stats.avg_bluff_time
                truth_avg = stats.avg_truth_time
                # Solo aplicar si hay diferencia notable entre sus patrones
                if abs(bluff_avg - truth_avg) > 2.0:
                    dist_bluff = abs(elapsed - bluff_avg)
                    dist_truth = abs(elapsed - truth_avg)
                    if dist_bluff < dist_truth:
                        threshold += 0.04   # tiempo más parecido a cuando miente
                    else:
                        threshold -= 0.02   # tiempo más parecido a cuando dice verdad

        # 6. ML
        p_bluff_ml = bluff_model.predict_bluff(key, bid.face, bucket, elapsed, stats)
        if p_bluff_ml is not None:
            ml_signal = (p_bluff_ml - 0.5) * 0.20  # rango ±0.10
            threshold += ml_signal

        return min(threshold, 0.45)

    def _gavilan_allowed(self, game: "Game", bot_id: str) -> bool:
        if not game.rules.allow_gavilan:
            return False
        foreign_bids = sum(
            1 for b in game.bid_history
            if getattr(b, "player_id", None) != bot_id
        )
        return foreign_bids >= self.GAVILAN_MIN_BIDS_IN_ROUND

    def _try_gavilan(self, game: "Game", bot_id: str,
                     own_dice: list, dice_count: int, prob: float) -> bool:
        if dice_count >= 5:
            # Sin posibilidad de recuperar: umbral muy exigente
            threshold = self.GAVILAN_PROB_MIN_5DICE
            gate      = self.GAVILAN_RAND_5DICE
        else:
            # Puede recuperar un dado si gana el gavilán → más agresivo
            threshold = self.GAVILAN_PROB_MIN_RECOVER
            gate      = self.GAVILAN_RAND_RECOVER

        if prob < threshold:
            return False

        bid     = game.current_bid
        face    = bid.face
        unknown = game.total_dice() - len(own_dice)
        if face == 1:
            own_m           = sum(1 for d in own_dice if d == 1)
            expected_others = unknown / 6
        else:
            own_m           = sum(1 for d in own_dice if d == face or d == 1)
            expected_others = unknown * 2 / 6

        expected_total = own_m + expected_others
        if expected_total < bid.quantity:
            return False

        return random.random() < gate

    def _calzo_makes_sense(self, game: "Game", own_dice: list) -> bool:
        bid     = game.current_bid
        face    = bid.face
        unknown = game.total_dice() - len(own_dice)
        if face == 1:
            own_m           = sum(1 for d in own_dice if d == 1)
            expected_others = unknown / 6
        else:
            own_m           = sum(1 for d in own_dice if d == face or d == 1)
            expected_others = unknown * 2 / 6
        return abs(own_m + expected_others - bid.quantity) <= self.CALZO_DIFF_MAX

    def _has_safe_bid_alternative(self, game: "Game", bot_id: str, own_dice: list, safe_prob: float) -> bool:
        """True si existe una apuesta válida con probabilidad >= safe_prob."""
        strong = self._strong_faces(own_dice)
        for c in self.candidate_bids(game, bot_id, max_candidates=25, prefer_faces=strong):
            if self.prob_bid_holds_bayesian(game, c, bot_id) >= safe_prob:
                return True
        return False

    def _choose_bid(self, game: "Game", bot_id: str,
                    own_dice: list, low_dice: bool) -> dict:
        strong     = self._strong_faces(own_dice)
        candidates = self.candidate_bids(game, bot_id, max_candidates=40, prefer_faces=strong)

        if not candidates:
            return {"action": "dudo"} if game.current_bid else {"action": "bid", "quantity": 1, "face": 2}

        scored   = [(b, self.prob_bid_holds_bayesian(game, b, bot_id)) for b in candidates]
        min_prob = self.BID_MIN_PROB_LOW_DICE if low_dice else self.BID_MIN_PROB

        # Bluff deliberado
        if random.random() < self.BLUFF_PROB:
            weak = [(b, p) for b, p in scored if p < 0.45]
            if weak:
                weak.sort(key=lambda x: x[1], reverse=True)
                chosen = weak[0][0]
                return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

        chosen = self._pick_bid(scored, min_prob, aggression=0.20)

        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    @staticmethod
    def _strong_faces(dice: list[int]) -> list[int]:
        if not dice:
            return list(range(2, 7)) + [1]
        aces        = sum(1 for d in dice if d == 1)
        face_counts = {f: sum(1 for d in dice if d == f) + aces for f in range(2, 7)}
        return sorted(face_counts, key=lambda f: -face_counts[f]) + [1]


# ---------------------------------------------------------------------------
# ExpertBot — sistema híbrido de cuatro capas sobre VeryHardBot
#
# [1] ML Signal Layer       — Gradient Boosting heredado de VeryHardBot (sin cambios)
# [2] In-Game Behavior      — modelado dinámico por jugador dentro de la partida
# [3] Multi-Player Context  — análisis posicional con múltiples jugadores
# [4] Nash-Aware Stabilizer — limita desviación del juego óptimo aproximado
#
# FinalThreshold = Expert_threshold
#                + InGameBehaviorSignal
#                + MultiPlayerContextSignal
#                + PositioningSignal
#                + NashBaselineAdjustment
# ---------------------------------------------------------------------------


@dataclass
class InGamePlayerState:
    """
    Estado comportamental de un jugador observado en la partida actual.
    Se resetea automáticamente cada partida (bot_id es UUID nuevo por partida).
    Complementa _PlayerStats (histórico entre partidas) con señales en tiempo real.
    """
    actions_total:   int = 0
    bids_game:       int = 0
    dudos_game:      int = 0
    calzos_game:     int = 0
    pasos_game:      int = 0
    # Resultados de duelos propios (ellos dudaron/calzaron)
    duelos_won:      int = 0
    duelos_lost:     int = 0
    calzos_hit:      int = 0
    calzos_missed:   int = 0
    # Bluff/verdad clasificados retroactivamente por on_round_reveal
    bluffs_observed: int = 0
    truths_observed: int = 0
    # Ventana de últimas 8 acciones
    recent_actions: list = field(default_factory=list)

    @property
    def aggression_index(self) -> float:
        total = self.bids_game + self.dudos_game + self.calzos_game
        return self.dudos_game / max(total, 1)

    @property
    def calzo_tendency(self) -> float:
        total = self.bids_game + self.dudos_game + self.calzos_game
        return self.calzos_game / max(total, 1)

    @property
    def pass_tendency(self) -> float:
        return self.pasos_game / max(self.actions_total, 1)

    @property
    def ingame_bluff_rate(self) -> float:
        total = self.bluffs_observed + self.truths_observed
        return self.bluffs_observed / max(total, 1) if total else 0.5

    @property
    def dudo_success_rate(self) -> float:
        total = self.duelos_won + self.duelos_lost
        return self.duelos_won / max(total, 1)

    @property
    def volatility_index(self) -> float:
        if self.actions_total < 4:
            return 0.5
        t = max(self.actions_total, 1)
        probs = [self.bids_game / t, self.dudos_game / t,
                 self.calzos_game / t, self.pasos_game / t]
        return min(sum((p - 0.25) ** 2 for p in probs), 1.0)

    def add_action(self, action_type: str) -> None:
        self.actions_total += 1
        self.recent_actions.append(action_type)
        if len(self.recent_actions) > 8:
            self.recent_actions.pop(0)
        if action_type == "bid":
            self.bids_game += 1
        elif action_type == "dudo":
            self.dudos_game += 1
        elif action_type == "calzo":
            self.calzos_game += 1
        elif action_type == "paso":
            self.pasos_game += 1


@dataclass
class NashBaselineState:
    """
    Estado Nash-aware de la mesa. Controla desviación máxima del juego óptimo aproximado.

    nash_drift_limit escala con el stage del juego:
      early (>70% dados): ±0.10 — conservador
      mid   (40-70%):     ±0.17 — equilibrado
      late  (<40%):       ±0.25 — explotación máxima
    """
    total_dice_initial:       int   = 10
    current_total_dice:       int   = 10
    average_table_aggression: float = 0.0
    exploit_streak:           int   = 0    # rondas consecutivas explotando al límite

    @property
    def game_stage(self) -> str:
        ratio = self.current_total_dice / max(self.total_dice_initial, 1)
        if ratio > 0.70:
            return "early"
        if ratio > 0.40:
            return "mid"
        return "late"

    @property
    def nash_drift_limit(self) -> float:
        base = {"early": 0.10, "mid": 0.17, "late": 0.25}[self.game_stage]
        if self.exploit_streak >= 3:
            base *= 0.70   # anti-overfitting
        return base

    def update(self, game: "Game") -> None:
        self.current_total_dice = game.total_dice()


class ExpertBot(VeryHardBot):
    """
    Bot Expert — hereda de VeryHardBot y añade tres capas extra:
    comportamiento in-game, análisis multi-jugador y estabilización Nash-aware.
    """

    EXPERT_CALZO_PROB_MIN         = 0.72
    EXPERT_CALZO_PROB_MIN_RECOVER = 0.65   # con recuperación activa y < 5 dados
    EXPERT_SAFE_BID_THRESHOLD     = 0.80  # si existe apuesta con prob >= esto, preferir sobre calzo
    EXPERT_BID_MIN_PROB           = 0.52
    EXPERT_BLUFF_PROB             = 0.10

    def __init__(self):
        super().__init__()
        # bot_id → {stable_player_id → InGamePlayerState}
        self._igps: dict[str, dict[str, InGamePlayerState]] = defaultdict(dict)
        # bot_id → NashBaselineState
        self._nash: dict[str, NashBaselineState] = {}
        # watermark para evitar doble-conteo al sincronizar round_bids con IGPS
        self._igps_watermark: dict[str, int] = defaultdict(int)
        # bot_id activo durante decide() — se usa en _dudo_threshold
        self._current_bot_id: str = ""

    def _player_threat_score(self, game: "Game", bot_id: str, target_id: str) -> float:
        score = super()._player_threat_score(game, bot_id, target_id)
        key = self._stable_id(game, target_id)
        igps = self._igps.get(bot_id, {}).get(key)
        if igps and igps.actions_total >= 3:
            if igps.aggression_index > 0.55:
                score *= 1.3
            if igps.calzo_tendency > 0.25 and igps.calzos_game >= 2:
                hit_rate = igps.calzos_hit / max(igps.calzos_game, 1)
                if hit_rate > 0.5:
                    score *= 1.25
        return score

    # ------------------------------------------------------------------ IGPS / Nash

    def _get_igps(self, bot_id: str, player_key: str) -> InGamePlayerState:
        d = self._igps[bot_id]
        if player_key not in d:
            d[player_key] = InGamePlayerState()
        return d[player_key]

    def _get_nash(self, bot_id: str, game: "Game") -> NashBaselineState:
        if bot_id not in self._nash:
            total = game.total_dice()
            self._nash[bot_id] = NashBaselineState(
                total_dice_initial=total,
                current_total_dice=total,
            )
        n = self._nash[bot_id]
        n.update(game)
        return n

    def _update_table_aggression(self, bot_id: str) -> None:
        d = self._igps.get(bot_id, {})
        if not d:
            return
        nash = self._nash.get(bot_id)
        if nash is None:
            return
        avg = sum(s.aggression_index for s in d.values()) / len(d)
        nash.average_table_aggression = 0.7 * nash.average_table_aggression + 0.3 * avg

    # ------------------------------------------------------------------ señales

    def _ingame_behavior_signal(
        self, igps: InGamePlayerState, stats: "_PlayerStats"
    ) -> float:
        """
        Capa 2: ajuste al umbral de dudo por comportamiento observado en esta partida.
        Retorna valor en [-0.10, +0.12].
        """
        if igps.actions_total < 3:
            return 0.0

        signal = 0.0
        obs = igps.bluffs_observed + igps.truths_observed

        # Diferencia entre tasa de bluff in-game y la histórica
        if obs >= 2:
            delta = igps.ingame_bluff_rate - stats.bluff_rate
            signal += delta * 0.18  # aprox ±0.09

        # Calza mucho: sus bids tienen respaldo real → menos dudo
        if igps.calzo_tendency > 0.30 and igps.calzos_game >= 2:
            signal -= 0.04

        # Muy agresivo dudando: cuando apuesta, está seguro → menos dudo
        if igps.aggression_index > 0.55 and igps.dudos_game >= 2:
            signal -= 0.04

        # Alta volatilidad: comportamiento errático → conservadurismo
        if igps.volatility_index > 0.65 and igps.actions_total >= 5:
            signal -= 0.03

        # Calzo exitoso reciente (últimas 4 acciones): mano fuerte en este momento
        recent_calzos = igps.recent_actions[-4:].count("calzo")
        if recent_calzos >= 2:
            signal -= 0.04

        return max(-0.10, min(0.12, signal))

    def _multiplayer_context_signal(
        self,
        igps_dict: dict,
        game: "Game",
        bid_player_key: str,
        bot_id: str,
    ) -> float:
        """
        Capa 3: señal de posición y comportamiento de mesa.
        Solo relevante con ≥3 jugadores. Retorna valor en [-0.06, +0.08].
        """
        order = game.player_order
        n = len(order)
        if n < 3:
            return 0.0

        signal = 0.0
        try:
            bot_pos    = order.index(bot_id)
            bidder_pos = (order.index(game.current_bid.player_id)
                          if game.current_bid else -1)
        except ValueError:
            return 0.0

        if bidder_pos >= 0:
            dist = (bot_pos - bidder_pos) % n
            proximity = 1.0 / max(dist, 1)
            igps_b = igps_dict.get(bid_player_key)
            if igps_b and igps_b.actions_total >= 3:
                if igps_b.ingame_bluff_rate > 0.55:
                    signal += proximity * 0.04
                # Calzo-spammer próximo: sus bids tienen respaldo → menos dudo
                if igps_b.calzo_tendency > 0.30 and dist == 1:
                    signal -= 0.03

        # Mesa muy agresiva: más jugadores que dudan frecuentemente
        aggressive = sum(
            1 for s in igps_dict.values()
            if s.aggression_index > 0.50 and s.actions_total >= 3
        )
        if aggressive >= 2:
            signal += 0.02

        return max(-0.06, min(0.08, signal))

    def _positioning_signal(self, game: "Game") -> float:
        """Penalización si somos los que abren la ronda (menos información)."""
        return -0.03 if game.current_bid is None else 0.0

    def _player_exploitability(
        self, igps: InGamePlayerState, stats: "_PlayerStats"
    ) -> float:
        """Cuán predecible y explotable es el jugador [0, 1]."""
        score = 0.40
        if stats.bids_total >= 20:
            score += 0.15
        elif stats.bids_total >= 8:
            score += 0.07
        if igps.actions_total >= 6 and igps.volatility_index < 0.30:
            score += 0.20
        elif igps.volatility_index > 0.70:
            score -= 0.20
        if stats.bluff_rate > 0.50:
            score += 0.10
        obs = igps.bluffs_observed + igps.truths_observed
        if obs >= 3 and igps.ingame_bluff_rate > 0.55:
            score += 0.10
        return max(0.0, min(1.0, score))

    def _nash_adjustment(
        self,
        nash: NashBaselineState,
        exploit_signal: float,
        exploitability: float,
    ) -> float:
        """
        Capa 4: escala exploit_signal por exploitability y lo clampea al drift limit.
        Actualiza exploit_streak para anti-overfitting.
        """
        raw     = exploit_signal * exploitability
        limit   = nash.nash_drift_limit
        clamped = max(-limit, min(limit, raw))
        if abs(clamped) > limit * 0.75:
            nash.exploit_streak += 1
        else:
            nash.exploit_streak = max(0, nash.exploit_streak - 1)
        return clamped

    # ------------------------------------------------------------------ decide

    def _sync_round_bids(self, game: "Game", bot_id: str, mem: "_BotMemory") -> None:
        """Extiende el padre para alimentar IGPS con cada nueva apuesta vista."""
        cur_round = game.round_number
        if cur_round != mem.last_round:
            self._igps_watermark[bot_id] = 0

        super()._sync_round_bids(game, bot_id, mem)

        watermark  = self._igps_watermark[bot_id]
        new_bids   = mem.round_bids[watermark:]
        for bid in new_bids:
            pid = getattr(bid, "player_id", None)
            if pid:
                key = self._stable_id(game, pid)
                self._get_igps(bot_id, key).add_action("bid")
        self._igps_watermark[bot_id] = len(mem.round_bids)

    def decide(self, game: "Game", bot_id: str) -> dict:
        self._current_bot_id = bot_id
        mem      = self._get_mem(bot_id, game)
        nash     = self._get_nash(bot_id, game)
        self._sync_round_bids(game, bot_id, mem)
        self._update_table_aggression(bot_id)

        own_dice   = game.players[bot_id].dice
        dice_count = len(own_dice)
        low_dice   = dice_count <= self.AGGRESSION_LOW_DICE

        if game.current_bid is not None:
            bid  = game.current_bid
            prob = self.prob_bid_holds_bayesian(game, bid, bot_id)

            # Gavilán (heredado)
            if (bid.player_id != bot_id
                    and game.current_player_id() != bot_id
                    and self._gavilan_allowed(game, bot_id)):
                if self._try_gavilan(game, bot_id, own_dice, dice_count, prob):
                    return {"action": "dudo"}

            # Calzo — umbral más bajo si puede recuperar; evita calzar a spammers
            is_off_turn      = game.current_player_id() != bot_id
            can_recover      = dice_count < 5 and (
                game.rules.calzo_recovers_on_turn
                or (is_off_turn and game.rules.allow_gavilan)
            )
            expert_calzo_min = (
                self.EXPERT_CALZO_PROB_MIN_RECOVER if can_recover
                else self.EXPERT_CALZO_PROB_MIN
            )
            if (prob >= expert_calzo_min
                    and bid.player_id != bot_id
                    and self._calzo_makes_sense(game, own_dice)
                    and not self._skip_calzo_vs_spammer(bot_id, bid.player_id, game)
                    and not self._has_safe_bid_alternative(
                        game, bot_id, own_dice, self.EXPERT_SAFE_BID_THRESHOLD)):
                return {"action": "calzo"}

            # Dudo — umbral enriquecido con las 4 capas
            threshold = self._dudo_threshold(mem, bid, game)
            if prob < threshold:
                return {"action": "dudo"}

        if game.last_paso is not None:
            passer_id = game.last_paso["player_id"]
            dudo_prob = self._dudo_paso_threshold(mem, passer_id, game)
            p_bluff   = self.prob_paso_is_bluff(game, passer_id)
            if p_bluff >= 1.0:
                return {"action": "dudo"}
            if random.random() < dudo_prob:
                return {"action": "dudo"}

        paso_threshold = (self.PASO_PROB_THRESHOLD_LOW_DICE if low_dice
                          else self.PASO_PROB_THRESHOLD)
        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > paso_threshold and random.random() < self.PASO_RAND:
                return {"action": "paso"}

        return self._expert_choose_bid(game, bot_id, own_dice, low_dice, nash)

    def _skip_calzo_vs_spammer(
        self, bot_id: str, bidder_id: str, game: "Game"
    ) -> bool:
        """Evita calzar a jugadores que calzan mucho (probablemente tienen dados fuertes)."""
        key  = self._stable_id(game, bidder_id)
        igps = self._igps[bot_id].get(key)
        if igps and igps.calzo_tendency > 0.40 and igps.calzos_game >= 2:
            return random.random() < 0.55
        return False

    def _dudo_threshold(self, mem: "_BotMemory", bid: "Bid", game: "Game") -> float:
        """
        Override: añade capas 2-4 al umbral base del ExpertBot (capas 1 + ML).
        """
        base = super()._dudo_threshold(mem, bid, game)

        bot_id = self._current_bot_id
        if not bot_id:
            return base

        bidder_id = bid.player_id
        key       = self._stable_id(game, bidder_id)
        stats     = mem.player_stats.get(key)
        if stats is None:
            return base

        igps      = self._get_igps(bot_id, key)
        igps_dict = self._igps.get(bot_id, {})
        nash      = self._get_nash(bot_id, game)

        # Capa 2: comportamiento in-game
        igbs = self._ingame_behavior_signal(igps, stats)

        # Capa 3: contexto multi-jugador
        mps  = self._multiplayer_context_signal(igps_dict, game, key, bot_id)

        # Posicionamiento
        pos  = self._positioning_signal(game)

        # Capa 4: Nash-aware
        exploit_signal = igbs + mps
        exploitability = self._player_exploitability(igps, stats)
        nash_adj       = self._nash_adjustment(nash, exploit_signal, exploitability)

        final = base + nash_adj + pos
        return max(0.08, min(0.50, final))

    def _expert_choose_bid(
        self,
        game: "Game",
        bot_id: str,
        own_dice: list,
        low_dice: bool,
        nash: NashBaselineState,
    ) -> dict:
        """Bid con agresividad adaptada al contexto de la mesa."""
        igps_dict  = self._igps.get(bot_id, {})
        aggression = 0.20

        # Late game → más agresivo
        if nash.game_stage == "late":
            aggression += 0.08
        elif nash.game_stage == "early":
            aggression -= 0.03

        # Jugadores pasivos → más presión
        passive = sum(
            1 for s in igps_dict.values()
            if s.pass_tendency > 0.40 and s.actions_total >= 4
        )
        if passive >= 1:
            aggression += 0.05

        # Jugadores agresivos → variar para inducir error
        aggressive = sum(
            1 for s in igps_dict.values()
            if s.aggression_index > 0.55 and s.actions_total >= 4
        )
        if aggressive >= 1:
            aggression -= 0.04

        # Caras a deprioritizar: evitar dar calzo fácil a calzo-spammers
        avoid_face = None
        if game.current_bid is not None:
            for pid, player in game.players.items():
                if pid == bot_id:
                    continue
                key = self._stable_id(game, pid)
                s = igps_dict.get(key)
                if s and s.calzo_tendency > 0.35 and s.calzos_game >= 2:
                    avoid_face = game.current_bid.face
                    break

        strong = self._strong_faces(own_dice)
        if avoid_face is not None:
            strong = ([f for f in strong if f != avoid_face]
                      + [f for f in strong if f == avoid_face])

        candidates = self.candidate_bids(game, bot_id, max_candidates=40,
                                         prefer_faces=strong)
        if not candidates:
            return ({"action": "dudo"} if game.current_bid
                    else {"action": "bid", "quantity": 1, "face": 2})

        scored   = [(b, self.prob_bid_holds_bayesian(game, b, bot_id))
                    for b in candidates]
        min_prob = self.BID_MIN_PROB_LOW_DICE if low_dice else self.EXPERT_BID_MIN_PROB

        # Bluff deliberado controlado
        if random.random() < self.EXPERT_BLUFF_PROB:
            weak = [(b, p) for b, p in scored if p < 0.45]
            if weak:
                weak.sort(key=lambda x: x[1], reverse=True)
                chosen = weak[0][0]
                return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

        aggression = max(0.05, min(0.40, aggression))
        chosen = self._pick_bid(scored, min_prob, aggression=aggression)
        return {"action": "bid", "quantity": chosen.quantity, "face": chosen.face}

    # ------------------------------------------------------------------ feedback del servidor

    def on_round_reveal(
        self, bot_id: str, game: "Game", all_dice: dict[str, list[int]]
    ) -> None:
        """Extiende el padre para clasificar bids como bluff/verdad en IGPS."""
        super().on_round_reveal(bot_id, game, all_dice)

        total_dice = sum(len(v) for v in all_dice.values())
        if total_dice == 0:
            return

        aces = sum(1 for dice in all_dice.values() for d in dice if d == 1)

        def count_face(face: int) -> int:
            if face == 1:
                return sum(1 for dice in all_dice.values() for d in dice if d == 1)
            return (sum(1 for dice in all_dice.values() for d in dice if d == face)
                    + aces)

        mem = self._get_mem(bot_id, game)
        for bid in mem.round_bids:
            pid  = getattr(bid, "player_id", None)
            face = getattr(bid, "face", None)
            qty  = getattr(bid, "quantity", None)
            if pid is None or face is None or qty is None:
                continue
            key  = self._stable_id(game, pid)
            igps = self._get_igps(bot_id, key)
            if count_face(face) < qty:
                igps.bluffs_observed += 1
            else:
                igps.truths_observed += 1

    def on_reveal(self, bot_id: str, result: dict, game: "Game | None" = None) -> None:
        """Extiende el padre para registrar resultados de duelos/calzos en IGPS."""
        super().on_reveal(bot_id, result, game)
        if game is None:
            return

        action = result.get("action")
        challenger_id = result.get("challenger_id")
        if not challenger_id or challenger_id == bot_id:
            return

        key  = self._stable_id(game, challenger_id)
        igps = self._get_igps(bot_id, key)

        if action == "dudo":
            loser_id = result.get("loser_id")
            # bid_holds=True → apostador ganó → challenger perdió el dudo
            if result.get("bid_holds"):
                igps.duelos_lost += 1
            else:
                igps.duelos_won += 1
            igps.add_action("dudo")

        elif action == "calzo":
            if result.get("calzo_success"):
                igps.calzos_hit += 1
            else:
                igps.calzos_missed += 1
            igps.add_action("calzo")

    def on_paso_made(
        self,
        bot_id: str,
        passer_id: str,
        passer_dice_count: int,
        stable_passer_id: str | None = None,
    ) -> None:
        """Extiende el padre para registrar paso en IGPS del pasador."""
        super().on_paso_made(bot_id, passer_id, passer_dice_count, stable_passer_id)
        key  = stable_passer_id or passer_id
        igps = self._get_igps(bot_id, key)
        igps.add_action("paso")

    def _get_mem(self, bot_id: str, game: "Game") -> "_BotMemory":
        """
        Override: si no tenemos global_mem propio, usamos el de VeryHardBot
        (que contiene los stats de DB cargados en startup).
        """
        mem        = self._memory[bot_id]
        global_mem = self._memory.get("__global__")

        # Fallback: usar la memoria global del VeryHardBot singleton
        if global_mem is None:
            try:
                vh = _REGISTRY.get("very_hard")
            except NameError:
                vh = None
            if isinstance(vh, VeryHardBot) and vh is not self:
                global_mem = vh._memory.get("__global__")

        if global_mem and not mem._db_merged:
            for pid, player in game.players.items():
                if player.anon_id and player.anon_id in global_mem.player_stats:
                    key = player.anon_id
                    if key not in mem.player_stats:
                        src = global_mem.player_stats[key]
                        dst = mem.player_stats[key]
                        dst.bids_total        = src.bids_total
                        dst.bids_bluff        = src.bids_bluff
                        dst.face_bid_counts   = defaultdict(int, src.face_bid_counts)
                        dst.face_bluff_counts = defaultdict(int, src.face_bluff_counts)
                        dst.qty_bucket_counts = defaultdict(int, src.qty_bucket_counts)
                        dst.qty_bucket_bluff  = defaultdict(int, src.qty_bucket_bluff)
                        dst.copy_count        = src.copy_count
                        dst.total_rounds      = src.total_rounds
                        dst.paso_count        = src.paso_count
                        dst.paso_bluff_count  = src.paso_bluff_count
                        dst.paso_dice_sum     = src.paso_dice_sum
            mem._db_merged = True

        return mem


# ---------------------------------------------------------------------------
# Registro de estrategias
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, BotStrategy] = {
    "easy":      EasyBot(),
    "medium":    MediumBot(),
    "hard":      HardBot(),
    "very_hard": VeryHardBot(),
    "expert":    ExpertBot(),
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


def decide_direction(game: "Game", bot_id: str) -> str | None:
    """
    Punto de entrada público para decisión de sentido.
    Retorna "cw", "ccw" o None (mantener).
    """
    player = game.players.get(bot_id)
    if not player or not player.is_bot:
        return None
    strategy = _REGISTRY.get(player.bot_difficulty, _REGISTRY["medium"])
    return strategy.decide_direction(game, bot_id)


def notify_reveal(game: "Game", result: dict):
    """
    Llamado por el manager tras resolver un dudo o calzo (o dudo de paso).
    Notifica a todos los ExpertBots y ExpertBots activos en la partida.
    """
    all_dice_raw: dict = result.get("all_dice") or {}
    all_dice: dict[str, list[int]] = {
        pid: list(dice) for pid, dice in all_dice_raw.items()
        if isinstance(dice, (list, tuple))
    }

    for difficulty in ("very_hard", "expert"):
        strategy = _REGISTRY.get(difficulty)
        if not isinstance(strategy, VeryHardBot):
            continue
        for pid, player in game.players.items():
            if player.is_bot and player.bot_difficulty == difficulty:
                strategy.on_reveal(pid, result, game)
                if all_dice:
                    strategy.on_round_reveal(pid, game, all_dice)


def notify_paso(game: "Game", passer_id: str):
    """
    Llamado por el manager cuando un jugador hace un paso.
    Notifica a ExpertBots y ExpertBots activos en la partida.
    """
    passer      = game.players.get(passer_id)
    passer_dice = passer.dice_count if passer else 5

    for difficulty in ("very_hard", "expert"):
        strategy = _REGISTRY.get(difficulty)
        if not isinstance(strategy, VeryHardBot):
            continue
        stable_passer = strategy._stable_id(game, passer_id)
        for pid, player in game.players.items():
            if player.is_bot and player.bot_difficulty == difficulty and pid != passer_id:
                strategy.on_paso_made(pid, passer_id, passer_dice, stable_passer)
