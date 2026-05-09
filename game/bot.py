"""
Lógica de decisión para bots del juego Dudo.

Arquitectura: patrón plugin.
  - BotStrategy  — clase base abstracta con utilidades compartidas
  - EasyBot       — usa sus dados pero con umbrales relajados y algo de ruido
  - MediumBot     — bayesiano con umbrales razonables, sin Calzo
  - HardBot       — bayesiano completo: prioriza caras propias, Calzo selectivo, duda precisa
  - VeryHardBot   — memoria de rondas, modelado de rivales, bluff, Gavilán adaptativo

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
        low_third  = good[:max(1, n // 3)]
        high_third = good[max(0, n - n // 3):]

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

    def decide(self, game: "Game", bot_id: str) -> dict:
        own_dice = game.players[bot_id].dice

        if game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob < self.DUDO_THRESHOLD:
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
# VeryHardBot — memoria de rondas, modelado de rivales, bluff, Gavilán
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
    """Estado persistente entre rondas para un bot VeryHard concreto."""
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
    CALZO_PROB_MIN = 0.75
    CALZO_DIFF_MAX = 0.35

    # Gavilán
    GAVILAN_PROB_MIN          = 0.85
    GAVILAN_PROB_MIN_5DICE    = 0.98
    GAVILAN_RAND              = 0.55
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
                        dst.face_bid_counts   = dict(src.face_bid_counts)
                        dst.face_bluff_counts = dict(src.face_bluff_counts)
                        dst.qty_bucket_counts = dict(src.qty_bucket_counts)
                        dst.qty_bucket_bluff  = dict(src.qty_bucket_bluff)
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

            # Calzo
            if (prob >= self.CALZO_PROB_MIN
                    and bid.player_id != bot_id
                    and self._calzo_makes_sense(game, own_dice)):
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
        foreign_bids = sum(
            1 for b in game.bid_history
            if getattr(b, "player_id", None) != bot_id
        )
        return foreign_bids >= self.GAVILAN_MIN_BIDS_IN_ROUND

    def _try_gavilan(self, game: "Game", bot_id: str,
                     own_dice: list, dice_count: int, prob: float) -> bool:
        if dice_count >= 5:
            threshold = self.GAVILAN_PROB_MIN_5DICE
            gate      = self.GAVILAN_RAND_5DICE
        else:
            threshold = self.GAVILAN_PROB_MIN
            gate      = self.GAVILAN_RAND

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
# Registro de estrategias
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, BotStrategy] = {
    "easy":      EasyBot(),
    "medium":    MediumBot(),
    "hard":      HardBot(),
    "very_hard": VeryHardBot(),
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


def notify_reveal(game: "Game", result: dict):
    """
    Llamado por el manager tras resolver un dudo o calzo (o dudo de paso).
    Notifica a todos los VeryHardBots activos en la partida para que
    actualicen su memoria con el resultado real.

    Si el resultado incluye all_dice, se usa para aprendizaje retroactivo
    de TODAS las apuestas de la ronda (no solo la que fue dudada).
    """
    vh = _REGISTRY.get("very_hard")
    if not isinstance(vh, VeryHardBot):
        return

    all_dice_raw: dict = result.get("all_dice") or {}
    # all_dice_raw puede ser {player_id: [d1, d2, ...]} o vacío para paso sin reveal
    all_dice: dict[str, list[int]] = {
        pid: list(dice) for pid, dice in all_dice_raw.items()
        if isinstance(dice, (list, tuple))
    }

    for pid, player in game.players.items():
        if player.is_bot and player.bot_difficulty == "very_hard":
            vh.on_reveal(pid, result, game)
            if all_dice:
                vh.on_round_reveal(pid, game, all_dice)


def notify_paso(game: "Game", passer_id: str):
    """
    Llamado por el manager cuando un jugador hace un paso.
    Permite al VeryHard registrar el paso en su memoria estadística.
    """
    vh = _REGISTRY.get("very_hard")
    if not isinstance(vh, VeryHardBot):
        return
    passer = game.players.get(passer_id)
    passer_dice = passer.dice_count if passer else 5
    stable_passer = vh._stable_id(game, passer_id)
    for pid, player in game.players.items():
        if player.is_bot and player.bot_difficulty == "very_hard" and pid != passer_id:
            vh.on_paso_made(pid, passer_id, passer_dice, stable_passer)
