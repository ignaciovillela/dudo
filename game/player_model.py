"""
BluffModel — modelo de predicción de bluff por jugador.

Arquitectura
------------
Un único LogisticRegression entrenado con TODOS los datos históricos de la DB,
usando features por jugador + contexto de apuesta:

  Features (por muestra = una apuesta):
    f1  face_1 .. face_6          — one-hot de la cara apostada       (6)
    f2  qty_bucket_1/2/3          — one-hot del bucket de cantidad     (3)
    f3  player_global_bluff_rate  — tasa global de mentira del apostador
    f4  player_face_bluff_rate    — tasa de mentira en esa cara concreta
    f5  player_qty_bluff_rate     — tasa de mentira en ese bucket
    f6  player_copy_rate          — frecuencia de copiado
    f7  bids_total_log            — log(bids_total + 1) — experiencia del jugador

  Target:
    1 = la apuesta era mentira (bluff), 0 = verdad

El modelo se entrena al inicio con los datos globales de player_bid_stats.
Para jugadores con pocos datos (< MIN_SAMPLES) retorna None y el bot usa
las heurísticas clásicas.

Re-entrenamiento
----------------
Se llama a `bluff_model.retrain()` al inicio del servidor (una vez) y
opcionalmente puede llamarse periodicamente (no implementado aquí).
El entrenamiento dura < 100ms incluso con miles de filas.

Predicción en tiempo real
--------------------------
`bluff_model.predict_bluff(anon_id, face, bucket, stats)` retorna
P(bluff) ∈ [0,1] o None si no hay suficientes datos del jugador.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from game.bot import _PlayerStats

log = logging.getLogger(__name__)

MIN_SAMPLES_GLOBAL  = 50    # mínimo de filas globales para entrenar el modelo
MIN_SAMPLES_PLAYER  = 5     # mínimo de bids de un jugador para usar ML en sus predicciones


def _face_onehot(face: int) -> list[float]:
    v = [0.0] * 6
    if 1 <= face <= 6:
        v[face - 1] = 1.0
    return v


def _bucket_onehot(bucket: int) -> list[float]:
    v = [0.0] * 3
    if 1 <= bucket <= 3:
        v[bucket - 1] = 1.0
    return v


def _build_feature(
    face: int,
    bucket: int,
    global_bluff_rate: float,
    face_bluff_rate: float,
    qty_bluff_rate: float,
    copy_rate: float,
    bids_total: int,
    # tiempo de decisión — 0.0 cuando no hay dato
    elapsed: float = 0.0,
    avg_bluff_time: float = 0.0,
    avg_truth_time: float = 0.0,
    time_sample_count: int = 0,
) -> list[float]:
    """
    Vector de features (20 dimensiones):
      [0:6]   one-hot cara (6)
      [6:9]   one-hot bucket cantidad (3)
      [9]     bluff_rate global
      [10]    face_bluff_rate
      [11]    qty_bluff_rate
      [12]    copy_rate
      [13]    log(bids_total + 1)
      [14]    log(avg_bluff_time + 1)     — promedio de tiempo cuando miente
      [15]    log(avg_truth_time + 1)     — promedio de tiempo cuando dice verdad
      [16]    bluff_time / truth_time     — ratio (1.0 si iguales)
      [17]    log(elapsed + 1)            — tiempo de esta apuesta concreta
      [18]    elapsed / avg_total_time    — anomalía relativa al propio promedio
      [19]    has_time_data               — 1 si hay ≥5 muestras de tiempo
    """
    avg_total = (avg_bluff_time + avg_truth_time) / 2 if (avg_bluff_time + avg_truth_time) > 0 else 1.0
    time_ratio_bluff_truth = avg_bluff_time / max(avg_truth_time, 0.5)
    elapsed_ratio = elapsed / max(avg_total, 0.5) if elapsed > 0 and avg_total > 0 else 1.0
    has_time = 1.0 if time_sample_count >= 5 else 0.0

    return (
        _face_onehot(face)
        + _bucket_onehot(bucket)
        + [
            global_bluff_rate,
            face_bluff_rate,
            qty_bluff_rate,
            copy_rate,
            float(np.log1p(bids_total)),
            float(np.log1p(avg_bluff_time)),
            float(np.log1p(avg_truth_time)),
            float(np.clip(time_ratio_bluff_truth, 0.1, 10.0)),
            float(np.log1p(elapsed)),
            float(np.clip(elapsed_ratio, 0.0, 10.0)),
            has_time,
        ]
    )


class BluffModel:
    """
    Singleton que mantiene el modelo LogisticRegression entrenado
    y permite predicciones en tiempo real.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._clf     = None          # sklearn LogisticRegression
        self._trained = False

    # ------------------------------------------------------------------
    # Entrenamiento
    # ------------------------------------------------------------------

    def retrain(self, rows: list[dict]) -> None:
        """
        Entrena el modelo con filas de player_bid_stats.

        Cada fila debe tener:
            anon_id, face, qty_bucket, bids_total, bids_bluff
        y opcionalmente stats de paso (ignoradas aquí; las usa _dudo_paso_threshold).

        El entrenamiento expande cada fila en bids_total muestras individuales
        (bids_bluff de ellas con target=1, el resto target=0), usando las
        tasas acumuladas como features del jugador en ese momento.
        """
        if len(rows) < MIN_SAMPLES_GLOBAL:
            log.info("[bluff_model] not enough data to train (%d rows)", len(rows))
            return

        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.preprocessing import StandardScaler
            from sklearn.pipeline import Pipeline
        except ImportError:
            log.warning("[bluff_model] scikit-learn not available")
            return

        # Agregar por jugador para calcular rates globales por jugador
        player_totals: dict[str, dict] = {}
        for r in rows:
            aid = r["anon_id"]
            if aid not in player_totals:
                player_totals[aid] = {
                    "bids_total": 0, "bids_bluff": 0,
                    "face": {}, "bucket": {},
                    "bluff_time_sum": 0.0, "bluff_time_n": 0,
                    "truth_time_sum": 0.0, "truth_time_n": 0,
                }
            pt = player_totals[aid]
            pt["bids_total"] += r["bids_total"]
            pt["bids_bluff"] += r["bids_bluff"]
            pt["bluff_time_sum"] += r.get("bid_time_bluff_sum", 0.0)
            pt["bluff_time_n"]   += r.get("bid_time_bluff_n", 0)
            pt["truth_time_sum"] += r.get("bid_time_truth_sum", 0.0)
            pt["truth_time_n"]   += r.get("bid_time_truth_n", 0)
            face   = r["face"]
            bucket = r["qty_bucket"]
            pt["face"].setdefault(face,   {"t": 0, "b": 0})
            pt["face"][face]["t"]   += r["bids_total"]
            pt["face"][face]["b"]   += r["bids_bluff"]
            pt["bucket"].setdefault(bucket, {"t": 0, "b": 0})
            pt["bucket"][bucket]["t"] += r["bids_total"]
            pt["bucket"][bucket]["b"] += r["bids_bluff"]

        X: list[list[float]] = []
        y: list[int]         = []

        for r in rows:
            aid    = r["anon_id"]
            face   = r["face"]
            bucket = r["qty_bucket"]
            bt     = r["bids_total"]
            bb     = r["bids_bluff"]
            # tiempo acumulado de esta celda (face, bucket)
            t_bluff_s = r.get("bid_time_bluff_sum", 0.0)
            t_bluff_n = r.get("bid_time_bluff_n", 0)
            t_truth_s = r.get("bid_time_truth_sum", 0.0)
            t_truth_n = r.get("bid_time_truth_n", 0)

            pt  = player_totals[aid]
            gbr = pt["bids_bluff"] / max(pt["bids_total"], 1)

            fd  = pt["face"].get(face, {"t": 0, "b": 0})
            fbr = fd["b"] / max(fd["t"], 1)

            bd  = pt["bucket"].get(bucket, {"t": 0, "b": 0})
            qbr = bd["b"] / max(bd["t"], 1)

            # Tiempos por jugador (globales, no por celda)
            avg_bt = pt["bluff_time_sum"] / max(pt["bluff_time_n"], 1)
            avg_tt = pt["truth_time_sum"] / max(pt["truth_time_n"], 1)
            t_n    = pt["bluff_time_n"] + pt["truth_time_n"]
            # elapsed de entrenamiento: promedio de bluff o truth según target
            elapsed_bluff = t_bluff_s / max(t_bluff_n, 1)
            elapsed_truth = t_truth_s / max(t_truth_n, 1)

            if bt == 0:
                continue

            # Muestra positiva (bluff) — elapsed = avg bluff time de esta celda
            if bb > 0:
                feat = _build_feature(face, bucket, gbr, fbr, qbr, 0.0,
                                      pt["bids_total"], elapsed_bluff,
                                      avg_bt, avg_tt, t_n)
                X.append(feat)
                y.append(1)
            # Muestra negativa (verdad) — elapsed = avg truth time de esta celda
            if bt - bb > 0:
                feat = _build_feature(face, bucket, gbr, fbr, qbr, 0.0,
                                      pt["bids_total"], elapsed_truth,
                                      avg_bt, avg_tt, t_n)
                X.append(feat)
                y.append(0)

        if len(X) < MIN_SAMPLES_GLOBAL:
            log.info("[bluff_model] expanded dataset too small (%d)", len(X))
            return

        X_arr = np.array(X, dtype=float)
        y_arr = np.array(y, dtype=int)

        clf = Pipeline([
            ("scaler", StandardScaler()),
            ("gb", GradientBoostingClassifier(
                n_estimators=120,
                max_depth=4,
                learning_rate=0.08,
                subsample=0.8,
                random_state=42,
            )),
        ])
        clf.fit(X_arr, y_arr)

        with self._lock:
            self._clf     = clf
            self._trained = True

        log.info("[bluff_model] trained on %d samples from %d players",
                 len(X), len(player_totals))

    # ------------------------------------------------------------------
    # Predicción
    # ------------------------------------------------------------------

    def predict_bluff(
        self,
        anon_id: str,
        face: int,
        bucket: int,
        elapsed: float,
        stats: "_PlayerStats",
    ) -> float | None:
        """
        Retorna P(bluff) ∈ [0,1] o None si el modelo no está entrenado
        o el jugador tiene menos de MIN_SAMPLES_PLAYER bids.
        """
        if not self._trained or stats.bids_total < MIN_SAMPLES_PLAYER:
            return None

        with self._lock:
            clf = self._clf

        if clf is None:
            return None

        feat = _build_feature(
            face,
            bucket,
            stats.bluff_rate,
            stats.face_bluff_rate(face),
            stats.qty_bluff_rate(bucket),
            stats.copy_rate,
            stats.bids_total,
            elapsed,
            stats.avg_bluff_time,
            stats.avg_truth_time,
            stats.time_sample_count,
        )
        try:
            prob = clf.predict_proba(np.array([feat], dtype=float))[0][1]
            return float(prob)
        except Exception as exc:
            log.debug("[bluff_model] predict error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Carga de stats de DB → _PlayerStats en memoria del Expert
    # ------------------------------------------------------------------

    @staticmethod
    async def load_player_stats_into_bot(pool) -> None:
        """
        Carga player_bid_stats y player_paso_stats de la DB y las inyecta
        en la memoria del VeryHardBot singleton.

        Se llama una sola vez al inicio del servidor.
        """
        import game.bot as bot_module
        vh = bot_module._REGISTRY.get("very_hard")
        if not isinstance(vh, bot_module.VeryHardBot):
            return

        try:
            async with pool.acquire() as conn:
                bid_rows  = await conn.fetch(
                    "SELECT anon_id, face, qty_bucket, bids_total, bids_bluff "
                    "FROM player_bid_stats"
                )
                paso_rows = await conn.fetch(
                    "SELECT anon_id, pasos_total, pasos_bluff, paso_dice_sum "
                    "FROM player_paso_stats"
                )
        except Exception as exc:
            log.warning("[bluff_model] failed to load player stats: %s", exc)
            return

        # Hay un único _BotMemory "global" para el Expert singleton.
        # No está asociado a un bot_id concreto; usamos la clave especial "__global__"
        # para que los stats de jugadores humanos estén disponibles desde el primer turno.
        mem = vh._memory["__global__"]

        for r in bid_rows:
            stats = mem.player_stats[r["anon_id"]]
            stats.merge_from_db(dict(r))

        for r in paso_rows:
            stats = mem.player_stats[r["anon_id"]]
            stats.merge_paso_from_db(dict(r))

        log.info("[bluff_model] loaded stats for %d players from DB",
                 len(set(r["anon_id"] for r in bid_rows)))

    @staticmethod
    async def load_and_train(pool) -> None:
        """
        Carga las filas de player_bid_stats, inyecta en la memoria del bot
        y entrena el modelo ML. Llamado una sola vez en el startup.
        """
        await BluffModel.load_player_stats_into_bot(pool)

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT anon_id, face, qty_bucket, bids_total, bids_bluff "
                    "FROM player_bid_stats"
                )
        except Exception as exc:
            log.warning("[bluff_model] cannot load bid rows for training: %s", exc)
            return

        bluff_model.retrain([dict(r) for r in rows])


# Singleton global
bluff_model = BluffModel()
