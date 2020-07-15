import aiohttp
import discord
from discord.ext import commands

from kyogre.exts.pokemon import Pokemon

WEATHER_LIST = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
WEATHER_MATCH_LIST = ['NO_WEATHER', 'NO_WEATHER', 'CLEAR', 'CLEAR', 'RAINY',
                      'PARTLY_CLOUDY', 'OVERCAST', 'WINDY', 'SNOW', 'FOG']
ROCKET_LEVEL_MAP = {"grunt": 3, "cliff": 4, "arlo": 4, "sierra": 4, "jesse": 4, "james": 4, "giovanni": 5}


class CounterHelpers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def clean(txt):
        text = txt.replace('_', ' ').title()
        form_index = text.lower().find("form")
        if form_index > 0:
            text = text[:form_index]
            split = text.split()
            split[-1] = f"({split[-1]})"
            text = ' '.join(split)
        return text

    async def counters(self, ctx, pkmn, user=None, weather=None, movesetstr="Unknown Moveset", opponent=None):
        if isinstance(pkmn, str):
            pkmn = Pokemon.get_pokemon(self.bot, pkmn)
        if not pkmn:
            return
        img_url = pkmn.img_url
        pokebattler_name = pkmn.species.upper()
        if opponent:
            battle_type = "rocket"
            pokebattler_name += "_SHADOW_FORM"
            level = ROCKET_LEVEL_MAP[opponent]
        else:
            battle_type = "raids"
            level = pkmn.raid_level
            if not level.isdigit():
                level = "5"
            if pkmn.alolan:
                pokebattler_name += "_ALOLA_FORM"
            if pkmn.galarian:
                pokebattler_name += "_GALARIAN_FORM"
        url = f"https://fight.pokebattler.com/{battle_type}/defenders/{pokebattler_name}/levels/RAID_LEVEL_{level}/attackers/"
        if user:
            url += "users/{user}/".format(user=user)
            userstr = "user #{user}'s".format(user=user)
        else:
            url += "levels/30/"
            userstr = "Level 30"

        if not weather:
            index = 0
        else:
            index = WEATHER_LIST.index(weather)
        weather = WEATHER_MATCH_LIST[index]
        if not opponent:
            url += "strategies/CINEMATIC_ATTACK_WHEN_POSSIBLE/DEFENSE_RANDOM_MC"
        url += f"?sort=OVERALL&weatherCondition={weather}&dodgeStrategy=DODGE_REACTION_TIME&aggregation=AVERAGE"
        if opponent:
            if level <= 3:
                url += "&defenderShieldStrategy=SHIELD_0"
            else:
                url += "&defenderShieldStrategy=SHIELD_2"
        async with ctx.typing():
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url) as resp:
                    data = await resp.json()
            title_url = url.replace('https://fight', 'https://www')
            colour = ctx.guild.me.colour
            hyperlink_icon = 'https://i.imgur.com/fn9E5nb.png'
            pbtlr_icon = 'https://www.pokebattler.com/favicon-32x32.png'
            data = data['attackers'][0]
            raid_cp = data['cp']
            atk_levels = '30'
            if movesetstr == "Unknown Moveset":
                ctrs = data['randomMove']['defenders'][-6:]
                est = data['randomMove']['total']['estimator']
            else:
                for moveset in data['byMove']:
                    move1 = moveset['move1'][:-5].lower().title().replace('_', ' ')
                    move2 = moveset['move2'].lower().title().replace('_', ' ')
                    moveset_str = f'{move1} | {move2}'
                    if moveset_str == movesetstr:
                        ctrs = moveset['defenders'][-6:]
                        est = moveset['total']['estimator']
                        break
                else:
                    movesetstr = "Unknown Moveset"
                    ctrs = data['randomMove']['defenders'][-6:]
                    est = data['randomMove']['total']['estimator']

            title = '{pkmn} | {weather} | {movesetstr}'.format(pkmn=pkmn.name, weather=WEATHER_LIST[index].title(),
                                                               movesetstr=movesetstr)
            stats_msg = "**CP:** {raid_cp}\n".format(raid_cp=raid_cp)
            stats_msg += "**Weather:** {weather}\n".format(weather=self.clean(weather))
            stats_msg += "**Attacker Level:** {atk_levels}".format(atk_levels=atk_levels)
            ctrs_embed = discord.Embed(colour=colour)
            ctrs_embed.set_author(name=title, url=title_url, icon_url=hyperlink_icon)
            ctrs_embed.set_thumbnail(url=img_url)
            index = 1
            for ctr in reversed(ctrs):
                ctr_name = self.clean(ctr['pokemonId'])
                ctr_nick = self.clean(ctr.get('name', ''))
                ctr_cp = ctr['cp']
                moveset = ctr['byMove'][-1]
                moves = "{move1} | {move2}".format(move1=self.clean(moveset['move1'])[:-5],
                                                   move2=self.clean(moveset['move2']))
                name = "#{index} - {ctr_name}".format(index=index, ctr_name=(ctr_nick or ctr_name))
                cpstr = "CP"
                ctrs_embed.add_field(name=name, value=f"{cpstr}: {ctr_cp}\n{moves}")
                index += 1
            ctrs_embed.add_field(name=f"Results courtesy of Pokebattler. {userstr}'s attackers",
                                 value=f"[See your personalized results!](https://www.pokebattler.com/raids/{pokebattler_name})")
            if user:
                ctrs_embed.add_field(name="Pokebattler Estimator:", value="Difficulty rating: {est}".format(est=est))
                await ctx.channel.send(f"Check your inbox {ctx.author.mention}, "
                                       f"I've sent your personalized results to you directly!")
                return await ctx.author.send(embed=ctrs_embed)
            await ctx.channel.send(embed=ctrs_embed)

    async def get_generic_counters(self, guild, pkmn, weather=None, user=None, opponent=None):
        if isinstance(pkmn, str):
            pkmn = Pokemon.get_pokemon(self.bot, pkmn)
        if not pkmn:
            return
        emoji_dict = {0: '0\u20e3', 1: '1\u20e3', 2: '2\u20e3', 3: '3\u20e3', 4: '4\u20e3',
                      5: '5\u20e3', 6: '6\u20e3', 7: '7\u20e3', 8: '8\u20e3', 9: '9\u20e3',
                      10: "🇦", 11: '🇧', 12: '🇨', 13: '🇩', 14: '🇪',
                      15: '🇫', 16: '🇬', 17: '🇭', 18: '🇮', 19: '🇯'
                      }
        ctrs_dict = {}
        ctrs_index = 0
        ctrs_dict[ctrs_index] = {}
        ctrs_dict[ctrs_index]['moveset'] = "Unknown Moveset"
        ctrs_dict[ctrs_index]['emoji'] = '0\u20e3'
        img_url = pkmn.img_url
        pokebattler_name = pkmn.species.upper()
        if opponent:
            battle_type = "rocket"
            pokebattler_name += "_SHADOW_FORM"
            level = ROCKET_LEVEL_MAP[opponent]
        else:
            battle_type = "raids"
            level = pkmn.raid_level
            if not level.isdigit():
                level = "5"
            if pkmn.alolan:
                pokebattler_name += "_ALOLA_FORM"
            if pkmn.galarian:
                pokebattler_name += "_GALARIAN_FORM"
        url = f"https://fight.pokebattler.com/{battle_type}/defenders/{pokebattler_name}/levels/RAID_LEVEL_{level}/attackers/"
        if user:
            url += "users/{user}/".format(user=user)
        else:
            url += "levels/30/"

        if not weather:
            index = 0
        else:
            index = WEATHER_LIST.index(weather)
        weather = WEATHER_MATCH_LIST[index]
        if not opponent:
            url += "strategies/CINEMATIC_ATTACK_WHEN_POSSIBLE/DEFENSE_RANDOM_MC"
        url += f"?sort=OVERALL&weatherCondition={weather}&dodgeStrategy=DODGE_REACTION_TIME&aggregation=AVERAGE"
        if opponent:
            if level <= 3:
                url += "&defenderShieldStrategy=SHIELD_0"
            else:
                url += "&defenderShieldStrategy=SHIELD_2"
        title_url = url.replace('https://fight', 'https://www')
        hyperlink_icon = 'https://i.imgur.com/fn9E5nb.png'
        pbtlr_icon = 'https://www.pokebattler.com/favicon-32x32.png'
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                data = await resp.json()
        data = data['attackers'][0]
        raid_cp = data['cp']
        atk_levels = '30'
        ctrs = data['randomMove']['defenders'][-6:]
        weather_title = WEATHER_LIST[index].title()
        if weather_title == 'None':
            weather_title = "No Weather"
        title = f'{pkmn.name} | {weather_title} | Unknown Moveset | Level 30 Attackers'
        stats_msg = "**CP:** {raid_cp}\n".format(raid_cp=raid_cp)
        stats_msg += "**Weather:** {weather}\n".format(weather=self.clean(weather))
        stats_msg += "**Attacker Level:** {atk_levels}".format(atk_levels=atk_levels)
        ctrs_embed = discord.Embed(colour=guild.me.colour)
        ctrs_embed.set_author(name=title, url=title_url, icon_url=hyperlink_icon)
        ctrs_embed.set_thumbnail(url=img_url)
        ctrindex = 1
        description = ''
        for ctr in reversed(ctrs):
            ctr_name = self.clean(ctr['pokemonId'])
            moveset = ctr['byMove'][-1]
            moves = f"{self.clean(moveset['move1'])[:-5]} | {self.clean(moveset['move2'])}"
            name = f"#{ctrindex} - {ctr_name}"
            description += f"**{name}** - {moves}\n"
            ctrindex += 1
        ctrs_embed.description = description
        ctrs_dict[ctrs_index]['embed'] = ctrs_embed
        for moveset in data['byMove']:
            description = ''
            ctrs_index += 1
            move1 = moveset['move1'][:-5].lower().title().replace('_', ' ')
            move2 = moveset['move2'].lower().title().replace('_', ' ')
            movesetstr = f'{move1} | {move2}'
            ctrs = moveset['defenders'][-6:]
            title = f'{pkmn.name} | {WEATHER_LIST[index].title()} | {movesetstr} | Level 30 Attackers'
            ctrs_embed = discord.Embed(colour=guild.me.colour)
            ctrs_embed.set_author(name=title, url=title_url, icon_url=hyperlink_icon)
            ctrs_embed.set_thumbnail(url=img_url)
            ctrindex = 1
            for ctr in reversed(ctrs):
                ctr_name = self.clean(ctr['pokemonId'])
                moveset = ctr['byMove'][-1]
                moves = f"{self.clean(moveset['move1'])[:-5]} | {self.clean(moveset['move2'])}"
                name = f"#{ctrindex} - {ctr_name}"
                description += f"**{name}** - {moves}\n"
                # ctrs_embed.add_field(name=name, value=moves)
                ctrindex += 1
            ctrs_embed.description = description = ''
            ctrs_dict[ctrs_index] = {'moveset': movesetstr, 'embed': ctrs_embed, 'emoji': emoji_dict[ctrs_index]}
            if ctrs_index == 19:
                break
        moveset_list = []
        for moveset in ctrs_dict:
            moveset_list.append(f"{ctrs_dict[moveset]['emoji']}: {ctrs_dict[moveset]['moveset']}\n")
        for moveset in ctrs_dict:
            ctrs_dict[moveset]['embed'].add_field(name="**Possible Movesets:**",
                                                  value=f"{''.join(moveset_list)}", inline=True)
            ctrs_dict[moveset]['embed'].add_field(name="Results courtesy of Pokebattler",
                                                  value=f"[See your personalized results!](https://www.pokebattler.com/raids/{pokebattler_name})",
                                                  inline=False)

        return ctrs_dict


def setup(bot):
    bot.add_cog(CounterHelpers(bot))
