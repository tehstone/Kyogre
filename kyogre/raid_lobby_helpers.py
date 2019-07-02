import asyncio
import copy
import datetime
import time

import discord

from kyogre.exts.pokemon import Pokemon
from kyogre import counters_helpers, embed_utils, list_helpers, utils

async def _backout(ctx, Kyogre, guild_dict):
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = channel.guild
    trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    if (author.id in trainer_dict) and (trainer_dict[author.id]['status']['lobby']):
        count = trainer_dict[author.id]['count']
        trainer_dict[author.id]['status'] = {'maybe':0, 'coming':0,'here':count,'lobby':0}
        lobby_list = []
        for trainer in trainer_dict:
            count = trainer_dict[trainer]['count']
            if trainer_dict[trainer]['status']['lobby']:
                user = guild.get_member(trainer)
                lobby_list.append(user.mention)
                trainer_dict[trainer]['status'] = {'maybe':0, 'coming':0, 'here':count, 'lobby':0}
        if (not lobby_list):
            await channel.send("There's no one else in the lobby for this raid!")
            try:
                del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
            except KeyError:
                pass
            return
        await channel.send('Backout - {author} has indicated that the group consisting of {lobby_list} and the people with them has backed out of the lobby! If this is inaccurate, please use **!lobby** or **!cancel** to help me keep my lists accurate!'.format(author=author.mention, lobby_list=', '.join(lobby_list)))
        try:
            del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
        except KeyError:
            pass
    else:
        lobby_list = []
        trainer_list = []
        for trainer in trainer_dict:
            if trainer_dict[trainer]['status']['lobby']:
                user = guild.get_member(trainer)
                lobby_list.append(user.mention)
                trainer_list.append(trainer)
        if (not lobby_list):
            await channel.send("There's no one in the lobby for this raid!")
            return

        backoutmsg = await channel.send('Backout - {author} has requested a backout! If one of the following trainers reacts with the check mark, I will assume the group is backing out of the raid lobby as requested! {lobby_list}'.format(author=author.mention, lobby_list=', '.join(lobby_list)))
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(Kyogre, backoutmsg, channel, trainer_list, react_list=['✅'])
        except TypeError:
            timeout = True
        if not timeout and res.emoji == '✅':
            for trainer in trainer_list:
                count = trainer_dict[trainer]['count']
                if trainer in trainer_dict:
                    trainer_dict[trainer]['status'] = {'maybe':0, 'coming':0, 'here':count, 'lobby':0}
            await channel.send('{user} confirmed the group is backing out!'.format(user=reactuser.mention))
            try:
                del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
            except KeyError:
                pass
        else:
            return

async def _starting(ctx, Kyogre, guild_dict, raid_info, team):
    channel = ctx.channel
    guild = ctx.guild
    ctx_startinglist = []
    team_list = []
    ctx.team_names = ["mystic", "valor", "instinct", "unknown"]
    team = team if team and team.lower() in ctx.team_names else "all"
    ctx.trainer_dict = copy.deepcopy(guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
    regions = guild_dict[guild.id]['raidchannel_dict'][channel.id]['regions']
    if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('type',None) == 'egg':
        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 < datetime.datetime.now().timestamp():
            starting_str = "Please tell me which raid boss has hatched before starting your lobby."
        else:
            starting_str = "How can you start when the egg hasn't hatched!?"
        await channel.send(starting_str)
        return
    if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('lobby',False):
        starting_str = "Please wait for the group in the lobby to enter the raid."
        await channel.send(starting_str)
        return
    trainer_joined = False
    for trainer in ctx.trainer_dict:
        count = ctx.trainer_dict[trainer]['count']
        user = guild.get_member(trainer)
        if team in ctx.team_names:
            if ctx.trainer_dict[trainer]['party'][team]:
                team_list.append(user.id)
            teamcount = ctx.trainer_dict[trainer]['party'][team]
            herecount = ctx.trainer_dict[trainer]['status']['here']
            lobbycount = ctx.trainer_dict[trainer]['status']['lobby']
            if ctx.trainer_dict[trainer]['status']['here'] and (user.id in team_list):
                ctx.trainer_dict[trainer]['status'] = {'maybe':0, 'coming':0, 'here':herecount - teamcount, 'lobby':lobbycount + teamcount}
                trainer_joined = True
                ctx_startinglist.append(user.mention)
        else:
            if ctx.trainer_dict[trainer]['status']['here'] and (user.id in team_list or team == "all"):
                ctx.trainer_dict[trainer]['status'] = {'maybe':0, 'coming':0, 'here':0, 'lobby':count}
                trainer_joined = True
                ctx_startinglist.append(user.mention)
        if trainer_joined:
            joined = guild_dict[guild.id].setdefault('trainers',{}).setdefault(regions[0], {}).setdefault(trainer,{}).setdefault('joined',0) + 1
            guild_dict[guild.id]['trainers'][regions[0]][trainer]['joined'] = joined
            
    if len(ctx_startinglist) == 0:
        starting_str = "How can you start when there's no one waiting at this raid!?"
        await channel.send(starting_str)
        return
    guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = ctx.trainer_dict
    starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('starttime',None)
    if starttime:
        timestr = ' to start at **{}** '.format(starttime.strftime('%I:%M %p (%H:%M)'))
        guild_dict[guild.id]['raidchannel_dict'][channel.id]['starttime'] = None
    else:
        timestr = ' '
    starting_str = 'Starting - The group that was waiting{timestr}is starting the raid! Trainers {trainer_list}, if you are not in this group and are waiting for the next group, please respond with {here_emoji} or **!here**. If you need to ask those that just started to back out of their lobby, use **!backout**'.format(timestr=timestr, trainer_list=', '.join(ctx_startinglist), here_emoji=utils.parse_emoji(guild, Kyogre.config['here_id']))
    guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby'] = {"exp":time.time() + 120, "team":team}
    if starttime:
        starting_str += '\n\nThe start time has also been cleared, new groups can set a new start time wtih **!starttime HH:MM AM/PM** (You can also omit AM/PM and use 24-hour time!).'
        report_channel = Kyogre.get_channel(guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
        raidmsg = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidmessage'])
        reportmsg = await report_channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
        embed = raidmsg.embeds[0]
        embed_indices = await embed_utils.get_embed_field_indices(embed)
        embed.set_field_at(embed_indices["next"], name="**Next Group**", value="Set with **!starttime**", inline=True)
        try:
            await raidmsg.edit(content=raidmsg.content,embed=embed)
        except discord.errors.NotFound:
            pass
        try:
            await reportmsg.edit(content=reportmsg.content,embed=embed)
        except discord.errors.NotFound:
            pass
    await channel.send(starting_str)
    ctx.bot.loop.create_task(lobby_countdown(ctx, Kyogre, team, guild_dict, raid_info))


async def lobby_countdown(ctx, Kyogre, team, guild_dict, raid_info):
    await asyncio.sleep(120)
    if ('lobby' not in guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]) or (time.time() < guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['lobby']['exp']):
        return
    ctx_lobbycount = 0
    trainer_delete_list = []
    for trainer in ctx.trainer_dict:
        if ctx.trainer_dict[trainer]['status']['lobby']:
            ctx_lobbycount += ctx.trainer_dict[trainer]['status']['lobby']
            trainer_delete_list.append(trainer)
    if ctx_lobbycount > 0:
        await ctx.channel.send('The group of {count} in the lobby has entered the raid! Wish them luck!'.format(count=str(ctx_lobbycount)))
    for trainer in trainer_delete_list:
        if team in ctx.team_names:
            herecount = ctx.trainer_dict[trainer]['status'].get('here', 0)
            teamcount = ctx.trainer_dict[trainer]['party'][team]
            ctx.trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here':herecount - teamcount, 'lobby': ctx_lobbycount}
            ctx.trainer_dict[trainer]['party'][team] = 0
            ctx.trainer_dict[trainer]['count'] = ctx.trainer_dict[trainer]['count'] - teamcount
        else:
            del ctx.trainer_dict[trainer]
    try:
        del guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['lobby']
    except KeyError:
        pass
    await list_helpers._edit_party(ctx, Kyogre, guild_dict, raid_info, ctx.channel, ctx.author)
    guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'] = ctx.trainer_dict
    regions = guild_dict[ctx.channel.guild.id]['raidchannel_dict'][ctx.channel.id].get('regions', None)
    if regions:
        await list_helpers.update_listing_channels(Kyogre, guild_dict, ctx.guild, 'raid', edit=True, regions=regions)

async def _weather(ctx, Kyogre, guild_dict, weather):
    guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['weather'] = weather.lower()
    pkmn = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id].get('pokemon', None)
    pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    if pkmn:
        if str(pkmn.raid_level) in guild_dict[ctx.guild.id]['configure_dict']['counters']['auto_levels']:
            ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, ctx.guild, pkmn, weather.lower())
            try:
                ctrsmessage = await ctx.channel.fetch_message(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['ctrsmessage'])
                moveset = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['moveset']
                newembed = ctrs_dict[moveset]['embed']
                await ctrsmessage.edit(embed=newembed)
            except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                pass
            guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['ctrs_dict'] = ctrs_dict
    raid_message = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['raidmessage']
    raid_message = await ctx.channel.fetch_message(raid_message)
    embed = raid_message.embeds[0]
    embed_indices = await embed_utils.get_embed_field_indices(embed)
    new_embed = embed
    gym_embed = embed.fields[embed_indices['gym']]
    gym_embed_value = '\n'.join(gym_embed.value.split('\n')[:2])
    gym_embed_value += "\n**Weather**: " + weather
    new_embed.set_field_at(embed_indices['gym'], name=gym_embed.name, value=gym_embed_value, inline=True)
    await raid_message.edit(embed=new_embed)
    return await ctx.channel.send("Weather set to {}!".format(weather.lower()))
