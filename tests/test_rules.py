"""Tests de las reglas puras del juego (sin red ni base de datos)."""
import pytest

from game.models import Bid, Game, Player, RuleConfig


def make_game(*dice_per_player):
    game = Game(room_id="test")
    for i, dice in enumerate(dice_per_player):
        pid = f"p{i}"
        game.players[pid] = Player(id=pid, name=f"J{i}", dice=list(dice), dice_count=len(dice))
        game.player_order.append(pid)
    return game


def bid(quantity, face):
    return Bid(quantity=quantity, face=face, player_id="p0", player_name="J0")


class TestIsValidBid:
    def test_primera_apuesta_cualquiera_valida(self):
        game = make_game([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert game.is_valid_bid(bid(1, 2))

    @pytest.mark.parametrize("quantity,face", [(0, 3), (-1, 3), (1, 0), (1, 7)])
    def test_apuesta_fuera_de_rango_invalida(self, quantity, face):
        game = make_game([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert not game.is_valid_bid(bid(quantity, face))

    def test_misma_cara_mayor_cantidad(self):
        game = make_game([1] * 5, [1] * 5)
        game.current_bid = bid(3, 4)
        assert game.is_valid_bid(bid(4, 4))
        assert not game.is_valid_bid(bid(3, 4))
        assert not game.is_valid_bid(bid(2, 4))

    def test_misma_cantidad_cara_mayor(self):
        game = make_game([1] * 5, [1] * 5)
        game.current_bid = bid(3, 4)
        assert game.is_valid_bid(bid(3, 5))
        assert not game.is_valid_bid(bid(3, 3))

    def test_normal_a_ases_pide_la_mitad_hacia_arriba(self):
        game = make_game([1] * 5, [1] * 5)
        game.current_bid = bid(5, 4)  # ceil(5/2) = 3
        assert game.is_valid_bid(bid(3, 1))
        assert not game.is_valid_bid(bid(2, 1))

    def test_ases_a_normal_pide_el_doble_mas_uno(self):
        game = make_game([1] * 5, [1] * 5)
        game.current_bid = bid(3, 1)  # 3*2+1 = 7
        assert game.is_valid_bid(bid(7, 2))
        assert not game.is_valid_bid(bid(6, 6))


class TestCountDice:
    def test_los_ases_son_comodin_para_otras_caras(self):
        game = make_game([1, 1, 3, 4, 5], [3, 3, 6, 6, 1])
        # 3 treses (1 de J0 y 2 de J1) + 3 ases comodín (2 de J0 y 1 de J1)
        assert game.count_dice(3) == 6

    def test_en_apuesta_de_ases_solo_cuentan_los_unos(self):
        game = make_game([1, 1, 3, 4, 5], [3, 3, 6, 6, 1])
        assert game.count_dice(1) == 3

    def test_jugador_desconectado_no_cuenta(self):
        game = make_game([2, 2, 2, 2, 2], [2, 2, 2, 2, 2])
        game.players["p1"].connected = False
        assert game.count_dice(2) == 5


class TestPaso:
    @pytest.mark.parametrize(
        "dice,expected",
        [
            ([1, 2, 3, 4, 5], True),   # todos distintos
            ([6, 6, 6, 6, 6], True),   # todos iguales
            ([2, 2, 2, 5, 5], True),   # full
            ([2, 2, 3, 4, 5], False),  # un par
            ([2, 2, 2, 4, 5], False),  # trío sin par
            ([2, 2, 4, 4, 5], False),  # dos pares
        ],
    )
    def test_validacion_del_paso(self, dice, expected):
        game = make_game(dice, [1, 2, 3, 4, 5])
        assert game.is_valid_paso("p0") is expected

    def test_paso_con_menos_de_cinco_dados_es_invalido(self):
        game = make_game([1, 2, 3, 4], [1, 2, 3, 4, 5])
        assert not game.is_valid_paso("p0")


class TestTurnos:
    def test_avanza_en_sentido_horario_y_antihorario(self):
        game = make_game(*[[1, 2, 3, 4, 5]] * 3)
        game.current_player_idx = 0
        game.direction = 1
        game.advance_turn()
        assert game.current_player_id() == "p1"
        game.direction = -1
        game.advance_turn()
        game.advance_turn()
        assert game.current_player_id() == "p2"


class TestRuleConfig:
    def test_payload_invalido_conserva_los_valores_actuales(self):
        base = RuleConfig(elimination_mode="loser", turn_timeout_seconds=30)
        cfg = RuleConfig.from_payload(
            {"elimination_mode": "otro", "turn_timeout_seconds": 45}, current=base
        )
        assert cfg.elimination_mode == "loser"
        assert cfg.turn_timeout_seconds == 30

    def test_payload_valido_se_aplica(self):
        cfg = RuleConfig.from_payload(
            {"elimination_mode": "loser", "turn_timeout_seconds": 60, "allow_gavilan": False}
        )
        assert cfg.elimination_mode == "loser"
        assert cfg.turn_timeout_seconds == 60
        assert cfg.allow_gavilan is False
