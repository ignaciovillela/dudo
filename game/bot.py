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

        if game.last_paso is not None and game.current_bid is None:
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

        good = [(b, p) for b, p in scored if p >= self.BID_MIN_PROB]
        if good:
            good.sort(key=lambda x: (x[0].quantity, x[1]), reverse=True)
            chosen = good[0][0]
        else:
            scored.sort(key=lambda x: -x[1])
            chosen = scored[0][0]

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

        if game.last_paso is not None and game.current_bid is None:
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

        good = [(b, p) for b, p in scored if p >= self.BID_MIN_PROB]
        if good:
            good.sort(key=lambda x: (x[0].quantity, x[1]), reverse=True)
            chosen = good[0][0]
        else:
            scored.sort(key=lambda x: -x[1])
            chosen = scored[0][0]

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
    Historial de un rival para modelado de comportamiento.

    Patrones rastreados:
    - bluff_rate: % de veces que mintió cuando fue dudado con éxito
    - face_bluff_counts: cuántas veces mintió apostando cada cara concreta
    - face_bid_counts: cuántas veces apostó cada cara (verdad o mentira)
    - copy_count: cuántas veces copió la cantidad del bid anterior (+0 o +1 en misma cara)
    - total_rounds_observed: rondas en las que el bot lo ha observado
    """
    bids_made:             int = 0
    times_caught_bluffing: int = 0
    # Por cara (1-6): veces que apostó esa cara siendo mentira
    face_bluff_counts:  dict = field(default_factory=lambda: defaultdict(int))
    # Por cara (1-6): veces que apostó esa cara (verdad o mentira)
    face_bid_counts:    dict = field(default_factory=lambda: defaultdict(int))
    # Cuántas veces "copió" al anterior (incrementó qty en 1 o 0 en la misma cara)
    copy_count:         int = 0
    total_rounds:       int = 0

    @property
    def bluff_rate(self) -> float:
        return self.times_caught_bluffing / max(self.bids_made, 1)

    def face_bluff_rate(self, face: int) -> float:
        """Tasa de mentira específica para una cara."""
        total = self.face_bid_counts.get(face, 0)
        if total < 3:          # sin suficientes muestras, usar tasa global
            return self.bluff_rate
        return self.face_bluff_counts.get(face, 0) / total

    @property
    def copy_rate(self) -> float:
        """Frecuencia con la que copia la apuesta anterior en lugar de subir de verdad."""
        return self.copy_count / max(self.bids_made, 1)


@dataclass
class _BotMemory:
    """Estado persistente entre rondas para un bot VeryHard concreto."""
    last_round:   int  = -1
    player_stats: dict = field(default_factory=lambda: defaultdict(_PlayerStats))
    # Historial de bids de la ronda en curso: list[Bid] (caché local para detectar copiado)
    round_bids:   list = field(default_factory=list)


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

    # Dudo de paso activo
    DUDO_PASO_PROB = 0.40

    def __init__(self):
        self._memory: dict[str, _BotMemory] = defaultdict(_BotMemory)

    # ------------------------------------------------------------------ decide

    def decide(self, game: "Game", bot_id: str) -> dict:
        mem = self._memory[bot_id]
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

        if game.last_paso is not None and game.current_bid is None:
            if random.random() < self.DUDO_PASO_PROB:
                return {"action": "dudo"}

        paso_threshold = self.PASO_PROB_THRESHOLD_LOW_DICE if low_dice else self.PASO_PROB_THRESHOLD
        if self.can_paso(game, bot_id) and game.current_bid is not None:
            prob = self.prob_bid_holds_bayesian(game, game.current_bid, bot_id)
            if prob > paso_threshold and random.random() < self.PASO_RAND:
                return {"action": "paso"}

        return self._choose_bid(game, bot_id, own_dice, low_dice)

    # ------------------------------------------------------------------ feedback del servidor

    def on_reveal(self, bot_id: str, result: dict):
        """
        Llamado por el manager tras cada dudo resuelto.
        result es el dict que ya se broadcast a los clientes:
          action, bid (dict), bid_holds, challenger_id, loser_id, all_dice, ...

        Actualiza:
        - times_caught_bluffing si el apostador perdió el dudo
        - face_bluff_counts / face_bid_counts con la cara apostada
        - copy_count según patrones de bid de la ronda (via round_bids de la memoria)
        """
        action = result.get("action")
        if action not in ("dudo", "calzo"):
            return

        mem = self._memory[bot_id]

        if action == "dudo":
            bid_dict  = result.get("bid") or {}
            bidder_id = bid_dict.get("player_id")
            face      = bid_dict.get("face")
            bid_holds = result.get("bid_holds", True)
            loser_id  = result.get("loser_id")

            if bidder_id and bidder_id != bot_id and face:
                stats = mem.player_stats[bidder_id]
                stats.face_bid_counts[face] = stats.face_bid_counts.get(face, 0) + 1
                # Si el apostador perdió el dudo → estaba mintiendo
                if loser_id == bidder_id:
                    stats.times_caught_bluffing += 1
                    stats.face_bluff_counts[face] = stats.face_bluff_counts.get(face, 0) + 1

        elif action == "calzo":
            # Calzo exacto: el apostador decía la verdad — registrar cara como honesta
            bid_dict  = result.get("bid") or {}
            bidder_id = bid_dict.get("player_id")
            face      = bid_dict.get("face")
            if bidder_id and bidder_id != bot_id and face:
                stats = mem.player_stats[bidder_id]
                stats.face_bid_counts[face] = stats.face_bid_counts.get(face, 0) + 1
                # No incrementamos bluff_count — fue verdad

        # Detectar copiado en la ronda usando round_bids acumulados
        self._detect_copy_patterns(mem)

    # ------------------------------------------------------------------ helpers internos

    def _sync_round_bids(self, game: "Game", bot_id: str, mem: _BotMemory):
        """
        Mantiene mem.round_bids sincronizado con game.bid_history.
        No registra bids propios. Detecta inicio de ronda nueva para limpiar.
        """
        current_round = game.round_number
        if current_round != mem.last_round:
            # Nueva ronda: actualizar bids_made con los bids del historial previo
            # que aún no hayamos contado (on_reveal los procesa uno a uno, pero
            # bids_made necesita el total).
            for bid in mem.round_bids:
                pid = getattr(bid, "player_id", None)
                if pid and pid != bot_id:
                    mem.player_stats[pid].bids_made += 1
            mem.round_bids = []
            mem.last_round = current_round

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

    def _dudo_threshold(self, mem: _BotMemory, bid: "Bid", game: "Game") -> float:
        """
        Umbral de dudo enriquecido:
        1. Base según bluff_rate global del apostador.
        2. Bonus si la cara que apostó tiene una tasa de mentira alta (≥ 2 muestras).
        3. Bonus si en esta ronda el jugador ha copiado la apuesta anterior.
        """
        bidder_id = bid.player_id
        stats     = mem.player_stats.get(bidder_id)

        if stats is None:
            return self.DUDO_THRESHOLD_BASE

        # 1. Base global
        br = stats.bluff_rate
        if br > 0.40:
            threshold = self.DUDO_THRESHOLD_HIGH
        elif br < 0.10 and stats.bids_made >= 5:
            threshold = self.DUDO_THRESHOLD_LOW
        else:
            threshold = self.DUDO_THRESHOLD_BASE

        # 2. Cara específica: si suele mentir con esta cara, dudar más fácil
        face_br = stats.face_bluff_rate(bid.face)
        if face_br > 0.50 and stats.face_bid_counts.get(bid.face, 0) >= 2:
            threshold += self.DUDO_FACE_BONUS

        # 3. Copiado en esta ronda: indicio de juego débil/bluff
        #    Detectar si el bid actual es copia del anterior en bid_history
        bids = mem.round_bids
        if len(bids) >= 2:
            prev = bids[-2]
            curr = bids[-1]
            if (getattr(curr, "player_id", None) == bidder_id
                    and getattr(curr, "face", None) == getattr(prev, "face", None)
                    and 0 <= getattr(curr, "quantity", 0) - getattr(prev, "quantity", 0) <= 1):
                threshold += self.DUDO_COPY_BONUS

        return min(threshold, 0.45)   # techo para no dudar ciegamente siempre

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

        good = [(b, p) for b, p in scored if p >= min_prob]
        if good:
            good.sort(key=lambda x: (x[0].quantity, x[1]), reverse=True)
            chosen = good[0][0]
        else:
            scored.sort(key=lambda x: -x[1])
            chosen = scored[0][0]

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
    Llamado por el manager tras resolver un dudo o calzo.
    Notifica a todos los VeryHardBots activos en la partida para que
    actualicen su memoria con el resultado real.

    result: el mismo dict que se broadcast como tipo "reveal".
    """
    vh = _REGISTRY.get("very_hard")
    if not isinstance(vh, VeryHardBot):
        return
    for pid, player in game.players.items():
        if player.is_bot and player.bot_difficulty == "very_hard":
            vh.on_reveal(pid, result)
