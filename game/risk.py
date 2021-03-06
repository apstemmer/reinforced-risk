from typing import List, Dict, Tuple
from enum import Enum
from random import shuffle
from math import floor
import random
from players import Player, Human, Machine, RandomAgent
import torch


class Country:
    owner: Player = None
    continent = None
    units: int = 0

    def __init__(self, name: str, adj: List[str]):
        self.name = name
        self.adj = adj

    def conquer(self, conquerer: Player):
        self.owner = conquerer
        # Assume owner has been set in initialization
        # else crash (need to fix Game constructor)
        self.continent.update_owner()

    def __repr__(self):
        return f"Country({self.owner},{self.units},{self.continent})"


class Continent:
    owner = None

    def __init__(self, name: str, countries: List[Country], reward: int):
        # Name of continent and ownership reward
        self.name = name
        self.reward = reward
        self.countries = countries
        for country in self.countries:
            country.continent = self

    def update_owner(self):
        potential_owner = self.countries[0].owner
        if all(cntry.owner == potential_owner for cntry in self.countries):
            self.owner = potential_owner

    def __repr__(self):
        return "Continent({}, {}, {})".format(self.name, self.reward, self.owner)


class Step(Enum):
    Placement = 1
    Attack = 2
    Fortify = 3


class Turn:
    """
    This class holds all the state associated with
    whose turn and step of the turn we are currently in.
    """

    def __init__(self, players: List[Player]):
        self.curr = players[0]
        self.players: List[Player] = players
        self.step = Step.Placement

    def __repr__(self):
        if self.step == Step.Placement:
            return "{} may place {} units".format(self.curr.name, self.curr.free_units)
        elif self.step == Step.Attack:
            return "{} may attack".format(self.curr.name)
        elif self.step == Step.Fortify:
            return "{} may fortify once".format(self.curr.name)
        else:
            return "Invalid state..."

    def next_state(self, game):
        if self.step == Step.Placement:
            if self.curr.free_units == 0:
                self.step = Step.Attack
            elif game.free_tiles_left():
                # If there are still empty tiles, allow next player to place
                # This should only be true in initial placement phase
                self.curr = self.players[(self.players.index(
                    self.curr) + 1) % len(self.players)]
                self.step = Step.Placement
            else:
                raise ValueError(
                    f"Player still has {self.curr.free_units} units to place")
        elif self.step == Step.Attack:
            self.step = Step.Fortify
        elif self.step == Step.Fortify:
            # if the next player has been defeated, remove from list.
            self.curr = self.players[(self.players.index(
                self.curr) + 1) % len(self.players)]
            if [t for t in game.tiles.values() if t.owner == self.curr] == []:
                prev = self.curr
                self.curr = self.players[(self.players.index(
                    self.curr) + 1) % len(self.players)]
                self.players.remove(prev)
            self.step = Step.Placement
            self.curr.refill_troops(game.tiles, game.continents)


class Risk:

    turn: Turn = None
    tiles: Dict[str, Country] = {}
    continents = {}
    deck = None
    players = []

    def __init__(self, config):
        self.continents = {}
        for continent, countryDict in config['countries'].items():
            ContCountries = []
            for countryName, neighbours in countryDict.items():
                newCountry = Country(
                    name=countryName,
                    adj=neighbours)
                ContCountries.append(newCountry)
                self.tiles[newCountry.name] = newCountry

            self.continents[continent] = Continent(
                name=continent,
                countries=ContCountries,
                reward=config['contvals'][continent])
        cards = []
        for card in config['cards']:
            cards.append(Card(*card))
        self.deck = Deck(cards)

        for player in config['players']:
            if player['type'] == "Human":
                self.players.append(Human(player['name'], player['troops'], self))
            elif player['type'] == "Machine":
                self.players.append(Machine(player['name'], player['troops'], self, terr_num=len(self.tiles), play_num=len(config['players'])))
            elif player['type'] == "Random":
                self.players.append(RandomAgent(player['name'], player['troops'], self))

        # by default first player in array begins turn, can be changed in config
        self.turn = Turn(self.players)

        if config['playstyle']['init_allocation'] == "uniform_random":
            print("playstyle: uniform_random")
            idx = 0
            tiles_per_player = len(self.tiles)/len(self.players)
            # Find average amount of units to add to a tile on init
            units_per_tile = {player.name: {
                "min": floor(player.free_units/tiles_per_player),
                "remain": int(player.free_units - tiles_per_player*floor(player.free_units/tiles_per_player))
            }
                for player
                in self.players}
            for _, tile in self.tiles.items():
                tile.conquer(self.players[idx % len(self.players)])
                # randomly allocate either one more or one less to tile to
                units_to_tile = units_per_tile[tile.owner.name]['min']
                # Eat up remainder troops near beginning of loop
                if units_per_tile[tile.owner.name]['remain'] > 0:
                    units_to_tile += 1
                    units_per_tile[tile.owner.name]['remain'] -= 1
                # Add units to the tile. If no units left, use remainder
                if tile.owner.free_units >= units_to_tile:
                    tile.owner.free_units -= units_to_tile
                    tile.units += units_to_tile
                else:
                    tile.units += tile.owner.free_units
                    tile.owner.free_units = 0
                idx += 1

            # Only do initial refill if not in manual mode
            self.turn.curr.refill_troops(self.tiles, self.continents)
        elif config['playstyle']['init_allocation'] == "manual":
            # Players can pick where to place units on turn at beginning
            pass

    def __repr__(self):
        """
        Serialize game
        """
        state = {
            "num_players": len(self.turn.players),
            "curr_player": self.turn.players.index(self.turn.curr)+1,
            "tiles": list(self.tiles.values())
        }

        return str(state)

    def gen_state_vector(self):
        # State vector is of size
        state_vector = []
        countries = [ tile[1] for tile in sorted(self.tiles.items())]
        for country in countries:
            idx = self.players.index(country.owner)
            p = [0 for _ in range(len(self.players))]
            p[idx] = country.units
            state_vector += p
        
        if self.turn.step == Step.Placement:
            state_vector += [1,0,0]
        elif self.turn.step == Step.Attack:
            state_vector += [0,1,0]
        elif self.turn.step == Step.Fortify:
            state_vector += [0,0,1]

        # state has unsinged 16 bit values, cannot have negative number of units on tile
        return torch.tensor(state_vector, dtype=torch.float) 

    def state_idx(self, country, player):
        countries = [ tile[1] for tile in sorted(self.tiles.items())]
        return len(self.players)*countries.index(country) + self.players.index(player)


    def attack(self, attacker: Country, defender: Country):
        # Might need to refactor to allow machine to find probabilities
        if attacker == None or defender == None:
            return
        if attacker.units >= 4:
            attdie = 3
        elif attacker.units == 3:
            attdie = 2
        elif attacker.units == 2:
            attdie = 1
        if defender.units >= 2:
            defdie = 2
        elif defender.units == 1:
            defdie = 1
        attrolls = sorted([random.randint(1, 6)
                           for _ in range(attdie)], reverse=True)
        defrolls = sorted([random.randint(1, 6)
                           for _ in range(defdie)], reverse=True)
        pairs = zip(attrolls, defrolls)
        for att, defn in pairs:
            if att > defn:
                #print(f"{defender.name} lost a unit")
                defender.units -= 1
            else:
                #print(f"{attacker.name} lost a unit")
                attacker.units -= 1
        # Did the attack destroy all units on tile?
        if defender.units <= 0:
            # make attacker owner of defender
            defender.conquer(attacker.owner)
            return True
        else:
            False

    def fortify(self, fro: Country, to: Country, num: int):
        if fro.units > num and num > 0:
            fro.units -= num
            to.units += num
        elif num <= 0:
            raise ValueError("Must fortify with at least one unit")
        else:
            raise ValueError("Cannot fortify with that many units")

    def place(self, player: Player, num: int, tile: str):
        if tile not in self.tiles.keys():
            raise KeyError("Invalid tile given as input.")
        elif self.turn.curr.free_units < num:
            raise ValueError("Trying to place too many units.")
        elif self.tiles[tile].owner != player and self.tiles[tile].owner != None:
            raise ValueError("You do not own this tile.")
        elif num <= 0:
            raise ValueError("Number of units to place must be greater than 0")
        elif self.turn.curr == player and \
                self.turn.step == Step.Placement and \
                self.turn.curr.free_units >= num:
            if self.tiles[tile].owner == None:
                self.tiles[tile].owner = player
            player.free_units -= num
            self.tiles[tile].units += num
            # if self.turn.curr.free_units == 0:
            #     self.turn.next_state(self)
            return

    def get_players(self):
        return self.players

    def query_action(self):
        return str(self.turn)

    def validate_input(self):
        raise NotImplementedError

    def game_over(self):
        owners = []
        for continent in self.continents.values():
            owners.append(continent.owner)
        if all(owner == owners[0] and owner != None for owner in owners):
            return owners[0]
        else:
            None

    def free_tiles_left(self):
        free_land = {k: v for k, v in self.tiles.items() if v.owner == None}
        return len(free_land) > 0

    def find_attack_lines(self, player: Player):
        # given a player, find all tiles it can currently attack
        player_countries = {tile: tile.adj for _,
                            tile in self.tiles.items() if tile.owner == player}
        line_list = []
        for country, reach in player_countries.items():
            for nbor in reach:
                if self.tiles[nbor].owner != player and country.units > 1:
                    line_list.append((country, self.tiles[nbor]))
        return line_list

    def find_fortify_lines(self, player: Player):
        # Could use a refactor
        # fortification can only happen once per turn and can only happen
        # between connected tiles of the same owner
        player_countries = [(tile.name,  t) for _, tile in self.tiles.items(
        ) for t in tile.adj if tile.owner == player and self.tiles[t].owner == player]

        tile_groups = []
        for country, adj in player_countries:
            added = False
            for group in tile_groups:
                if country in group or adj in group:
                    # if one in group add both
                    group |= set([country, adj])
                    added = True
            if added == False:
                tile_groups.append(set([country, adj]))

        fortify_paths = []
        for group in tile_groups:
            fortify_paths += [(self.tiles[from_name], self.tiles[to_name], num_units) 
                                for from_name in list(group) 
                                for to_name in list(group) if from_name != to_name and self.tiles[from_name].units > 1
                                for num_units in range(1, self.tiles[from_name].units)]
        return fortify_paths

    def play(self):
        steps = 0
        while not self.game_over():
            # Add optional loop for manually placing troops at beginning
            if self.turn.step == Step.Placement:
                # What if all countries are owned, stop while
                if self.free_tiles_left():
                    # if there are still unowned tiles, next player must place there
                    try:
                        terr, num = self.turn.curr.placement_control(
                            {k: v for k, v in self.tiles.items() if v.owner == None}, 
                            units=self.turn.curr.free_units, 
                            state= self.gen_state_vector(), 
                            querystyle="initial")
                        self.place(self.turn.curr, num, terr)
                        #print(f"{self.turn.curr.name} placed {num} troops on {terr}\n")
                        self.turn.next_state(self)
                    except (KeyError, ValueError) as e:
                        print(e)
                        continue
                else:
                    # if all tiles are owned by a player, you must place on your own tiles
                    owned_land = {k: v for k, v in self.tiles.items()
                                  if v.owner == self.turn.curr}
                    try:
                        terr, num = self.turn.curr.placement_control(
                            owned_land, self.turn.curr.free_units, self.gen_state_vector(), querystyle="default")
                        self.place(self.turn.curr, num, terr)

                        if self.turn.curr.free_units == 0:
                            self.turn.next_state(self)
                    except (KeyError, ValueError) as e:
                        print(f"Placement error: {e}")
                        continue

            elif self.turn.step == Step.Attack:
                att_lines = self.find_attack_lines(self.turn.curr)
                if len(att_lines) == 0:
                    self.turn.next_state(self)
                    continue
                try:
                    fro, to = self.turn.curr.attack_control(att_lines, state=self.gen_state_vector())
                    if fro == None or to == None:
                        # Only go to next state if player has stopped attacking
                        self.turn.next_state(self)
                        self.turn.curr.feedback("attack", False, state=self.gen_state_vector(), next_state=self.gen_state_vector()) 
                    else:
                        pre_attack_state = self.gen_state_vector()

                        if self.attack(fro, to):
                            uns = self.turn.curr.overtaking_tile(
                                list(range(1, fro.units)),
                                state = self.gen_state_vector()
                                )
                            fro.units -= uns
                            to.units += uns

                        self.turn.curr.feedback("attack", True, pre_attack_state, next_state=self.gen_state_vector()) 

                except (KeyError, ValueError) as e:
                    print(f"Attacking error{e}")
                    continue

            elif self.turn.step == Step.Fortify:
                fort_lines = self.find_fortify_lines(self.turn.curr)
                if len(fort_lines) == 0:
                    self.turn.next_state(self)
                    continue
                try:
                    ffro, fto, num = self.turn.curr.fortify_control(fort_lines, state=self.gen_state_vector())
                    if ffro != None and fto != None and num > 0:
                        self.fortify(ffro, fto, num)
                    self.turn.next_state(self)
                    steps += 1
                    if steps % 1000 == 0:
                        print(steps)
                    if steps % 10000 == 0:
                        print(self)
                except (KeyError, ValueError) as e:
                    print(f"Fortification Error:{e}")
                    continue
            
            

        print(f"{self.game_over().name} wins the match in {steps} turns")
        return self.game_over()

    def reset(self):
        # Resets the game, allowing for further training
        raise NotImplementedError

class CardUnit(Enum):
    Soldier = 1
    Horse = 2
    Cannon = 3
    WildCard = 4


class Card:
    location = None
    unit = None

    def __init__(self, location, unit):

        self.location = Risk.tiles[location] if location else None
        self.unit = {
            "Horse": CardUnit.Horse,
            "Soldier": CardUnit.Soldier,
            "Cannon": CardUnit.Cannon,
            "WildCard": CardUnit.WildCard
        }[unit]


class Deck:
    cards = []

    def __init__(self, cards: List[Card]):
        self.cards = cards

    def pop(self):
        return self.cards.pop()

    def shuffle(self):
        shuffle(self.cards)
