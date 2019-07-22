import aiohttp
import discord

from kyogre.exts.pokemon import Pokemon

async def _counters(ctx, Kyogre, pkmn, user = None, weather = None, movesetstr = "Unknown Moveset"):
    if isinstance(pkmn, str):
        pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    if not pkmn:
        return
    img_url = pkmn.img_url
    level = pkmn.raid_level
    if not level.isdigit():
        level = "5"
    pokebattler_name = pkmn.species.upper()
    if pkmn.alolan:
        pokebattler_name += "_ALOLA_FORM"
    url = "https://fight.pokebattler.com/raids/defenders/{pkmn}/levels/RAID_LEVEL_{level}/attackers/".format(pkmn=pokebattler_name,level=level)
    if user:
        url += "users/{user}/".format(user=user)
        userstr = "user #{user}'s".format(user=user)
    else:
        url += "levels/30/"
        userstr = "Level 30"
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    match_list = ['NO_WEATHER','NO_WEATHER','CLEAR','CLEAR','RAINY',
                        'PARTLY_CLOUDY','OVERCAST','WINDY','SNOW','FOG']
    if not weather:
        index = 0
    else:
        index = weather_list.index(weather)
    weather = match_list[index]
    url += "strategies/CINEMATIC_ATTACK_WHEN_POSSIBLE/DEFENSE_RANDOM_MC?sort=OVERALL&"
    url += "weatherCondition={weather}&dodgeStrategy=DODGE_REACTION_TIME&aggregation=AVERAGE".format(weather=weather)
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
        def clean(txt):
            return txt.replace('_', ' ').title()
        title = '{pkmn} | {weather} | {movesetstr}'.format(pkmn=pkmn.name,weather=weather_list[index].title(),movesetstr=movesetstr)
        stats_msg = "**CP:** {raid_cp}\n".format(raid_cp=raid_cp)
        stats_msg += "**Weather:** {weather}\n".format(weather=clean(weather))
        stats_msg += "**Attacker Level:** {atk_levels}".format(atk_levels=atk_levels)
        ctrs_embed = discord.Embed(colour=colour)
        ctrs_embed.set_author(name=title,url=title_url,icon_url=hyperlink_icon)
        ctrs_embed.set_thumbnail(url=img_url)
        ctrs_embed.set_footer(text='Results courtesy of Pokebattler', icon_url=pbtlr_icon)
        index = 1
        for ctr in reversed(ctrs):
            ctr_name = clean(ctr['pokemonId'])
            ctr_nick = clean(ctr.get('name',''))
            ctr_cp = ctr['cp']
            moveset = ctr['byMove'][-1]
            moves = "{move1} | {move2}".format(move1=clean(moveset['move1'])[:-5], move2=clean(moveset['move2']))
            name = "#{index} - {ctr_name}".format(index=index, ctr_name=(ctr_nick or ctr_name))
            cpstr = "CP"
            ctrs_embed.add_field(name=name,value=f"{cpstr}: {ctr_cp}\n{moves}")
            index += 1
        ctrs_embed.add_field(name="Results with {userstr} attackers".format(userstr=userstr), value="[See your personalized results!](https://www.pokebattler.com/raids/{pkmn})".format(pkmn=pokebattler_name))
        if user:
            ctrs_embed.add_field(name="Pokebattler Estimator:", value="Difficulty rating: {est}".format(est=est))
            await ctx.channel.send(f"Check your inbox {ctx.author.mention}, I've sent your personalized results to you directly!")
            return await ctx.author.send(embed=ctrs_embed)
        await ctx.channel.send(embed=ctrs_embed)


async def _get_generic_counters(Kyogre, guild, pkmn, weather=None):
    if isinstance(pkmn, str):
        pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    if not pkmn:
        return
    emoji_dict = {0: '0\u20e3', 1: '1\u20e3', 2: '2\u20e3', 3: '3\u20e3', 4: '4\u20e3', 5: '5\u20e3', 6: '6\u20e3', 7: '7\u20e3', 8: '8\u20e3', 9: '9\u20e3', 10: '10\u20e3'}
    ctrs_dict = {}
    ctrs_index = 0
    ctrs_dict[ctrs_index] = {}
    ctrs_dict[ctrs_index]['moveset'] = "Unknown Moveset"
    ctrs_dict[ctrs_index]['emoji'] = '0\u20e3'
    img_url = pkmn.img_url
    level = pkmn.raid_level
    if not level.isdigit():
        level = "5"
    pokebattler_name = pkmn.species.upper()
    if pkmn.alolan:
        pokebattler_name = f"{pkmn.species.upper()}_ALOLA_FORM"
    url = "https://fight.pokebattler.com/raids/defenders/{pkmn}/levels/RAID_LEVEL_{level}/attackers/".format(pkmn=pokebattler_name,level=level)
    url += "levels/30/"
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    match_list = ['NO_WEATHER','NO_WEATHER','CLEAR','CLEAR','RAINY',
                        'PARTLY_CLOUDY','OVERCAST','WINDY','SNOW','FOG']
    if not weather:
        index = 0
    else:
        index = weather_list.index(weather)
    weather = match_list[index]
    url += "strategies/CINEMATIC_ATTACK_WHEN_POSSIBLE/DEFENSE_RANDOM_MC?sort=OVERALL&"
    url += "weatherCondition={weather}&dodgeStrategy=DODGE_REACTION_TIME&aggregation=AVERAGE".format(weather=weather)
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
    def clean(txt):
        return txt.replace('_', ' ').title()
    title = '{pkmn} | {weather} | Unknown Moveset'.format(pkmn=pkmn.name,weather=weather_list[index].title())
    stats_msg = "**CP:** {raid_cp}\n".format(raid_cp=raid_cp)
    stats_msg += "**Weather:** {weather}\n".format(weather=clean(weather))
    stats_msg += "**Attacker Level:** {atk_levels}".format(atk_levels=atk_levels)
    ctrs_embed = discord.Embed(colour=guild.me.colour)
    ctrs_embed.set_author(name=title,url=title_url,icon_url=hyperlink_icon)
    ctrs_embed.set_thumbnail(url=img_url)
    ctrs_embed.set_footer(text='Results courtesy of Pokebattler', icon_url=pbtlr_icon)
    ctrindex = 1
    for ctr in reversed(ctrs):
        ctr_name = clean(ctr['pokemonId'])
        moveset = ctr['byMove'][-1]
        moves = "{move1} | {move2}".format(move1=clean(moveset['move1'])[:-5], move2=clean(moveset['move2']))
        name = "#{index} - {ctr_name}".format(index=ctrindex, ctr_name=ctr_name)
        ctrs_embed.add_field(name=name,value=moves)
        ctrindex += 1
    ctrs_dict[ctrs_index]['embed'] = ctrs_embed
    for moveset in data['byMove']:
        ctrs_index += 1
        move1 = moveset['move1'][:-5].lower().title().replace('_', ' ')
        move2 = moveset['move2'].lower().title().replace('_', ' ')
        movesetstr = f'{move1} | {move2}'
        ctrs = moveset['defenders'][-6:]
        title = '{pkmn} | {weather} | {movesetstr}'.format(pkmn=pkmn.name, weather=weather_list[index].title(), movesetstr=movesetstr)
        ctrs_embed = discord.Embed(colour=guild.me.colour)
        ctrs_embed.set_author(name=title,url=title_url,icon_url=hyperlink_icon)
        ctrs_embed.set_thumbnail(url=img_url)
        ctrs_embed.set_footer(text='Results courtesy of Pokebattler', icon_url=pbtlr_icon)
        ctrindex = 1
        for ctr in reversed(ctrs):
            ctr_name = clean(ctr['pokemonId'])
            moveset = ctr['byMove'][-1]
            moves = "{move1} | {move2}".format(move1=clean(moveset['move1'])[:-5], move2=clean(moveset['move2']))
            name = "#{index} - {ctr_name}".format(index=ctrindex, ctr_name=ctr_name)
            ctrs_embed.add_field(name=name,value=moves)
            ctrindex += 1
        ctrs_dict[ctrs_index] = {'moveset': movesetstr, 'embed': ctrs_embed, 'emoji': emoji_dict[ctrs_index]}
    moveset_list = []
    for moveset in ctrs_dict:
        moveset_list.append(f"{ctrs_dict[moveset]['emoji']}: {ctrs_dict[moveset]['moveset']}\n")
    for moveset in ctrs_dict:
        ctrs_split = int(round(len(moveset_list)/2+0.1))
        ctrs_dict[moveset]['embed'].add_field(name="**Possible Movesets:**", value=f"{''.join(moveset_list[:ctrs_split])}", inline=True)
        ctrs_dict[moveset]['embed'].add_field(name="\u200b", value=f"{''.join(moveset_list[ctrs_split:])}",inline=True)
        ctrs_dict[moveset]['embed'].add_field(name="Results with Level 30 attackers", value="[See your personalized results!](https://www.pokebattler.com/raids/{pkmn})".format(pkmn=pokebattler_name),inline=False)

    return ctrs_dict
