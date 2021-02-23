import json
import math
import os
import tempfile

from discord.ext import commands
import discord
from string import ascii_lowercase

from kyogre import utils
from kyogre.exts.db.kyogredb import PokemonTable
from kyogre.exts.bosscp import cp_multipliers

from discord.ext.commands import CommandError

class PokemonNotFound(CommandError):
    """Exception raised when Pokemon given does not exist."""
    def __init__(self, pokemon, retry=True):
        self.pokemon = pokemon
        self.retry = retry

class Pokedex(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

"""
Calculating PoGO base stats from MSG base stats
ATK = round(round(2*(0.875*max(atk,spa)+0.125*min(atk,spa))) * (1+(spe-75)/500))
DEF = round(round(2*(0.875*max(def,spd)+0.125*min(def,spd))) * (1+(spe-75)/500))
STA = floor(1.75*HP+50)
"""

class Pokemon():
    """Represents a Pokemon.

    This class contains the attributes of a specific pokemon, and
    provides methods of which to get specific info and results on it.

    Parameters
    -----------
    bot: :class:`eevee.core.bot.Eevee`
        Current instance of Eevee
    pkmn: str or int
        The name or id of a Pokemon
    guild: :class:`discord.Guild`, optional
        The guild that is requesting the Pokemon
    moveset: :class:`list` or :class:`tuple` of :class:`str`, optional
        `kwarg-only:` The two moves of this Pokemon
    weather: :class:`str`, optional
        `kwarg-only:` Weather during the encounter

    Raises
    -------
    :exc:`.errors.PokemonNotFound`
        The pkmn argument was not a valid index and was not found in the
        list of Pokemon names.

    Attributes
    -----------
    species: :class:`str`
        Lowercase string representing the species of the Pokemon (formless)
    id: :class:`int`
        Pokemon ID number
    types: :class:`list` of :class:`str`
        A :class:`list` of the Pokemon's types
    moveset: :class:`list` or :class:`tuple` of :class:`str`
        The two moves of this Pokemon
    weather: :class:`str`
        Weather during the encounter
    guild: :class:`discord.Guild`
        Guild that created the Pokemon
    bot: :class:`eevee.core.bot.Eevee`
        Current instance of Eevee
    """

    # https://p337.info/pokemongo/pages/shiny-release-dates/api/?utm_source=share&utm_medium=ios_app
    __slots__ = ('species', 'id', 'types', 'bot', 'guild', 'pkmn_list',
                 'pb_raid', 'weather', 'moveset', 'form', 'shiny', 'alolan', 'galarian', 'mega',
                 'legendary', 'mythical', 'base_attack', 'base_defense', 'base_stamina')

    _alolans_list = ['rattata', 'raticate', 'vulpix', 'ninetails', 'sandshrew', 'sandslash', 'grimer', 'muk',
                     'meowth', 'persian', 'diglett', 'dugtrio', 'geodude', 'graveler', 'golem', 'exeggutor',
                     'marowak', 'raichu']

    _galarians_list = ['zigzagoon', 'linoone', 'meowth', "farfetch'd", 'stunfisk', 'corsola', 'weezing',
                       'yamask', 'ponyta', 'rapidash', 'mr. mime', 'darumaka', 'darmanitan']

    _megas_list = ['charizard', 'venasaur', 'blastoise', 'beedrill']
    
    _form_list = [
        'normal', 'sunny', 'rainy', 'snowy', 'sunglasses',
        'ash', 'party', 'witch', 'santa', 'summer', 'detective', 'flower', 'fragment',
        'defense', 'attack', 'speed', 
        'plant', 'sandy', 'trash',
        'overcast', 'sunshine',
        'east', 'west',
        'spring', 'summer', 'autumn', 'winter',
        'standard', 'zen',
        'red', 'blue',
        'heat', 'wash', 'frost', 'fan', 'mow',
        'altered', 'origin',
        'incarnate', 'therian'

    ]
    _stat_forms = [
        'sunny', 'rainy', 'snowy', 'defense', 'attack', 'speed', 'normal',
        'plant', 'sandy', 'trash', 'overcast', 'sunshine'
    ]
    _prefix_forms = _form_list
    _form_dict = {
        'squirtle': ['sunglasses', 'normal'],
        'wartortle': ['sunglasses', 'normal'],
        'blastoise': ['sunglasses', 'normal'],
        'eevee': ['normal', 'flower'],
        'pikachu':  ['ash', 'party', 'witch', 'santa', 'summer', 'normal', 'detective', 'flower', 'fragment'],
        'raichu':  ['ash', 'party', 'witch', 'santa', 'summer', 'normal', 'detective', 'flower', 'fragment'],
        'pichu':  ['ash', 'party', 'witch', 'santa', 'summer', 'normal', 'detective', 'flower', 'fragment'],
        'unown': list(ascii_lowercase + '!?'),
        'spinda': [str(n) for n in range(1, 9)],
        'castform': ['normal', 'rainy', 'snowy', 'sunny'],
        'deoxys': ['defense', 'normal', 'attack', 'speed'],
        'burmy': ['plant', 'sandy', 'trash'],
        'wormadon': ['plant', 'sandy', 'trash'],
        'cherrim': ['overcast', 'sunshine'],
        'shellos': ['east', 'west'],
        'gastrodon': ['east', 'west'],
        'rotom': ['normal', 'heat', 'wash', 'frost', 'fan', 'mow'],
        'basculin': ['red', 'blue'],
        'darmanitan': ['standard', 'zen'],
        'deerling': ['spring', 'summer', 'autumn', 'winter'],
        'sawsbuck': ['spring', 'summer', 'autumn', 'winter'],
        'giratina': ['altered', 'origin'],
        'tornadus': ['incarnate', 'therian'],
        'mewtwo': ['armored']
    }

    _raid_stamina = {1: 600, 2: 1800, 3: 3600, 4: 9000, 5: 15000, 6: 22500}

    def __init__(self, bot, pkmn, guild=None, **attribs):
        self.bot = bot
        self.guild = guild
        p_obj = Pokemon.find_obj(pkmn)
        if not p_obj:
            raise PokemonNotFound(pkmn)
        self.id = p_obj['id']
        self.species = p_obj['name']
        self.pb_raid = None
        self.weather = attribs.get('weather', None)
        self.moveset = attribs.get('moveset', [])
        self.form = attribs.get('form', '')
        if self.form not in Pokemon._form_dict.get(self.species, []):
            self.form = None
        self.shiny = attribs.get('shiny', False) and p_obj['shiny']
        self.alolan = attribs.get('alolan', False) and p_obj['alolan']
        self.galarian = attribs.get('galarian', False) and p_obj['galarian']
        self.legendary = p_obj['legendary']
        self.mythical = p_obj['mythical']
        if self.alolan:
            self.types = p_obj['types']['alolan']
        elif self.galarian:
            self.types = p_obj['types']['galarian']
        else:
            self.types = p_obj['types']['default']
        self.base_attack = p_obj.get('attack', None)
        self.base_defense = p_obj.get('defense', None)
        self.base_stamina = p_obj.get('stamina', None)

    def __str__(self):
        return self.name

    @staticmethod
    def get_pkmn_dict():
        return {r['name'].lower(): r for r in PokemonTable.select().where(PokemonTable.released).dicts()}

    @staticmethod
    def get_pkmn_dict_all_by_name():
        return {r['name'].lower(): r for r in PokemonTable.select().dicts()}

    @staticmethod
    def get_pkmn_dict_all_by_id():
        return {r['id']: r for r in PokemonTable.select().dicts()}


    @property
    def name(self):
        # name without cosmetic modifiers (for identifying substantive differences)
        name = self.species.title()
        if self.form and self.form in Pokemon._stat_forms:
            if self.form in Pokemon._prefix_forms:
                name = f'{self.form.title()} {name}'
            else:
                name = f'{name} {self.form.title()}'
        if self.alolan:
            name = f'Alolan {name}'
        if self.galarian:
            name = f'Galarian {name}'
        return name
    
    @property
    def full_name(self):
        # name with all modifiers
        name = self.species.title()
        if self.form:
            if self.form in Pokemon._prefix_forms:
                name = f'{self.form.title()} {name}'
            else:
                name = f'{name} {self.form.title()}'
        if self.alolan:
            name = f'Alolan {name}'
        if self.galarian:
            name = f'Galarian {name}'
        if self.shiny:
            name = f'Shiny {name}'
        return name

    @property
    def emoji_name(self):
        name = self.species.title()
        if self.form:
            name = f'{name}{self.form.title()}'
        if self.alolan:
            name = f'{name}alola'
        if self.galarian:
            name = f'{name}galar'
        return name.lower()

    async def get_pb_raid(self, weather=None, userid=None, moveset=None):
        """Get a PokeBattler Raid for this Pokemon

        This can quickly produce a PokeBattler Raid for the current
        Pokemon, with the option of providing a PokeBattler User ID to
        get customised results.

        The resulting PokeBattler Raid object will be saved under the
        `pb_raid` attribute of the Pokemon instance for later retrieval,
        unless it's customised with an ID.

        Parameters
        -----------
        weather: :class:`str`, optional
            The weather during the raid
        userid: :class:`int`, optional
            The Pokebattler User ID to generate the PB Raid with
        moveset: list or tuple, optional
            A :class:`list` or :class:`tuple` with a :class:`str` representing
            ``move1`` and ``move2`` of the Pokemon.

        Returns
        --------
        :class:`eevee.cogs.pokebattler.objects.PBRaid` or :obj:`None`
            PokeBattler Raid instance or None if not a Raid Pokemon.

        Example
        --------

        .. code-block:: python3

            pokemon = Pokemon(ctx.bot, 'Groudon')
            moveset = ('Dragon Tail', 'Solar Beam')
            pb_raid = pokemon.get_pb_raid('windy', 12345, moveset)
        """

        # if a Pokebattler Raid exists with the same settings, return it
        if self.pb_raid:
            if not (weather or userid) and not moveset:
                return self.pb_raid
            if weather:
                self.pb_raid.change_weather(weather)

        # if it doesn't exist or settings changed, generate it
        else:
            pb_cog = self.bot.cogs.get('PokeBattler', None)
            if not pb_cog:
                return None
            if not weather:
                weather = self.weather or 'DEFAULT'
            weather = pb_cog.PBRaid.get_weather(weather)
            pb_raid = await pb_cog.PBRaid.get(
                self.bot, self, weather=self.weather, userid=userid)

        # set the moveset for the Pokebattler Raid
        if not moveset:
            moveset = self.moveset
        try:
            pb_raid.set_moveset(moveset)
        except RuntimeError:
            pass

        # don't save it if it's a user-specific Pokebattler Raid
        if not userid:
            self.pb_raid = pb_raid

        return pb_raid

    @property
    def img_url(self):
        """:class:`str` : Pokemon sprite image URL"""
        pkmn_no = str(self.id).zfill(3)
        if self.form:
            if self.form == '?':
                form_str = 'question'
            else:    
                form_str = self.form
        else:
            form_str = ""
        if self.alolan:
            region_str = "a"
        elif self.galarian:
            region_str = "g"
        else:
            region_str = ""
        if self.shiny:
            shiny_str = "s"
        else:
            shiny_str = ""
        return ('https://raw.githubusercontent.com/tehstone/Kyogre/master/'
                f'images/pkmn/{pkmn_no}{form_str}_{region_str}{shiny_str}.png?cache=3')

    @property
    def is_raid(self):
        """:class:`bool` : Indicates if the pokemon can show in Raids"""
        return self.name.lower() in self.get_raidlist(self.bot)

    @property
    def is_exraid(self):
        """:class:`bool` : Indicates if the pokemon can show in Raids"""
        return self.name.lower() in self.bot.raid_info['raid_eggs']['EX']['pokemon']

    @property
    def raid_level(self):
        """:class:`int` or :obj:`None` : Returns raid egg level"""
        return utils.get_level(self.bot, self.name)

    def set_guild(self, guild):
        """:class:`discord.Guild` or :obj:`None` : Sets the relevant Guild"""
        self.guild = guild

    @property
    def weak_against(self):
        """:class:`dict` : Returns a dict of all types the Pokemon is
        weak against.
        """
        types_eff = {}
        for t, v in self.type_effects.items():
            if round(v, 3) > 1:
                types_eff[t] = v
        return types_eff

    @property
    def strong_against(self):
        """:class:`dict` : Returns a dict of all types the Pokemon is
        strong against.
        """
        types_eff = {}
        for t, v in self.type_effects.items():
            if round(v, 3) < -1:
                types_eff[t] = v
        return types_eff

    @property
    def type_effects(self):
        """:class:`dict` : Returns a dict of all Pokemon types and their
        relative effectiveness as values.
        """
        type_eff = {}
        for _type in self.types:
            for atk_type in self.bot.defense_chart[_type]:
                if atk_type not in type_eff:
                    type_eff[atk_type] = 1
                type_eff[atk_type] *= utils.get_effectiveness(self.bot.defense_chart[_type][atk_type])
        return type_eff

    @property
    def type_effects_grouped(self):
        """:class:`dict` : Returns a dict of all Pokemon types and their
        relative effectiveness as values, grouped by the following:
            * ultra
            * super
            * low
            * worst
        """
        type_eff_dict = {
            'ultra' : [],
            'super' : [],
            'low'   : [],
            'worst' : []
        }
        for t, v in self.type_effects.items():
            if v > 1.9:
                type_eff_dict['ultra'].append(t)
            elif v > 1.3:
                type_eff_dict['super'].append(t)
            elif v < 0.6:
                type_eff_dict['worst'].append(t)
            else:
                type_eff_dict['low'].append(t)
        return type_eff_dict

    def get_cp_by_level(self, level, atk=15, dfn=15, sta=15):
        mult = cp_multipliers[level]
        attack = self.base_attack + atk
        defense = self.base_defense + dfn
        stamina = self.base_stamina + sta
        return int((attack * math.sqrt(defense) * math.sqrt(stamina) * mult * mult) / 10)

    def get_raid_cp_range(self, boosted=False):
        if not self.is_raid:
            return None
        if boosted:
            level = 25
        else:
            level = 20
        min_cp = self.get_cp_by_level(level, 10, 10, 10)
        max_cp = self.get_cp_by_level(level, 15, 15, 15)
        return min_cp, max_cp

    @property
    def get_boss_cp(self):
        if not self.is_raid:
            return None
        stamina = self._raid_stamina[int(self.raid_level)]
        return int(((self.base_attack + 15) * math.sqrt(self.base_defense + 15) * math.sqrt(stamina)) / 10)

    @classmethod
    def find_obj(cls, pkmn):
        if pkmn.isdigit():
            p_obj = next((v for k, v in Pokemon.get_pkmn_dict().items() if v['id'] == int(pkmn)), None)
        else:
            p_obj = next((v for k, v in Pokemon.get_pkmn_dict().items() if k == pkmn.strip().lower()), None)
        return p_obj

    @classmethod
    def get_pokemon(cls, bot, argument, guild=None):
        try:
            argument = int(argument)
            p_obj = Pokemon.find_obj(str(argument))
            return cls(bot, str(p_obj['name']), guild)
        except ValueError:
            pass
        argument = argument.lower()
        if 'shiny' in argument:
            shiny = True
            argument = argument.replace('shiny', '').strip()
        else:
            shiny = False
        if 'alolan' in argument:
            alolan = True
            argument = argument.replace('alolan', '').strip()
        else:
            alolan = False
        if 'galarian' in argument:
            galarian = True
            argument = argument.replace('galarian', '').strip()
        else:
            galarian = False
        arg_split = argument.split()
        if arg_split[0].lower() == 'mega':
            arg_split[0] = f"{arg_split[0]}-{arg_split[1]}"
            del arg_split[1]
            argument = ' '.join(arg_split)

        form = None
        detected_forms = []
        form_check = None
        # this logic will fail for pokemon with multiple word name (e.g. Tapu Koko et al)
        arg_split = argument.split()
        candidates = [f for f in Pokemon._form_list if f in arg_split]
        for c in candidates:
            detected_forms.append(c)
            argument = argument.replace(c, '').strip()
        arg_split = argument.split()
        p_obj = None
        if arg_split:
            if len(arg_split) > 1:
                if 'unown' == arg_split[1] or 'spinda' == arg_split[1]:
                    if arg_split[0] in Pokemon._form_dict[arg_split[1]]:
                        detected_forms.append(arg_split[0])
                    p_obj = Pokemon.find_obj(arg_split[1].strip(','))
        if not p_obj:
            if len(arg_split) > 0:
                p_obj = Pokemon.find_obj(arg_split[0].strip(','))
        if not p_obj:
            pkmn_list = [p for p in Pokemon.get_pkmn_dict()]
            match = utils.get_match(pkmn_list, argument, score_cutoff=80)[0]
        else:
            match = p_obj['name']
        if not match:
            return None

        form_list = Pokemon._form_dict.get(match, [])
        forms = [d for d in detected_forms if d in form_list]
        if forms:
            form = ' '.join(forms)
        return cls(bot, str(match), guild, shiny=shiny, alolan=alolan, galarian=galarian, form=form)

    @staticmethod
    def has_forms(name):
        return name.lower() in Pokemon._form_dict

    @staticmethod
    def is_form(name):
        return name.lower() in Pokemon._form_list

    @staticmethod
    def get_forms_for_pokemon(name):
        if name in Pokemon._form_dict:
            return Pokemon._form_dict[name]
        return []

    @staticmethod
    def get_forms_list():
        return Pokemon._form_list

    @staticmethod
    def get_alolans_list():
        return Pokemon._alolans_list

    @staticmethod
    def get_galarians_list():
        return Pokemon._galarians_list

    @staticmethod
    def get_raidlist(bot):
        raidlist = []
        for level in bot.raid_info['raid_eggs']:
            for pokemon in bot.raid_info['raid_eggs'][level]['pokemon']:
                mon = Pokemon.get_pokemon(bot, pokemon)
                if mon:
                    raidlist.append(mon.name.lower())
        return raidlist

    @staticmethod
    def save_pokemon_to_json():
        try:
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(os.path.join('data', 'pokestop_data_backup1')),
                                             delete=False) as f:
                pokemon = (PokemonTable
                           .select(PokemonTable.id,
                                   PokemonTable.name,
                                   PokemonTable.legendary,
                                   PokemonTable.mythical,
                                   PokemonTable.shiny,
                                   PokemonTable.alolan,
                                   PokemonTable.galarian,
                                   PokemonTable.types,
                                   PokemonTable.released,
                                   PokemonTable.attack,
                                   PokemonTable.defense,
                                   PokemonTable.stamina))
                s = []
                for poke in pokemon:
                    p = {"id": poke.id,
                         "name": poke.name,
                         "legendary": poke.legendary,
                         "mythical": poke.mythical,
                         "shiny": poke.shiny,
                         "alolan": poke.alolan,
                         "galarian": poke.galarian,
                         "types": poke.types,
                         "released": poke.released,
                         "attack": poke.attack,
                         "defense": poke.defense,
                         "stamina": poke.stamina}
                    s.append(p)
                f.write(json.dumps(s, indent=4))
                tempname = f.name
            try:
                os.remove(os.path.join('data', 'pokemon_data_backup1'))
            except OSError as e:
                pass
            try:
                os.rename(os.path.join('data', 'pokemon_data_backup1'), os.path.join('data', 'pokemon_data_backup2'))
            except OSError as e:
                pass
            os.rename(tempname, os.path.join('data', 'pokemon_data_backup1'))
            return None
        except Exception as err:
            return err


def setup(bot):
    bot.add_cog(Pokedex(bot))
