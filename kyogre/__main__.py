import asyncio
import copy
import datetime
import sys
import time

import dateparser

import discord
from discord.ext import commands

from kyogre import checks, counters_helpers, embed_utils
from kyogre import entity_updates, list_helpers, raid_helpers, raid_lobby_helpers, utils
from kyogre.bot import KyogreBot

from kyogre.exts.pokemon import Pokemon

from kyogre.exts.db.kyogredb import *
KyogreDB.start('data/kyogre.db')

Kyogre = KyogreBot()
logger = Kyogre.logger

guild_dict = Kyogre.guild_dict

config = Kyogre.config
defense_chart = Kyogre.defense_chart
type_list = Kyogre.type_list
raid_info = Kyogre.raid_info
raid_path = Kyogre.raid_json_path

active_raids = Kyogre.active_raids


"""
Helper functions
"""
def get_gyms(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    return location_matching_cog.get_gyms(guild_id, regions)


def get_stops(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    return location_matching_cog.get_stops(guild_id, regions)


def get_all_locations(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    return location_matching_cog.get_all(guild_id, regions)


async def location_match_prompt(channel, author_id, name, locations):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    return await location_matching_cog.match_prompt(channel, author_id, name, locations)


@Kyogre.command(hidden=True)
async def template(ctx, *, sample_message):
    """Sample template messages to see how they would appear."""
    (msg, errors) = utils.do_template(sample_message, ctx.author, ctx.guild)
    if errors:
        if msg.startswith('[') and msg.endswith(']'):
            embed = discord.Embed(
                colour=ctx.guild.me.colour, description=msg[1:-1])
            embed.add_field(name='Warning', value='The following could not be found:\n{}'.format(
                '\n'.join(errors)))
            await ctx.channel.send(embed=embed)
        else:
            msg = '{}\n\n**Warning:**\nThe following could not be found: {}'.format(
                msg, ', '.join(errors))
            await ctx.channel.send(msg)
    elif msg.startswith('[') and msg.endswith(']'):
        await ctx.channel.send(embed=discord.Embed(colour=ctx.guild.me.colour, description=msg[1:-1].format(user=ctx.author.mention)))
    else:
        await ctx.channel.send(msg.format(user=ctx.author.mention))


"""
Server Management
"""
async def raid_notice_expiry_check(message):
    logger.info('Expiry_Check - ' + message.channel.name)
    channel = message.channel
    guild = channel.guild
    global active_raids
    message = await channel.fetch_message(message.id)
    if message not in active_raids:
        active_raids.append(message)
        logger.info('raid_notice_expiry_check - Message added to watchlist - ' + channel.name)
        await asyncio.sleep(0.5)
        while True:
            try:
                if guild_dict[guild.id]['raid_notice_dict'][message.id]['exp'] <= time.time():
                    await expire_raid_notice(message)
            except KeyError:
                pass
            await asyncio.sleep(60)
            continue


async def expire_raid_notice(message):
    channel = message.channel
    guild = channel.guild
    raid_notice_dict = guild_dict[guild.id]['raid_notice_dict']
    try:
        trainer = raid_notice_dict[message.id]['reportauthor']
        user = guild.get_member(trainer)
        channel = guild.get_channel(raid_notice_dict[message.id]['reportchannel'])
        regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
        if len(regions) > 0:
            region = regions[0]
        if region is not None:
            role_to_remove = discord.utils.get(guild.roles, name=region + '-raids')
            await user.remove_roles(*[role_to_remove], reason="Raid availability expired or was cancelled by user.")
        else:
            logger.info('expire_raid_notice - Failed to remove role for user ' + user.display_name)
    except:
        logger.info('expire_raid_notice - Failed to remove role. User unknown')
    try:
        await message.edit(content=raid_notice_dict[message.id]['expedit']['content'], embed=discord.Embed(description=raid_notice_dict[message.id]['expedit']['embedcontent'], colour=message.embeds[0].colour.value))
        await message.clear_reactions()
    except discord.errors.NotFound:
        pass
    try:
        user_message = await channel.fetch_message(raid_notice_dict[message.id]['reportmessage'])
        await user_message.delete()
    except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
        pass
    del guild_dict[guild.id]['raid_notice_dict'][message.id]


async def guild_cleanup(loop=True):
    while (not Kyogre.is_closed()):
        guilddict_srvtemp = copy.deepcopy(guild_dict)
        logger.info('Server_Cleanup ------ BEGIN ------')
        guilddict_srvtemp = guild_dict
        dict_guild_list = []
        bot_guild_list = []
        dict_guild_delete = []
        for guildid in guilddict_srvtemp.keys():
            dict_guild_list.append(guildid)
        for guild in Kyogre.guilds:
            bot_guild_list.append(guild.id)
            guild_id = guild.id
        guild_diff = set(dict_guild_list) - set(bot_guild_list)
        for s in guild_diff:
            dict_guild_delete.append(s)
        for s in dict_guild_delete:
            try:
                del guild_dict[s]
                logger.info(('Server_Cleanup - Cleared ' + str(s)) +
                            ' from save data')
            except KeyError:
                pass
        logger.info('Server_Cleanup - SAVING CHANGES')
        try:
            admin_commands_cog = Kyogre.cogs.get('AdminCommands')
            if not admin_commands_cog:
                return None
            await admin_commands_cog.save(guild_id)
        except Exception as err:
            logger.info('Server_Cleanup - SAVING FAILED' + str(err))
        logger.info('Server_Cleanup ------ END ------')
        await asyncio.sleep(7200)
        continue

async def message_cleanup(loop=True):
    while (not Kyogre.is_closed()):
        logger.info('message_cleanup ------ BEGIN ------')
        guilddict_temp = copy.deepcopy(guild_dict)
        update_ids = set()
        for guildid in guilddict_temp.keys():
            guild_id = guildid
            questreport_dict = guilddict_temp[guildid].get('questreport_dict',{})
            wildreport_dict = guilddict_temp[guildid].get('wildreport_dict',{})
            report_dict_dict = {
                'questreport_dict':questreport_dict,
                'wildreport_dict':wildreport_dict,
            }
            report_edit_dict = {}
            report_delete_dict = {}
            for report_dict in report_dict_dict:
                for reportid in report_dict_dict[report_dict].keys():
                    if report_dict_dict[report_dict][reportid].get('exp', 0) <= time.time():
                        report_channel = Kyogre.get_channel(report_dict_dict[report_dict][reportid].get('reportchannel'))
                        if report_channel:
                            user_report = report_dict_dict[report_dict][reportid].get('reportmessage',None)
                            if user_report:
                                report_delete_dict[user_report] = {"action":"delete","channel":report_channel}
                            if report_dict_dict[report_dict][reportid].get('expedit') == "delete":
                                report_delete_dict[reportid] = {"action":"delete","channel":report_channel}
                            else:
                                report_edit_dict[reportid] = {"action":report_dict_dict[report_dict][reportid].get('expedit',"edit"),"channel":report_channel}
                        try:
                            del guild_dict[guildid][report_dict][reportid]
                        except KeyError:
                            pass
            for messageid in report_delete_dict.keys():
                try:
                    report_message = await report_delete_dict[messageid]['channel'].fetch_message(messageid)
                    await report_message.delete()
                    update_ids.add(guildid)
                except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException, KeyError):
                    pass
            for messageid in report_edit_dict.keys():
                try:
                    report_message = await report_edit_dict[messageid]['channel'].fetch_message(messageid)
                    await report_message.edit(content=report_edit_dict[messageid]['action']['content'],embed=discord.Embed(description=report_edit_dict[messageid]['action'].get('embedcontent'), colour=report_message.embeds[0].colour.value))
                    await report_message.clear_reactions()
                    update_ids.add(guildid)
                except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException, IndexError, KeyError):
                    pass
        # save server_dict changes after cleanup
        for id in update_ids:
            guild = Kyogre.get_guild(id)
            await list_helpers.update_listing_channels(Kyogre, guild, 'wild', edit=True)
            await list_helpers.update_listing_channels(Kyogre, guild, 'research', edit=True)
        logger.info('message_cleanup - SAVING CHANGES')
        try:
            admin_commands_cog = Kyogre.cogs.get('AdminCommands')
            if not admin_commands_cog:
                return None
            await admin_commands_cog.save(guild_id)
        except Exception as err:
            logger.info('message_cleanup - SAVING FAILED' + str(err))
        logger.info('message_cleanup ------ END ------')
        await asyncio.sleep(600)
        continue


async def _print(owner, message):
    if 'launcher' in sys.argv[1:]:
        if 'debug' not in sys.argv[1:]:
            await owner.send(message)
    print(message)
    logger.info(message)


async def maint_start(bot):
    tasks = []
    try:
        raids_cog = bot.get_cog("RaidCommands")
        tasks.append(event_loop.create_task(raids_cog.channel_cleanup()))
        tasks.append(event_loop.create_task(message_cleanup()))
        logger.info('Maintenance Tasks Started')
    except KeyboardInterrupt:
        [task.cancel() for task in tasks]

event_loop = asyncio.get_event_loop()
Kyogre.event_loop = event_loop

"""
Events
"""
@Kyogre.event
async def on_ready():
    Kyogre.owner = discord.utils.get(
        Kyogre.get_all_members(), id=config['master'])
    await _print(Kyogre.owner, 'Starting up...')
    Kyogre.uptime = datetime.datetime.now()
    owners = []
    guilds = len(Kyogre.guilds)
    users = 0
    for guild in Kyogre.guilds:
        users += len(guild.members)
        try:
            if guild.id not in guild_dict:
                guild_dict[guild.id] = {
                    'configure_dict':{
                        'welcome': {'enabled':False,'welcomechan':'','welcomemsg':''},
                        'want': {'enabled':False, 'report_channels': []},
                        'raid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}},
                        'exraid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}, 'permissions':'everyone'},
                        'wild': {'enabled':False, 'report_channels': {}},
                        'lure': {'enabled':False, 'report_channels': {}},
                        'counters': {'enabled':False, 'auto_levels': []},
                        'research': {'enabled':False, 'report_channels': {}},
                        'archive': {'enabled':False, 'category':'same','list':None},
                        'invite': {'enabled':False},
                        'team':{'enabled':False},
                        'settings':{'offset':0,'regional':None,'done':False,'prefix':None,'config_sessions':{}}
                    },
                    'wildreport_dict:':{},
                    'questreport_dict':{},
                    'raidchannel_dict':{},
                    'trainers':{}
                }
            else:
                guild_dict[guild.id]['configure_dict'].setdefault('trade', {})
        except KeyError:
            guild_dict[guild.id] = {
                'configure_dict':{
                    'welcome': {'enabled':False,'welcomechan':'','welcomemsg':''},
                    'want': {'enabled':False, 'report_channels': []},
                    'raid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}},
                    'exraid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}, 'permissions':'everyone'},
                    'counters': {'enabled':False, 'auto_levels': []},
                    'wild': {'enabled':False, 'report_channels': {}},
                    'lure': {'enabled':False, 'report_channels': {}},
                    'research': {'enabled':False, 'report_channels': {}},
                    'archive': {'enabled':False, 'category':'same','list':None},
                    'invite': {'enabled':False},
                    'team':{'enabled':False},
                    'settings':{'offset':0,'regional':None,'done':False,'prefix':None,'config_sessions':{}}
                },
                'wildreport_dict:':{},
                'questreport_dict':{},
                'raidchannel_dict':{},
                'trainers':{}
            }
        owners.append(guild.owner)
    help_cog = Kyogre.cogs.get('HelpCommand')
    help_cog.set_avatar(Kyogre.user.avatar_url)
    await _print(Kyogre.owner, "{server_count} servers connected.\n{member_count} members found.".format(server_count=guilds, member_count=users))
    await maint_start(Kyogre)


@Kyogre.event
@checks.good_standing()
async def on_raw_reaction_add(payload):
    channel = Kyogre.get_channel(payload.channel_id)
    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.errors.NotFound, AttributeError):
        return
    guild = message.guild
    try:
        user = guild.get_member(payload.user_id)
    except AttributeError:
        return
    if channel.id in guild_dict[guild.id]['raidchannel_dict'] and user.id != Kyogre.user.id:
        if message.id == guild_dict[guild.id]['raidchannel_dict'][channel.id].get('ctrsmessage',None):
            ctrs_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['ctrs_dict']
            for i in ctrs_dict:
                if ctrs_dict[i]['emoji'] == str(payload.emoji):
                    newembed = ctrs_dict[i]['embed']
                    moveset = i
                    break
            else:
                return
            await message.edit(embed=newembed)
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['moveset'] = moveset
            await message.remove_reaction(payload.emoji, user)
        elif message.id == guild_dict[guild.id]['raidchannel_dict'][channel.id].get('raidmessage',None):
            if str(payload.emoji) == '\u2754':
                prefix = guild_dict[guild.id]['configure_dict']['settings']['prefix']
                prefix = prefix or Kyogre.config['default_prefix']
                avatar = Kyogre.user.avatar_url
                await utils.get_raid_help(prefix, avatar, user)
            await message.remove_reaction(payload.emoji, user)
    wildreport_dict = guild_dict[guild.id].setdefault('wildreport_dict', {})
    if message.id in wildreport_dict and user.id != Kyogre.user.id:
        wild_dict = wildreport_dict.get(message.id, None)
        if str(payload.emoji) == '🏎':
            wild_dict['omw'].append(user.mention)
            wildreport_dict[message.id] = wild_dict
        elif str(payload.emoji) == '💨':
            for reaction in message.reactions:
                if reaction.emoji == '💨' and reaction.count >= 2:
                    if wild_dict['omw']:
                        despawn = "has despawned"
                        await channel.send(f"{', '.join(wild_dict['omw'])}: {wild_dict['pokemon'].title()} {despawn}!")
                    wilds_cog = Kyogre.cogs.get('WildSpawnCommands')
                    await wilds_cog.expire_wild(message)
    questreport_dict = guild_dict[guild.id].setdefault('questreport_dict', {})
    if message.id in questreport_dict and user.id != Kyogre.user.id:
        quest_dict = questreport_dict.get(message.id, None)        
        if quest_dict and (quest_dict['reportauthor'] == payload.user_id or can_manage(user)):
            if str(payload.emoji) == '\u270f':
                researchcommands_cog = Kyogre.cogs.get('ResearchCommands')
                await researchcommands_cog.modify_research_report(payload)
            elif str(payload.emoji) == '🚫':
                try:
                    await message.edit(embed=discord.Embed(description="Research report cancelled",
                                                           colour=message.embeds[0].colour.value))
                    await message.clear_reactions()
                except discord.errors.NotFound:
                    pass
                del questreport_dict[message.id]
                await _refresh_listing_channels_internal(guild, "research")
            await message.remove_reaction(payload.emoji, user)
    raid_dict = guild_dict[guild.id].setdefault('raidchannel_dict', {})
    if channel.id in raid_dict:
        raid_report = channel.id
    else:
        raid_report = get_raid_report(guild, message.id)
    if raid_report is not None and user.id != Kyogre.user.id:
        if raid_dict[raid_report].get('reporter', 0) == payload.user_id or can_manage(user):
            try:
                await message.remove_reaction(payload.emoji, user)
            except:
                pass
            if str(payload.emoji) == '\u270f':
                await modify_raid_report(payload, raid_report)
            elif str(payload.emoji) == '🚫':
                try:
                    await message.edit(embed=discord.Embed(description="Raid report cancelled",
                                                           colour=message.embeds[0].colour.value))
                    await message.clear_reactions()
                except discord.errors.NotFound:
                    pass
                report_channel = Kyogre.get_channel(raid_report)
                await report_channel.delete()
                try:
                    del raid_dict[raid_report]
                except:
                    pass
                await _refresh_listing_channels_internal(guild, "raid")
    pvp_dict = guild_dict[guild.id].setdefault('pvp_dict', {})
    if message.id in pvp_dict and user.id != Kyogre.user.id:
        trainer = pvp_dict[message.id]['reportauthor']
        if trainer == payload.user_id or can_manage(user):
            if str(payload.emoji) == '🚫':
                pvp_cog = Kyogre.cogs.get('PvP')
                if not pvp_cog:
                    return None
                return await pvp_cog.expire_pvp(message)
        if str(payload.emoji) == '\u2694':
            attacker = guild.get_member(payload.user_id)
            defender = guild.get_member(pvp_dict[message.id]['reportauthor'])
            if attacker == defender:
                return
            battle_msg = await channel.send(content=f"{defender.mention} you have been challenged "
                                                    f"by {attacker.mention}!",
                                            embed=discord.Embed(colour=discord.Colour.red(),
                                            description=f"{defender.mention} you have been challenged "
                                                        f"by {attacker.mention}!"),
                                            delete_after=30)
            await battle_msg.edit(content="")
    raid_notice_dict = guild_dict[guild.id].setdefault('raid_notice_dict', {})
    if message.id in raid_notice_dict and user.id != Kyogre.user.id:
        trainer = raid_notice_dict[message.id]['reportauthor']
        if trainer == payload.user_id or can_manage(user):
            if str(payload.emoji) == '🚫':
                return await expire_raid_notice(message)
            if str(payload.emoji) == '\u23f2':
                exp = raid_notice_dict[message.id]['exp'] + 1800
                raid_notice_dict[message.id]['exp'] = exp
                expire = datetime.datetime.fromtimestamp(exp)
                expire_str = expire.strftime('%b %d %I:%M %p')
                embed = message.embeds[0]
                index = 0
                found = False
                for field in embed.fields:
                    if "expire" in field.name.lower():
                        found = True
                        break
                    index += 1
                if found:
                    embed.set_field_at(index, name=embed.fields[index].name, value=expire_str, inline=True)
                else:
                    embed.add_field(name='**Expires:**', value='{end}'.format(end=expire_str), inline=True)
                await message.edit(embed=embed)
                await message.remove_reaction(payload.emoji, user)
    if user.id != Kyogre.user.id:
        for i,d in Kyogre.active_invasions.items():
            if d["message"].id == message.id:
                if d["author"] == payload.user_id or can_manage(user):
                    invasions_cog = Kyogre.cogs.get('Invasions')
                    if str(payload.emoji) == '💨':
                        await invasions_cog.expire_invasion(i)
                        break
                    elif str(payload.emoji) in ['🇵', '\u270f']:
                        await invasions_cog.modify_report(payload)


def get_raid_report(guild, message_id):
    raid_dict = guild_dict[guild.id]['raidchannel_dict']
    for raid in raid_dict:
        if raid_dict[raid]['raidreport'] == message_id:
            return raid
        if 'raidcityreport' in raid_dict[raid]:
            if raid_dict[raid]['raidcityreport'] == message_id:
                return raid
    return None


def can_manage(user):
    if checks.is_user_dev_or_owner(config, user.id):
        return True
    for role in user.roles:
        if role.permissions.manage_messages:
            return True
    return False


async def modify_raid_report(payload, raid_report):
    channel = Kyogre.get_channel(payload.channel_id)
    try:
        message = await channel.fetch_message(payload.message_id)
    except (discord.errors.NotFound, AttributeError):
        return
    guild = message.guild
    try:
        user = guild.get_member(payload.user_id)
    except AttributeError:
        return
    raids_cog = Kyogre.cogs.get('RaidCommands')
    raid_dict = guild_dict[guild.id].setdefault('raidchannel_dict', {})
    config_dict = guild_dict[guild.id]['configure_dict']
    regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
    raid_channel = channel.id
    if channel.id not in guild_dict[guild.id]['raidchannel_dict']:
        for rchannel in guild_dict[guild.id]['raidchannel_dict']:
            if raid_dict[rchannel]['raidreport'] == message.id:
                raid_channel = rchannel
                break
    raid_channel = Kyogre.get_channel(raid_report)
    raid_report = raid_dict[raid_channel.id]
    report_channel_id = raid_report['reportchannel']
    report_channel = Kyogre.get_channel(report_channel_id)
    gyms = None
    gyms = get_gyms(guild.id, regions)
    choices_list = ['Location', 'Hatch / Expire Time', 'Boss / Tier']
    gym = raid_report["address"]
    prompt = f'Modifying details for **raid** at **{gym}**\n' \
        f'Which item would you like to modify ***{user.display_name}***?'
    match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=user.id)
    err_msg = None
    success_msg = None
    if match in choices_list:
        # Updating location
        if match == choices_list[0]:
            query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                               description="What is the correct Location?"))
            try:
                gymmsg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                await query_msg.delete()
                gymmsg = None
            if not gymmsg:
                error = "took too long to respond"
            elif gymmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await gymmsg.delete()
            elif gymmsg:
                if gyms:
                    gym = await location_match_prompt(channel, user.id, gymmsg.clean_content, gyms)
                    if not gym:
                        await channel.send(
                            embed=discord.Embed(
                                colour=discord.Colour.red(),
                                description=f"I couldn't find a gym named '{gymmsg.clean_content}'. "
                                f"Try again using the exact gym name!"))
                        Kyogre.help_logger.info(f"User: {user.name}, channel: {channel}, error: Couldn't find gym with name: {gymmsg.clean_content}")
                    else:
                        location = gym.name
                        raid_channel_ids = raids_cog.get_existing_raid(guild, gym)
                        if raid_channel_ids:
                            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
                            if guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]:
                                await channel.send(
                                    embed=discord.Embed(
                                        colour=discord.Colour.red(),
                                        description=f"A raid has already been reported for {gym.name}"))
                                Kyogre.help_logger.info(f"User: {user.name}, channel: {channel}, error: Raid already reported.")
                        else:
                            await entity_updates.update_raid_location(Kyogre, guild_dict, message,
                                                                      report_channel, raid_channel, gym)
                            await _refresh_listing_channels_internal(guild, "raid")
                            await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                   description="Raid location updated"))
                            await gymmsg.delete()
                            await query_msg.delete()

        # Updating time
        elif match == choices_list[1]:
            timewait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                              description="What is the Hatch / Expire time?"))
            try:
                timemsg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                timemsg = None
                await timewait.delete()
            if not timemsg:
                error = "took too long to respond"
            elif timemsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await timemsg.delete()
            raidexp = await utils.time_to_minute_count(guild_dict, raid_channel, timemsg.clean_content)
            if raidexp is not False:
                await raids_cog._timerset(raid_channel, raidexp)
            await _refresh_listing_channels_internal(guild, "raid")
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                 description="Raid hatch / expire time updated"))
            await timewait.delete()
            await timemsg.delete()
        # Updating boss
        elif match == choices_list[2]:
            bosswait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                              description="What is the Raid Tier / Boss?"))
            try:
                bossmsg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                bossmsg = None
                await bosswait.delete()
            if not bossmsg:
                error = "took too long to respond"
            elif bossmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await bossmsg.delete()
            await raids_cog.changeraid_internal(None, guild, raid_channel, bossmsg.clean_content)
            if not bossmsg.clean_content.isdigit():
                await raids_cog._timerset(raid_channel, 45)
            await _refresh_listing_channels_internal(guild, "raid")
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                 description="Raid Tier / Boss updated"))
            await bosswait.delete()
            await bossmsg.delete()
    else:
        return


## TODO: UPDATE THIS:
"""
'configure_dict':{
            'welcome': {'enabled':False,'welcomechan':'','welcomemsg':''},
            'want': {'enabled':False, 'report_channels': []},
            'raid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}},
            'exraid': {'enabled':False, 'report_channels': {}, 'categories':'same','category_dict':{}, 'permissions':'everyone'},
            'counters': {'enabled':False, 'auto_levels': []},
            'wild': {'enabled':False, 'report_channels': {}},
            'research': {'enabled':False, 'report_channels': {}},
            'archive': {'enabled':False, 'category':'same','list':None},
            'invite': {'enabled':False},
            'team':{'enabled':False},
            'settings':{'offset':0,'regional':None,'done':False,'prefix':None,'config_sessions':{}}
        },
        'wildreport_dict:':{},
        'questreport_dict':{},
        'raidchannel_dict':{},
        'trainers':{}
"""

@Kyogre.command(name="raidavailable", aliases=["rav"], brief="Report that you're actively looking for raids")
async def _raid_available(ctx, exptime=None):
    """**Usage**: `!raidavailable/rav [time]`
    Assigns a tag-able role (such as @renton-raids) to you so that others looking for raids can ask for help.
    Tag will remain for 60 minutes by default or for the amount of time you provide. Provide '0' minutes to keep it in effect indefinitely."""
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author
    regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
    if len(regions) > 0:
        region = regions[0]
    role_to_assign = discord.utils.get(guild.roles, name=region + '-raids')
    for role in trainer.roles:
        if role.name == role_to_assign.name:
            raid_notice_dict = copy.deepcopy(guild_dict[guild.id].get('raid_notice_dict',{}))
            for rnmessage in raid_notice_dict:
                try:
                    if raid_notice_dict[rnmessage]['reportauthor'] == trainer.id:
                        rnmessage = await channel.fetch_message(rnmessage)
                        await expire_raid_notice(rnmessage)
                        await message.delete()
                except:
                    pass
            role_to_remove = discord.utils.get(guild.roles, name=role_to_assign)
            try:
                await trainer.remove_roles(*[role_to_remove],
                                           reason="Raid availability expired or was cancelled by user.")
            except:
                pass
            return
    expiration_minutes = False
    time_err = "Unable to determine the time you provided, you will be notified for raids for the next 60 minutes"
    if exptime:
        if exptime.isdigit():
            if int(exptime) == 0:
                expiration_minutes = 2628000
            else:
                expiration_minutes = await utils.time_to_minute_count(guild_dict, channel, exptime, time_err)
    else:
        time_err = "No expiration time provided, you will be notified for raids for the next 60 minutes"
    if expiration_minutes is False:
        time_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=time_err), delete_after=10)
        expiration_minutes = 60

    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    expire = now + datetime.timedelta(minutes=expiration_minutes)

    raid_notice_embed = discord.Embed(title='{trainer} is available for Raids!'
                                      .format(trainer=trainer.display_name), colour=guild.me.colour)
    if exptime != "0":
        raid_notice_embed.add_field(name='**Expires:**', value='{end}'
                                    .format(end=expire.strftime('%b %d %I:%M %p')), inline=True)
    raid_notice_embed.add_field(name='**To add 30 minutes:**', value='Use the ⏲️ react.', inline=True)
    raid_notice_embed.add_field(name='**To cancel:**', value='Use the 🚫 react.', inline=True)

    if region is not None:
        footer_text = f"Use the **@{region}-raids** tag to notify all trainers who are currently available"
        raid_notice_embed.set_footer(text=footer_text)
    raid_notice_msg = await channel.send(content='{trainer} is available for Raids!'
                                         .format(trainer=trainer.display_name), embed=raid_notice_embed)
    await raid_notice_msg.add_reaction('\u23f2')
    await raid_notice_msg.add_reaction('🚫')
    expiremsg = '**{trainer} is no longer available for Raids!**'.format(trainer=trainer.display_name)
    raid_notice_dict = copy.deepcopy(guild_dict[guild.id].get('raid_notice_dict', {}))
    raid_notice_dict[raid_notice_msg.id] = {
        'exp':time.time() + (expiration_minutes * 60),
        'expedit': {"content": "", "embedcontent": expiremsg},
        'reportmessage': message.id,
        'reportchannel': channel.id,
        'reportauthor': trainer.id,
    }
    guild_dict[guild.id]['raid_notice_dict'] = raid_notice_dict
    event_loop.create_task(raid_notice_expiry_check(raid_notice_msg))
    
    await trainer.add_roles(*[role_to_assign], reason="User announced raid availability.")
    await message.delete()

"""
Data Management Commands
"""
@Kyogre.command(name="refresh_listings", hidden=True)
@commands.has_permissions(manage_guild=True)
async def _refresh_listing_channels(ctx, list_type, *, regions=None):
    if regions:
        regions = [r.strip() for r in regions.split(',')]
    await list_helpers.update_listing_channels(Kyogre, ctx.guild, list_type, edit=True, regions=regions)
    await ctx.message.add_reaction('\u2705')


async def _refresh_listing_channels_internal(guild, list_type, *, regions=None):
    if regions:
        regions = [r.strip() for r in regions.split(',')]
    await list_helpers.update_listing_channels(Kyogre, guild, list_type, edit=True, regions=regions)


"""
Status Management
"""


"""
List Commands
"""
@Kyogre.group(name="list", aliases=['lists'], case_insensitive=True)
async def _list(ctx):
    if ctx.invoked_subcommand is None:
        listmsg = ""
        guild = ctx.guild
        channel = ctx.channel
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
        if checks.check_raidreport(ctx) or checks.check_exraidreport(ctx):
            raid_dict = guild_dict[guild.id]['configure_dict']['raid']
            if raid_dict.get('listings', {}).get('enabled', False):
                msg = await ctx.channel.send("*Raid list command disabled when listings are provided by server*")
                await asyncio.sleep(10)
                await msg.delete()
                await ctx.message.delete()
                return
            region = None
            if guild_dict[guild.id]['configure_dict'].get('regions', {}).get('enabled', False) \
                    and raid_dict.get('categories', None) == 'region':
                region = raid_dict.get('category_dict', {}).get(channel.id, None)
            listmsg = await list_helpers._get_listing_messages(Kyogre, guild_dict, 'raid', channel, region)
        elif checks.check_raidactive(ctx):
            newembed = discord.Embed(colour=discord.Colour.purple(), title="Trainer Status List")
            blue_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['mystic'])
            red_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['valor'])
            yellow_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['instinct'])
            team_emojis = {'instinct': yellow_emoji, 'mystic': blue_emoji, 'valor': red_emoji, 'unknown': "❔"}
            team_list = ["mystic", "valor", "instinct", "unknown"]
            status_list = ["maybe", "coming", "here"]
            trainer_dict = copy.deepcopy(guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
            status_dict = {'maybe': {'total': 0, 'trainers': {}}, 'coming': {'total': 0, 'trainers': {}},
                           'here': {'total': 0, 'trainers': {}}, 'lobby': {'total': 0, 'trainers': {}}}
            for trainer in trainer_dict:
                for status in status_list:
                    if trainer_dict[trainer]['status'][status]:
                        status_dict[status]['trainers'][trainer] = {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
                        for team in team_list:
                            if trainer_dict[trainer]['party'][team] > 0:
                                status_dict[status]['trainers'][trainer][team] = trainer_dict[trainer]['party'][team]
                                status_dict[status]['total'] += trainer_dict[trainer]['party'][team]
            for status in status_list:
                embed_value = None
                if status_dict[status]['total'] > 0:
                    embed_value = u"\u200B"
                    for trainer in status_dict[status]['trainers']:
                        member = channel.guild.get_member(trainer)
                        if member is not None:
                            embed_value += f"{member.display_name} "
                            for team in status_dict[status]['trainers'][trainer]:
                                embed_value += team_emojis[team] * status_dict[status]['trainers'][trainer][team]
                            embed_value += "\n"
                if embed_value is not None:
                    newembed.add_field(name=f'**{status.capitalize()}**', value=embed_value, inline=True)
            if len(newembed.fields) < 1:
                newembed.description = "No one has RSVPd for this raid yet."
            await channel.send(embed=newembed)
        else:
            raise checks.errors.CityRaidChannelCheckFail()


@_list.command()
@checks.activechannel()
async def interested(ctx, tags: str = ''):
    """Lists the number and users who are interested in the raid.

    Usage: !list interested
    Works only in raid channels."""
    if tags and tags.lower() == "tags" or tags.lower() == "tag":
        tags = True
    listmsg = await list_helpers._interest(ctx, Kyogre, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def coming(ctx, tags: str = ''):
    """Lists the number and users who are coming to a raid.

    Usage: !list coming
    Works only in raid channels."""
    if tags and tags.lower() == "tags" or tags.lower() == "tag":
        tags = True
    listmsg = await list_helpers._otw(ctx, Kyogre, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def here(ctx, tags: str = ''):
    """List the number and users who are present at a raid.

    Usage: !list here
    Works only in raid channels."""
    if tags and tags.lower() == "tags" or tags.lower() == "tag":
        tags = True
    listmsg = await list_helpers._waiting(ctx, Kyogre, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activeraidchannel()
async def lobby(ctx, tag=False):
    """List the number and users who are in the raid lobby.

    Usage: !list lobby
    Works only in raid channels."""
    listmsg = await list_helpers._lobbylist(ctx, Kyogre)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activeraidchannel()
async def bosses(ctx):
    """List each possible boss and the number of users that have RSVP'd for it.

    Usage: !list bosses
    Works only in raid channels."""
    listmsg = await list_helpers._bosslist(ctx, Kyogre)
    if len(listmsg) > 0:
        await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def teams(ctx):
    """List the teams for the users that have RSVP'd to a raid.

    Usage: !list teams
    Works only in raid channels."""
    listmsg = await list_helpers.teamlist(ctx, Kyogre)
    await ctx.channel.send(listmsg)


def print_emoji_name(guild, emoji_string):
    # By default, just print the emoji_string
    ret = ('`' + emoji_string) + '`'
    emoji = utils.parse_emoji(guild, emoji_string)
    # If the string was transformed by the parse_emoji
    # call, then it really was an emoji and we should
    # add the raw string so people know what to write.
    if emoji != emoji_string:
        ret = ((emoji + ' (`') + emoji_string) + '`)'
    return ret


try:
    event_loop.run_until_complete(Kyogre.start(config['bot_token']))
except discord.LoginFailure:
    logger.critical('Invalid token')
    event_loop.run_until_complete(Kyogre.logout())
    Kyogre._shutdown_mode = 0
except KeyboardInterrupt:
    logger.info('Keyboard interrupt detected. Quitting...')
    event_loop.run_until_complete(Kyogre.logout())
    Kyogre._shutdown_mode = 0
except Exception as e:
    logger.critical('Fatal exception', exc_info=e)
    event_loop.run_until_complete(Kyogre.logout())
finally:
    pass
try:
    sys.exit(Kyogre._shutdown_mode)
except AttributeError:
    sys.exit(0)
