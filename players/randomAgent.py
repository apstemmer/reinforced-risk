from .player import Player
import random


class RandomAgent(Player):
    """
    A Random player, randomly selects moves
    """

    def __init__(self, name, troops, context):
        super().__init__(name, troops, context)

    def placement_control(self, placeable, units, state, querystyle="default"):
        ch = random.choice(list(placeable.keys())), random.randint(1, units)
        return ch

    def attack_control(self, att_lines, state):
        # 25% of the time dont attack
        if random.random() > 0.75 or att_lines == []:
            return None, None
        ch = random.choice(att_lines)
        return ch[0], ch[1]

    def fortify_control(self, fort_lines, state):
        # 10% of the time don't fortify
        # print(fort_lines)
        if random.random() > 0.9 or len(fort_lines) == 0:
            return None, None, 0
        fline = random.choice(fort_lines)
        return fline

    def overtaking_tile(self, num_units, state):
        return random.choice(num_units)
