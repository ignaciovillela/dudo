from game.models import Bid, Game, Player


def make_game(hands: dict[str, list[int]], phase: str = "playing") -> Game:
    """Game with one player per hand, in insertion order, with fixed dice."""
    game = Game(room_id="test", phase=phase)
    for pid, dice in hands.items():
        game.players[pid] = Player(id=pid, name=pid.upper(), dice=list(dice), dice_count=len(dice))
        game.player_order.append(pid)
    return game


def bid(quantity: int, face: int, player_id: str = "a") -> Bid:
    return Bid(quantity=quantity, face=face, player_id=player_id, player_name=player_id.upper())
