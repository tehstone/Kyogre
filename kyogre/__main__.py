import asyncio
import copy
import datetime
import errno
import gettext
import io
import os
import pickle
import sys
import tempfile
import textwrap
import time
import traceback

from contextlib import redirect_stdout

import aiohttp
import dateparser
from dateutil.relativedelta import relativedelta

import discord
from discord.ext import commands

from kyogre import checks, configuration, constants, counters_helpers, embed_utils
from kyogre import entity_updates, list_helpers, raid_helpers, raid_lobby_helpers, utils
from kyogre.bot import KyogreBot
from kyogre.errors import custom_error_handling
from kyogre.logs import init_loggers
from kyogre.exts.pokemon import Pokemon
from kyogre.exts.bosscp import boss_cp_chart
from kyogre.exts.locationmatching import Gym

from kyogre.exts.db.kyogredb import *
KyogreDB.start('data/kyogre.db')

logger = init_loggers()
_ = gettext.gettext


def _get_prefix(bot, message):
    guild = message.guild
    try:
        prefix = bot.guild_dict[guild.id]['configure_dict']['settings']['prefix']
    except (KeyError, AttributeError):
        prefix = None
    if not prefix:
        prefix = bot.config['default_prefix']
    return commands.when_mentioned_or(prefix)(bot, message)


Kyogre = KyogreBot(
    command_prefix=_get_prefix, case_insensitive=True,
    activity=discord.Game(name="Pokemon Go"))

custom_error_handling(Kyogre, logger)


class RenameUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        module = module.replace("meowth", "kyogre")
        return super().find_class(module, name)


def _load_data(bot):
    try:
        with open(os.path.join('data', 'serverdict'), 'rb') as fd:
            bot.guild_dict = RenameUnpickler(fd).load()
        logger.info('Serverdict Loaded Successfully')
    except OSError:
        logger.info('Serverdict Not Found - Looking for Backup')
        try:
            with open(os.path.join('data', 'serverdict_backup'), 'rb') as fd:
                bot.guild_dict = RenameUnpickler(fd).load()
            logger.info('Serverdict Backup Loaded Successfully')
        except OSError:
            logger.info('Serverdict Backup Not Found - Creating New Serverdict')
            bot.guild_dict = {}
            with open(os.path.join('data', 'serverdict'), 'wb') as fd:
                pickle.dump(bot.guild_dict, fd, -1)
            logger.info('Serverdict Created')


_load_data(Kyogre)

guild_dict = Kyogre.guild_dict

config = {}
defense_chart = {}
type_list = []
raid_info = {}

active_raids = []
active_wilds = []
active_pvp = []
active_lures = []


"""
Helper functions
"""
def load_config():
    global config
    global defense_chart
    global type_list
    global raid_info
    # Load configuration
    with open('config.json', 'r') as fd:
        config = json.load(fd)
    # Set up message catalog access
    # Load raid info
    raid_path_source = os.path.join('data', 'raid_info.json')
    with open(raid_path_source, 'r') as fd:
        raid_info = json.load(fd)
    # Load type information
    with open(os.path.join('data', 'defense_chart.json'), 'r') as fd:
        defense_chart = json.load(fd)
    with open(os.path.join('data', 'type_list.json'), 'r') as fd:
        type_list = json.load(fd)
    return raid_path_source


raid_path = load_config()

Kyogre.raid_info = raid_info
Kyogre.type_list = type_list
Kyogre.defense_chart = defense_chart

Kyogre.config = config
Kyogre.raid_json_path = raid_path

default_exts = ['raiddatahandler', 'tutorial', 'silph', 'utilities', 'pokemon', 'trade', 'locationmatching']

for ext in default_exts:
    try:
        Kyogre.load_extension(f"kyogre.exts.{ext}")
    except Exception as e:
        print(f'**Error when loading extension {ext}:**\n{type(e).__name__}: {e}')
    else:
        if 'debug' in sys.argv[1:]:
            print(f'Loaded {ext} extension.')


@Kyogre.command(name='load')
@checks.is_owner()
async def _load(ctx, *extensions):
    for ext in extensions:
        try:
            ctx.bot.unload_extension(f"kyogre.exts.{ext}")
            ctx.bot.load_extension(f"kyogre.exts.{ext}")
        except Exception as e:
            error_title = '**Error when loading extension'
            await ctx.send(f'{error_title} {ext}:**\n'
                           f'{type(e).__name__}: {e}')
        else:
            await ctx.send('**Extension {ext} Loaded.**\n'.format(ext=ext))


@Kyogre.command(name='unload')
@checks.is_owner()
async def _unload(ctx, *extensions):
    exts = [ex for ex in extensions if f"exts.{ex}" in Kyogre.extensions]
    for ex in exts:
        ctx.bot.unload_extension(f"exts.{ex}")
    s = 's' if len(exts) > 1 else ''
    await ctx.send("**Extension{plural} {est} unloaded.**\n".format(plural=s, est=', '.join(exts)))


def get_raidlist():
    raidlist = []
    for level in raid_info['raid_eggs']:
        for entry in raid_info['raid_eggs'][level]['pokemon']:
            pokemon = Pokemon.get_pokemon(Kyogre, entry)
            raidlist.append(pokemon.id)
            raidlist.append(str(pokemon).lower())
    return raidlist


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


def create_gmaps_query(details, channel, type="raid"):
    """Given an arbitrary string, create a Google Maps
    query using the configured hints"""
    if type == "raid" or type == "egg":
        report = "raid"
    else:
        report = type
    if "/maps" in details and "http" in details:
        mapsindex = details.find('/maps')
        newlocindex = details.rfind('http', 0, mapsindex)
        if newlocindex == -1:
            return
        newlocend = details.find(' ', newlocindex)
        if newlocend == -1:
            newloc = details[newlocindex:]
            return newloc
        else:
            newloc = details[newlocindex:newlocend + 1]
            return newloc
    details_list = details.split()
    # look for lat/long coordinates in the location details. If provided,
    # then channel location hints are not needed in the  maps query
    if re.match (r'^\s*-?\d{1,2}\.?\d*,\s*-?\d{1,3}\.?\d*\s*$', details): #regex looks for lat/long in the format similar to 42.434546, -83.985195.
        return "https://www.google.com/maps/search/?api=1&query={0}".format('+'.join(details_list))
    loc_list = guild_dict[channel.guild.id]['configure_dict'][report]['report_channels'][channel.id].split()
    return 'https://www.google.com/maps/search/?api=1&query={0}+{1}'.format('+'.join(details_list), '+'.join(loc_list))  


@Kyogre.command(name='gym')
async def _gym(ctx, *, name):
    """Lookup locations to a gym by providing it's name.
    Gym name provided should be as close as possible to
    the name displayed in game."""
    message = ctx.message
    channel = ctx.channel
    guild = ctx.guild
    gyms = get_gyms(guild.id)
    gym = await location_match_prompt(channel, message.author.id, name, gyms)
    if not gym:
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No gym found with name '{name}'. Try again using the exact gym name!"))
    else:
        gym_embed = discord.Embed(title='Click here for directions to {0}!'.format(gym.name), url=gym.maps_url, colour=guild.me.colour)
        gym_info = "**Name:** {name}\n**Region:** {region}\n**Notes:** {notes}".format(name=gym.name, notes="_EX Eligible Gym_" if gym.ex_eligible else "N/A", region=gym.region.title())
        gym_embed.add_field(name='**Gym Information**', value=gym_info, inline=False)
        return await channel.send(content="", embed=gym_embed)


def get_gyms(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    gyms = location_matching_cog.get_gyms(guild_id, regions)
    return gyms


def get_stops(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    stops = location_matching_cog.get_stops(guild_id, regions)
    return stops


def get_all_locations(guild_id, regions=None):
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        return None
    stops = location_matching_cog.get_all(guild_id, regions)
    return stops


async def location_match_prompt(channel, author_id, name, locations):
    # note: the following logic assumes json constraints -- no duplicates in source data
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    result = location_matching_cog.location_match(name, locations)
    results = [(match.name, score) for match, score in result]
    match = await prompt_match_result(channel, author_id, name, results)
    return next((l for l in locations if l.name == match), None)


async def prompt_match_result(channel, author_id, target, result_list):
    if not isinstance(result_list, list):
        result_list = [result_list]
    if not result_list or result_list[0] is None or result_list[0][0] is None:
        return None
    # quick check if a full match exists
    exact_match = [match for match, score in result_list if match.lower() == target.lower()]
    if len(exact_match) == 1:
        return exact_match[0]
    # reminder: partial, exact matches have 100 score, that's why this check exists
    perfect_scores = [match for match, score in result_list if score == 100]
    if len(perfect_scores) != 1:
        # one or more imperfect candidates only, ask user which to use
        sorted_result = sorted(result_list, key=lambda t: t[1], reverse=True)
        choices_list = [match for match, score in sorted_result]
        prompt = "Didn't find an exact match for '{0}'. {1} potential matches found.".format(target, len(result_list))
        match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=author_id)
    else:
        # found a solitary best match
        match = perfect_scores[0]
    return match


def get_category(channel, level, category_type="raid"):
    guild = channel.guild
    if category_type == "raid" or category_type == "egg":
        report = "raid"
    else:
        report = category_type
    catsort = guild_dict[guild.id]['configure_dict'][report].get('categories', None)
    if catsort == "same":
        return channel.category
    elif catsort == "region":
        category = discord.utils.get(guild.categories,id=guild_dict[guild.id]['configure_dict'][report]['category_dict'][channel.id])
        return category
    elif catsort == "level":
        category = discord.utils.get(guild.categories,id=guild_dict[guild.id]['configure_dict'][report]['category_dict'][level])
        return category
    else:
        return None


async def create_raid_channel(raid_type, pkmn, level, gym, report_channel):
    guild = report_channel.guild
    cat = None
    if raid_type == "exraid":
        name = "ex-raid-egg-"
        raid_channel_overwrite_dict = report_channel.overwrites
        # If and when ex reporting is revisited this will need a complete rewrite. Overwrites went from Tuple -> Dict
        # if guild_dict[guild.id]['configure_dict']['invite']['enabled']:
        #     if guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone":
        #         everyone_overwrite = (guild.default_role, discord.PermissionOverwrite(send_messages=False))
        #         raid_channel_overwrite_list.append(everyone_overwrite)
        #     for overwrite in raid_channel_overwrite_dict:
        #         if isinstance(overwrite[0], discord.Role):
        #             if overwrite[0].permissions.manage_guild or
        #             #overwrite[0].permissions.manage_channels or overwrite[0].permissions.manage_messages:
        #                 continue
        #             overwrite[1].send_messages = False
        #         elif isinstance(overwrite[0], discord.Member):
        #             if report_channel.permissions_for(overwrite[0]).manage_guild or
        #             report_channel.permissions_for(overwrite[0]).manage_channels or
        #             report_channel.permissions_for(overwrite[0]).manage_messages:
        #                 continue
        #             overwrite[1].send_messages = False
        #         if (overwrite[0].name not in guild.me.top_role.name) and (overwrite[0].name not in guild.me.name):
        #             overwrite[1].send_messages = False
        #     for role in guild.role_hierarchy:
        #         if role.permissions.manage_guild or role.permissions.manage_channels
        #         or role.permissions.manage_messages:
        #             raid_channel_overwrite_dict.update({role: discord.PermissionOverwrite(send_messages=True)})
        # else:
        if guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone":
            everyone_overwrite = {guild.default_role: discord.PermissionOverwrite(send_messages=True)}
            raid_channel_overwrite_dict.update(everyone_overwrite)
        cat = get_category(report_channel, "EX", category_type=raid_type)
    else:
        reporting_channels = await list_helpers.get_region_reporting_channels(guild, gym.region, guild_dict)
        report_channel = guild.get_channel(reporting_channels[0])
        raid_channel_overwrite_dict = report_channel.overwrites
        if raid_type == "raid":
            name = pkmn.name.lower() + "_"
            cat = get_category(report_channel, str(pkmn.raid_level), category_type=raid_type)
        elif raid_type == "egg":
            name = "{level}-egg_".format(level=str(level))
            cat = get_category(report_channel, str(level), category_type=raid_type)
    kyogre_overwrite = {Kyogre.user: discord.PermissionOverwrite(send_messages=True, read_messages=True, manage_roles=True, manage_channels=True, manage_messages=True, add_reactions=True, external_emojis=True, read_message_history=True, embed_links=True, mention_everyone=True, attach_files=True)}
    raid_channel_overwrite_dict.update(kyogre_overwrite)
    enabled = raid_helpers.raid_channels_enabled(guild, report_channel, guild_dict)
    if not enabled:
        user_overwrite = {guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=False, read_message_history=False)}
        raid_channel_overwrite_dict.update(user_overwrite)
        role = discord.utils.get(guild.roles, name=gym.region)
        if role is not None:
            role_overwrite = {role: discord.PermissionOverwrite(send_messages=False, read_messages=False, read_message_history=False)}
            raid_channel_overwrite_dict.update(role_overwrite)
    name = utils.sanitize_name(name+gym.name)
    return await guild.create_text_channel(name, overwrites=raid_channel_overwrite_dict, category=cat)


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
async def pvp_expiry_check(message):
    logger.info('Expiry_Check - ' + message.channel.name)
    channel = message.channel
    guild = channel.guild
    global active_pvp
    message = await channel.fetch_message(message.id)
    if message not in active_pvp:
        active_pvp.append(message)
        logger.info('pvp_expiry_check - Message added to watchlist - ' + channel.name)
        await asyncio.sleep(0.5)
        while True:
            try:
                if guild_dict[guild.id]['pvp_dict'][message.id]['exp'] <= time.time():
                    await expire_pvp(message)
            except KeyError:
                pass
            await asyncio.sleep(30)
            continue


async def expire_pvp(message):
    channel = message.channel
    guild = channel.guild
    pvp_dict = guild_dict[guild.id]['pvp_dict']
    try:
        await message.edit(content=pvp_dict[message.id]['expedit']['content'],
                           embed=discord.Embed(description=pvp_dict[message.id]['expedit']['embedcontent'],
                                               colour=message.embeds[0].colour.value))
        await message.clear_reactions()
    except discord.errors.NotFound:
        pass
    try:
        user_message = await channel.fetch_message(pvp_dict[message.id]['reportmessage'])
        await user_message.delete()
    except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
        pass
    del guild_dict[guild.id]['pvp_dict'][message.id]


async def raid_notice_expiry_check(message):
    logger.info('Expiry_Check - ' + message.channel.name)
    channel = message.channel
    guild = channel.guild
    global active_pvp
    message = await channel.fetch_message(message.id)
    if message not in active_pvp:
        active_pvp.append(message)
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

async def lure_expiry_check(message, lure_id):
    logger.info('Expiry_Check - ' + message.channel.name)
    channel = message.channel
    global active_lures
    message = await message.channel.fetch_message(message.id)
    offset = guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
    expire_time = datetime.datetime.utcnow() + datetime.timedelta(hours=offset) + datetime.timedelta(minutes=30)
    if message not in active_lures:
        active_lures.append(message)
        logger.info(
        'lure_expiry_check - Message added to watchlist - ' + message.channel.name
        )
        await asyncio.sleep(0.5)
        while True:
            if expire_time.timestamp() <= (datetime.datetime.utcnow() + datetime.timedelta(hours=offset)).timestamp():
                await expire_lure(message)
            await asyncio.sleep(30)
            continue

async def expire_lure(message):
    channel = message.channel
    guild = channel.guild
    try:
        await message.edit(content="", embed=discord.Embed(description="This lure has expired"))
        await message.clear_reactions();
    except discord.errors.NotFound:
        pass

async def wild_expiry_check(message):
    logger.info('Expiry_Check - ' + message.channel.name)
    guild = message.channel.guild
    global active_wilds
    message = await message.channel.fetch_message(message.id)
    if message not in active_wilds:
        active_wilds.append(message)
        logger.info(
        'wild_expiry_check - Message added to watchlist - ' + message.channel.name
        )
        await asyncio.sleep(0.5)
        while True:
            try:
                if guild_dict[guild.id]['wildreport_dict'][message.id]['exp'] <= time.time():
                    await expire_wild(message)
            except KeyError:
                pass
            await asyncio.sleep(30)
            continue

async def expire_wild(message):
    channel = message.channel
    guild = channel.guild
    wild_dict = guild_dict[guild.id]['wildreport_dict']
    try:
        await message.edit(embed=discord.Embed(description=wild_dict[message.id]['expedit']['embedcontent'], colour=message.embeds[0].colour.value))
        await message.clear_reactions()
    except discord.errors.NotFound:
        pass
    try:
        user_message = await channel.fetch_message(wild_dict[message.id]['reportmessage'])
        await user_message.delete()
    except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
        pass
    del guild_dict[guild.id]['wildreport_dict'][message.id]
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'wild', edit=True, regions=raid_helpers.get_channel_regions(channel, 'wild', guild_dict))

async def expiry_check(channel):
    logger.info('Expiry_Check - ' + channel.name)
    guild = channel.guild
    global active_raids
    channel = Kyogre.get_channel(channel.id)
    if channel not in active_raids:
        active_raids.append(channel)
        logger.info(
            'Expire_Channel - Channel Added To Watchlist - ' + channel.name)
        await asyncio.sleep(0.5)
        while True:
            try:
                if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',{}):
                    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
                    start = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('start',False)
                    end = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('end',False)
                    if start and guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
                        if start < now:
                            pokemon = raid_info['raid_eggs']['EX']['pokemon'][0]
                            await _eggtoraid(None, pokemon.lower(), channel, author=None)
                    if end and end < now:
                        event_loop.create_task(expire_channel(channel))
                        try:
                            active_raids.remove(channel)
                        except ValueError:
                            logger.info(
                                'Expire_Channel - Channel Removal From Active Raid Failed - Not in List - ' + channel.name)
                        logger.info(
                            'Expire_Channel - Channel Expired And Removed From Watchlist - ' + channel.name)
                        break
                elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                    if guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp']:
                        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] <= time.time():
                            if guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
                                pokemon = guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon']
                                egglevel = guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel']
                                if not pokemon and len(raid_info['raid_eggs'][egglevel]['pokemon']) == 1:
                                    pokemon = raid_info['raid_eggs'][egglevel]['pokemon'][0]
                                elif not pokemon and egglevel == "5" and guild_dict[channel.guild.id]['configure_dict']['settings'].get('regional','').lower() in raid_info['raid_eggs']["5"]['pokemon']:
                                    pokemon = str(Pokemon.get_pokemon(Kyogre, guild_dict[channel.guild.id]['configure_dict']['settings']['regional']))
                                if pokemon:
                                    logger.info(
                                        'Expire_Channel - Egg Auto Hatched - ' + channel.name)
                                    try:
                                        active_raids.remove(channel)
                                    except ValueError:
                                        logger.info(
                                            'Expire_Channel - Channel Removal From Active Raid Failed - Not in List - ' + channel.name)
                                    await _eggtoraid(None, pokemon.lower(), channel, author=None)
                                    break
                            event_loop.create_task(expire_channel(channel))
                            try:
                                active_raids.remove(channel)
                            except ValueError:
                                logger.info(
                                    'Expire_Channel - Channel Removal From Active Raid Failed - Not in List - ' + channel.name)
                            logger.info(
                                'Expire_Channel - Channel Expired And Removed From Watchlist - ' + channel.name)
                            break
            except:
                pass
            await asyncio.sleep(30)
            continue


async def expire_channel(channel):
    guild = channel.guild
    alreadyexpired = False
    logger.info('Expire_Channel - ' + channel.name)
    # If the channel exists, get ready to delete it.
    # Otherwise, just clean up the dict since someone
    # else deleted the actual channel at some point.
    channel_exists = Kyogre.get_channel(channel.id)
    channel = channel_exists
    if (channel_exists == None) and (not Kyogre.is_closed()):
        try:
            del guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]
        except KeyError:
            pass
        return
    elif (channel_exists):
        dupechannel = False
        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['active'] == False:
            alreadyexpired = True
        else:
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['active'] = False
        logger.info('Expire_Channel - Channel Expired - ' + channel.name)
        dupecount = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('duplicate',0)
        if dupecount >= 3:
            dupechannel = True
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = 0
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] = time.time()
            if (not alreadyexpired):
                await channel.send('This channel has been successfully reported as a duplicate and will be deleted in 1 minute. Check the channel list for the other raid channel to coordinate in!\nIf this was in error, reset the raid with **!timerset**')
            delete_time = (guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] + (1 * 60)) - time.time()
        elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg' and not guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',{}):
            if (not alreadyexpired):
                pkmn = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
                if pkmn:
                    await _eggtoraid(None, pkmn.lower(), channel)
                    return
                maybe_list = []
                trainer_dict = copy.deepcopy(
                    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
                for trainer in trainer_dict.keys():
                    if trainer_dict[trainer]['status']['maybe']:
                        user = channel.guild.get_member(trainer)
                        maybe_list.append(user.mention)
                h = 'hatched-'
                new_name = h if h not in channel.name else ''
                new_name += channel.name
                await channel.edit(name=new_name)
                await channel.send("**This egg has hatched!**\n\n...or the time has just expired. Trainers {trainer_list}: Update the raid to the pokemon that hatched using **!raid <pokemon>** or reset the hatch timer with **!timerset**. This channel will be deactivated until I get an update and I'll delete it in 45 minutes if I don't hear anything.".format(trainer_list=', '.join(maybe_list)))
            delete_time = (guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] + (45 * 60)) - time.time()
            expiremsg = '**This level {level} raid egg has expired!**'.format(
                level=guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['egglevel'])
        else:
            if (not alreadyexpired):
                e = 'expired-'
                new_name = e if e not in channel.name else ''
                new_name += channel.name
                await channel.edit(name=new_name)
                await channel.send('This channel timer has expired! The channel has been deactivated and will be deleted in 1 minute.\nTo reactivate the channel, use **!timerset** to set the timer again.')
            delete_time = (guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] + (1 * 60)) - time.time()
            raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',False) else " raid"
            expiremsg = '**This {pokemon}{raidtype} has expired!**'.format(
                pokemon=guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['pokemon'].capitalize(), raidtype=raidtype)
        await asyncio.sleep(delete_time)
        # If the channel has already been deleted from the dict, someone
        # else got to it before us, so don't do anything.
        # Also, if the channel got reactivated, don't do anything either.
        try:
            if (not guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['active']) and (not Kyogre.is_closed()):
                if dupechannel:
                    try:
                        report_channel = Kyogre.get_channel(
                            guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                        reportmsg = await report_channel.fetch_message(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                        await reportmsg.delete()
                    except:
                        pass
                else:
                    try:
                        report_channel = Kyogre.get_channel(
                            guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                        reportmsg = await report_channel.fetch_message(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                        await reportmsg.edit(embed=discord.Embed(description=expiremsg, colour=channel.guild.me.colour))
                        await reportmsg.clear_reactions()
                        await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=True, regions=guild_dict[guild.id]['raidchannel_dict'][channel.id].get('regions', None))
                    except:
                        pass
                    # channel doesn't exist anymore in serverdict
                archive = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('archive',False)
                logs = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('logs', {})
                channel_exists = Kyogre.get_channel(channel.id)
                if channel_exists == None:
                    return
                elif not archive and not logs:
                    try:
                        del guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]
                    except KeyError:
                        pass
                    await channel_exists.delete()
                    logger.info(
                        'Expire_Channel - Channel Deleted - ' + channel.name)
                elif archive or logs:
                    # Todo: Fix this
                    # Overwrites were changed from Tuple -> Dict
                    # try:
                    #     for overwrite in channel.overwrites:
                    #         if isinstance(overwrite[0], discord.Role):
                    #             if overwrite[0].permissions.manage_guild or overwrite[0].permissions.manage_channels:
                    #                 await channel.set_permissions(overwrite[0], read_messages=True)
                    #                 continue
                    #         elif isinstance(overwrite[0], discord.Member):
                    #             if channel.permissions_for(overwrite[0]).manage_guild or channel.permissions_for(overwrite[0]).manage_channels:
                    #                 await channel.set_permissions(overwrite[0], read_messages=True)
                    #                 continue
                    #         if (overwrite[0].name not in guild.me.top_role.name) and (overwrite[0].name not in guild.me.name):
                    #             await channel.set_permissions(overwrite[0], read_messages=False)
                    #     for role in guild.role_hierarchy:
                    #         if role.permissions.manage_guild or role.permissions.manage_channels:
                    #             await channel.set_permissions(role, read_messages=True)
                    #         continue
                    #     await channel.set_permissions(guild.default_role, read_messages=False)
                    # except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                    #     pass
                    new_name = 'archived-'
                    if new_name not in channel.name:
                        new_name += channel.name
                        category = guild_dict[channel.guild.id]['configure_dict'].get('archive', {}).get('category', 'same')
                        if category == 'same':
                            newcat = channel.category
                        else:
                            newcat = channel.guild.get_channel(category)
                        await channel.edit(name=new_name, category=newcat)
                        await channel.send('-----------------------------------------------\n**The channel has been archived and removed from view for everybody but Kyogre and those with Manage Channel permissions. Any messages that were deleted after the channel was marked for archival will be posted below. You will need to delete this channel manually.**\n-----------------------------------------------')
                        while logs:
                            earliest = min(logs)
                            embed = discord.Embed(colour=logs[earliest]['color_int'], description=logs[earliest]['content'], timestamp=logs[earliest]['created_at'])
                            if logs[earliest]['author_nick']:
                                embed.set_author(name="{name} [{nick}]".format(name=logs[earliest]['author_str'],nick=logs[earliest]['author_nick']), icon_url = logs[earliest]['author_avy'])
                            else:
                                embed.set_author(name=logs[earliest]['author_str'], icon_url = logs[earliest]['author_avy'])
                            await channel.send(embed=embed)
                            del logs[earliest]
                            await asyncio.sleep(.25)
                        del guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]
        except:
            pass

Kyogre.expire_channel = expire_channel

async def channel_cleanup(loop=True):
    while (not Kyogre.is_closed()):
        global active_raids
        guilddict_chtemp = copy.deepcopy(guild_dict)
        logger.info('Channel_Cleanup ------ BEGIN ------')
        # for every server in save data
        for guildid in guilddict_chtemp.keys():
            guild = Kyogre.get_guild(guildid)
            log_str = 'Channel_Cleanup - Server: ' + str(guildid)
            log_str = log_str + ' - CHECKING FOR SERVER'
            if guild == None:
                logger.info(log_str + ': NOT FOUND')
                continue
            logger.info(((log_str + ' (') + guild.name) +
                        ')  - BEGIN CHECKING SERVER')
            # clear channel lists
            dict_channel_delete = []
            discord_channel_delete = []
            # check every raid channel data for each server
            for channelid in guilddict_chtemp[guildid]['raidchannel_dict']:
                channel = Kyogre.get_channel(channelid)
                log_str = 'Channel_Cleanup - Server: ' + guild.name
                log_str = (log_str + ': Channel:') + str(channelid)
                logger.info(log_str + ' - CHECKING')
                channelmatch = Kyogre.get_channel(channelid)
                if channelmatch == None:
                    # list channel for deletion from save data
                    dict_channel_delete.append(channelid)
                    logger.info(log_str + " - NOT IN DISCORD")
                # otherwise, if kyogre can still see the channel in discord
                else:
                    logger.info(
                        ((log_str + ' (') + channel.name) + ') - EXISTS IN DISCORD')
                    # if the channel save data shows it's not an active raid
                    if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['active'] == False:
                        if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['type'] == 'egg':
                            # and if it has been expired for longer than 45 minutes already
                            if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] < (time.time() - (45 * 60)):
                                # list the channel to be removed from save data
                                dict_channel_delete.append(channelid)
                                # and list the channel to be deleted in discord
                                discord_channel_delete.append(channel)
                                logger.info(
                                    log_str + ' - 15+ MIN EXPIRY NONACTIVE EGG')
                                continue
                            # and if it has been expired for longer than 1 minute already
                        elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] < (time.time() - (1 * 60)):
                                # list the channel to be removed from save data
                            dict_channel_delete.append(channelid)
                                # and list the channel to be deleted in discord
                            discord_channel_delete.append(channel)
                            logger.info(
                                log_str + ' - 5+ MIN EXPIRY NONACTIVE RAID')
                            continue
                        event_loop.create_task(expire_channel(channel))
                        logger.info(
                            log_str + ' - = RECENTLY EXPIRED NONACTIVE RAID')
                        continue
                    # if the channel save data shows it as an active raid still
                    elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['active'] == True:
                        # if it's an exraid
                        if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['type'] == 'exraid':
                            logger.info(log_str + ' - EXRAID')

                            continue
                        # or if the expiry time for the channel has already passed within 5 minutes
                        elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] <= time.time():
                            # list the channel to be sent to the channel expiry function
                            event_loop.create_task(expire_channel(channel))
                            logger.info(log_str + ' - RECENTLY EXPIRED')

                            continue

                        if channel not in active_raids:
                            # if channel is still active, make sure it's expiry is being monitored
                            event_loop.create_task(expiry_check(channel))
                            logger.info(
                                log_str + ' - MISSING FROM EXPIRY CHECK')
                            continue
            # for every channel listed to have save data deleted
            for c in dict_channel_delete:
                try:
                    # attempt to delete the channel from save data
                    del guild_dict[guildid]['raidchannel_dict'][c]
                    logger.info(
                        'Channel_Cleanup - Channel Savedata Cleared - ' + str(c))
                except KeyError:
                    pass
            # for every channel listed to have the discord channel deleted
            for c in discord_channel_delete:
                try:
                    # delete channel from discord
                    await c.delete()
                    logger.info(
                        'Channel_Cleanup - Channel Deleted - ' + c.name)
                except:
                    logger.info(
                        'Channel_Cleanup - Channel Deletion Failure - ' + c.name)
                    pass
        # save server_dict changes after cleanup
        logger.info('Channel_Cleanup - SAVING CHANGES')
        try:
            await _save(guildid)
        except Exception as err:
            logger.info('Channel_Cleanup - SAVING FAILED' + str(err))
        logger.info('Channel_Cleanup ------ END ------')
        await asyncio.sleep(600)
        continue

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
            await _save(guild_id)
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
            await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'wild', edit=True)
            await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'research', edit=True)
        logger.info('message_cleanup - SAVING CHANGES')
        try:
            await _save(guild_id)
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


async def maint_start():
    tasks = []
    try:
        tasks.append(event_loop.create_task(channel_cleanup()))
        tasks.append(event_loop.create_task(message_cleanup()))
        logger.info('Maintenance Tasks Started')
    except KeyboardInterrupt:
        [task.cancel() for task in tasks]

event_loop = asyncio.get_event_loop()

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
    await _print(Kyogre.owner, "{server_count} servers connected.\n{member_count} members found.".format(server_count=guilds, member_count=users))
    await maint_start()


@Kyogre.event
async def on_guild_join(guild):
    owner = guild.owner
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
        'trainers':{},
        'trade_dict': {}
    }
    await owner.send("I'm Kyogre, a Discord helper bot for Pokemon Go communities, and someone has invited me to your server! Type **!help** to see a list of things I can do, and type **!configure** in any channel of your server to begin!")


@Kyogre.event
async def on_guild_remove(guild):
    try:
        if guild.id in guild_dict:
            try:
                del guild_dict[guild.id]
            except KeyError:
                pass
    except KeyError:
        pass


@Kyogre.event
async def on_member_join(member):
    """Welcome message to the server and some basic instructions."""
    guild = member.guild
    await calculate_invite_used(guild)
    team_msg = ' or '.join(['**!team {0}**'.format(team)
                           for team in config['team_dict'].keys()])
    if not guild_dict[guild.id]['configure_dict']['welcome']['enabled']:
        return
    # Build welcome message
    if guild_dict[guild.id]['configure_dict']['welcome'].get('welcomemsg', 'default') == "default":
        admin_message = ' If you have any questions just ask an admin.'
        welcomemessage = 'Welcome to {server}, {user}! '
        if guild_dict[guild.id]['configure_dict']['team']['enabled']:
            welcomemessage += 'Set your team by typing {team_command}.'.format(
                team_command=team_msg)
        welcomemessage += admin_message
    else:
        welcomemessage = guild_dict[guild.id]['configure_dict']['welcome']['welcomemsg']

    if guild_dict[guild.id]['configure_dict']['welcome']['welcomechan'] == 'dm':
        send_to = member
    elif str(guild_dict[guild.id]['configure_dict']['welcome']['welcomechan']).isdigit():
        send_to = discord.utils.get(guild.text_channels, id=int(guild_dict[guild.id]['configure_dict']['welcome']['welcomechan']))
    else:
        send_to = discord.utils.get(guild.text_channels, name=guild_dict[guild.id]['configure_dict']['welcome']['welcomechan'])
    if send_to:
        if welcomemessage.startswith("[") and welcomemessage.endswith("]"):
            await send_to.send(embed=discord.Embed(colour=guild.me.colour, description=welcomemessage[1:-1].format(server=guild.name, user=member.mention)))
        else:
            await send_to.send(welcomemessage.format(server=guild.name, user=member.mention))
    else:
        return


async def calculate_invite_used(guild):
    t_guild_dict = copy.deepcopy(guild_dict)
    invite_dict = t_guild_dict[guild.id]['configure_dict'].get('invite_counts', {})
    all_invites = await guild.invites()
    for inv in all_invites:
        if inv.code in invite_dict:
            count = invite_dict.get(inv.code, inv.uses)
            if inv.uses > count:
                if guild.system_channel:
                    await guild.system_channel.send(f"Using invite code: {inv.code}")
        elif inv.uses == 1:
            await guild.system_channel.send(f"Possibly using invite code: {inv.code}")
        invite_dict[inv.code] = inv.uses

    guild_dict[guild.id]['configure_dict']['invite_counts'] = invite_dict
    return


@Kyogre.event
async def on_member_update(before, after):
    guild = after.guild
    region_dict = guild_dict[guild.id]['configure_dict'].get('regions',None)
    if region_dict:
        notify_channel = region_dict.get('notify_channel',None)
        if (not before.bot) and notify_channel is not None:
            prev_roles = set([r.name for r in before.roles])
            post_roles = set([r.name for r in after.roles])
            added_roles = post_roles-prev_roles
            removed_roles = prev_roles-post_roles
            regioninfo_dict = region_dict.get('info',None)
            if regioninfo_dict:
                notify = None
                if len(added_roles) > 0:
                    # a single member update event should only ever have 1 role change
                    role = list(added_roles)[0]
                    if role in regioninfo_dict.keys():
                        notify = await Kyogre.get_channel(notify_channel).send(f"{after.mention} you have joined the {role.capitalize()} region.")
                if len(removed_roles) > 0:
                    # a single member update event should only ever have 1 role change
                    role = list(removed_roles)[0]
                    if role in regioninfo_dict.keys():
                        notify = await Kyogre.get_channel(notify_channel).send(f"{after.mention} you have left the {role.capitalize()} region.")
                if notify:
                    await asyncio.sleep(8)
                    await notify.delete()


@Kyogre.event
@checks.good_standing()
async def on_message(message):
    if (not message.author.bot):
        await Kyogre.process_commands(message)

@Kyogre.event
async def on_message_delete(message):
    guild = message.guild
    channel = message.channel
    author = message.author
    if not channel or not guild:
        return
    if channel.id in guild_dict[guild.id]['raidchannel_dict'] and guild_dict[guild.id]['configure_dict']['archive']['enabled']:
        if message.content.strip() == "!archive":
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['archive'] = True
        if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('archive', False):
            logs = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('logs', {})
            logs[message.id] = {'author_id': author.id, 'author_str': str(author),'author_avy':author.avatar_url,'author_nick':author.nick,'color_int':author.color.value,'content': message.clean_content,'created_at':message.created_at}
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['logs'] = logs

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
                    await expire_wild(message)
    questreport_dict = guild_dict[guild.id].setdefault('questreport_dict', {})
    if message.id in questreport_dict and user.id != Kyogre.user.id:
        quest_dict = questreport_dict.get(message.id, None)        
        if quest_dict and (quest_dict['reportauthor'] == payload.user_id or can_manage(user)):
            if str(payload.emoji) == '\u270f':
                await modify_research_report(payload)
            elif str(payload.emoji) == '🚫':
                try:
                    await message.edit(embed=discord.Embed(description="Research report cancelled", colour=message.embeds[0].colour.value))
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
        reporter = raid_dict[raid_report].get('reporter', 0)
        if (raid_dict[raid_report].get('reporter', 0) == payload.user_id or can_manage(user)):
            try:
                await message.remove_reaction(payload.emoji, user)
            except:
                pass
            if str(payload.emoji) == '\u270f':
                await modify_raid_report(payload, raid_report)
            elif str(payload.emoji) == '🚫':
                try:
                    await message.edit(embed=discord.Embed(description="Raid report cancelled", colour=message.embeds[0].colour.value))
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
        if (trainer == payload.user_id or can_manage(user)):
            if str(payload.emoji) == '🚫':
                return await expire_pvp(message)
        if str(payload.emoji) == '\u2694':
            attacker = guild.get_member(payload.user_id)
            defender = guild.get_member(pvp_dict[message.id]['reportauthor'])
            if attacker == defender:
                return
            battle_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"{defender.mention} you have been challenged by {attacker.mention}!"))
    raid_notice_dict = guild_dict[guild.id].setdefault('raid_notice_dict', {})
    if message.id in raid_notice_dict and user.id != Kyogre.user.id:
        trainer = raid_notice_dict[message.id]['reportauthor']
        if (trainer == payload.user_id or can_manage(user)):
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

async def modify_research_report(payload):
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
    questreport_dict = guild_dict[guild.id].setdefault('questreport_dict', {})
    research_embed = discord.Embed(colour=message.guild.me.colour).set_thumbnail(url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
    research_embed.set_footer(text='Reported by {user}'.format(user=user.display_name), icon_url=user.avatar_url_as(format=None, static_format='jpg', size=32))
    config_dict = guild_dict[guild.id]['configure_dict']
    regions = raid_helpers.get_channel_regions(channel, 'research', guild_dict)
    stops = None
    stops = get_stops(guild.id, regions)
    stop = questreport_dict[message.id]['location']
    prompt = f'Modifying details for **research task** at **{stop}**\nWhich item would you like to modify ***{user.display_name}***?'
    choices_list = ['Pokestop','Task', 'Reward']
    match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=user.id)
    err_msg = None
    confirmed = None
    if match in choices_list:
        if match == choices_list[0]:
            query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct Pokestop?"))
            try:
                pokestopmsg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                pokestopmsg = None
                await pokestopmsg.delete()
            if not pokestopmsg:
                error = "took too long to respond"
            elif pokestopmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await pokestopmsg.delete()
            elif pokestopmsg:
                if stops:
                    stop = await location_match_prompt(channel, user.id, pokestopmsg.clean_content, stops)
                    if not stop:
                        err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a pokestop named '{pokestopmsg.clean_content}'. Try again using the exact pokestop name!"))
                    else:
                        if get_existing_research(guild, stop):
                            err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"A quest has already been reported for {stop.name}"))
                        else:
                            location = stop.name
                            loc_url = stop.maps_url
                            questreport_dict[message.id]['location'] = location
                            questreport_dict[message.id]['url'] = loc_url
                            await _refresh_listing_channels_internal(guild, "research")
                            confirmed = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Research listing updated"))
                            await pokestopmsg.delete()
                            await query_msg.delete()
        elif match == choices_list[1]:
            questwait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct research task?"))
            try:
                questmsg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                questmsg = None
            await questwait.delete()
            if not questmsg:
                error = "took too long to respond"
            elif questmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await questmsg.delete()
            elif questmsg:
                quest = await _get_quest_v(channel, user.id, questmsg.clean_content)
                reward = await _prompt_reward_v(channel, user.id, quest)
                if not reward:
                    error = "didn't identify the reward"
            if not quest:
                error = "didn't identify the quest"
            questreport_dict[message.id]['quest'] = quest.name
            questreport_dict[message.id]['reward'] = reward
            await _refresh_listing_channels_internal(guild, "research")
            confirmed = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Research listing updated"))
            await questmsg.delete()
        elif match == choices_list[2]:
            rewardwait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct reward?"))
            quest = guild_dict[guild.id]['questreport_dict'].get(message.id, None)
            quest = await _get_quest_v(channel, user.id, quest['quest'])
            
            reward = await _prompt_reward_v(channel, user.id, quest)
            if not reward:
                error = "didn't identify the reward"
            questreport_dict[message.id]['reward'] = reward
            await _refresh_listing_channels_internal(guild, "research")
            confirmed = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Research listing updated"))
            await rewardwait.delete()
        embed = message.embeds[0]
        embed.clear_fields()
        location = questreport_dict[message.id]['location']
        name = questreport_dict[message.id]['quest']
        reward = questreport_dict[message.id]['reward']
        embed.add_field(name="**Pokestop:**",value='\n'.join(textwrap.wrap(location.title(), width=30)),inline=True)
        embed.add_field(name="**Quest:**",value='\n'.join(textwrap.wrap(name.title(), width=30)),inline=True)
        embed.add_field(name="**Reward:**",value='\n'.join(textwrap.wrap(reward.title(), width=30)),inline=True)
        embed.url = questreport_dict[message.id]['url']
        new_msg = f'{name} Field Research task, reward: {reward} reported at {location}'
        await message.edit(content=new_msg,embed=embed)
    else:
        return

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
    prompt = f'Modifying details for **raid** at **{gym}**\nWhich item would you like to modify ***{user.display_name}***?'
    match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=user.id)
    err_msg = None
    success_msg = None
    if match in choices_list:
        # Updating location
        if match == choices_list[0]:
            query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the correct Location?"))
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
                        err_msg =  await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a gym named '{gymmsg.clean_content}'. Try again using the exact gym name!"))
                    else:
                        location = gym.name
                        raid_channel_ids = get_existing_raid(guild, gym)
                        if raid_channel_ids:
                            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
                            if guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]:
                                err_msg =  await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"A raid has already been reported for {gym.name}"))
                        else:
                            await entity_updates.update_raid_location(message, report_channel, raid_channel, gym)
                            await _refresh_listing_channels_internal(guild, "raid")
                            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Raid location updated"))
                            await gymmsg.delete()
                            await query_msg.delete()

        # Updating time
        elif match == choices_list[1]:
            timewait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the Hatch / Expire time?"))
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
            raidexp = await time_to_minute_count(raid_channel, timemsg.clean_content)
            if raidexp is not False:
                await _timerset(raid_channel, raidexp)
            await _refresh_listing_channels_internal(guild, "raid")
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Raid hatch / expire time updated"))
            await timewait.delete()
            await timemsg.delete()
        # Updating boss
        elif match == choices_list[2]:
            bosswait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(), description="What is the Raid Tier / Boss?"))
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
            await changeraid_internal(guild, raid_channel, bossmsg.clean_content)
            if not bossmsg.clean_content.isdigit():
                await _timerset(raid_channel, 45)
            await _refresh_listing_channels_internal(guild, "raid")
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description="Raid Tier / Boss updated"))
            await bosswait.delete()
            await bossmsg.delete()
    else:
        return

"""
Admin Commands
"""
@Kyogre.command(hidden=True, name='mention_toggle', aliases=['mt'])
@commands.has_permissions(manage_roles=True)
async def mention_toggle(ctx, rolename):
    role = discord.utils.get(ctx.guild.roles, name=rolename)
    if role:
        await role.edit(mentionable = not role.mentionable)
        if role.mentionable:
            outcome = "on"
        else:
            outcome = "off"
        confirmation = await ctx.channel.send(f"{rolename} mention turned {outcome}")
        await asyncio.sleep(5)
        await ctx.message.delete()
        await confirmation.delete()
    else:
        await ctx.message.add_reaction('❎')


@Kyogre.command(hidden=True, name="eval")
@checks.is_dev_or_owner()
async def _eval(ctx, *, body: str):
    """Evaluates a code"""
    env = {
        'bot': ctx.bot,
        'ctx': ctx,
        'channel': ctx.channel,
        'author': ctx.author,
        'guild': ctx.guild,
        'message': ctx.message
    }
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])
        # remove `foo`
        return content.strip('` \n')
    env.update(globals())
    body = cleanup_code(body)
    stdout = io.StringIO()
    to_compile = (f'async def func():\n{textwrap.indent(body, "  ")}')
    try:
        exec(to_compile, env)
    except Exception as e:
        return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')
    func = env['func']
    try:
        with redirect_stdout(stdout):
            ret = await func()
    except Exception as e:
        value = stdout.getvalue()
        await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
    else:
        value = stdout.getvalue()
        try:
            await ctx.message.add_reaction('\u2705')
        except:
            pass
        if ret is None:
            if value:
                paginator = commands.Paginator(prefix='```py')
                for line in textwrap.wrap(value, 80):
                    paginator.add_line(line.rstrip().replace('`', '\u200b`'))
                for p in paginator.pages:
                    await ctx.send(p)
        else:
            ctx.bot._last_result = ret
            await ctx.send(f'```py\n{value}{ret}\n```')

@Kyogre.command()
@checks.is_owner()
async def save(ctx):
    """Save persistent state to file.

    Usage: !save
    File path is relative to current directory."""
    try:
        await _save(ctx.guild.id)
        logger.info('CONFIG SAVED')
    except Exception as err:
        await _print(Kyogre.owner, 'Error occured while trying to save!')
        await _print(Kyogre.owner, err)

async def _save(guildid):
    with tempfile.NamedTemporaryFile('wb', dir=os.path.dirname(os.path.join('data', 'serverdict')), delete=False) as tf:
        pickle.dump(guild_dict, tf, -1)
        tempname = tf.name
    try:
        os.remove(os.path.join('data', 'serverdict_backup'))
    except OSError as e:
        pass
    try:
        os.rename(os.path.join('data', 'serverdict'), os.path.join('data', 'serverdict_backup'))
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
    os.rename(tempname, os.path.join('data', 'serverdict'))

    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    if not location_matching_cog:
        await _print(Kyogre.owner, 'Pokestop and Gym data not saved!')
        return None
    stop_save = location_matching_cog.saveStopsToJson(guildid)
    gym_save = location_matching_cog.saveGymsToJson(guildid)
    if stop_save is not None:
        await _print(Kyogre.owner, f'Failed to save pokestop data with error: {stop_save}!')
    if gym_save is not None:
        await _print(Kyogre.owner, f'Failed to save gym data with error: {gym_save}!')


@Kyogre.command()
@checks.is_owner()
async def restart(ctx):
    """Restart after saving.

    Usage: !restart.
    Calls the save function and restarts Kyogre."""
    try:
        await _save(ctx.guild.id)
    except Exception as err:
        await _print(Kyogre.owner, 'Error occured while trying to save!')
        await _print(Kyogre.owner, err)
    await ctx.channel.send('Restarting...')
    Kyogre._shutdown_mode = 26
    await Kyogre.logout()

@Kyogre.command()
@checks.is_owner()
async def exit(ctx):
    """Exit after saving.

    Usage: !exit.
    Calls the save function and quits the script."""
    try:
        await _save(ctx.guild.id)
    except Exception as err:
        await _print(Kyogre.owner, 'Error occured while trying to save!')
        await _print(Kyogre.owner, err)
    await ctx.channel.send('Shutting down...')
    Kyogre._shutdown_mode = 0
    await Kyogre.logout()

@Kyogre.command()
@commands.has_permissions(manage_guild=True)
async def kban(ctx, *, user: str = '', reason: str = ''):
    converter = commands.MemberConverter()
    try:
        trainer = await converter.convert(ctx, user)
        trainer_id = trainer.id
    except:
        return await ctx.channel.send("User not found.")   
    trainer = guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).setdefault(trainer_id,{})
    trainer['is_banned'] = True
    ban_reason = trainer.get('ban_reason')
    if not ban_reason:
        ban_reason = []
    elif not isinstance(ban_reason, list):
        ban_reason = [ban_reason]
    trainer['ban_reason'] = ban_reason.append(reason)
    try:
        await ctx.message.add_reaction('\u2705')
    except:
        pass

@Kyogre.command()
@commands.has_permissions(manage_guild=True)
async def kunban(ctx, *, user: str = ''):
    channel = ctx.channel
    converter = commands.MemberConverter()
    try:
        trainer = await converter.convert(ctx, user)
        trainer_id = trainer.id
    except:
        return await channel.send("User not found.")   
    trainer = guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).get(trainer_id, None)
    trainer['is_banned'] = False
    try:
        await ctx.message.add_reaction('\u2705')
    except:
        pass

@Kyogre.group(name='region', case_insensitive=True)
@checks.allowregion()
async def _region(ctx):
    """Handles user-region settings"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()

@_region.command(name="join")
async def join(ctx, *, region_names):
    """Joins regional roles from the provided comma-separated list

    Examples:
    !region join kanto
    !region join kanto, johto, hoenn"""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    response = ""
    region_info_dict = guild_dict[guild.id]['configure_dict']['regions']['info']
    enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
    requested_roles = set([r for r in re.split(r'\s*,\s*', region_names.lower().replace(" ", "")) if r])
    if not requested_roles:
        return await channel.send(_user_region_list("join", author, enabled_roles))
    valid_requests = requested_roles & enabled_roles
    invalid_requests = requested_roles - enabled_roles
    role_objs = [discord.utils.get(guild.roles, name=role) for role in valid_requests]
    if role_objs:
        try:
            await author.add_roles(*role_objs, reason="user requested region role add via ")
            await message.add_reaction('✅')
            response += "Successfully joined "
        except:
            response += "Failed joining "
        response += f"{len(valid_requests)} roles:\n{', '.join(valid_requests)}"
    if invalid_requests:
        response += f"\n\n{len(invalid_requests)} invalid roles detected:\n{', '.join(invalid_requests)}\n\n"
        response += f"Acceptable regions are: {', '.join(enabled_roles)}"
    resp = await channel.send(response)
    await asyncio.sleep(20)
    await resp.delete()

@_region.command(name="leave")
async def _leave(ctx, *, region_names: str = ''):
    """Leaves regional roles from the provided comma-separated list

    Examples:
    !region leave kanto
    !region leave kanto, johto, hoenn"""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    response = ""
    region_info_dict = guild_dict[guild.id]['configure_dict']['regions']['info']
    enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
    requested_roles = set([r for r in re.split(r'\s*,\s*', region_names.lower().strip()) if r])
    if not requested_roles:
        return await channel.send(_user_region_list("leave", author, enabled_roles))
    valid_requests = requested_roles & enabled_roles
    invalid_requests = requested_roles - enabled_roles
    role_objs = [discord.utils.get(guild.roles, name=role) for role in valid_requests]
    if role_objs:
        try:
            await author.remove_roles(*role_objs, reason="user requested region role remove via ")
            await message.add_reaction('✅')
            response += "Successfully left "
        except:
            response += "Failed leaving "
        response += f"{len(valid_requests)} roles:\n{', '.join(valid_requests)}"
    if invalid_requests:
        response += f"\n\n{len(invalid_requests)} invalid roles detected:\n{', '.join(invalid_requests)}\n\n"
        response += f"Acceptable regions are: {', '.join(enabled_roles)}"
    resp = await channel.send(response)
    await asyncio.sleep(20)
    await resp.delete()
                  
def _user_region_list(action, author, enabled_roles):
    roles = [r.name for r in author.roles]
    response = f"Please select one or more regions separated by commas `!region {action} renton, kent`\n\n"
    if action == "join":
        response += f" Regions available to join are: {', '.join(set(enabled_roles).difference(roles)) or 'N/A'}"
    else:
        response += f" Regions available to leave are: {', '.join(set(enabled_roles).intersection(roles)) or 'N/A'}"
    return response

@_region.command(name="list")
async def _list(ctx):
    """Lists the user's active region roles

    Usage: !region list"""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    region_info_dict = guild_dict[guild.id]['configure_dict']['regions']['info']
    enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
    user_roles = set([r.name for r in author.roles])
    active_roles = user_roles & enabled_roles
    response = f"You have {len(active_roles)} active region roles:\n{', '.join(active_roles)}"
    response += f" Regions available to join are: {', '.join(set(active_roles).difference(enabled_roles)) or 'N/A'}"
    await message.add_reaction('✅')
    resp = await channel.send(response)
    await asyncio.sleep(20)
    await resp.delete()

@Kyogre.group(name='set', case_insensitive=True)
async def _set(ctx):
    """Changes a setting."""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()

@_set.command()
@commands.has_permissions(manage_guild=True)
async def regional(ctx, regional):
    """Changes server regional pokemon."""
    regional = regional.lower()
    if regional == "reset" and checks.is_dev_or_owner(ctx):
        msg = "Are you sure you want to clear all regionals?"
        question = await ctx.channel.send(msg)
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(Kyogre, question, ctx.message.channel, ctx.message.author.id)
        except TypeError:
            timeout = True
        await question.delete()
        if timeout or res.emoji == '❎':
            return
        elif res.emoji == '✅':
            pass
        else:
            return
        guild_dict_copy = copy.deepcopy(guild_dict)
        for guildid in guild_dict_copy.keys():
            guild_dict[guildid]['configure_dict']['settings']['regional'] = None
        return
    elif regional == 'clear':
        regional = None
        _set_regional(Kyogre, ctx.guild, regional)
        await ctx.message.channel.send("Regional raid boss cleared!")
        return
    regional = Pokemon.get_pokemon(Kyogre, regional)
    if regional.is_raid:
        _set_regional(Kyogre, ctx.guild, regional)
        await ctx.message.channel.send("Regional raid boss set to **{boss}**!").format(boss=regional.name)
    else:
        await ctx.message.channel.send("That Pokemon doesn't appear in raids!")
        return

def _set_regional(bot, guild, regional):
    bot.guild_dict[guild.id]['configure_dict']['settings']['regional'] = regional


@_set.command()
@commands.has_permissions(manage_guild=True)
async def timezone(ctx, *, timezone: str = ''):
    """Changes server timezone."""
    try:
        timezone = float(timezone)
    except ValueError:
        await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! Please double check what you sent me and resend a number from **-12** to **12**.")
        return
    if (not ((- 12) <= timezone <= 14)):
        await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! Please double check what you sent me and resend a number from **-12** to **12**.")
        return
    _set_timezone(Kyogre, ctx.guild, timezone)
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
    await ctx.channel.send("Timezone has been set to: `UTC{offset}`\nThe current time is **{now}**").format(
        offset=timezone, now=now.strftime("%H:%M"))


def _set_timezone(bot, guild, timezone):
    bot.guild_dict[guild.id]['configure_dict']['settings']['offset'] = timezone


@_set.command()
@commands.has_permissions(manage_guild=True)
async def prefix(ctx, prefix=None):
    """Changes server prefix."""
    if prefix == 'clear':
        prefix = None
    prefix = prefix.strip()
    _set_prefix(Kyogre, ctx.guild, prefix)
    if prefix != None:
        await ctx.channel.send('Prefix has been set to: `{}`'.format(prefix))
    else:
        default_prefix = Kyogre.config['default_prefix']
        await ctx.channel.send('Prefix has been reset to default: `{}`'.format(default_prefix))

def _set_prefix(bot, guild, prefix):
    bot.guild_dict[guild.id]['configure_dict']['settings']['prefix'] = prefix

@_set.command()
async def silph(ctx, silph_user: str = None):
    """Links a server member to a Silph Road Travelers Card."""
    if not silph_user:
        await ctx.send('Silph Road Travelers Card cleared!')
        try:
            del guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['silphid']
        except:
            pass
        return

    silph_cog = ctx.bot.cogs.get('Silph')
    if not silph_cog:
        return await ctx.send(
            "The Silph Extension isn't accessible at the moment, sorry!")

    async with ctx.typing():
        card = await silph_cog.get_silph_card(silph_user)
        if not card:
            return await ctx.send('Silph Card for {silph_user} not found.'.format(silph_user=silph_user))

    if not card.discord_name:
        return await ctx.send(
            'No Discord account found linked to this Travelers Card!')

    if card.discord_name != str(ctx.author):
        return await ctx.send(
            'This Travelers Card is linked to another Discord account!')

    try:
        offset = ctx.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset']
    except KeyError:
        offset = None

    trainers = guild_dict[ctx.guild.id].get('trainers', {})
    author = trainers.setdefault('info', {}).get(ctx.author.id,{})
    author['silphid'] = silph_user
    trainers.setdefault('info', {})[ctx.author.id] = author
    guild_dict[ctx.guild.id]['trainers'] = trainers

    await ctx.send(
        'This Travelers Card has been successfully linked to you!',
        embed=card.embed(offset))

@_set.command()
async def pokebattler(ctx, pbid: int = 0):
    """Links a server member to a PokeBattler ID."""
    if not pbid:
        await ctx.send('Pokebattler ID cleared!')
        try:
            del guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['pokebattlerid']
        except:
            pass
        return
    trainers = guild_dict[ctx.guild.id].get('trainers',{})
    author = trainers.setdefault('info', {}).get(ctx.author.id,{})
    author['pokebattlerid'] = pbid
    trainers.setdefault('info', {})[ctx.author.id] = author
    guild_dict[ctx.guild.id]['trainers'] = trainers
    await ctx.send('Pokebattler ID set to {pbid}!'.format(pbid=pbid))

@Kyogre.group(name='get', case_insensitive=True)
@commands.has_permissions(manage_guild=True)
async def _get(ctx):
    """Get a setting value"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()

@_get.command()
@commands.has_permissions(manage_guild=True)
async def prefix(ctx):
    """Get server prefix."""
    prefix = _get_prefix(Kyogre, ctx.message)
    await ctx.channel.send('Prefix for this server is: `{}`'.format(prefix))

@_get.command()
@commands.has_permissions(manage_guild=True)
async def perms(ctx, channel_id = None):
    """Show Kyogre's permissions for the guild and channel."""
    channel = discord.utils.get(ctx.bot.get_all_channels(), id=channel_id)
    guild = channel.guild if channel else ctx.guild
    channel = channel or ctx.channel
    guild_perms = guild.me.guild_permissions
    chan_perms = channel.permissions_for(guild.me)
    req_perms = discord.Permissions(268822608)

    embed = discord.Embed(colour=ctx.guild.me.colour)
    embed.set_author(name='Bot Permissions', icon_url="https://i.imgur.com/wzryVaS.png")

    wrap = functools.partial(textwrap.wrap, width=20)
    names = [wrap(channel.name), wrap(guild.name)]
    if channel.category:
        names.append(wrap(channel.category.name))
    name_len = max(len(n) for n in names)
    def same_len(txt):
        return '\n'.join(txt + ([' '] * (name_len-len(txt))))
    names = [same_len(n) for n in names]
    chan_msg = [f"**{names[0]}** \n{channel.id} \n"]
    guild_msg = [f"**{names[1]}** \n{guild.id} \n"]
    def perms_result(perms):
        data = []
        meet_req = perms >= req_perms
        result = "**PASS**" if meet_req else "**FAIL**"
        data.append(f"{result} - {perms.value} \n")
        true_perms = [k for k, v in dict(perms).items() if v is True]
        false_perms = [k for k, v in dict(perms).items() if v is False]
        req_perms_list = [k for k, v in dict(req_perms).items() if v is True]
        true_perms_str = '\n'.join(true_perms)
        if not meet_req:
            missing = '\n'.join([p for p in false_perms if p in req_perms_list])
            meet_req_result = "**MISSING**"
            data.append(f"{meet_req_result} \n{missing} \n")
        if true_perms_str:
            meet_req_result = "**ENABLED**"
            data.append(f"{meet_req_result} \n{true_perms_str} \n")
        return '\n'.join(data)
    guild_msg.append(perms_result(guild_perms))
    chan_msg.append(perms_result(chan_perms))
    embed.add_field(name='GUILD', value='\n'.join(guild_msg))
    if channel.category:
        cat_perms = channel.category.permissions_for(guild.me)
        cat_msg = [f"**{names[2]}** \n{channel.category.id} \n"]
        cat_msg.append(perms_result(cat_perms))
        embed.add_field(name='CATEGORY', value='\n'.join(cat_msg))
    embed.add_field(name='CHANNEL', value='\n'.join(chan_msg))

    try:
        await ctx.send(embed=embed)
    except discord.errors.Forbidden:
        # didn't have permissions to send a message with an embed
        try:
            msg = "I couldn't send an embed here, so I've sent you a DM"
            await ctx.send(msg)
        except discord.errors.Forbidden:
            # didn't have permissions to send a message at all
            pass
        await ctx.author.send(embed=embed)

@Kyogre.command()
@commands.has_permissions(manage_guild=True)
async def welcome(ctx, user: discord.Member=None):
    """Test welcome on yourself or mentioned member.

    Usage: !welcome [@member]"""
    if (not user):
        user = ctx.author
    await on_member_join(user)

@Kyogre.command(hidden=True,aliases=['opl'])
@commands.has_permissions(manage_guild=True)
async def outputlog(ctx):
    """Get current Kyogre log.

    Usage: !outputlog
    Output is a link to hastebin."""
    with open(os.path.join('logs', 'kyogre.log'), 'r', encoding='latin-1', errors='replace') as logfile:
        logdata = logfile.read()
        async with aiohttp.ClientSession() as session:
            async with session.post("https://hastebin.com/documents",data=logdata.encode('utf-8')) as post:
                post = await post.json()
                reply = "https://hastebin.com/{}".format(post['key'])
    await ctx.channel.send(reply)

@Kyogre.command(aliases=['say'])
@commands.has_permissions(manage_guild=True)
async def announce(ctx, *, announce=None):
    """Repeats your message in an embed from Kyogre.

    Usage: !announce [announcement]
    If the announcement isn't added at the same time as the command, Kyogre will wait 3 minutes for a followup message containing the announcement."""
    message = ctx.message
    channel = message.channel
    guild = message.guild
    author = message.author
    announcetitle = 'Announcement'
    if announce == None:
        titlewait = await channel.send("If you would like to set a title for your announcement please reply with the title, otherwise reply with 'skip'.")
        titlemsg = await Kyogre.wait_for('message', timeout=180, check=(lambda reply: reply.author == message.author))
        await titlewait.delete()
        if titlemsg != None:
            if titlemsg.content.lower() == "skip":
                pass
            else:
                announcetitle = titlemsg.content
            await titlemsg.delete()
        announcewait = await channel.send("I'll wait for your announcement!")
        announcemsg = await Kyogre.wait_for('message', timeout=180, check=(lambda reply: reply.author == message.author))
        await announcewait.delete()
        if announcemsg != None:
            announce = announcemsg.content
            await announcemsg.delete()
        else:
            confirmation = await channel.send("You took too long to send me your announcement! Retry when you're ready.")
    embeddraft = discord.Embed(colour=guild.me.colour, description=announce)
    if ctx.invoked_with == "announce":
        title = announcetitle
        if Kyogre.user.avatar_url:
            embeddraft.set_author(name=title, icon_url=Kyogre.user.avatar_url)
        else:
            embeddraft.set_author(name=title)
    draft = await channel.send(embed=embeddraft)
    reaction_list = ['❔', '✅', '❎']
    owner_msg_add = ''
    if checks.is_owner_check(ctx):
        owner_msg_add = '🌎 '
        owner_msg_add += 'to send it to all servers, '
        reaction_list.insert(0, '🌎')

    def check(reaction, user):
        if user.id == author.id:
            if (str(reaction.emoji) in reaction_list) and (reaction.message.id == rusure.id):
                return True
        return False
    msg = "That's what you sent, does it look good? React with "
    msg += "{}❔ "
    msg += "to send to another channel, "
    msg += "✅ "
    msg += "to send it to this channel, or "
    msg += "❎ "
    msg += "to cancel"
    rusure = await channel.send(msg.format(owner_msg_add))
    try:
        timeout = False
        res, reactuser = await utils.simple_ask(Kyogre, rusure, channel, author.id, react_list=reaction_list)
    except TypeError:
        timeout = True
    if not timeout:
        await rusure.delete()
        if res.emoji == '❎':
            confirmation = await channel.send('Announcement Cancelled.')
            await draft.delete()
        elif res.emoji == '✅':
            confirmation = await channel.send('Announcement Sent.')
        elif res.emoji == '❔':
            channelwait = await channel.send('What channel would you like me to send it to?')
            channelmsg = await Kyogre.wait_for('message', timeout=60, check=(lambda reply: reply.author == message.author))
            if channelmsg.content.isdigit():
                sendchannel = Kyogre.get_channel(int(channelmsg.content))
            elif channelmsg.raw_channel_mentions:
                sendchannel = Kyogre.get_channel(channelmsg.raw_channel_mentions[0])
            else:
                sendchannel = discord.utils.get(guild.text_channels, name=channelmsg.content)
            if (channelmsg != None) and (sendchannel != None):
                announcement = await sendchannel.send(embed=embeddraft)
                confirmation = await channel.send('Announcement Sent.')
            elif sendchannel == None:
                confirmation = await channel.send("That channel doesn't exist! Retry when you're ready.")
            else:
                confirmation = await channel.send("You took too long to send me your announcement! Retry when you're ready.")
            await channelwait.delete()
            await channelmsg.delete()
            await draft.delete()
        elif (res.emoji == '🌎') and checks.is_owner_check(ctx):
            failed = 0
            sent = 0
            count = 0
            recipients = {

            }
            embeddraft.set_footer(text='For support, contact us on our Discord server. Invite Code: hhVjAN8')
            embeddraft.colour = discord.Colour.lighter_grey()
            for guild in Kyogre.guilds:
                recipients[guild.name] = guild.owner
            for (guild, destination) in recipients.items():
                try:
                    await destination.send(embed=embeddraft)
                except discord.HTTPException:
                    failed += 1
                    logger.info('Announcement Delivery Failure: {} - {}'.format(destination.name, guild))
                else:
                    sent += 1
                count += 1
            logger.info('Announcement sent to {} server owners: {} successful, {} failed.'.format(count, sent, failed))
            confirmation = await channel.send('Announcement sent to {} server owners: {} successful, {} failed.').format(count, sent, failed)
        await asyncio.sleep(10)
        await confirmation.delete()
    else:
        await rusure.delete()
        confirmation = await channel.send('Announcement Timed Out.')
        await asyncio.sleep(10)
        await confirmation.delete()
    await asyncio.sleep(30)
    await message.delete()

@Kyogre.group(case_insensitive=True, invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def configure(ctx, *, configlist: str=""):
    """Kyogre Configuration

    Usage: !configure [list]
    Kyogre will DM you instructions on how to configure Kyogre for your server.
    If it is not your first time configuring, you can choose a section to jump to.
    You can also include a comma separated [list] of sections from the following:
    all, team, welcome, regions, raid, exraid, invite, counters, wild, research, meetup, subscription, archive, trade, timezone"""
    await _configure(ctx, configlist)

async def _configure(ctx, configlist):
    guild = ctx.message.guild
    owner = ctx.message.author
    try:
        await ctx.message.delete()
    except (discord.errors.Forbidden, discord.errors.HTTPException):
        pass
    config_sessions = guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('config_sessions',{}).setdefault(owner.id,0) + 1
    guild_dict[ctx.guild.id]['configure_dict']['settings']['config_sessions'][owner.id] = config_sessions
    for session in guild_dict[guild.id]['configure_dict']['settings']['config_sessions'].keys():
        if not guild.get_member(session):
            del guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][session]
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    firstconfig = False
    all_commands = ['team', 'welcome', 'regions', 'raid', 'exraid', 'exinvite', 'counters', 'wild', 'research', 'meetup', 'subscriptions', 'archive', 'trade', 'timezone', 'pvp', 'join', 'lure']
    enabled_commands = []
    configreplylist = []
    config_error = False
    if not config_dict_temp['settings']['done']:
        firstconfig = True
    if configlist and not firstconfig:
        configlist = configlist.lower().replace("timezone","settings").split(",")
        configlist = [x.strip().lower() for x in configlist]
        diff = set(configlist) - set(all_commands)
        if diff and "all" in diff:
            configreplylist = all_commands
        elif not diff:
            configreplylist = configlist
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="I'm sorry, I couldn't understand some of what you entered. Let's just start here."))
    if config_dict_temp['settings']['config_sessions'][owner.id] > 1:
        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="**MULTIPLE SESSIONS!**\n\nIt looks like you have **{yoursessions}** active configure sessions. I recommend you send **cancel** first and then send your request again to avoid confusing me.\n\nYour Sessions: **{yoursessions}** | Total Sessions: **{allsessions}**".format(allsessions=sum(config_dict_temp['settings']['config_sessions'].values()),yoursessions=config_dict_temp['settings']['config_sessions'][owner.id])))
    configmessage = "Welcome to the configuration for Kyogre! I will be guiding you through some steps to get me setup on your server.\n\n**Role Setup**\nBefore you begin the configuration, please make sure my role is moved to the top end of the server role hierarchy. It can be under admins and mods, but must be above team and general roles. [Here is an example](http://i.imgur.com/c5eaX1u.png)"
    if not firstconfig and not configreplylist:
        configmessage += "\n\n**Welcome Back**\nThis isn't your first time configuring. You can either reconfigure everything by replying with **all** or reply with a comma separated list to configure those commands. Example: `subscription, raid, wild`"
        for commandconfig in config_dict_temp.keys():
            if config_dict_temp[commandconfig].get('enabled',False):
                enabled_commands.append(commandconfig)
        configmessage += "\n\n**Enabled Commands:**\n{enabled_commands}".format(enabled_commands=", ".join(enabled_commands))
        configmessage += "\n\n**All Commands:**\n**all** - To redo configuration\n\
**team** - For Team Assignment configuration\n**welcome** - For Welcome Message configuration\n\
**regions** - for region configuration\n**raid** - for raid command configuration\n\
**exraid** - for EX raid command configuration\n**invite** - for invite command configuration\n\
**counters** - for automatic counters configuration\n**wild** - for wild command configuration\n\
**research** - for !research command configuration\n**meetup** - for !meetup command configuration\n\
**subscriptions** - for subscription command configuration\n**archive** - For !archive configuration\n\
**trade** - For trade command configuration\n**timezone** - For timezone configuration\n\
**join** - For !join command configuration\n**pvp** - For !pvp command configuration"
        configmessage += '\n\nReply with **cancel** at any time throughout the questions to cancel the configure process.'
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=configmessage).set_author(name='Kyogre Configuration - {guild}'.format(guild=guild.name), icon_url=Kyogre.user.avatar_url))
        while True:
            config_error = False
            def check(m):
                return m.guild == None and m.author == owner
            configreply = await Kyogre.wait_for('message', check=check)
            configreply.content = configreply.content.replace("timezone", "settings")
            if configreply.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description='**CONFIG CANCELLED!**\n\nNo changes have been made.'))
                del guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]
                return None
            elif "all" in configreply.content.lower():
                configreplylist = all_commands
                break
            else:
                configreplylist = configreply.content.lower().split(",")
                configreplylist = [x.strip() for x in configreplylist]
                for configreplyitem in configreplylist:
                    if configreplyitem not in all_commands:
                        config_error = True
                        break
            if config_error:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="I'm sorry I don't understand. Please reply with the choices above."))
                continue
            else:
                break
    elif firstconfig == True:
        configmessage += '\n\nReply with **cancel** at any time throughout the questions to cancel the configure process.'
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=configmessage).set_author(name='Kyogre Configuration - {guild}'.format(guild=guild.name), icon_url=Kyogre.user.avatar_url))
        configreplylist = all_commands
    try:
        config_func_dict = {"team":configuration._configure_team,
                "welcome":configuration._configure_welcome,
                "regions":configuration._configure_regions,
                "raid":configuration._configure_raid,
                "exraid":configuration._configure_exraid,
                "meetup":configuration._configure_meetup,
                "exinvite":configuration._configure_exinvite,
                "counters":configuration._configure_counters,
                "wild":configuration._configure_wild,
                "research":configuration._configure_research,
                "subscriptions":configuration._configure_subscriptions,
                "archive":configuration._configure_archive,
                "trade":configuration._configure_trade,
                "settings":configuration._configure_settings,
                "pvp":configuration._configure_pvp,
                "join":configuration._configure_join,
                "lure":configuration._configure_lure
                }
        for item in configreplylist:
            try:
                func = config_func_dict[item]
                ctx = await func(ctx, Kyogre)
                if not ctx:
                    return None
            except:
                pass
    finally:
        if ctx:
            ctx.config_dict_temp['settings']['done'] = True
            await ctx.channel.send("Config changed: overwriting config dict.")
            guild_dict[guild.id]['configure_dict'] = ctx.config_dict_temp
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Alright! Your settings have been saved and I'm ready to go! If you need to change any of these settings, just type **!configure** in your server again.").set_author(name='Configuration Complete', icon_url=Kyogre.user.avatar_url))
        del guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]

@configure.command(name='all')
async def configure_all(ctx):
    """All settings"""
    await _configure(ctx, "all")

async def _check_sessions_and_invoke(ctx, func_ref):
    guild = ctx.message.guild
    owner = ctx.message.author
    try:
        await ctx.message.delete()
    except (discord.errors.Forbidden, discord.errors.HTTPException):
        pass
    if not guild_dict[guild.id]['configure_dict']['settings']['done']:
        await _configure(ctx, "all")
        return
    config_sessions = guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('config_sessions',{}).setdefault(owner.id,0) + 1
    guild_dict[ctx.guild.id]['configure_dict']['settings']['config_sessions'][owner.id] = config_sessions
    if guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id] > 1:
        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="**MULTIPLE SESSIONS!**\n\nIt looks like you have **{yoursessions}** active configure sessions. I recommend you send **cancel** first and then send your request again to avoid confusing me.\n\nYour Sessions: **{yoursessions}** | Total Sessions: **{allsessions}**".format(allsessions=sum(guild_dict[guild.id]['configure_dict']['settings']['config_sessions'].values()),yoursessions=guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id])))
    ctx = await func_ref(ctx, Kyogre)
    if ctx:
        guild_dict[guild.id]['configure_dict'] = ctx.config_dict_temp
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Alright! Your settings have been saved and I'm ready to go! If you need to change any of these settings, just type **!configure** in your server again.").set_author(name='Configuration Complete', icon_url=Kyogre.user.avatar_url))
    del guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]

@configure.command()
async def team(ctx):
    """!team command settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_team)

@configure.command()
async def welcome(ctx):
    """Welcome message settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_welcome)

@configure.command()
async def regions(ctx):
    """region configuration for server"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_regions)

@configure.command()
async def raid(ctx):
    """!raid reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_raid)

@configure.command()
async def exraid(ctx):
    """!exraid reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_exraid)

@configure.command()
async def exinvite(ctx):
    """!invite command settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_exinvite)

@configure.command()
async def counters(ctx):
    """Automatic counters settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_counters)

@configure.command()
async def wild(ctx):
    """!wild reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_wild)

@configure.command()
async def research(ctx):
    """!research reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_research)

@configure.command(aliases=['event'])
async def meetup(ctx):
    """!meetup reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_meetup)

@configure.command()
async def subscriptions(ctx):
    """!subscription settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_subscriptions)

@configure.command()
async def pvp(ctx):
    """!pvp settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_pvp)

@configure.command()
async def join(ctx):
    """!join settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_join)

@configure.command()
async def lure(ctx):
    """!lure settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_lure)

@configure.command()
async def archive(ctx):
    """Configure !archive command settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_archive)

@configure.command(aliases=['settings'])
async def timezone(ctx):
    """Configure timezone and other settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_settings)

@configure.command()
async def trade(ctx):
    """!trade reporting settings"""
    return await _check_sessions_and_invoke(ctx, configuration._configure_trade)

@Kyogre.command()
@checks.is_owner()
async def reload_json(ctx):
    """Reloads the JSON files for the server

    Usage: !reload_json
    Useful to avoid a full restart if boss list changed"""
    load_config()
    await ctx.message.add_reaction('☑')

@Kyogre.command()
@checks.is_dev_or_owner()
async def raid_json(ctx, level=None, *, newlist=None):
    'Edits or displays raid_info.json\n\n    Usage: !raid_json [level] [list]'
    msg = ''
    if (not level) and (not newlist):
        for level in raid_info['raid_eggs']:
            msg += '\n**Level {level} raid list:** `{raidlist}` \n'.format(level=level, raidlist=raid_info['raid_eggs'][level]['pokemon'])
            for pkmn in raid_info['raid_eggs'][level]['pokemon']:
                p = Pokemon.get_pokemon(Kyogre, pkmn)
                msg += '{name} ({number})'.format(name=str(p), number=p.id)
                msg += ' '
            msg += '\n'
        return await ctx.channel.send(msg)
    elif level in raid_info['raid_eggs'] and (not newlist):
        msg += '**Level {level} raid list:** `{raidlist}` \n'.format(level=level, raidlist=raid_info['raid_eggs'][level]['pokemon'])
        for pkmn in raid_info['raid_eggs'][level]['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, pkmn)
            msg += '{name} ({number})'.format(name=str(p), number=p.id)
            msg += ' '
        msg += '\n'
        return await ctx.channel.send(msg)
    elif level in raid_info['raid_eggs'] and newlist:
        newlist = [re.sub(r'\'', '', item).strip() for item in newlist.strip('[]').split(',')]
        try:
            monlist = [Pokemon.get_pokemon(Kyogre, name).name.lower() for name in newlist]
        except:
            return await ctx.channel.send("I couldn't understand the list you supplied! Please use a comma-separated list of Pokemon species names.")
        msg += 'I will replace this:\n'
        msg += '**Level {level} raid list:** `{raidlist}` \n'.format(level=level, raidlist=raid_info['raid_eggs'][level]['pokemon'])
        for pkmn in raid_info['raid_eggs'][level]['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, pkmn)
            msg += '{name} ({number})'.format(name=p.name, number=p.id)
            msg += ' '
        msg += '\n\nWith this:\n'
        msg += '**Level {level} raid list:** `{raidlist}` \n'.format(level=level, raidlist=monlist)
        for p in monlist:
            p = Pokemon.get_pokemon(Kyogre, p)
            msg += '{name} ({number})'.format(name=p.name, number=p.id)
            msg += ' '
        msg += '\n\nContinue?'
        question = await ctx.channel.send(msg)
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(Kyogre, question, ctx.channel, ctx.author.id)
        except TypeError:
            timeout = True
        if timeout or res.emoji == '❎':
            return await ctx.channel.send("Configuration cancelled!")
        elif res.emoji == '✅':
            with open(os.path.join('data', 'raid_info.json'), 'r') as fd:
                data = json.load(fd)
            data['raid_eggs'][level]['pokemon'] = monlist
            with open(os.path.join('data', 'raid_info.json'), 'w') as fd:
                json.dump(data, fd, indent=2, separators=(', ', ': '))
            load_config()
            await question.clear_reactions()
            await question.add_reaction('☑')
            return await ctx.channel.send("Configuration successful!")
        else:
            return await ctx.channel.send("I'm not sure what went wrong, but configuration is cancelled!")

@Kyogre.command()
@commands.has_permissions(manage_guild=True)
async def reset_board(ctx, *, user=None, type=None):
    guild = ctx.guild
    trainers = guild_dict[guild.id]['trainers']
    tgt_string = ""
    tgt_trainer = None
    if user:
        converter = commands.MemberConverter()
        for argument in user.split():
            try:
                await ctx.channel.send(argument)
                tgt_trainer = await converter.convert(ctx, argument)
                tgt_string = tgt_trainer.display_name
            except:
                tgt_trainer = None
                tgt_string = "every user"
            if tgt_trainer:
                user = user.replace(argument,"").strip()
                break
        for argument in user.split():
            if "raid" in argument.lower():
                type = "raid_reports"
                break
            elif "egg" in argument.lower():
                type = "egg_reports"
                break
            elif "ex" in argument.lower():
                type = "ex_reports"
                break
            elif "wild" in argument.lower():
                type = "wild_reports"
                break
            elif "res" in argument.lower():
                type = "research_reports"
                break
            elif "join" in argument.lower():
                type = "joined"
                break
    if not type:
        type = "total_reports"
    if tgt_string == "":
        tgt_string = "all report types and all users"
    msg = "Are you sure you want to reset the **{type}** report stats for **{target}**?".format(type=type, target=tgt_string)
    question = await ctx.channel.send(msg)
    try:
        timeout = False
        res, reactuser = await utils.simple_ask(Kyogre, question, ctx.message.channel, ctx.message.author.id)
    except TypeError:
        timeout = True
    await question.delete()
    if timeout or res.emoji == '❎':
        return
    elif res.emoji == '✅':
        pass
    else:
        return
    regions = guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys()
    for region in regions:
        trainers.setdefault(region, {})
        for trainer in trainers[region]:
            if tgt_trainer:
                trainer = tgt_trainer.id
            if type == "total_reports":
                for rtype in trainers[region][trainer]:
                    trainers[region][trainer][rtype] = 0
            else:
                type_score = trainers[region][trainer].get(type, 0)
                type_score = 0
            if tgt_trainer:
                await ctx.send("{trainer}'s report stats have been cleared!".format(trainer=tgt_trainer.display_name))
                return
    await ctx.send("This server's report stats have been reset!")

@Kyogre.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def changeraid(ctx, newraid):
    """Changes raid boss.

    Usage: !changeraid <new pokemon or level>
    Only usable by admins."""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    return await changeraid_internal(ctx, guild, channel, newraid)

async def changeraid_internal(ctx, guild, channel, newraid):
    if (not channel) or (channel.id not in guild_dict[guild.id]['raidchannel_dict']):
        await channel.send('The channel you entered is not a raid channel.')
        return
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    if newraid.isdigit():
        raid_channel_name = '{egg_level}-egg_'.format(egg_level=newraid)
        raid_channel_name += utils.sanitize_name(raid_dict['address'])
        raid_dict['egglevel'] = newraid
        raid_dict['pokemon'] = ''
        changefrom = raid_dict['type']
        raid_dict['type'] = 'egg'
        egg_img = raid_info['raid_eggs'][newraid]['egg_img']
        boss_list = []
        for entry in raid_info['raid_eggs'][newraid]['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, entry)
            boss_list.append((((str(p) + ' (') + str(p.id)) + ') ') + ''.join(utils.types_to_str(guild, p.types, Kyogre.config)))
        raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'.format(str(egg_img))
        raid_message = await channel.fetch_message(raid_dict['raidmessage'])
        report_channel = Kyogre.get_channel(raid_dict['reportchannel'])
        report_message = await report_channel.fetch_message(raid_dict['raidreport'])
        raid_embed = raid_message.embeds[0]
        embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
        if embed_indices["possible"] is not None:
            index = embed_indices["possible"]
            raid_embed.set_field_at(index, name="**Possible Bosses:**", value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
            if len(boss_list) > 2:
                raid_embed.set_field_at(index+1, name='\u200b', value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
        else:
            raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
            if len(boss_list) > 2:
                raid_embed.add_field(name='\u200b', value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
        raid_embed.set_thumbnail(url=raid_img_url)
        if changefrom == "egg":
            raid_message.content = re.sub(r'level\s\d', 'Level {}'.format(newraid), raid_message.content, flags=re.IGNORECASE)
            report_message.content = re.sub(r'level\s\d', 'Level {}'.format(newraid), report_message.content, flags=re.IGNORECASE)
        else:
            raid_message.content = re.sub(r'.*\sraid\sreported','Level {} reported'.format(newraid), raid_message.content, flags=re.IGNORECASE)
            report_message.content = re.sub(r'.*\sraid\sreported','Level {}'.format(newraid), report_message.content, flags=re.IGNORECASE)
        await raid_message.edit(new_content=raid_message.content, embed=raid_embed, content=raid_message.content)
        try:
            raid_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices)
            await report_message.edit(new_content=report_message.content, embed=raid_embed, content=report_message.content)
            if raid_dict['raidcityreport'] is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                report_city_msg = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                await report_city_msg.edit(new_content=report_city_msg.content, embed=raid_embed, content=report_city_msg.content)
        except (discord.errors.NotFound, AttributeError):
            pass
        await channel.edit(name=raid_channel_name, topic=channel.topic)
    elif newraid and not newraid.isdigit():
        # What a hack, subtract raidtime from exp time because _eggtoraid will add it back
        egglevel = raid_dict['egglevel']
        if egglevel == "0":
            egglevel = Pokemon.get_pokemon(Kyogre, newraid).raid_level
        raid_dict['exp'] -= 60 * raid_info['raid_eggs'][egglevel]['raidtime']
        author = None
        author_id = raid_dict.get('reporter', None)
        if author_id is not None:
            author = guild.get_member(author_id)
        await _eggtoraid(ctx, newraid.lower(), channel, author=author)

@Kyogre.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def clearstatus(ctx):
    """Clears raid channel status lists.

    Usage: !clearstatus
    Only usable by admins."""
    msg = "Are you sure you want to clear all status for this raid? Everybody will have to RSVP again. If you are wanting to clear one user's status, use `!setstatus <user> cancel`"
    question = await ctx.channel.send(msg)
    try:
        timeout = False
        res, reactuser = await utils.simple_ask(Kyogre, question, ctx.message.channel, ctx.message.author.id)
    except TypeError:
        timeout = True
    await question.delete()
    if timeout or res.emoji == '❎':
        return
    elif res.emoji == '✅':
        pass
    else:
        return
    try:
        guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'] = {}
        await ctx.channel.send('Raid status lists have been cleared!')
    except KeyError:
        pass

@Kyogre.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def setstatus(ctx, member: discord.Member, status,*, status_counts: str = ''):
    """Changes raid channel status lists.

    Usage: !setstatus <user> <status> [count]
    User can be a mention or ID number. Status can be maybeinterested/i, coming/c, here/h, or cancel/x
    Only usable by admins."""
    valid_status_list = ['interested', 'i', 'maybe', 'coming', 'c', 'here', 'h', 'cancel','x']
    if status not in valid_status_list:
        await ctx.message.channel.send("{status} is not a valid status!").format(status=status)
        return
    ctx.message.author = member
    ctx.message.content = "{}{} {}".format(ctx.prefix, status, status_counts)
    await ctx.bot.process_commands(ctx.message)

@Kyogre.command()
@checks.allowarchive()
async def archive(ctx):
    """Marks a raid channel for archival.

    Usage: !archive"""
    message = ctx.message
    channel = message.channel
    await ctx.message.delete()
    await _archive(channel)

async def _archive(channel):
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['archive'] = True
    await asyncio.sleep(10)
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['archive'] = True

"""
Miscellaneous
"""

@Kyogre.command(name='uptime')
async def cmd_uptime(ctx):
    "Shows Kyogre's uptime"
    guild = ctx.guild
    channel = ctx.channel
    embed_colour = guild.me.colour or discord.Colour.lighter_grey()
    uptime_str = await _uptime(Kyogre)
    embed = discord.Embed(colour=embed_colour, icon_url=Kyogre.user.avatar_url)
    embed.add_field(name='Uptime', value=uptime_str)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        await channel.send('I need the `Embed links` permission to send this')

async def _uptime(bot):
    'Shows info about Kyogre'
    time_start = bot.uptime
    time_now = datetime.datetime.now()
    ut = relativedelta(time_now, time_start)
    (ut.years, ut.months, ut.days, ut.hours, ut.minutes)
    if ut.years >= 1:
        uptime = '{yr}y {mth}m {day}d {hr}:{min}'.format(yr=ut.years, mth=ut.months, day=ut.days, hr=ut.hours, min=ut.minutes)
    elif ut.months >= 1:
        uptime = '{mth}m {day}d {hr}:{min}'.format(mth=ut.months, day=ut.days, hr=ut.hours, min=ut.minutes)
    elif ut.days >= 1:
        uptime = '{day} days {hr} hrs {min} mins'.format(day=ut.days, hr=ut.hours, min=ut.minutes)
    elif ut.hours >= 1:
        uptime = '{hr} hrs {min} mins {sec} secs'.format(hr=ut.hours, min=ut.minutes, sec=ut.seconds)
    else:
        uptime = '{min} mins {sec} secs'.format(min=ut.minutes, sec=ut.seconds)
    return uptime

@Kyogre.command()
async def about(ctx):
    'Shows info about Kyogre'
    repo_url = 'https://github.com/klords/Kyogre'
    owner = Kyogre.owner
    channel = ctx.channel
    uptime_str = await _uptime(Kyogre)
    yourserver = ctx.message.guild.name
    yourmembers = len(ctx.message.guild.members)
    embed_colour = ctx.guild.me.colour or discord.Colour.lighter_grey()
    about = "I'm Kyogre! A Pokemon Go helper bot for Discord!\n\nI'm a variant of the open-source Kyogre bot made by FoglyOgly.\n\nFor questions or feedback regarding Kyogre, please contact us on [our GitHub repo]({repo_url})\n\n".format(repo_url=repo_url)
    member_count = 0
    guild_count = 0
    for guild in Kyogre.guilds:
        guild_count += 1
        member_count += len(guild.members)
    embed = discord.Embed(colour=embed_colour, icon_url=Kyogre.user.avatar_url)
    embed.add_field(name='About Kyogre', value=about, inline=False)
    embed.add_field(name='Owner', value=owner)
    if guild_count > 1:
        embed.add_field(name='Servers', value=guild_count)
        embed.add_field(name='Members', value=member_count)
    embed.add_field(name="Your Server", value=yourserver)
    embed.add_field(name="Your Members", value=yourmembers)
    embed.add_field(name='Uptime', value=uptime_str)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        await channel.send('I need the `Embed links` permission to send this')

@Kyogre.command()
@checks.allowteam()
async def team(ctx,*,content):
    """Set your team role.

    Usage: !team <team name>
    The team roles have to be created manually beforehand by the server administrator."""
    guild = ctx.guild
    toprole = guild.me.top_role.name
    position = guild.me.top_role.position
    team_msg = ' or '.join(['**!team {0}**'.format(team) for team in config['team_dict'].keys()])
    high_roles = []
    guild_roles = []
    lowercase_roles = []
    harmony = None
    for role in guild.roles:
        if (role.name.lower() in config['team_dict']) and (role.name not in guild_roles):
            guild_roles.append(role.name)
    lowercase_roles = [element.lower() for element in guild_roles]
    for team in config['team_dict'].keys():
        if team.lower() not in lowercase_roles:
            try:
                temp_role = await guild.create_role(name=team.lower(), hoist=False, mentionable=True)
                guild_roles.append(team.lower())
            except discord.errors.HTTPException:
                await ctx.channel.send('Maximum guild roles reached.')
                return
            if temp_role.position > position:
                high_roles.append(temp_role.name)
    if high_roles:
        await ctx.channel.send('My roles are ranked lower than the following team roles: **{higher_roles_list}**\nPlease get an admin to move my roles above them!'.format(higher_roles_list=', '.join(high_roles)))
        return
    role = None
    team_split = content.lower().split()
    entered_team = team_split[0]
    entered_team = ''.join([i for i in entered_team if i.isalpha()])
    if entered_team in lowercase_roles:
        index = lowercase_roles.index(entered_team)
        role = discord.utils.get(ctx.guild.roles, name=guild_roles[index])
    if 'harmony' in lowercase_roles:
        index = lowercase_roles.index('harmony')
        harmony = discord.utils.get(ctx.guild.roles, name=guild_roles[index])
    # Check if user already belongs to a team role by
    # getting the role objects of all teams in team_dict and
    # checking if the message author has any of them.    for team in guild_roles:
    for team in guild_roles:
        temp_role = discord.utils.get(ctx.guild.roles, name=team)
        if temp_role:
            # and the user has this role,
            if (temp_role in ctx.author.roles) and (harmony not in ctx.author.roles):
                # then report that a role is already assigned
                await ctx.channel.send('You already have a team role!')
                return
            if role and (role.name.lower() == 'harmony') and (harmony in ctx.author.roles):
                # then report that a role is already assigned
                await ctx.channel.send('You are already in Team Harmony!')
                return
        # If the role isn't valid, something is misconfigured, so fire a warning.
        else:
            await ctx.channel.send('{team_role} is not configured as a role on this server. Please contact an admin for assistance.'.format(team_role=team))
            return
    # Check if team is one of the three defined in the team_dict
    if entered_team not in config['team_dict'].keys():
        await ctx.channel.send('"{entered_team}" isn\'t a valid team! Try {available_teams}'.format(entered_team=entered_team, available_teams=team_msg))
        return
    # Check if the role is configured on the server
    elif role == None:
        await ctx.channel.send('The "{entered_team}" role isn\'t configured on this server! Contact an admin!'.format(entered_team=entered_team))
    else:
        try:
            if harmony and (harmony in ctx.author.roles):
                await ctx.author.remove_roles(harmony)
            await ctx.author.add_roles(role)
            await ctx.channel.send('Added {member} to Team {team_name}! {team_emoji}'.format(member=ctx.author.mention, team_name=role.name.capitalize(), team_emoji=utils.parse_emoji(ctx.guild, config['team_dict'][entered_team])))
            await ctx.author.send("Now that you've set your team, head to <#538883360953729025> to set up your desired regions")
        except discord.Forbidden:
            await ctx.channel.send("I can't add roles!")

@Kyogre.command(hidden=True)
async def profile(ctx, user: discord.Member = None):
    """Displays a user's social and reporting profile.

    Usage:!profile [user]"""
    if not user:
        user = ctx.message.author
    silph = guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).setdefault(user.id,{}).get('silphid',None)
    if silph:
        card = "Traveler Card"
        silph = f"[{card}](https://sil.ph/{silph.lower()})"
    raids, eggs, wilds, research, joined = await temp(ctx, user)
    embed = discord.Embed(title="{user}\'s Trainer Profile".format(user=user.display_name), colour=user.colour)
    embed.set_thumbnail(url=user.avatar_url)
    embed.add_field(name="Silph Road", value=f"{silph}", inline=True)
    embed.add_field(name="Pokebattler", value=f"{guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).get('pokebattlerid',None)}", inline=True)
    embed.add_field(name="Raid Reports", value=f"{raids}", inline=True)
    embed.add_field(name="Egg Reports", value=f"{eggs}", inline=True)
    embed.add_field(name="Wild Reports", value=f"{wilds}", inline=True)
    embed.add_field(name="Research Reports", value=f"{research}", inline=True)
    embed.add_field(name="Raids Joined", value=f"{joined}", inline=True)
    await ctx.send(embed=embed)

async def temp(ctx, user):
    regions = guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys()
    raids, eggs, wilds, research, joined = 0, 0, 0, 0, 0
    for region in regions:
        raids += guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('raid_reports',0)
        eggs += guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('egg_reports',0)
        wilds += guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('wild_reports',0)
        research += guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('research_reports',0)
        joined += guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('joined',0)
    return [raids, eggs, wilds, research, joined]
    await ctx.channel.send(raids)
    await ctx.channel.send(eggs)
    await ctx.channel.send(wilds)
    await ctx.channel.send(research)
    await ctx.channel.send(joined)

@Kyogre.command()
async def leaderboard(ctx, type="total", region=None):
    """Displays the top ten reporters of a server.

    Usage: !leaderboard [type] [region]
    Accepted types: raids, eggs, wilds, research, joined
    Region must be any configured region"""
    guild = ctx.guild
    leaderboard = {}
    rank = 1
    field_value = ""
    typelist = ["total", "raids", "eggs", "exraids", "wilds", "research", "joined"]
    type = type.lower()
    regions = list(guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
    if type not in typelist:
        if type in regions:
            region = type
            type = "total"
        else:
            return await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Leaderboard type not supported. Please select from: **{', '.join(typelist)}**"))
    if region is not None:
        region = region.lower()
        if region in regions:
            regions = [region]
        else:
            return await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No region found with name {region}"))
    for region in regions:
        trainers = copy.deepcopy(guild_dict[guild.id]['trainers'].setdefault(region, {}))
        for trainer in trainers.keys():
            user = guild.get_member(trainer)
            if user is None:
                continue
            raids, wilds, exraids, eggs, research, joined = 0, 0, 0, 0, 0, 0
            
            raids += trainers[trainer].setdefault('raid_reports', 0)
            wilds += trainers[trainer].setdefault('wild_reports', 0)
            exraids += trainers[trainer].setdefault('ex_reports', 0)
            eggs += trainers[trainer].setdefault('egg_reports', 0)
            research += trainers[trainer].setdefault('research_reports', 0)
            joined += trainers[trainer].setdefault('joined', 0)
            total_reports = raids + wilds + exraids + eggs + research + joined
            trainer_stats = {'trainer':trainer, 'total':total_reports, 'raids':raids, 'wilds':wilds, 'research':research, 'exraids':exraids, 'eggs':eggs, 'joined':joined}
            if trainer_stats[type] > 0 and user:
                if trainer in leaderboard:
                    leaderboard[trainer] = combine_dicts(leaderboard[trainer], trainer_stats)
                else:
                    leaderboard[trainer] = trainer_stats
    leaderboardlist = []
    for key, value in leaderboard.items():
        leaderboardlist.append(value)
    leaderboardlist = sorted(leaderboardlist,key= lambda x: x[type], reverse=True)[:10]
    embed = discord.Embed(colour=guild.me.colour)
    leaderboard_title = f"Reporting Leaderboard ({type.title()})"
    if len(regions) == 1:
        leaderboard_title += f" {region.capitalize()}"
    embed.set_author(name=leaderboard_title, icon_url=Kyogre.user.avatar_url)
    for trainer in leaderboardlist:
        user = guild.get_member(int(trainer['trainer']))
        if user:
            if guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                field_value += "Raids: **{raids}** | Eggs: **{eggs}** | ".format(raids=trainer['raids'], eggs=trainer['eggs'])
            if guild_dict[guild.id]['configure_dict']['exraid']['enabled']:
                field_value += "EX Raids: **{exraids}** | ".format(exraids=trainer['exraids'])
            if guild_dict[guild.id]['configure_dict']['wild']['enabled']:
                field_value += "Wilds: **{wilds}** | ".format(wilds=trainer['wilds'])
            if guild_dict[guild.id]['configure_dict']['research']['enabled']:
                field_value += "Research: **{research}** | ".format(research=trainer['research'])
            if guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                field_value += "Raids Joined: **{joined}** | ".format(joined=trainer['joined'])
            embed.add_field(name=f"{rank}. {user.display_name} - {type.title()}: **{trainer[type]}**", value=field_value[:-3], inline=False)
            field_value = ""
            rank += 1
    if len(embed.fields) == 0:
        embed.add_field(name="No Reports", value="Nobody has made a report or this report type is disabled.")
    await ctx.send(embed=embed)

def combine_dicts(a, b):
    for key,value in a.items():
        if key != 'trainer':
            a[key] = a[key] + b[key]
    return a

@Kyogre.command(aliases=["invite"])
@checks.allowjoin()
async def join(ctx):
    channel = ctx.message.channel
    guild = ctx.message.guild
    join_dict = guild_dict[guild.id]['configure_dict'].setdefault('join')
    if join_dict.get('enabled', False):
        return await channel.send(join_dict['link'])

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

"""
PVP
"""
@Kyogre.group(name="pvp", case_insensitive=True)
@checks.allowpvp()
async def _pvp(ctx):
    """Handles pvp related commands"""

    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()

@_pvp.command(name="available", aliases=["av"])
async def _pvp_available(ctx, exptime=None):
    """Announces that you're available for pvp
    Usage: `!pvp available [time]`
    Kyogre will post a message stating that you're available for PvP
    for the next 30 minutes by default, or optionally for the amount 
    of time you provide.

    Kyogre will also notify any other users who have added you as 
    a friend that you are now available.
    """
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author

    time_msg = None
    expiration_minutes = False
    if exptime:
        if exptime.isdigit():
            expiration_minutes = await time_to_minute_count(channel, exptime)
    else:
        time_err = "No expiration time provided, your PvP session will remain active for 30 minutes"
    if expiration_minutes is False:
        time_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=time_err))
        expiration_minutes = 30

    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    expire = now + datetime.timedelta(minutes=expiration_minutes)

    league_text = ""
    prompt = 'Do you have a League Preference?'
    choices_list = ['Great League', 'Ultra League', 'Master League', 'Other', 'No Preference']
    match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=trainer.id)
    if match in choices_list:
        if match == choices_list[3]:
            specifiy_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Please specify your battle criteria:"))
            try:
                pref_msg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == trainer))
            except asyncio.TimeoutError:
                pref_msg = None
                await specifiy_msg.delete()
            if pref_msg:
                league_text = pref_msg.clean_content
                await specifiy_msg.delete()
                await pref_msg.delete()
        else:
            league_text = match
    else:
        league_text = choices_list[3]

    pvp_embed = discord.Embed(title='{trainer} is available for PvP!'.format(trainer=trainer.display_name), colour=guild.me.colour)

    pvp_embed.add_field(name='**Expires:**', value='{end}'.format(end=expire.strftime('%I:%M %p')), inline=True)
    pvp_embed.add_field(name='**League Preference:**', value='{league}'.format(league=league_text), inline=True)
    pvp_embed.add_field(name='**To challenge:**', value='Use the \u2694 react.', inline=True)
    pvp_embed.add_field(name='**To cancel:**', value='Use the 🚫 react.', inline=True)
    pvp_embed.set_footer(text='{trainer}'.format(trainer=trainer.display_name), icon_url=trainer.avatar_url_as(format=None, static_format='jpg', size=32))
    pvp_embed.set_thumbnail(url="https://github.com/KyogreBot/Kyogre/blob/master/images/misc/pvpn_large.png?raw=true")

    pvp_msg = await channel.send(content=('{trainer} is available for PvP!').format(trainer=trainer.display_name),embed=pvp_embed)
    await pvp_msg.add_reaction('\u2694')
    await pvp_msg.add_reaction('🚫')
    
    expiremsg = '**{trainer} is no longer available for PvP!**'.format(trainer=trainer.display_name)
    pvp_dict = copy.deepcopy(guild_dict[guild.id].get('pvp_dict',{}))
    pvp_dict[pvp_msg.id] = {
        'exp':time.time() + (expiration_minutes * 60),
        'expedit': {"content":"","embedcontent":expiremsg},
        'reportmessage':message.id,
        'reportchannel':channel.id,
        'reportauthor':trainer.id,
    }
    guild_dict[guild.id]['pvp_dict'] = pvp_dict
    await _send_pvp_notification_async(ctx)
    event_loop.create_task(pvp_expiry_check(pvp_msg))
    if time_msg is not None:
        await asyncio.sleep(10)
        await time_msg.delete()
    

async def _send_pvp_notification_async(ctx):
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = guild.get_member(message.author.id)
    trainer_info_dict = guild_dict[guild.id]['trainers'].setdefault('info', {})
    friends = trainer_info_dict.setdefault(message.author.id, {}).setdefault('friends', [])
    outbound_dict = {}
    tag_msg = f'**{trainer.mention}** wants to battle! Who will challenge them?!'
    for friend in friends:
        friend = guild.get_member(friend)
        outbound_dict[friend.id] = {'discord_obj': friend, 'message': tag_msg}
    role_name = utils.sanitize_name(f"pvp {trainer.name}")
    return await _generate_role_notification_async(role_name, channel, outbound_dict)

@_pvp.command(name="add")
async def _pvp_add_friend(ctx, *, friends):
    """Adds another user as a friend to your friends list
    Usage: `!pvp add <friend>`
    Usage: `!pvp add AshKetchum#1234, ProfessorOak#5309`

    Kyogre will add the friends you list to your friends list.
    Whenever one of your friends announces they are available to
    battle, Kyogre will notify you.

    Provide any number of friends using their discord name including
    the "#0000" discriminator with a comma between each name
    """
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author
    trainer_dict = copy.deepcopy(guild_dict[guild.id]['trainers'])
    trainer_info_dict = trainer_dict.setdefault('info', {})
    friend_list = set([r for r in re.split(r'\s*,\s*', friends.strip()) if r])
    if len(friend_list) < 1:
        err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please provide the name of at least one other trainer.\n\
            Name should be the `@mention` of another Discord user.'))
        await asyncio.sleep(15)
        await message.delete()
        await err_msg.delete()
    friend_list_success = []
    friend_list_errors = []
    friend_list_exist = []
    for user in friend_list:
        try:
            tgt_trainer = await commands.MemberConverter().convert(ctx, user.strip())
        except:
            friend_list_errors.append(user)
            continue
        if tgt_trainer is not None:
            tgt_friends = trainer_info_dict.setdefault(tgt_trainer.id, {}).setdefault('friends', [])
            if trainer.id not in tgt_friends:
                tgt_friends.append(trainer.id)
                friend_list_success.append(user)
            else:
                friend_list_exist.append(user)
        else:
            friend_list_errors.append(user)
    failed_msg = None
    exist_msg = None
    success_msg = None
    if len(friend_list_errors) > 0:
        failed_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Unable to find the following users:\n\
            {', '.join(friend_list_errors)}"))
        await message.add_reaction('👍')
    if len(friend_list_exist) > 0:
        exist_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=f"You're already friends with the following users:\n\
            {', '.join(friend_list_exist)}"))
        await message.add_reaction('👍')
    if len(friend_list_success) > 0:
        success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully added the following friends:\n\
            {', '.join(friend_list_success)}"))
        guild_dict[guild.id]['trainers'] = trainer_dict
        await message.add_reaction('✅')
    await asyncio.sleep(10)
    if failed_msg is not None:
        await failed_msg.delete()
    if exist_msg is not None:
        await exist_msg.delete()
    if success_msg is not None:
        await success_msg.delete()
    return


@_pvp.command(name="remove", aliases=["rem"])
async def _pvp_remove_friend(ctx, *, friends: str = ''):
    """Remove a user from your friends list

    Usage: `!pvp [remove|rem] <friend>`
    Usage: `!pvp add AshKetchum#1234, ProfessorOak#5309`

    Kyogre will remove the friends you list from your friends list.

    Provide any number of friends using their discord name including
    the "#0000" discriminator with a comma between each name
    """
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author
    trainer_dict = copy.deepcopy(guild_dict[guild.id]['trainers'])
    trainer_info_dict = trainer_dict.setdefault('info', {})
    friend_list = set([r for r in re.split(r'\s*,\s*', friends.strip()) if r])
    if len(friend_list) < 1:
        err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please provide the name of at least one other trainer.\n\
            Name should be the `@mention` of another Discord user.'))
        await asyncio.sleep(15)
        await message.delete()
        await err_msg.delete()
    friend_list_success = []
    friend_list_errors = []
    friend_list_notexist = []
    for user in friend_list:
        try:
            tgt_trainer = await commands.MemberConverter().convert(ctx, user.strip())
        except:
            friend_list_errors.append(user)
            continue
        if tgt_trainer is not None:
            tgt_friends = trainer_info_dict.setdefault(tgt_trainer.id, {}).setdefault('friends', [])
            if trainer.id in tgt_friends:
                tgt_friends.remove(trainer.id)
                friend_list_success.append(user)
            else:
                friend_list_notexist.append(user)
        else:
            friend_list_errors.append(user)
    
    failed_msg = None
    notexist_msg = None
    success_msg = None
    if len(friend_list_errors) > 0:
        failed_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Unable to find the following users:\n\
            {', '.join(friend_list_errors)}"))
        await message.add_reaction('👍')
    if len(friend_list_notexist) > 0:
        notexist_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=f"You're not friends with the following users:\n\
            {', '.join(friend_list_notexist)}"))
        await message.add_reaction('👍')
    if len(friend_list_success) > 0:
        success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully removed the following friends:\n\
            {', '.join(friend_list_success)}"))
        guild_dict[guild.id]['trainers'] = trainer_dict
        await message.add_reaction('✅')
    await asyncio.sleep(10)
    if failed_msg is not None:
        await failed_msg.delete()
    if notexist_msg is not None:
        await notexist_msg.delete()
    if success_msg is not None:
        await success_msg.delete()
    return

"""
Notifications
"""

def _get_subscription_command_error(content, subscription_types):
    error_message = None

    if ' ' not in content:
        return "Both a subscription type and target must be provided! Type `!help sub (add|remove|list)` for more details!"

    subscription, target = content.split(' ', 1)

    if subscription not in subscription_types:
        error_message = "{subscription} is not a valid subscription type!".format(subscription=subscription.title())

    if target == 'list':
        error_message = "`list` is not a valid target. Did you mean `!sub list`?"
    
    return error_message

async def _parse_subscription_content(content, source, message = None):
    channel = message.channel
    author = message.author.id 
    sub_list = []
    error_list = []
    raid_level_list = [str(n) for n in list(range(1, 6))]
    sub_type, target = content.split(' ', 1)

    if sub_type == 'gym':
        if message:
            channel = message.channel
            guild = message.guild
            trainer = message.author.id
            gyms = get_gyms(guild.id)
            if gyms:
                gym_dict = {}
                for t in target.split(','):
                    gym = await location_match_prompt(channel, trainer, t, gyms)
                    if gym:
                        if source == 'add':
                            question_spec = 'would you like to be notified'
                        else:
                            question_spec = 'would you like to remove notifications'
                        level = await utils.ask_list(Kyogre, f"For {gym.name} which level raids {question_spec}?",
                                                     channel, ['All'] + list(range(1, 6)),
                                                     user_list=[author], multiple=True)
                        if level:
                            if 'All' in level:
                                level = list(range(1, 6))
                            for l in level:
                                gym_level_dict = gym_dict.get(l, {'ids': [], 'names': []})
                                gym_level_dict['ids'].append(gym.id)
                                gym_level_dict['names'].append(gym.name)
                                gym_dict[l] = gym_level_dict
                        else:
                            error_list.append(t)
                    else:
                        error_list.append(t)
                for l in gym_dict.keys():
                    entry = f"L{l} Raids at {', '.join(gym_dict[l]['names'])}"
                    sub_list.append(('gym', l, entry, gym_dict[l]['ids']))
            return sub_list, error_list
    if sub_type == 'item':
        result = RewardTable.select(RewardTable.name,RewardTable.quantity)
        result = result.objects(Reward)
        results = [o for o in result]
        item_names = [r.name.lower() for r in results]
        targets = target.split(',')
        for t in targets:
            candidates = utils.get_match(item_names, t, score_cutoff=60, isPartial=True, limit=20)
            name = await prompt_match_result(channel, author, t, candidates)
            if name is not None:
                sub_list.append((sub_type, name, name))
            else:
                error_list.append(t)
        return sub_list, error_list
    if sub_type == 'wild':
        perfect_pattern = r'((100(\s*%)?|perfect)(\s*ivs?\b)?)'
        target, count = re.subn(perfect_pattern, '', target, flags=re.I)
        if count:
            sub_list.append((sub_type, 'perfect', 'Perfect IVs'))

    if sub_type == 'lure':
        result = LureTypeTable.select(LureTypeTable.name)
        result = result.objects(Lure)
        results = [o for o in result]
        lure_names = [r.name.lower() for r in results]
        targets = target.split(',')
        for t in targets:
            candidates = utils.get_match(lure_names, t, score_cutoff=60, isPartial=True, limit=20)
            name = await prompt_match_result(channel, author, t, candidates)
            if name is not None:
                sub_list.append((sub_type, name, name))
            else:
                error_list.append(t)
        return sub_list, error_list
            
    if ',' in target:
        target = set([t.strip() for t in target.split(',')])
    else:
        target = set([target])

    if sub_type == 'raid':
        ex_pattern = r'^(ex([- ]*eligible)?)$'
        ex_r = re.compile(ex_pattern, re.I)
        matches = list(filter(ex_r.match, target))
        if matches:
            entry = 'EX-Eligible Raids'
            for match in matches:
                target.remove(match)
            sub_list.append((sub_type, 'ex-eligible', entry))
    
    for name in target:
        pkmn = Pokemon.get_pokemon(Kyogre, name)
        if pkmn:
            sub_list.append((sub_type, pkmn.name, pkmn.name))
        else:
            error_list.append(name)
    
    return sub_list, error_list


@Kyogre.group(name="subscription", aliases=["sub"])
@checks.allowsubscription()
async def _sub(ctx):
    """Handles user subscriptions"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()


@_sub.command(name="add")
async def _sub_add(ctx, *, content):
    """Create a subscription

    Usage: !sub add <type> <target>
    Kyogre will send you a notification if an event is generated
    matching the details of your subscription.
    
    Valid types are: pokemon, raid, research, wild, and gym
    Note: 'Pokemon' includes raid, research, and wild reports"""
    subscription_types = ['pokemon','raid','research','wild','nest','gym','shiny','item','lure']
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author.id
    error_list = []

    content = content.strip().lower()
    if content == 'shiny':
        candidate_list = [('shiny', 'shiny', 'shiny')]
    else:
        error_message = _get_subscription_command_error(content, subscription_types)
        if error_message:
            response = await message.channel.send(error_message)
            return await utils.sleep_and_cleanup([message, response], 10)

        candidate_list, error_list = await _parse_subscription_content(content, 'add', message)
    
    existing_list = []
    sub_list = []

    for sub in candidate_list:
        s_type = sub[0]
        s_target = sub[1]
        s_entry = sub[2]
        if len(sub) > 3:
            spec = sub[3]
            try:
                result, __ = SubscriptionTable.get_or_create(trainer=trainer, type=s_type, target=s_target)
                current_gym_ids = result.specific
                if current_gym_ids:
                    current_gym_ids = current_gym_ids.strip('[').strip(']')
                    split_ids = current_gym_ids.split(', ')
                    split_ids = [int(s) for s in split_ids]
                else:
                    split_ids = []
                spec = [int(s) for s in spec]
                new_ids = set(split_ids + spec)
                result.specific = list(new_ids)
                if len(result.specific) > 0:
                    result.save()
                    sub_list.append(s_entry)
            except:
                error_list.append(s_entry)
        else:
            try:
                SubscriptionTable.create(trainer=trainer, type=s_type, target=s_target)
                sub_list.append(s_entry)
            except IntegrityError:
                existing_list.append(s_entry)
            except:
                error_list.append(s_entry)

    sub_count = len(sub_list)
    existing_count = len(existing_list)
    error_count = len(error_list)

    confirmation_msg = '{member}, successfully added {count} new subscriptions'.format(member=ctx.author.mention, count=sub_count)
    if sub_count > 0:
        confirmation_msg += '\n**{sub_count} Added:** \n\t{sub_list}'.format(sub_count=sub_count, sub_list=',\n'.join(sub_list))
    if existing_count > 0:
        confirmation_msg += '\n**{existing_count} Already Existing:** \n\t{existing_list}'.format(existing_count=existing_count, existing_list=', '.join(existing_list))
    if error_count > 0:
        confirmation_msg += '\n**{error_count} Errors:** \n\t{error_list}\n(Check the spelling and try again)'.format(error_count=error_count, error_list=', '.join(error_list))

    await channel.send(content=confirmation_msg)


@_sub.command(name="remove", aliases=["rm", "rem"])
async def _sub_remove(ctx,*,content):
    """Remove a subscription

    Usage: !sub remove <type> <target>
    You will no longer be notified of the specified target for the given event type.

    You can remove all subscriptions of a type:
    !sub remove <type> all

    Or remove all subscriptions:
    !sub remove all all"""
    subscription_types = ['all','pokemon','raid','research','wild','nest','gym','shiny','item','lure']
    message = ctx.message
    channel = message.channel
    guild = message.guild
    trainer = message.author.id

    content = content.strip().lower()
    if content == 'shiny':
        sub_type, target = ['shiny','shiny']
    else:
        error_message = _get_subscription_command_error(content, subscription_types)
        if error_message:
            response = await message.channel.send(error_message)
            return await utils.sleep_and_cleanup([message,response], 10)
        sub_type, target = content.split(' ', 1)

    candidate_list = []
    error_list = []
    not_found_list = []
    remove_list = []

    trainer_query = (TrainerTable
                        .select(TrainerTable.snowflake)
                        .where((TrainerTable.snowflake == trainer) & 
                        (TrainerTable.guild == guild.id)))

    # check for special cases
    skip_parse = False
    
    if sub_type == 'all':
        if target == 'all':
            try:
                remove_count = SubscriptionTable.delete().where((SubscriptionTable.trainer << trainer_query)).execute()
                message = f'I removed your {remove_count} subscriptions!'
            except:
                message = 'I was unable to remove your subscriptions!'
            confirmation_msg = f'{message}'
            await channel.send(content=confirmation_msg)
            return
        else:
            target = target.split(',')
            if sub_type == 'pokemon':
                for name in target:
                    pkmn = Pokemon.get_pokemon(Kyogre, name)
                    if pkmn:
                        candidate_list.append((sub_type, pkmn.name, pkmn.name))
                    else:
                        error_list.append(name)
            if sub_type != "gym":
                skip_parse = True
    elif target == 'all':
        candidate_list.append((sub_type, target, target))
        skip_parse = True
    elif target == 'shiny':
        candidate_list = [('shiny', 'shiny', 'shiny')]
        sub_type, target = ['shiny','shiny']
        skip_parse = True
    if not skip_parse:
        candidate_list, error_list = await _parse_subscription_content(content, 'remove', message)
    remove_count = 0
    for sub in candidate_list:
        s_type = sub[0]
        s_target = sub[1]
        s_entry = sub[2]
        if len(sub) > 3:
            spec = sub[3]
            try:
                result, __ = SubscriptionTable.get_or_create(trainer=trainer, type='gym', target=s_target)
                current_gym_ids = result.specific
                if current_gym_ids:
                    current_gym_ids = current_gym_ids.strip('[').strip(']')
                    split_ids = current_gym_ids.split(', ')
                    split_ids = [int(s) for s in split_ids]
                else:
                    split_ids = []
                for s in spec:
                    if s in split_ids:
                        remove_count += 1
                        split_ids.remove(s)
                result.specific = split_ids
                result.save()
                remove_list.append(s_entry)
            except:
                error_list.append(s_entry)
        else:
            try:
                if s_type == 'all':
                    remove_count += SubscriptionTable.delete().where(
                        (SubscriptionTable.trainer << trainer_query) &
                        (SubscriptionTable.target == s_target)).execute()
                elif s_target == 'all':
                    remove_count += SubscriptionTable.delete().where(
                        (SubscriptionTable.trainer << trainer_query) &
                        (SubscriptionTable.type == s_type)).execute()
                else:
                    remove_count += SubscriptionTable.delete().where(
                        (SubscriptionTable.trainer << trainer_query) &
                        (SubscriptionTable.type == s_type) &
                        (SubscriptionTable.target == s_target)).execute()
                if remove_count > 0:
                    remove_list.append(s_entry)
                else:
                    not_found_list.append(s_entry)
            except:
                error_list.append(s_entry)

    not_found_count = len(not_found_list)
    error_count = len(error_list)

    confirmation_msg = '{member}, successfully removed {count} subscriptions'\
        .format(member=ctx.author.mention, count=remove_count)
    if remove_count > 0:
        confirmation_msg += '\n**{remove_count} Removed:** \n\t{remove_list}'\
            .format(remove_count=remove_count, remove_list=',\n'.join(remove_list))
    if not_found_count > 0:
        confirmation_msg += '\n**{not_found_count} Not Found:** \n\t{not_found_list}'\
            .format(not_found_count=not_found_count, not_found_list=', '.join(not_found_list))
    if error_count > 0:
        confirmation_msg += '\n**{error_count} Errors:** \n\t{error_list}\n(Check the spelling and try again)'\
            .format(error_count=error_count, error_list=', '.join(error_list))
    await channel.send(content=confirmation_msg)


@_sub.command(name="list", aliases=["ls"])
async def _sub_list(ctx, *, content=None):
    """List the subscriptions for the user

    Usage: !sub list <type> 
    Leave type empty to receive complete list of all subscriptions.
    Or include a type to receive a specific list
    Valid types are: pokemon, raid, research, wild, and gym"""
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = message.guild
    subscription_types = ['pokemon','raid','research','wild','nest','gym','item']
    response_msg = ''
    invalid_types = []
    valid_types = []
    results = (SubscriptionTable
                .select(SubscriptionTable.type, SubscriptionTable.target, SubscriptionTable.specific)
                .join(TrainerTable, on=(SubscriptionTable.trainer == TrainerTable.snowflake))
                .where(SubscriptionTable.trainer == ctx.author.id)
                .where(TrainerTable.guild == ctx.guild.id))

    if content:
        sub_types = [re.sub('[^A-Za-z]+', '', s.lower()) for s in content.split(',')]
        for s in sub_types:
            if s in subscription_types:
                valid_types.append(s)
            else:
                invalid_types.append(s)

        if valid_types:
            results = results.where(SubscriptionTable.type << valid_types)
        else:
            response_msg = "No valid subscription types found! Valid types are: {types}".format(types=', '.join(subscription_types))
            response = await channel.send(response_msg)
            return await utils.sleep_and_cleanup([message,response], 10)
        
        if invalid_types:
            response_msg = "\nUnable to find these subscription types: {inv}".format(inv=', '.join(invalid_types))
    
    results = results.execute()
        
    response_msg = f"{author.mention}, check your inbox! I've sent your subscriptions to you directly!" + response_msg
    types = set([s.type for s in results])
    for r in results:
        if r.specific:
            current_gym_ids = r.specific.strip('[').strip(']')
            split_ids = current_gym_ids.split(', ')
            split_ids = [int(s) for s in split_ids]
            gyms = (GymTable
                    .select(LocationTable.id,
                            LocationTable.name, 
                            LocationTable.latitude, 
                            LocationTable.longitude, 
                            RegionTable.name.alias('region'),
                            GymTable.ex_eligible,
                            LocationNoteTable.note)
                    .join(LocationTable)
                    .join(LocationRegionRelation)
                    .join(RegionTable)
                    .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                    .where((LocationTable.guild == guild.id) &
                           (LocationTable.guild == RegionTable.guild) &
                           (LocationTable.id << split_ids)))
            result = gyms.objects(Gym)
            r.specific = ",\n\t".join([o.name for o in result])
    subscriptions = {}
    for t in types:
        if t == 'gym':
            for r in results:
                if r.type == 'gym':
                    if r.specific:
                        subscriptions[f"Level {r.target} Raids at"] = r.specific
                    else:
                        msg = subscriptions.get('gym', "")
                        if len(msg) < 1:
                            msg = r.target
                        else:
                            msg += f', {r.target}'
                        subscriptions['gym'] = msg

        else:
            subscriptions[t] = [s.target for s in results if s.type == t and t != 'gym']
    listmsg_list = []
    subscription_msg = ""
    for sub in subscriptions.keys():
        if not isinstance(subscriptions[sub], list):
            subscriptions[sub] = [subscriptions[sub]]
        new_msg = '**{category}**:\n\t{subs}\n\n'.format(category=sub.title(),subs='\n\t'.join(subscriptions[sub]))
        if len(subscription_msg) + len(new_msg) < constants.MAX_MESSAGE_LENGTH:
            subscription_msg += new_msg
        else:
            listmsg_list.append(subscription_msg)
            subscription_msg = new_msg
    listmsg_list.append(subscription_msg)
    if len(listmsg_list) > 0:
        if valid_types:
            await author.send(f"Your current {', '.join(valid_types)} subscriptions are:")
            for message in listmsg_list:
                await author.send(message)
        else:
            await author.send('Your current subscriptions are:')
            for message in listmsg_list:
                await author.send(message)
    else:
        if valid_types:
            await author.send("You don\'t have any subscriptions for {types}! use the **!subscription add** command to add some.".format(types=', '.join(valid_types)))
        else:
            await author.send("You don\'t have any subscriptions! use the **!subscription add** command to add some.")
    response = await channel.send(response_msg)
    await utils.sleep_and_cleanup([message,response], 10)


@_sub.command(name="adminlist", aliases=["alist"])
@commands.has_permissions(manage_guild=True)
async def _sub_adminlist(ctx, *, trainer=None):
    message = ctx.message
    channel = message.channel
    author = message.author

    if not trainer:
        response_msg = "Please provide a trainer name or id"
        response = await channel.send(response_msg)
        return await utils.sleep_and_cleanup([message,response], 10)

    if trainer.isdigit():
        trainerid = trainer
    else:
        converter = commands.MemberConverter()
        try:
            trainer_member = await converter.convert(ctx, trainer)
            trainerid = trainer_member.id
        except:
            response_msg = f"Could not process trainer with name: {trainer}"
            await channel.send(response_msg)
            return await utils.sleep_and_cleanup([message,response_msg], 10)
    try:
        results = (SubscriptionTable
            .select(SubscriptionTable.type, SubscriptionTable.target)
            .join(TrainerTable, on=(SubscriptionTable.trainer == TrainerTable.snowflake))
            .where(SubscriptionTable.trainer == trainerid)
            .where(TrainerTable.guild == ctx.guild.id))

        results = results.execute()
        subscription_msg = ''
        types = set([s.type for s in results])
        subscriptions = {t: [s.target for s in results if s.type == t] for t in types}

        for sub in subscriptions:
            subscription_msg += '**{category}**:\n\t{subs}\n\n'.format(category=sub.title(),subs='\n\t'.join(subscriptions[sub]))
        if len(subscription_msg) > 0:
            listmsg = "Listing subscriptions for user:  {id}\n".format(id=trainer)
            listmsg += 'Current subscriptions are:\n\n{subscriptions}'.format(subscriptions=subscription_msg)
            await message.add_reaction('✅')
            await author.send(listmsg)
        else:
            none_msg = await channel.send(f"No subscriptions found for user: {trainer}")
            await message.add_reaction('✅')
            return await utils.sleep_and_cleanup([none_msg], 10)
    except:
        response_msg = f"Encountered an error while looking up subscriptions for trainer with name: {trainer}"
        await channel.send(response_msg)
        return await utils.sleep_and_cleanup([response_msg, message], 10)


"""
Reporting
"""
def get_existing_raid(guild, location, only_ex = False):
    """returns a list of channel ids for raids reported at the location provided"""
    report_dict = {k: v for k, v in guild_dict[guild.id]['raidchannel_dict'].items() if ((v.get('egglevel', '').lower() != 'ex') if not only_ex else (v.get('egglevel', '').lower() == 'ex'))}
    def matches_existing(report):
        # ignore meetups
        if report.get('meetup', {}):
            return False
        return report.get('gym', None) and report['gym'].name.lower() == location.name.lower()
    return [channel_id for channel_id, report in report_dict.items() if matches_existing(report)]


def get_existing_research(guild, location):
    """returns a list of confirmation message ids for research reported at the location provided"""
    report_dict = guild_dict[guild.id]['questreport_dict']
    def matches_existing(report):
        return report['location'].lower() == location.name.lower()
    return [confirmation_id for confirmation_id, report in report_dict.items() if matches_existing(report)]


@Kyogre.command(name='lure', aliases=['lu'])
async def _lure(ctx, type, *, location):
    """Report that you're luring a pokestop.

    Usage: !lure <type> <location>
    Location should be the name of a Pokestop.
    Valid lure types are: normal, glacial, mossy, magnetic"""
    content = f"{type} {location}"
    await _lure_internal(ctx.message, content)


async def _lure_internal(message, content):
    guild = message.guild
    channel = message.channel
    author = message.author
    if len(content.split()) <= 1:
        return await channel.send(
            embed=discord.Embed(colour=discord.Colour.red(),
                                description='Give more details when reporting! Usage: **!lure <type> <location>**'))
    timestamp = (message.created_at +
                 datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset']))\
        .strftime('%Y-%m-%d %H:%M:%S')
    luretype = content.split()[0]
    pokestop = ' '.join(content.split()[1:])
    query = LureTypeTable.select()
    if id is not None:
        query = query.where(LureTypeTable.name == luretype)
    query = query.execute()
    result = [d for d in query]
    if len(result) != 1:
        return await channel.send(
            embed=discord.Embed(colour=discord.Colour.red(),
                                description='Unable to find the lure type provided, please try again.'))
    luretype = result[0]
    lure_regions = raid_helpers.get_channel_regions(channel, 'lure', guild_dict)
    stops = get_stops(guild.id, lure_regions)
    if stops:
        stop = await location_match_prompt(channel, author.id, pokestop, stops)
        if not stop:
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description="Unable to find that Pokestop. Please check the name and try again!"))
    report = TrainerReportRelation.create(created=timestamp, trainer=author.id, location=stop.id)
    lure = LureTable.create(trainer_report=report)
    LureTypeRelation.create(lure=lure, type=luretype)
    lure_embed = discord.Embed(
        title=f'Click here for my directions to the {luretype.name.capitalize()} lure!',
        description=f"Ask {author.display_name} if my directions aren't perfect!",
        url=stop.maps_url, colour=discord.Colour.purple())
    lure_embed.set_footer(
        text='Reported by {author} - {timestamp}'
            .format(author=author.display_name, timestamp=timestamp),
        icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    lurereportmsg = await channel.send(f'**{luretype.name.capitalize()}** lure reported by {author.display_name} at {stop.name}', embed=lure_embed)
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'lure', edit=False, regions=lure_regions)
    details = {'regions': lure_regions, 'type': 'lure', 'lure_type': luretype.name, 'location': stop.name}
    await _send_notifications_async('lure', details, message.channel, [message.author.id])
    event_loop.create_task(lure_expiry_check(lurereportmsg, report.id))

        
@Kyogre.command(name="wild", aliases=['w'])
@checks.allowwildreport()
async def _wild(ctx, pokemon, *, location):
    """Report a wild Pokemon spawn location.

    Usage: !wild <species> <location>
    Location should be the name of a Pokestop or Gym. Or a google maps link."""
    content = f"{pokemon} {location}"
    await _wild_internal(ctx.message, content)


async def _wild_internal(message, content):
    guild = message.guild
    channel = message.channel
    author = message.author
    timestamp = (message.created_at +
                 datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset']))\
                .strftime('%I:%M %p (%H:%M)')
    if len(content.split()) <= 1:
        return await channel.send(
            embed=discord.Embed(colour=discord.Colour.red(),
                                description='Give more details when reporting! Usage: **!wild <pokemon name> <location>**'))
    channel_regions = raid_helpers.get_channel_regions(channel, 'wild', guild_dict)
    rgx = r'\s*((100(\s*%)?|perfect)(\s*ivs?\b)?)\s*'
    content, count = re.subn(rgx, '', content.strip(), flags=re.I)
    is_perfect = count > 0
    entered_wild, wild_details = content.split(' ', 1)
    if Pokemon.has_forms(entered_wild):
        prompt = 'Which form of this Pokemon are you reporting?'
        choices_list = [f.capitalize() for f in Pokemon.get_forms_for_pokemon(entered_wild)]
        match = await utils.ask_list(Kyogre, prompt, channel, choices_list, user_list=author.id)
        content = ' '.join([match, content])
    pkmn = Pokemon.get_pokemon(Kyogre, entered_wild if entered_wild.isdigit() else content)
    if not pkmn:
        return await channel.send(
            embed=discord.Embed(colour=discord.Colour.red(),
                                description="Unable to find that pokemon. Please check the name and try again!"))
    wild_number = pkmn.id
    wild_img_url = pkmn.img_url
    expiremsg = '**This {pokemon} has despawned!**'.format(pokemon=pkmn.full_name)
    if len(pkmn.name.split(' ')) > 1:
        entered_wild, entered_wild, wild_details = content.split(' ', 2)
    else:
        wild_details = re.sub(pkmn.name.lower(), '', content, flags=re.I)
    wild_gmaps_link = ''
    locations = get_all_locations(guild.id, channel_regions)
    if locations and not ('http' in wild_details or '/maps' in wild_details):
        location = await location_match_prompt(channel, author.id, wild_details, locations)
        if location:
            wild_gmaps_link = location.maps_url
            wild_details = location.name
    if not wild_gmaps_link:
        if 'http' in wild_details or '/maps' in wild_details:
            wild_gmaps_link = create_gmaps_query(wild_details, channel, type="wild")
            wild_details = 'Custom Map Pin'
        else:
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description="Please use the name of an existing pokestop or gym, or include a valid Google Maps link."))
    wild_embed = discord.Embed(title='Click here for my directions to the wild {pokemon}!'.format(pokemon=pkmn.full_name), description="Ask {author} if my directions aren't perfect!".format(author=author.name), url=wild_gmaps_link, colour=guild.me.colour)
    wild_embed.add_field(name='**Details:**', value='{emoji}{pokemon} ({pokemonnumber}) {type}'.format(emoji='💯' if is_perfect else '',pokemon=pkmn.full_name, pokemonnumber=str(wild_number), type=''.join(utils.types_to_str(guild, pkmn.types, Kyogre.config))), inline=False)
    wild_embed.set_thumbnail(url=wild_img_url)
    wild_embed.add_field(name='**Reactions:**', value="{emoji}: I'm on my way!".format(emoji="🏎"))
    wild_embed.add_field(name='\u200b', value="{emoji}: The Pokemon despawned!".format(emoji="💨"))
    wild_embed.set_footer(text='Reported by {author} - {timestamp}'.format(author=author.display_name, timestamp=timestamp), icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    wildreportmsg = await channel.send(content='Wild {pokemon} reported by {member}! Details: {location_details}'.format(pokemon=pkmn.full_name, member=author.display_name, location_details=wild_details), embed=wild_embed)
    await asyncio.sleep(0.25)
    await wildreportmsg.add_reaction('🏎')
    await asyncio.sleep(0.25)
    await wildreportmsg.add_reaction('💨')
    await asyncio.sleep(0.25)
    wild_dict = copy.deepcopy(guild_dict[guild.id].get('wildreport_dict',{}))
    wild_dict[wildreportmsg.id] = {
        'exp':time.time() + 3600,
        'expedit': {"content":wildreportmsg.content,"embedcontent":expiremsg},
        'reportmessage':message.id,
        'reportchannel':channel.id,
        'reportauthor':author.id,
        'location':wild_details,
        'url':wild_gmaps_link,
        'pokemon':pkmn.full_name,
        'perfect':is_perfect,
        'omw': []
    }
    guild_dict[guild.id]['wildreport_dict'] = wild_dict
    wild_reports = guild_dict[guild.id].setdefault('trainers',{}).setdefault(channel_regions[0],{}).setdefault(author.id,{}).setdefault('wild_reports',0) + 1
    guild_dict[guild.id]['trainers'][channel_regions[0]][author.id]['wild_reports'] = wild_reports
    wild_details = {'pokemon': pkmn, 'perfect': is_perfect, 'location': wild_details, 'regions': channel_regions}
    event_loop.create_task(wild_expiry_check(wildreportmsg))
    await list_helpers.update_listing_channels(Kyogre, guild_dict, message.guild, 'wild', edit=False, regions=channel_regions)
    await _send_notifications_async('wild', wild_details, message.channel, [message.author.id])


@Kyogre.group(name="raid", aliases=['r', 're', 'egg', 'regg', 'raidegg'])
@checks.allowraidreport()
async def _raid(ctx,pokemon,*,location:commands.clean_content(fix_channel_mentions=True)="", weather=None, timer=None):
    """Report an ongoing raid or a raid egg.

    Usage: !raid <species/level> <gym name> [minutes]
    Kyogre will attempt to find a gym with the name you provide
    Kyogre's message will also include the type weaknesses of the boss.

    Finally, Kyogre will create a separate channel for the raid report, for the purposes of organizing the raid."""
    
    content = f"{pokemon} {location}".lower()
    if pokemon.isdigit():
        new_channel = await _raidegg(ctx, content)
    elif len(pokemon) == 2 and pokemon[0] == "t":
        new_channel = await _raidegg(ctx, content[1:])
    else:
        new_channel = await _raid_internal(ctx, content)
    ctx.raid_channel = new_channel


async def _raid_internal(ctx, content):
    message = ctx.message
    channel = message.channel
    guild = channel.guild
    author = message.author
    fromegg = False
    eggtoraid = False
    if guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('type') == "egg":
        fromegg = True
    raid_split = content.split()
    if len(raid_split) == 0:
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    if raid_split[0] == 'egg':
        await _raidegg(ctx, content)
        return
    if fromegg:
        eggdetails = guild_dict[guild.id]['raidchannel_dict'][channel.id]
        egglevel = eggdetails['egglevel']
        if raid_split[0].lower() == 'assume':
            if config['allow_assume'][egglevel] == 'False':
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='**!raid assume** is not allowed for this level egg.'))
            if not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                await _eggtoraid(ctx, raid_split[1].lower(), channel, author)
                return
            else:
                await _eggassume(" ".join(raid_split), channel, author)
                return
        elif (raid_split[0] == "alolan" and len(raid_split) > 2) or (raid_split[0] != "alolan" and len(raid_split) > 1):
            if (raid_split[0] not in Pokemon.get_forms_list() and len(raid_split) > 1):
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please report new raids in a reporting channel.'))
        elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['active'] == False:
            eggtoraid = True
        ## This is a hack but it allows users to report the just hatched boss before Kyogre catches up with hatching the egg.
        elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 < datetime.datetime.now().timestamp():
            eggtoraid = True
        else:            
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please wait until the egg has hatched before changing it to an open raid!'))
    raid_pokemon = Pokemon.get_pokemon(Kyogre, content)
    pkmn_error = None
    pkmn_error_dict = {'not_pokemon': "I couldn't determine the Pokemon in your report.\nWhat raid boss or raid tier are you reporting?",
                       'not_boss': 'That Pokemon does not appear in raids!\nWhat is the correct Pokemon?',
                       'ex': ("The Pokemon {pokemon} only appears in EX Raids!\nWhat is the correct Pokemon?").format(pokemon=str(raid_pokemon).capitalize()),
                       'level': "That is not a valid raid tier. Please provide the raid boss or tier for your report."}
    if not raid_pokemon:
        pkmn_error = 'not_pokemon'
        try:
            new_content = content.split()
            pkmn_index = new_content.index('alolan')
            del new_content[pkmn_index + 1]
            del new_content[pkmn_index]
            new_content = ' '.join(new_content)
        except ValueError:
            new_content = ' '.join(content.split())
    elif not raid_pokemon.is_raid:
        pkmn_error = 'not_boss'
        try:
            new_content = content.split()
            pkmn_index = new_content.index('alolan')
            del new_content[pkmn_index + 1]
            del new_content[pkmn_index]
            new_content = ' '.join(new_content)
        except ValueError:
            new_content = ' '.join(content.split())
    elif raid_pokemon.is_exraid:
        pkmn_error = 'ex'
        new_content = ' '.join(content.split()[1:])
    if pkmn_error is not None:
        while True:
            pkmn_embed=discord.Embed(colour=discord.Colour.red(), description=pkmn_error_dict[pkmn_error])
            pkmn_embed.set_footer(text="Reply with 'cancel' to cancel your raid report.")
            pkmnquery_msg = await channel.send(embed=pkmn_embed)
            try:
                pokemon_msg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == author))
            except asyncio.TimeoutError:
                await channel.send(embed=discord.Embed(colour=discord.Colour.light_grey(), description="You took too long to reply. Raid report cancelled."))
                await pkmnquery_msg.delete()
                return
            if pokemon_msg.clean_content.lower() == "cancel":
                await pkmnquery_msg.delete()
                await pokemon_msg.delete()
                await channel.send(embed=discord.Embed(colour=discord.Colour.light_grey(), description="Raid report cancelled."))
                return
            if pokemon_msg.clean_content.isdigit():
                if int(pokemon_msg.clean_content) > 0 and int(pokemon_msg.clean_content) <= 5:
                    return await _raidegg(ctx, ' '.join([str(pokemon_msg.clean_content), new_content]))
                else:
                    pkmn_error = 'level'
                    continue
            raid_pokemon = Pokemon.get_pokemon(Kyogre, pokemon_msg.clean_content)
            if not raid_pokemon:
                pkmn_error = 'not_pokemon'
            elif not raid_pokemon.is_raid:
                pkmn_error = 'not_boss'
            elif raid_pokemon.is_exraid:
                pkmn_error = 'ex'
            else:
                await pkmnquery_msg.delete()
                await pokemon_msg.delete()
                break
            await pkmnquery_msg.delete()
            await pokemon_msg.delete()
            await asyncio.sleep(.5)
    else:
        new_content = ' '.join(content.split()[len(raid_pokemon.full_name.split()):])
    if fromegg:
        return await _eggtoraid(ctx, raid_pokemon.full_name.lower(), channel, author)
    if eggtoraid:
        return await _eggtoraid(ctx, new_content.lower(), channel, author)
    raid_split = new_content.strip().split()
    if len(raid_split) == 0:
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    raidexp = False
    if raid_split[-1].isdigit() or ':' in raid_split[-1]:
        raidexp = await time_to_minute_count(channel, raid_split[-1])
        if raidexp is False:
            return
        else:
            del raid_split[-1]
            if _timercheck(raidexp, raid_info['raid_eggs'][raid_pokemon.raid_level]['raidtime']):
                time_embed = discord.Embed(description="That's too long. Level {raidlevel} Raid currently last no more than {hatchtime} minutes...\nExpire time will not be set.".format(raidlevel=raid_pokemon.raid_level, hatchtime=raid_info['raid_eggs'][raid_pokemon.raid_level]['hatchtime']), colour=discord.Colour.red())
                await channel.send(embed=time_embed)
                raidexp = False
    raid_details = ' '.join(raid_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    rgx = '[^a-zA-Z0-9]'
    weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
    if not weather:
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    raid_pokemon.weather = weather
    raid_details = raid_details.replace(str(weather), '', 1)
    if raid_details == '':
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    return await finish_raid_report(ctx, raid_details, raid_pokemon, raid_pokemon.raid_level, weather, raidexp)

async def retry_gym_match(channel, author_id, raid_details, gyms):
    attempt = raid_details.split(' ')
    if len(attempt) > 1:
        if attempt[-2] == "alolan" and len(attempt) > 2:
            del attempt[-2]
        del attempt[-1]
    attempt = ' '.join(attempt)
    gym = await location_match_prompt(channel, author_id, attempt, gyms)
    if gym:
        return gym
    else:
        attempt = raid_details.split(' ')
        if len(attempt) > 1:
            if attempt[0] == "alolan" and len(attempt) > 2:
                del attempt[0]
            del attempt[0]
        attempt = ' '.join(attempt)
        gym = await location_match_prompt(channel, author_id, attempt, gyms)
        if gym:
            return gym
        else:
            return None

async def _raidegg(ctx, content):
    message = ctx.message
    channel = message.channel

    if checks.check_eggchannel(ctx) or checks.check_raidchannel(ctx):
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Please report new raids in a reporting channel.'))
    
    guild = message.guild
    author = message.author
    raidexp = False
    hourminute = False
    raidegg_split = content.split()
    if raidegg_split[0].lower() == 'egg':
        del raidegg_split[0]
    if len(raidegg_split) <= 1:
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Usage: **!raidegg <level> <location>**'))
    if raidegg_split[0].isdigit():
        egg_level = int(raidegg_split[0])
        del raidegg_split[0]
    else:
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. Type **!help** raidegg for more info.'))
    raidexp = await time_to_minute_count(channel, raidegg_split[-1])
    if not raidexp:
        return
    else:
        del raidegg_split[-1]
        if _timercheck(raidexp, raid_info['raid_eggs'][str(egg_level)]['hatchtime']):
            await channel.send("That's too long. Level {raidlevel} Raid Eggs currently last no more than {hatchtime} minutes...".format(raidlevel=egg_level, hatchtime=raid_info['raid_eggs'][str(egg_level)]['hatchtime']))
            return
    raid_details = ' '.join(raidegg_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), 
            description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. Type **!help** raidegg for more info.'))
    rgx = '[^a-zA-Z0-9]'
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
    raid_details = raid_details.replace(str(weather), '', 1)
    if not weather:
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    if raid_details == '':
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), 
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    return await finish_raid_report(ctx, raid_details, None, egg_level, weather, raidexp)

async def finish_raid_report(ctx, raid_details, raid_pokemon, level, weather, raidexp):
    message = ctx.message
    channel = message.channel
    guild = channel.guild
    author = message.author
    timestamp = (message.created_at + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
    if raid_pokemon is None:
        raid_report = False
    else:
        raid_report = True
    report_regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
    gym = None
    gyms = get_gyms(guild.id, report_regions)
    other_region = False
    if gyms:
        gym = await location_match_prompt(channel, author.id, raid_details, gyms)
        if not gym:
            all_regions = list(guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
            gyms = get_gyms(guild.id, all_regions)
            gym = await location_match_prompt(channel, author.id, raid_details, gyms)
            if not gym:
                gym = await retry_gym_match(channel, author.id, raid_details, gyms)
                if not gym:
                    return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a gym named '{raid_details}'. Try again using the exact gym name!"))
            if report_regions[0] != gym.region:
                other_region = True
        raid_channel_ids = get_existing_raid(guild, gym)
        if raid_channel_ids:
            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
            try:
                raid_dict_entry = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
            except:
                return await message.add_reaction('\u274c')
            enabled =raid_helpers.raid_channels_enabled(guild, channel, guild_dict)
            if raid_dict_entry and not (raid_dict_entry['exp'] - 60 < datetime.datetime.now().timestamp()):
                msg = f"A raid has already been reported for {gym.name}."
                if enabled:
                    msg += f" Coordinate in {raid_channel.mention}"
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=msg))
            else:
                await message.add_reaction('✅')
                location = raid_dict_entry.get('address', 'unknown gym')
                if not enabled:
                    await channel.send(f"The egg at {location} has hatched into a {raid_pokemon.name} raid!")
                return await _eggtoraid(ctx, raid_pokemon.name.lower(), raid_channel)

        raid_details = gym.name
        raid_gmaps_link = gym.maps_url
        gym_regions = [gym.region]
    else:
        raid_gmaps_link = create_gmaps_query(raid_details, channel, type="raid")
    if other_region:
        report_channels = await list_helpers.get_region_reporting_channels(guild, gym_regions[0], guild_dict)
        report_channel = Kyogre.get_channel(report_channels[0])
    else:
        report_channel = channel
    if raid_report:
        raid_channel = await create_raid_channel("raid", raid_pokemon, None, gym, channel)
    else:
        egg_info = raid_info['raid_eggs'][str(level)]
        egg_img = egg_info['egg_img']
        boss_list = []
        for entry in egg_info['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, entry)
            boss_list.append(str(p) + ' (' + str(p.id) + ') ' + utils.types_to_str(guild, p.types, Kyogre.config))
        raid_channel = await create_raid_channel("egg", None, level, gym, channel)
    ow = raid_channel.overwrites_for(raid_channel.guild.default_role)
    ow.send_messages = True
    try:
        await raid_channel.set_permissions(raid_channel.guild.default_role, overwrite = ow)
    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
        pass
    raid_dict = {
        'regions': gym_regions,
        'reportcity': report_channel.id,
        'trainer_dict': {},
        'exp': time.time() + (60 * raid_info['raid_eggs'][str(level)]['raidtime']),
        'manual_timer': False,
        'active': True,
        'reportchannel': channel.id,
        'address': raid_details,
        'type': 'raid' if raid_report else 'egg',
        'pokemon': raid_pokemon.name.lower() if raid_report else '',
        'egglevel': str(level) if not raid_report else '0',
        'moveset': 0,
        'weather': weather,
        'gym': gym,
        'reporter': author.id
    }
    raid_embed = discord.Embed(title='Click here for directions to the raid!', url=raid_gmaps_link, colour=guild.me.colour)
    enabled =raid_helpers.raid_channels_enabled(guild, channel, guild_dict)
    if gym:
        if enabled:
            gym_info = "**Name:** {0}\n**Notes:** {1}".format(raid_details, "_EX Eligible Gym_" if gym.ex_eligible else "N/A")
            raid_embed.add_field(name='**Gym:**', value=gym_info, inline=False)
    cp_range = ''
    if raid_report:
        if enabled:
            if str(raid_pokemon).lower() in boss_cp_chart:
                cp_range = boss_cp_chart[str(raid_pokemon).lower()]
            raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'.format(pokemon=str(raid_pokemon), pokemonnumber=str(raid_pokemon.id), type=utils.types_to_str(guild, raid_pokemon.types, Kyogre.config), cprange='\n'+cp_range, inline=True))
            raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=utils.types_to_str(guild, raid_pokemon.weak_against.keys(), Kyogre.config), inline=True))
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
            raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**', inline=True)
        raid_img_url = raid_pokemon.img_url
        msg = entity_updates.build_raid_report_message(gym, 'raid', raid_pokemon.name, '0', raidexp, raid_channel, guild_dict)
    else:
        if enabled:
            if len(egg_info['pokemon']) > 1:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
                raid_embed.add_field(name='\u200b', value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
            else:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist}'.format(bosslist=''.join(boss_list)), inline=True)
                raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
            raid_embed.add_field(name='**Hatches:**', value='Set with **!timerset**', inline=True)
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
        raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'.format(str(egg_img))
        msg = entity_updates.build_raid_report_message(gym, 'egg', '', level, raidexp, raid_channel, guild_dict)
    if enabled:
        raid_embed.set_footer(text='Reported by {author} - {timestamp}'.format(author=author.display_name, timestamp=timestamp), icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    report_embed = raid_embed
    embed_indices = await embed_utils.get_embed_field_indices(report_embed)
    report_embed = await embed_utils.filter_fields_for_report_embed(report_embed, embed_indices)
    raidreport = await channel.send(content=msg, embed=report_embed)
    await asyncio.sleep(1)
    raid_embed.add_field(name='**Tips:**', value='`!i` if interested\n`!c` if on the way\n`!h` when you arrive\n`!list` to view all interested\n`!s` to signal lobby start', inline=True)
    ctrsmessage_id = None
    if raid_report:
        raidmsg = "{pokemon} raid reported by {member} in {citychannel} at {location_details} gym. Coordinate here!\n\nClick the question mark reaction to get help on the commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires.".format(pokemon=str(raid_pokemon), member=author.display_name, citychannel=channel.mention, location_details=raid_details)
        if str(level) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
            try:
                ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
                ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! Update weather with **!weather**. If you know the moveset of the boss, you can react to this message with the matching emoji and I will update the counters."
                ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
                ctrsmessage_id = ctrsmessage.id
                await ctrsmessage.pin()
                for moveset in ctrs_dict:
                    await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
                    await asyncio.sleep(0.25)
            except:
                ctrs_dict = {}
                ctrsmessage_id = None
        else:
            ctrs_dict = {}
            ctrsmessage_id = None
        raid_reports = guild_dict[guild.id].setdefault('trainers',{}).setdefault(gym.region, {}).setdefault(author.id,{}).setdefault('raid_reports',0) + 1  ######
        guild_dict[guild.id]['trainers'][gym.region][author.id]['raid_reports'] = raid_reports ######  
        raid_details = {'pokemon': raid_pokemon, 'tier': raid_pokemon.raid_level, 'ex-eligible': gym.ex_eligible if gym else False, 'location': raid_details, 'regions': gym_regions} ######   
    else:
        raidmsg = "Level {level} raid egg reported by {member} in {citychannel} at {location_details} gym. Coordinate here!\n\nClick the question mark reaction to get help on the commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires.".format(level=level, member=author.display_name, citychannel=channel.mention, location_details=raid_details)
        egg_reports = guild_dict[message.guild.id].setdefault('trainers',{}).setdefault(gym.region,{}).setdefault(author.id,{}).setdefault('egg_reports',0) + 1
        guild_dict[message.guild.id]['trainers'][gym.region][author.id]['egg_reports'] = egg_reports
        raid_details = {'tier': level, 'ex-eligible': gym.ex_eligible if gym else False, 'location': raid_details, 'regions': gym_regions}
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.add_reaction('\u2754')
    await asyncio.sleep(0.1)
    await raidmessage.add_reaction('\u270f')
    await asyncio.sleep(0.1)
    await raidmessage.add_reaction('🚫')
    await asyncio.sleep(0.1)
    await raidmessage.pin()
    raid_dict['raidmessage'] = raidmessage.id
    raid_dict['raidreport'] = raidreport.id
    raid_dict['raidcityreport'] = None
    if ctrsmessage_id is not None:
        raid_dict['ctrsmessage'] = ctrsmessage_id
        raid_dict['ctrs_dict'] = ctrs_dict
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict
    if raidexp is not False:
        await _timerset(raid_channel, raidexp)
    else:
        await raid_channel.send(content='Hey {member}, if you can, set the time left on the raid using **!timerset <minutes>** so others can check it with **!timer**.'.format(member=author.mention))
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=False, regions=gym_regions)
    if enabled:
        await _send_notifications_async('raid', raid_details, raid_channel, [author.id])
    else:
        await _send_notifications_async('raid', raid_details, channel, [author.id])
    await raidreport.add_reaction('\u270f')
    await asyncio.sleep(0.1)
    await raidreport.add_reaction('🚫')
    await asyncio.sleep(0.1)
    if other_region:
        region_command_channels = guild_dict[guild.id]['configure_dict']['regions'].setdefault('command_channels', [])
        channel_text = ''
        if len(region_command_channels) > 0:
            channel_text = ' in '
            for c in region_command_channels:
                channel_text += Kyogre.get_channel(c).mention
        region_msg = f'Hey {author.mention}, **{gym.name}** is in the **{gym_regions[0].capitalize()}** region. Your report was successful, but please consider joining that region{channel_text} to report raids at this gym in the future'
        embed = discord.Embed(colour=discord.Colour.gold(), description=region_msg)
        embed.set_footer(text=f"If you believe this region assignment is incorrect, please contact {guild.owner.display_name}")
        await channel.send(embed=embed)
        raidcityreport = await report_channel.send(content=msg, embed=report_embed)
        raid_dict['raidcityreport'] = raidcityreport.id
        await raidcityreport.add_reaction('\u270f')
        await asyncio.sleep(0.1)
        await raidcityreport.add_reaction('🚫')
        await asyncio.sleep(0.1)
    if not raid_report:
        if len(raid_info['raid_eggs'][str(level)]['pokemon']) == 1:
            await _eggassume('assume ' + raid_info['raid_eggs'][str(level)]['pokemon'][0], raid_channel)
        elif level == "5" and guild_dict[raid_channel.guild.id]['configure_dict']['settings'].get('regional',None) in raid_info['raid_eggs']["5"]['pokemon']:
            await _eggassume('assume ' + guild_dict[raid_channel.guild.id]['configure_dict']['settings']['regional'], raid_channel)
    event_loop.create_task(expiry_check(raid_channel))
    return raid_channel

async def _eggassume(args, raid_channel, author=None):

    guild = raid_channel.guild
    eggdetails = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
    report_channel = Kyogre.get_channel(eggdetails['reportchannel'])
    egglevel = eggdetails['egglevel']
    manual_timer = eggdetails['manual_timer']
    weather = eggdetails.get('weather', None)
    egg_report = await report_channel.fetch_message(eggdetails['raidreport'])
    raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
    entered_raid = re.sub('[\\@]', '', args.lower().lstrip('assume').lstrip(' '))
    raid_pokemon = Pokemon.get_pokemon(Kyogre, entered_raid)
    if not raid_pokemon:
        return
    if not raid_pokemon.is_raid:
        return await raid_channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f'The Pokemon {raid_pokemon.name} does not appear in raids!'))
    elif raid_pokemon.name.lower() not in raid_info['raid_eggs'][egglevel]['pokemon']:
        return await raid_channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f'The Pokemon {raid_pokemon.name} does not hatch from level {egglevel} raid eggs!'))
    eggdetails['pokemon'] = raid_pokemon.name
    oldembed = raid_message.embeds[0]
    raid_gmaps_link = oldembed.url
    enabled = raid_helpers.raid_channels_enabled(raid_channel.guild, raid_channel, guild_dict)
    if enabled:
        embed_indices = await embed_utils.get_embed_field_indices(oldembed)
        raid_embed = discord.Embed(title='Click here for directions to the raid!', url=raid_gmaps_link, colour=raid_channel.guild.me.colour)
        raid_embed.add_field(name=(oldembed.fields[embed_indices["gym"]].name), value=oldembed.fields[embed_indices["gym"]].value, inline=True)
        cp_range = ''
        if raid_pokemon.name.lower() in boss_cp_chart:
            cp_range = boss_cp_chart[raid_pokemon.name.lower()]
        raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'.format(pokemon=raid_pokemon.name, pokemonnumber=str(raid_pokemon.id), type=utils.types_to_str(raid_channel.guild, raid_pokemon.types, Kyogre.config), cprange='\n'+cp_range, inline=True))
        raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=utils.types_to_str(raid_channel.guild, raid_pokemon.weak_against, Kyogre.config)), inline=True)
        if embed_indices["next"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["next"]].name), value=oldembed.fields[embed_indices["next"]].value, inline=True)
        if embed_indices["hatch"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["hatch"]].name), value=oldembed.fields[embed_indices["hatch"]].value, inline=True)
        if embed_indices["tips"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["tips"]].name), value=oldembed.fields[embed_indices["tips"]].value, inline=True)

        raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
        raid_embed.set_thumbnail(url=raid_pokemon.img_url)
        try:
            await raid_message.edit(new_content=raid_message.content, embed=raid_embed, content=raid_message.content)
            raid_message = raid_message.id
        except discord.errors.NotFound:
            raid_message = None
        try:
            embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
            raid_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices)
            await egg_report.edit(new_content=egg_report.content, embed=raid_embed, content=egg_report.content)
            egg_report = egg_report.id
        except discord.errors.NotFound:
            egg_report = None
        if eggdetails['raidcityreport'] is not None:
            report_city_channel = Kyogre.get_channel(eggdetails['reportcity'])
            city_report = await report_city_channel.fetch_message(eggdetails['raidcityreport'])
            try:
                await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
                city_report = city_report.id
            except discord.errors.NotFound:
                city_report = None
    await raid_channel.send('This egg will be assumed to be {pokemon} when it hatches!'.format(pokemon=raid_pokemon.full_name))
    if str(egglevel) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! Update weather with **!weather**. If you know the moveset of the boss, you can react to this message with the matching emoji and I will update the counters."
        ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
        ctrsmessage_id = ctrsmessage.id
        await ctrsmessage.pin()
        for moveset in ctrs_dict:
            await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
            await asyncio.sleep(0.25)
    else:
        ctrs_dict = {}
        ctrsmessage_id = eggdetails.get('ctrsmessage', None)
    eggdetails['ctrs_dict'] = ctrs_dict
    eggdetails['ctrsmessage'] = ctrsmessage_id
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = eggdetails
    return

async def _eggtoraid(ctx, entered_raid, raid_channel, author=None):
    pkmn = Pokemon.get_pokemon(Kyogre, entered_raid)
    if not pkmn:
        return
    eggdetails = guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]
    egglevel = eggdetails['egglevel']
    if egglevel == "0":
        egglevel = pkmn.raid_level
    try:
        reportcitychannel = Kyogre.get_channel(eggdetails['reportcity'])
        reportcity = reportcitychannel.name
    except (discord.errors.NotFound, AttributeError):
        reportcity = None
    manual_timer = eggdetails['manual_timer']
    trainer_dict = eggdetails['trainer_dict']
    egg_address = eggdetails['address']
    weather = eggdetails.get('weather', None)
    try:
        gym = eggdetails['gym']
    except:
        gym = None
    try:
        reporter = eggdetails['reporter']
    except:
        reporter = None
    try:
        reportchannel = eggdetails['reportchannel']
    except:
        reportchannel = None
    if reportchannel is not None:
        reportchannel = Kyogre.get_channel(reportchannel)
    raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
    if not reportcitychannel:
        async for message in raid_channel.history(limit=500, reverse=True):
            if message.author.id == raid_channel.guild.me.id:
                c = 'Coordinate here'
                if c in message.content:
                    reportcitychannel = message.raw_channel_mentions[0]
                    break
    if reportchannel:
        try:
            egg_report = await reportchannel.fetch_message(eggdetails['raidreport'])
        except (discord.errors.NotFound, discord.errors.HTTPException):
            egg_report = None
    if reportcitychannel:
        try:
            city_report = await reportcitychannel.fetch_message(eggdetails['raidcityreport'])
        except (discord.errors.NotFound, discord.errors.HTTPException):
            city_report = None
    starttime = eggdetails.get('starttime',None)
    duplicate = eggdetails.get('duplicate',0)
    archive = eggdetails.get('archive',False)
    meetup = eggdetails.get('meetup',{})
    raid_match = pkmn.is_raid
    if (not raid_match):
        return await raid_channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f'The Pokemon {pkmn.full_name} does not appear in raids!'))
    if (egglevel.isdigit() and int(egglevel) > 0) or egglevel == 'EX':
        raidexp = eggdetails['exp'] + 60 * raid_info['raid_eggs'][str(egglevel)]['raidtime']
    else:
        raidexp = eggdetails['exp']
    end = datetime.datetime.utcfromtimestamp(raidexp) + datetime.timedelta(hours=guild_dict[raid_channel.guild.id]['configure_dict']['settings']['offset'])
    oldembed = raid_message.embeds[0]
    raid_gmaps_link = oldembed.url
    enabled = True
    if guild_dict[raid_channel.guild.id].get('raidchannel_dict',{}).get(raid_channel.id,{}).get('meetup',{}):
        guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['type'] = 'exraid'
        guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['egglevel'] = '0'
        await raid_channel.send("The event has started!", embed=oldembed)
        await raid_channel.edit(topic="")
        event_loop.create_task(expiry_check(raid_channel))
        return
    if egglevel.isdigit():
        hatchtype = 'raid'
        raidreportcontent = 'The egg has hatched into a {pokemon} raid at {location_details} gym.'.format(pokemon=entered_raid.capitalize(), location_details=egg_address)
        enabled =raid_helpers.raid_channels_enabled(raid_channel.guild, raid_channel, guild_dict)
        if enabled:
            raidreportcontent += 'Coordinate in {raid_channel}'.format(raid_channel=raid_channel.mention)
        raidmsg = "The egg reported in {citychannel} hatched into a {pokemon} raid! Details: {location_details}. Coordinate here!\n\nClick the question mark reaction to get help on the commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires.".format(citychannel=reportcitychannel.mention, pokemon=entered_raid.capitalize(), location_details=egg_address)
    elif egglevel == 'EX':
        hatchtype = 'exraid'
        if guild_dict[raid_channel.guild.id]['configure_dict']['invite']['enabled']:
            invitemsgstr = "Use the **!invite** command to gain access and coordinate"
            invitemsgstr2 = " after using **!invite** to gain access"
        else:
            invitemsgstr = "Coordinate"
            invitemsgstr2 = ""
        raidreportcontent = 'The EX egg has hatched into a {pokemon} raid! Details: {location_details}. {invitemsgstr} coordinate in {raid_channel}'.format(pokemon=entered_raid.capitalize(), location_details=egg_address, invitemsgstr=invitemsgstr,raid_channel=raid_channel.mention)
        raidmsg = "{pokemon} EX raid reported in {citychannel}! Details: {location_details}. Coordinate here{invitemsgstr2}!\n\nClick the question mark reaction to get help on the commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires.".format(pokemon=entered_raid.capitalize(), citychannel=reportcitychannel.mention, location_details=egg_address, invitemsgstr2=invitemsgstr2)
    raid_channel_name = utils.sanitize_name(pkmn.name.lower() + '_' + egg_address)
    embed_indices = await embed_utils.get_embed_field_indices(oldembed)
    raid_embed = discord.Embed(title='Click here for directions to the raid!', url=raid_gmaps_link, colour=raid_channel.guild.me.colour)
    if embed_indices["gym"] is not None:
        raid_embed.add_field(name=(oldembed.fields[embed_indices["gym"]].name), value=oldembed.fields[embed_indices["gym"]].value, inline=True)
    cp_range = ''
    if pkmn.name.lower() in boss_cp_chart:
        cp_range = boss_cp_chart[pkmn.name.lower()]
    raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'.format(pokemon=pkmn.name, pokemonnumber=str(pkmn.id), type=utils.types_to_str(raid_channel.guild, pkmn.types, Kyogre.config), cprange='\n'+cp_range, inline=True))
    raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=utils.types_to_str(raid_channel.guild, pkmn.weak_against, Kyogre.config)), inline=True)
    if embed_indices["next"] is not None:
        raid_embed.add_field(name=(oldembed.fields[embed_indices["next"]].name), value=oldembed.fields[embed_indices["next"]].value, inline=True)
    if meetup:
        raid_embed.add_field(name=oldembed.fields[3].name, value=end.strftime('%B %d at %I:%M %p (%H:%M)'), inline=True)
    else:
        raid_embed.add_field(name='**Expires:**', value=end.strftime('%B %d at %I:%M %p (%H:%M)'), inline=True)
    if embed_indices["tips"] is not None:
        raid_embed.add_field(name=(oldembed.fields[embed_indices["tips"]].name), value=oldembed.fields[embed_indices["tips"]].value, inline=True)
    raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
    raid_embed.set_thumbnail(url=pkmn.img_url)
    await raid_channel.edit(name=raid_channel_name, topic=end.strftime('Ends on %B %d at %I:%M %p (%H:%M)'))
    trainer_list = []
    trainer_dict = copy.deepcopy(guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'])
    for trainer in trainer_dict.keys():
        try:
            user = raid_channel.guild.get_member(trainer)
        except (discord.errors.NotFound, AttributeError):
            continue
        if (trainer_dict[trainer].get('interest',None)) and (entered_raid.lower() not in trainer_dict[trainer]['interest']):
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['status'] = {'maybe':0, 'coming':0, 'here':0, 'lobby':0}
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['party'] = {'mystic':0, 'valor':0, 'instinct':0, 'unknown':0}
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['count'] = 1
        else:
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['interest'] = []
    await asyncio.sleep(1)
    trainer_dict = copy.deepcopy(guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'])
    for trainer in trainer_dict.keys():
        if (trainer_dict[trainer]['status']['maybe']) or (trainer_dict[trainer]['status']['coming']) or (trainer_dict[trainer]['status']['here']):
            try:
                user = raid_channel.guild.get_member(trainer)
                trainer_list.append(user.mention)
            except (discord.errors.NotFound, AttributeError):
                continue
    trainers = ' ' + ', '.join(trainer_list) if trainer_list else ''
    await raid_channel.send(content="Trainers{trainer}: The raid egg has just hatched into a {pokemon} raid!\nIf you couldn't before, you're now able to update your status with **!coming** or **!here**. If you've changed your plans, use **!cancel**.".format(trainer=trainers, pokemon=entered_raid.title()), embed=raid_embed)
    raid_details = {'pokemon': pkmn, 'tier': pkmn.raid_level, 'ex-eligible': False if eggdetails['gym'] is None else eggdetails['gym'].ex_eligible, 'location': eggdetails['address'], 'regions': eggdetails['regions']}
    if enabled:
        await _send_notifications_async('raid', raid_details, raid_channel, [author] if author else [])
    else:
        await _send_notifications_async('raid', raid_details, reportchannel, [author] if author else [])
    for field in oldembed.fields:
        t = 'team'
        s = 'status'
        if (t in field.name.lower()) or (s in field.name.lower()):
            raid_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    try:
        await raid_message.edit(new_content=raidmsg, embed=raid_embed, content=raidmsg)
        raid_message = raid_message.id
    except (discord.errors.NotFound, AttributeError):
        raid_message = None
    try:
        embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
        report_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices)
        await egg_report.edit(new_content=raidreportcontent, embed=report_embed, content=raidreportcontent)
        egg_report = egg_report.id
    except (discord.errors.NotFound, AttributeError):
        egg_report = None
    if eggdetails['raidcityreport'] is not None:
        try:
            await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
        except (discord.errors.NotFound, AttributeError):
            city_report = None
    if str(egglevel) in guild_dict[raid_channel.guild.id]['configure_dict']['counters']['auto_levels'] and not eggdetails.get('pokemon', None):
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, raid_channel.guild, pkmn, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! Update weather with **!weather**. If you know the moveset of the boss, you can react to this message with the matching emoji and I will update the counters."
        ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
        ctrsmessage_id = ctrsmessage.id
        await ctrsmessage.pin()
        for moveset in ctrs_dict:
            await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
            await asyncio.sleep(0.25)
    else:
        ctrs_dict = eggdetails.get('ctrs_dict',{})
        ctrsmessage_id = eggdetails.get('ctrsmessage', None)
    regions = eggdetails.get('regions', None)
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id] = {
        'regions': regions,
        'reportcity': reportcitychannel.id,
        'trainer_dict': trainer_dict,
        'exp': raidexp,
        'manual_timer': manual_timer,
        'active': True,
        'raidmessage': raid_message,
        'raidreport': egg_report,
        'reportchannel': reportchannel.id,
        'address': egg_address,
        'type': hatchtype,
        'pokemon': pkmn.name.lower(),
        'egglevel': '0',
        'ctrs_dict': ctrs_dict,
        'ctrsmessage': ctrsmessage_id,
        'weather': weather,
        'moveset': 0,
        'gym': gym,
        'reporter': reporter
    }
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['starttime'] = starttime
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['duplicate'] = duplicate
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['archive'] = archive
    if author:
        raid_reports = guild_dict[raid_channel.guild.id].setdefault('trainers',{}).setdefault(regions[0], {}).setdefault(author.id,{}).setdefault('raid_reports',0) + 1
        guild_dict[raid_channel.guild.id]['trainers'][regions[0]][author.id]['raid_reports'] = raid_reports
        await list_helpers._edit_party(ctx, Kyogre, guild_dict, raid_info, raid_channel, author)
    await list_helpers.update_listing_channels(Kyogre, guild_dict, raid_channel.guild, 'raid', edit=False, regions=regions)
    await asyncio.sleep(1)
    event_loop.create_task(expiry_check(raid_channel))

@Kyogre.group(name="raidnotice", aliases=['rn'], case_insensitive=True)
@checks.allowraidreport()
async def _raidnotice(ctx):
    """Handles raid notification related commands"""

    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()

@_raidnotice.command(name="available", aliases=["av"])
async def _raid_available(ctx, exptime=None):
    """Announces that you're available for raids
    Usage: `!pvp available [time]`
    Kyogre will post a message stating that you're available for PvP
    for the next 30 minutes by default, or optionally for the amount 
    of time you provide.

    Kyogre will also notify any other users who have added you as 
    a friend that you are now available.
    """
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
                await trainer.remove_roles(*[role_to_remove], reason="Raid availability expired or was cancelled by user.")
            except:
                pass
            return
    time_msg = None
    expiration_minutes = False
    time_err = "Unable to determine the time you provided, you will be notified for raids for the next 60 minutes"
    if exptime:
        if exptime.isdigit():
            if int(exptime) == 0:
                expiration_minutes = 262800
            else:
                expiration_minutes = await time_to_minute_count(channel, exptime, time_err)
    else:
        time_err = "No expiration time provided, you will be notified for raids for the next 60 minutes"
    if expiration_minutes is False:
        time_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.orange(), description=time_err))
        expiration_minutes = 60

    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    expire = now + datetime.timedelta(minutes=expiration_minutes)

    raid_notice_embed = discord.Embed(title='{trainer} is available for Raids!'.format(trainer=trainer.display_name), colour=guild.me.colour)
    if exptime != "0":
        raid_notice_embed.add_field(name='**Expires:**', value='{end}'.format(end=expire.strftime('%b %d %I:%M %p')), inline=True)
    raid_notice_embed.add_field(name='**To add 30 minutes:**', value='Use the ⏲️ react.', inline=True)
    raid_notice_embed.add_field(name='**To cancel:**', value='Use the 🚫 react.', inline=True)

    if region is not None:
        footer_text = f"Use the **@{region}-raids** tag to notify all trainers who are currently available"
        raid_notice_embed.set_footer(text=footer_text)
    raid_notice_msg = await channel.send(content=('{trainer} is available for Raids!').format(trainer=trainer.display_name), embed=raid_notice_embed)
    await raid_notice_msg.add_reaction('\u23f2')
    await raid_notice_msg.add_reaction('🚫')
    expiremsg ='**{trainer} is no longer available for Raids!**'.format(trainer=trainer.display_name)
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
    if time_msg is not None:
        await asyncio.sleep(10)
        await time_msg.delete()
    await message.delete()

@Kyogre.command(aliases=['ex'])
@checks.allowexraidreport()
async def exraid(ctx, *,location:commands.clean_content(fix_channel_mentions=True)=""):
    """Report an upcoming EX raid.

    Usage: !exraid <location>
    Kyogre will insert the details (really just everything after the species name) into a
    Google maps link and post the link to the same channel the report was made in.
    Kyogre's message will also include the type weaknesses of the boss.

    Finally, Kyogre will create a separate channel for the raid report, for the purposes of organizing the raid."""
    await _exraid(ctx, location)

async def _exraid(ctx, location):
    message = ctx.message
    channel = message.channel
    config_dict = guild_dict[message.guild.id]['configure_dict']
    timestamp = (message.created_at + datetime.timedelta(hours=config_dict['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
    if not location:
        await channel.send('Give more details when reporting! Usage: **!exraid <location>**')
        return
    raid_details = location
    regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
    gym = None
    gyms = get_gyms(message.guild.id, regions)
    if gyms:
        gym = await location_match_prompt(message.channel, message.author.id, raid_details, gyms)
        if not gym:
            return await message.channel.send("I couldn't find a gym named '{0}'. Try again using the exact gym name!".format(raid_details))
        raid_channel_ids = get_existing_raid(message.guild, gym, only_ex=True)
        if raid_channel_ids:
            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
            return await message.channel.send(f"A raid has already been reported for {gym.name}. Coordinate in {raid_channel.mention}")
        raid_details = gym.name
        raid_gmaps_link = gym.maps_url
        regions = [gym.region]
    else:
        raid_gmaps_link = create_gmaps_query(raid_details, message.channel, type="exraid")
    egg_info = raid_info['raid_eggs']['EX']
    egg_img = egg_info['egg_img']
    boss_list = []
    for entry in egg_info['pokemon']:
        p = Pokemon.get_pokemon(Kyogre, entry)
        boss_list.append(str(p) + ' (' + str(p.id) + ') ' + utils.types_to_str(ctx.guild, p.types, Kyogre.config))
    raid_channel = await create_raid_channel("exraid", None, None, gym, message.channel)
    if config_dict['invite']['enabled']:
        for role in channel.guild.role_hierarchy:
            if role.permissions.manage_guild or role.permissions.manage_channels or role.permissions.manage_messages:
                try:
                    await raid_channel.set_permissions(role, send_messages=True)
                except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                    pass
    raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'.format(str(egg_img))
    raid_embed = discord.Embed(title='Click here for directions to the coming raid!', url=raid_gmaps_link, colour=message.guild.me.colour)
    if len(egg_info['pokemon']) > 1:
        raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
        raid_embed.add_field(name='\u200b', value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
    else:
        raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist}'.format(bosslist=''.join(boss_list)), inline=True)
        raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
    raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
    raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**', inline=True)
    raid_embed.set_footer(text='Reported by {author} - {timestamp}'.format(author=message.author, timestamp=timestamp), icon_url=message.author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    if config_dict['invite']['enabled']:
        invitemsgstr = "Use the **!invite** command to gain access and coordinate"
        invitemsgstr2 = " after using **!invite** to gain access"
    else:
        invitemsgstr = "Coordinate"
        invitemsgstr2 = ""
    raidreport = await channel.send(content='EX raid egg reported by {member}! Details: {location_details}. {invitemsgstr} in {raid_channel}'.format(member=message.author.mention, location_details=raid_details, invitemsgstr=invitemsgstr,raid_channel=raid_channel.mention), embed=raid_embed)
    await asyncio.sleep(1)
    raidmsg = "EX raid reported by {member} in {citychannel}! Details: {location_details}. Coordinate here{invitemsgstr2}!\n\nClick the question mark reaction to get help on the commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires.".format(member=message.author.display_name, citychannel=message.channel.mention, location_details=raid_details, invitemsgstr2=invitemsgstr2)
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.add_reaction('\u2754')
    await asyncio.sleep(0.1)
    await raidmessage.add_reaction('\u270f')
    await asyncio.sleep(0.1)
    await raidmessage.add_reaction('🚫')
    await asyncio.sleep(0.1)
    await raidmessage.pin()
    guild_dict[message.guild.id]['raidchannel_dict'][raid_channel.id] = {
        'regions': regions,
        'reportcity': channel.id,
        'trainer_dict': {},
        'exp': time.time() + (((60 * 60) * 24) * raid_info['raid_eggs']['EX']['hatchtime']),
        'manual_timer': False,
        'active': True,
        'raidmessage': raidmessage.id,
        'raidreport': raidreport.id,
        'address': raid_details,
        'type': 'egg',
        'pokemon': '',
        'egglevel': 'EX',
        'gym': gym,
        'reporter': message.author.id
    }
    if len(raid_info['raid_eggs']['EX']['pokemon']) == 1:
        await _eggassume('assume ' + raid_info['raid_eggs']['EX']['pokemon'][0], raid_channel)
    await raid_channel.send(content='Hey {member}, if you can, set the time left until the egg hatches using **!timerset <date and time>** so others can check it with **!timer**. **<date and time>** can just be written exactly how it appears on your EX Raid Pass.'.format(member=message.author.mention))
    ex_reports = guild_dict[message.guild.id].setdefault('trainers',{}).setdefault(regions[0], {}).setdefault(message.author.id,{}).setdefault('ex_reports',0) + 1
    guild_dict[message.guild.id]['trainers'][regions[0]][message.author.id]['ex_reports'] = ex_reports
    event_loop.create_task(expiry_check(raid_channel))

@Kyogre.command()
@checks.allowinvite()
async def exinvite(ctx):
    """Join an EX Raid.

    Usage: !invite"""
    await _exinvite(ctx)

async def _exinvite(ctx):
    bot = ctx.bot
    channel = ctx.channel
    author = ctx.author
    guild = ctx.guild
    await channel.trigger_typing()
    exraidlist = ''
    exraid_dict = {}
    exraidcount = 0
    rc_dict = bot.guild_dict[guild.id]['raidchannel_dict']
    for channelid in rc_dict:
        if (not discord.utils.get(guild.text_channels, id=channelid)) or rc_dict[channelid].get('meetup',{}):
            continue
        if (rc_dict[channelid]['egglevel'] == 'EX') or (rc_dict[channelid]['type'] == 'exraid'):
            if guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone" or (guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "same" and rc_dict[channelid]['reportcity'] == channel.id):
                exraid_channel = bot.get_channel(channelid)
                if exraid_channel.mention != '#deleted-channel':
                    exraidcount += 1
                    exraidlist += (('\n**' + str(exraidcount)) + '.**   ') + exraid_channel.mention
                    exraid_dict[str(exraidcount)] = exraid_channel
    if exraidcount == 0:
        await channel.send('No EX Raids have been reported in this server! Use **!exraid** to report one!')
        return
    exraidchoice = await channel.send("{0}, you've told me you have an invite to an EX Raid, and I'm just going to take your word for it! The following {1} EX Raids have been reported:\n{2}\nReply with **the number** (1, 2, etc) of the EX Raid you have been invited to. If none of them match your invite, type 'N' and report it with **!exraid**".format(author.mention, str(exraidcount), exraidlist))
    reply = await bot.wait_for('message', check=(lambda message: (message.author == author)))
    if reply.content.lower() == 'n':
        await exraidchoice.delete()
        exraidmsg = await channel.send('Be sure to report your EX Raid with **!exraid**!')
    elif (not reply.content.isdigit()) or (int(reply.content) > exraidcount):
        await exraidchoice.delete()
        exraidmsg = await channel.send("I couldn't tell which EX Raid you meant! Try the **!invite** command again, and make sure you respond with the number of the channel that matches!")
    elif (int(reply.content) <= exraidcount) and (int(reply.content) > 0):
        await exraidchoice.delete()
        overwrite = discord.PermissionOverwrite()
        overwrite.send_messages = True
        overwrite.read_messages = True
        exraid_channel = exraid_dict[str(int(reply.content))]
        try:
            await exraid_channel.set_permissions(author, overwrite=overwrite)
        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
            pass
        exraidmsg = await channel.send('Alright {0}, you can now send messages in {1}! Make sure you let the trainers in there know if you can make it to the EX Raid!').format(author.mention, exraid_channel.mention)
        await list_helpers._maybe(ctx, Kyogre, guild_dict, raid_info, 0, None)
    else:
        await exraidchoice.delete()
        exraidmsg = await channel.send("I couldn't understand your reply! Try the **!invite** command again!")
    return await utils.sleep_and_cleanup([ctx.message,reply,exraidmsg], 30)

@Kyogre.command(aliases=['shiny'])
@checks.allowresearchreport()
async def shinyquest(ctx, *, details):
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = message.guild
    if details is None:
        err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Please provide a Pokestop name when using this command!"))
        return await utils.sleep_and_cleanup([message,err_msg], 15)
    timestamp = (message.created_at + datetime.timedelta(hours=guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset']))
    to_event_end = 24*60*60 - timestamp-timestamp.replace(hour=0, minute=0, second=0, microsecond=0).seconds
    research_embed = discord.Embed(
        colour=message.guild.me.colour)\
        .set_thumbnail(
        url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
    research_embed.set_footer(text = 'Reported by {author} - {timestamp}'
                              .format(author = author.display_name,
                                      timestamp = timestamp.strftime('%I:%M %p (%H:%M)')),
                              icon_url = author.avatar_url_as(format = None, static_format='jpg', size=32))
    regions = raid_helpers.get_channel_regions(channel, 'research', guild_dict)
    stops = get_stops(guild.id, regions)
    stop = await location_match_prompt(channel, author.id, details, stops)
    if not stop:
        no_stop_msg = await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), description=f"No pokestop found with name {details}"))
        return await utils.sleep_and_cleanup([no_stop_msg], 15)
    location = stop.name
    loc_url = stop.maps_url
    regions = [stop.region]
    quest = await _get_quest(ctx, "Feebas Day")
    reward = await _prompt_reward(ctx, quest)

    research_embed.add_field(name="**Pokestop:**", value='\n'.join(textwrap.wrap(location.title(), width=30)), inline=True)
    research_embed.add_field(name="**Quest:**", value='\n'.join(textwrap.wrap(quest.name.title(), width=30)), inline=True)
    research_embed.add_field(name="**Reward:**", value='\n'.join(textwrap.wrap(reward.title(), width=30)), inline=True)
    research_msg = f'{quest.name} Field Research task, reward: {reward} reported at {location}'
    research_embed.title = 'Click here for my directions to the research!'
    research_embed.description = "Ask {author} if my directions aren't perfect!".format(author=author.name)
    research_embed.url = loc_url
    confirmation = await channel.send(research_msg,embed=research_embed)
    await asyncio.sleep(0.25)
    await confirmation.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await confirmation.add_reaction('🚫')
    await asyncio.sleep(0.25)
    research_dict = copy.deepcopy(guild_dict[guild.id].get('questreport_dict',{}))
    research_dict[confirmation.id] = {
        'regions': regions,
        'exp':time.time() + to_event_end,
        'expedit':"delete",
        'reportmessage':message.id,
        'reportchannel':channel.id,
        'reportauthor':author.id,
        'location':location,
        'url':loc_url,
        'quest':quest.name,
        'reward':reward
    }
    guild_dict[guild.id]['questreport_dict'] = research_dict
    research_reports = guild_dict[ctx.guild.id].setdefault('trainers', {})\
                           .setdefault(regions[0], {})\
                           .setdefault(author.id, {})\
                           .setdefault('research_reports', 0) + 1
    guild_dict[ctx.guild.id]['trainers'][regions[0]][author.id]['research_reports'] = research_reports
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'research', edit=False, regions=regions)
    pokemon = Pokemon.get_pokemon(Kyogre, 'feebas')
    research_details = {'pokemon': pokemon, 'location': location, 'regions': regions}
    await _send_notifications_async('shiny', research_details, channel, [message.author.id])


@Kyogre.command(aliases=['res'])
@checks.allowresearchreport()
async def research(ctx, *, details = None):
    """Report Field research
    Start a guided report method with just !research. 

    If you want to do a quick report, provide the pokestop name followed by the task text with a comma in between.
    Do not include any other commas.

    If you reverse the order, Kyogre will attempt to determine the pokestop.

    Usage: !research [pokestop name, quest]"""
    message = ctx.message
    channel = message.channel
    author = message.author
    guild = message.guild
    timestamp = (message.created_at + datetime.timedelta(
        hours=guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset']))
    to_midnight = 24*60*60 - (timestamp-timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).seconds
    error = False
    loc_url = create_gmaps_query("", message.channel, type="research")
    research_embed = discord.Embed(
        colour=message.guild.me.colour)\
        .set_thumbnail(
        url='https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/field-research.png?cache=0')
    research_embed.set_footer(text='Reported by {author} - {timestamp}'
                              .format(author=author.display_name,
                                      timestamp=timestamp.strftime('%I:%M %p (%H:%M)')),
                              icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    config_dict = guild_dict[guild.id]['configure_dict']
    regions = raid_helpers.get_channel_regions(channel, 'research', guild_dict)
    stops = get_stops(guild.id, regions)
    while True:
        if details:
            research_split = details.rsplit(",", 1)
            if len(research_split) != 2:
                error = "entered an incorrect amount of arguments.\n\nUsage: **!research** or **!research <pokestop>, <quest>**"
                break
            location, quest_name = research_split
            if stops:
                stop = await location_match_prompt(channel, author.id, location, stops)
                if not stop:
                    swap_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"\
                        I couldn't find a pokestop named '**{location}**'. \
                        Perhaps you have reversed the order of your report?\n\n\
                        Looking up stop with name '**{quest_name.strip()}**'"))
                    quest_name, location = research_split
                    stop = await location_match_prompt(channel, author.id, location.strip(), stops)
                    if not stop:
                        await swap_msg.delete()
                        err_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No pokestop found with name '**{location.strip()}**' either. Try reporting again using the exact pokestop name!"))
                        return await utils.sleep_and_cleanup([err_msg], 15)
                    await swap_msg.delete()
                if get_existing_research(guild, stop):
                    return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"A quest has already been reported for {stop.name}"))
                location = stop.name
                loc_url = stop.maps_url
                regions = [stop.region]
            else:
                loc_url = create_gmaps_query(location, channel, type="research")
            location = location.replace(loc_url,"").strip()
            quest = await _get_quest(ctx, quest_name)
            if not quest:
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a quest named '{quest_name}'"))
            reward = await _prompt_reward(ctx, quest)
            if not reward:
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a reward for '{quest_name}'"))
            research_embed.add_field(name="**Pokestop:**",value='\n'.join(textwrap.wrap(location.title(), width=30)),inline=True)
            research_embed.add_field(name="**Quest:**",value='\n'.join(textwrap.wrap(quest.name.title(), width=30)),inline=True)
            research_embed.add_field(name="**Reward:**",value='\n'.join(textwrap.wrap(reward.title(), width=30)),inline=True)
            break
        else:
            research_embed.add_field(name='**New Research Report**', value="I'll help you report a research quest!\n\nFirst, I'll need to know what **pokestop** you received the quest from. Reply with the name of the **pokestop**. You can reply with **cancel** to stop anytime.", inline=False)
            pokestopwait = await channel.send(embed=research_embed)
            try:
                pokestopmsg = await Kyogre.wait_for('message', timeout=60, check=(lambda reply: reply.author == message.author))
            except asyncio.TimeoutError:
                pokestopmsg = None
            await pokestopwait.delete()
            if not pokestopmsg:
                error = "took too long to respond"
                break
            elif pokestopmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await pokestopmsg.delete()
                break
            elif pokestopmsg:
                location = pokestopmsg.clean_content
                if stops:
                    stop = await location_match_prompt(channel, author.id, location, stops)
                    if not stop:
                        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"I couldn't find a pokestop named '{location}'. Try again using the exact pokestop name!"))
                    if get_existing_research(guild, stop):
                        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"A quest has already been reported for {stop.name}"))
                    location = stop.name
                    loc_url = stop.maps_url
                    regions = [stop.region]
                else:
                    loc_url = create_gmaps_query(location, channel, type="research")
                location = location.replace(loc_url,"").strip()
            await pokestopmsg.delete()
            research_embed.add_field(name="**Pokestop:**",value='\n'.join(textwrap.wrap(location.title(), width=30)),inline=True)
            research_embed.set_field_at(0, name=research_embed.fields[0].name, value="Great! Now, reply with the **quest** that you received from **{location}**. You can reply with **cancel** to stop anytime.\n\nHere's what I have so far:".format(location=location), inline=False)
            questwait = await channel.send(embed=research_embed)
            try:
                questmsg = await Kyogre.wait_for('message', timeout=60, check=(lambda reply: reply.author == message.author))
            except asyncio.TimeoutError:
                questmsg = None
            await questwait.delete()
            if not questmsg:
                error = "took too long to respond"
                break
            elif questmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await questmsg.delete()
                break
            elif questmsg:
                quest = await _get_quest(ctx, questmsg.clean_content)
            await questmsg.delete()
            if not quest:
                error = "didn't identify the quest"
                break
            research_embed.add_field(name="**Quest:**",value='\n'.join(textwrap.wrap(quest.name.title(), width=30)),inline=True)
            reward = await _prompt_reward(ctx, quest)
            if not reward:
                error = "didn't identify the reward"
                break
            research_embed.add_field(name="**Reward:**",value='\n'.join(textwrap.wrap(reward.title(), width=30)),inline=True)
            research_embed.remove_field(0)
            break
    if not error:
        research_msg = f'{quest.name} Field Research task, reward: {reward} reported at {location}'
        research_embed.title = 'Click here for my directions to the research!'
        research_embed.description = "Ask {author} if my directions aren't perfect!".format(author=author.name)
        research_embed.url = loc_url
        confirmation = await channel.send(research_msg,embed=research_embed)
        await asyncio.sleep(0.25)
        await confirmation.add_reaction('\u270f')
        await asyncio.sleep(0.25)
        await confirmation.add_reaction('🚫')
        await asyncio.sleep(0.25)
        research_dict = copy.deepcopy(guild_dict[guild.id].get('questreport_dict',{}))
        research_dict[confirmation.id] = {
            'regions': regions,
            'exp':time.time() + to_midnight,
            'expedit':"delete",
            'reportmessage':message.id,
            'reportchannel':channel.id,
            'reportauthor':author.id,
            'location':location,
            'url':loc_url,
            'quest':quest.name,
            'reward':reward
        }
        guild_dict[guild.id]['questreport_dict'] = research_dict
        research_reports = guild_dict[ctx.guild.id].setdefault('trainers',{}).setdefault(regions[0], {}).setdefault(author.id,{}).setdefault('research_reports',0) + 1
        guild_dict[ctx.guild.id]['trainers'][regions[0]][author.id]['research_reports'] = research_reports
        await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'research', edit=False, regions=regions)
        if 'encounter' in reward.lower():
            pokemon = reward.rsplit(maxsplit=1)[0]
            research_details = {'pokemon': [Pokemon.get_pokemon(Kyogre, p) for p in re.split(r'\s*,\s*', pokemon)], 'location': location, 'regions': regions}
            await _send_notifications_async('research', research_details, channel, [message.author.id])
        elif reward.split(' ')[0].isdigit() and 'stardust' not in reward.lower():
            item = ' '.join(reward.split(' ')[1:])
            research_details = {'item': item, 'location': location, 'regions': regions}
            await _send_notifications_async('item', research_details, channel, [message.author.id])
    else:
        research_embed.clear_fields()
        research_embed.add_field(name='**Research Report Cancelled**', value="Your report has been cancelled because you {error}! Retry when you're ready.".format(error=error), inline=False)
        confirmation = await channel.send(embed=research_embed)
        return await utils.sleep_and_cleanup([message,confirmation], 10)

async def _get_quest(ctx, name):
    channel = ctx.channel
    author = ctx.message.author.id
    return await _get_quest_v(channel, author, name)

async def _get_quest_v(channel, author, name):
    """gets a quest by name or id"""
    if not name:
        return
    quest_id = None
    if str(name).isnumeric():
        quest_id = int(name)
    try:
        query = QuestTable.select()
        if quest_id is not None:
            query = query.where(QuestTable.id == quest_id)
        query = query.execute()
        result = [d for d in query]
    except:
        return await channel.send("No quest data available!")
    if quest_id is not None:
        return None if not result else result[0]
    quest_names = [q.name.lower() for q in result]
    if name.lower() not in quest_names:
        candidates = utils.get_match(quest_names, name, score_cutoff=60, isPartial=True, limit=20)
        name = await prompt_match_result(channel, author, name, candidates)
    return next((q for q in result if q.name is not None and q.name.lower() == name.lower()), None)


async def _prompt_reward(ctx, quest, reward_type=None):
    channel = ctx.channel
    author = ctx.message.author.id
    return await _prompt_reward_v(channel, author, quest, reward_type)


async def _prompt_reward_v(channel, author, quest, reward_type=None):
    """prompts user for reward info selection using quest's reward pool
    can optionally specify a start point with reward_type"""
    if not quest or not quest.reward_pool:
        return
    if reward_type:
        if reward_type not in quest.reward_pool:
            raise ValueError("Starting point provided is invalid")
    else:
        candidates = [k for k, v in quest.reward_pool.items() if len(v) > 0]
        if len(candidates) == 0:
            return
        elif len(candidates) == 1:
            reward_type = candidates[0]
        else:
            prompt = "Please select a reward type:"
            reward_type = await utils.ask_list(Kyogre, prompt, channel, candidates, user_list=author)
    if not reward_type:
        return
    target_pool = quest.reward_pool[reward_type]
    # handle encounters
    if reward_type == "encounters":
        return f"{', '.join([p.title() for p in target_pool])} Encounter"
    # handle items
    if reward_type == "items":
        if len(target_pool) == 1:
            tp_key = list(target_pool.keys())[0]
            return f"{target_pool[tp_key][0]} {tp_key}"
        else:
            candidates = [k for k in target_pool]
            prompt = "Please select an item:"
            reward_type = await utils.ask_list(Kyogre, prompt, channel, candidates, user_list=author)
            if not reward_type:
                return
            target_pool = target_pool[reward_type]
    if len(target_pool) == 1:
        return f"{target_pool[0]} {reward_type.title()}"
    else:
        candidates = [str(q) for q in target_pool]
        prompt = "Please select the correct quantity:"
        quantity = await utils.ask_list(Kyogre, prompt, channel, candidates, user_list=author)
        if not quantity:
            return
        return f"{quantity} {reward_type.title()}"


@Kyogre.command(aliases=['event'])
@checks.allowmeetupreport()
async def meetup(ctx, *, location:commands.clean_content(fix_channel_mentions=True)=""):
    """Report an upcoming event.

    Usage: !meetup <location>
    Kyogre will insert the details (really just everything after the species name) into a
    Google maps link and post the link to the same channel the report was made in.

    Finally, Kyogre will create a separate channel for the report, for the purposes of organizing the event."""
    await _meetup(ctx, location)

async def _meetup(ctx, location):
    message = ctx.message
    channel = message.channel
    timestamp = (message.created_at + datetime.timedelta(hours=guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
    event_split = location.split()
    if len(event_split) <= 0:
        await channel.send('Give more details when reporting! Usage: **!meetup <location>**')
        return
    raid_details = ' '.join(event_split)
    raid_details = raid_details.strip()
    raid_gmaps_link = create_gmaps_query(raid_details, message.channel, type="meetup")
    raid_channel_name = 'meetup-'
    raid_channel_name += utils.sanitize_name(raid_details)
    raid_channel_category = get_category(message.channel,"EX", category_type="meetup")
    raid_channel = await message.guild.create_text_channel(raid_channel_name, overwrites=message.channel.overwrites, category=raid_channel_category)
    ow = raid_channel.overwrites_for(raid_channel.guild.default_role)
    ow.send_messages = True
    try:
        await raid_channel.set_permissions(raid_channel.guild.default_role, overwrite = ow)
    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
        pass
    raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/meetup.png?cache=0'
    raid_embed = discord.Embed(title='Click here for directions to the event!', url=raid_gmaps_link, colour=message.guild.me.colour)
    raid_embed.add_field(name='**Event Location:**', value=raid_details, inline=True)
    raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
    raid_embed.add_field(name='**Event Starts:**', value='Set with **!starttime**', inline=True)
    raid_embed.add_field(name='**Event Ends:**', value='Set with **!timerset**', inline=True)
    raid_embed.set_footer(text='Reported by {author} - {timestamp}'.format(author=message.author.display_name, timestamp=timestamp), icon_url=message.author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    raidreport = await channel.send(content='Meetup reported by {member}! Details: {location_details}. Coordinate in {raid_channel}'.format(member=message.author.display_name, location_details=raid_details, raid_channel=raid_channel.mention), embed=raid_embed)
    await asyncio.sleep(1)
    raidmsg = "Meetup reported by {member} in {citychannel}! Details: {location_details}. Coordinate here!\n\nTo update your status, choose from the following commands: **!maybe**, **!coming**, **!here**, **!cancel**. If you are bringing more than one trainer/account, add in the number of accounts total, teams optional, on your first status update.\nExample: `!coming 5 2m 2v 1i`\n\nTo see the list of trainers who have given their status:\n**!list interested**, **!list coming**, **!list here** or use just **!list** to see all lists. Use **!list teams** to see team distribution.\n\nSometimes I'm not great at directions, but I'll correct my directions if anybody sends me a maps link or uses **!location new <address>**. You can see the location of the event by using **!location**\n\nYou can set the start time with **!starttime <MM/DD HH:MM AM/PM>** (you can also omit AM/PM and use 24-hour time) and access this with **!starttime**.\nYou can set the end time with **!timerset <MM/DD HH:MM AM/PM>** and access this with **!timer**.\n\nThis channel will be deleted five minutes after the timer expires.".format(member=message.author.display_name, citychannel=message.channel.mention, location_details=raid_details)
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.pin()
    guild_dict[message.guild.id]['raidchannel_dict'][raid_channel.id] = {
        'reportcity': channel.id,
        'trainer_dict': {},
        'exp': time.time() + (((60 * 60) * 24) * raid_info['raid_eggs']['EX']['hatchtime']),
        'manual_timer': False,
        'active': True,
        'raidmessage': raidmessage.id,
        'raidreport': raidreport.id,
        'address': raid_details,
        'type': 'egg',
        'pokemon': '',
        'egglevel': 'EX',
        'meetup': {'start':None, 'end':None},
        'reporter': message.author.id
    }
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[raid_channel.guild.id]['configure_dict']['settings']['offset'])
    await raid_channel.send(content='Hey {member}, if you can, set the time that the event starts with **!starttime <date and time>** and also set the time that the event ends using **!timerset <date and time>**.'.format(member=message.author.mention))
    event_loop.create_task(expiry_check(raid_channel))


async def _send_notifications_async(type, details, new_channel, exclusions=[]):
    valid_types = ['raid', 'research', 'wild', 'nest', 'gym', 'shiny', 'item', 'lure']
    if type not in valid_types:
        return
    guild = new_channel.guild
    # get trainers
    try:
        results = (SubscriptionTable
                        .select(SubscriptionTable.trainer, SubscriptionTable.target, SubscriptionTable.specific)
                        .join(TrainerTable, on=(SubscriptionTable.trainer == TrainerTable.snowflake))
                        .where((SubscriptionTable.type == type) | 
                            (SubscriptionTable.type == 'pokemon') | 
                            (SubscriptionTable.type == 'gym') )
                        .where(TrainerTable.guild == guild.id)).execute()
    except:
        return
    # group targets by trainer
    trainers = set([s.trainer for s in results])
    target_dict = {t: {s.target: s.specific for s in results if s.trainer == t} for t in trainers}
    regions = set(details.get('regions', []))
    ex_eligible = details.get('ex-eligible', None)
    tier = details.get('tier', None)
    perfect = details.get('perfect', None)
    pokemon_list = details.get('pokemon', [])
    gym = details.get('location', None)
    item = details.get('item', None)
    lure_type = details.get('lure_type', None)
    if not isinstance(pokemon_list, list):
        pokemon_list = [pokemon_list]
    location = details.get('location', None)
    region_dict = guild_dict[guild.id]['configure_dict'].get('regions', None)
    outbound_dict = {}
    # build final dict
    for trainer in target_dict:
        user = guild.get_member(trainer)
        if trainer in exclusions or not user:
            continue
        if region_dict and region_dict.get('enabled', False):
            matched_regions = [n for n, o in region_dict.get('info', {}).items() if o['role'] in [r.name for r in user.roles]]
            if regions and regions.isdisjoint(matched_regions):
                continue
        targets = target_dict[trainer]
        descriptors = []
        target_matched = False
        if 'ex-eligible' in targets and ex_eligible:
            target_matched = True
            descriptors.append('ex-eligible')
        if tier and str(tier) in targets:
            tier = str(tier)
            if targets[tier]:
                try:
                    current_gym_ids = targets[tier].strip('[').strip(']')
                    split_ids = current_gym_ids.split(', ')
                    split_ids = [int(s) for s in split_ids]
                    target_gyms = (GymTable
                        .select(LocationTable.id,
                                LocationTable.name, 
                                LocationTable.latitude, 
                                LocationTable.longitude, 
                                RegionTable.name.alias('region'),
                                GymTable.ex_eligible,
                                LocationNoteTable.note)
                        .join(LocationTable)
                        .join(LocationRegionRelation)
                        .join(RegionTable)
                        .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                        .where((LocationTable.guild == guild.id) &
                               (LocationTable.guild == RegionTable.guild) &
                               (LocationTable.id << split_ids)))
                    target_gyms = target_gyms.objects(Gym)
                    found_gym_names = [r.name for r in target_gyms]
                    if gym in found_gym_names:
                        target_matched = True
                except:
                    pass
            else:
                target_matched = True
            descriptors.append('level {level}'.format(level=details['tier']))
        pkmn_adj = ''
        if perfect and 'perfect' in targets:
            target_matched = True
            pkmn_adj = 'perfect '
        for pokemon in pokemon_list:
            if pokemon.name in targets:
                target_matched = True
            full_name = pkmn_adj + pokemon.name
            descriptors.append(full_name)
        if gym in targets:
            target_matched = True
        if item and item.lower() in targets:
            target_matched = True
        if 'shiny' in targets:
            target_matched = True
        if lure_type and lure_type in targets:
            target_matched = True
        if not target_matched:
            continue
        description = ', '.join(descriptors)
        start = 'An' if re.match(r'^[aeiou]', description, re.I) else 'A'
        if type == 'item':
            start = 'An' if re.match(r'^[aeiou]', item, re.I) else 'A'
            message = f'{start} **{item}** task has been reported at {location}! For more details, go to the {new_channel.mention} channel.'
        elif type == 'lure':
            message = f'A **{lure_type.capitalize()}** lure has been dropped at {location}!'
        else:
            message = f'**New {type.title()}**! {start} {description} {type} at {location} has been reported! For more details, go to the {new_channel.mention} channel!'
        outbound_dict[trainer] = {'discord_obj': user, 'message': message}
    pokemon_names = ' '.join([p.name for p in pokemon_list])
    if type == 'item':
        role_name = utils.sanitize_name(f"{item} {location}".title())
    elif type == 'lure':
        role_name = utils.sanitize_name(f'{lure_type} {location}'.title())
    else:
        role_name = utils.sanitize_name(f"{type} {pokemon_names} {location}".title())
    return await _generate_role_notification_async(role_name, new_channel, outbound_dict)


async def _generate_role_notification_async(role_name, channel, outbound_dict):
    """Generates and handles a temporary role notification in the new raid channel"""
    if len(outbound_dict) == 0:
        return
    guild = channel.guild
    # generate new role
    temp_role = await guild.create_role(name=role_name, hoist=False, mentionable=True)
    for trainer in outbound_dict.values():
        await trainer['discord_obj'].add_roles(temp_role)
    # send notification message in channel
    obj = next(iter(outbound_dict.values()))
    message = obj['message']
    msg_obj = await channel.send(f'~{temp_role.mention} {message}')

    async def cleanup():
        await asyncio.sleep(300)
        await temp_role.delete()
        await msg_obj.delete()
    asyncio.ensure_future(cleanup())


"""
Data Management Commands
"""
@Kyogre.group(name="reports")
@commands.has_permissions(manage_guild=True)
async def _reports(ctx):
    """Report data management command"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()


@_reports.command(name="list", aliases=["ls"])
async def _reports_list(ctx, *, list_type, regions=''):
    """Lists the current active reports of the specified type, optionally for one or more regions"""
    valid_types = ['raid', 'research']
    channel = ctx.channel
    list_type = list_type.lower()
    if list_type not in valid_types:
        await channel.send(f"'{list_type}' is either invalid or unsupported. Please use one of the following: {', '.join(valid_types)}")
    await ctx.channel.send(f"This is a {list_type} listing")


@Kyogre.group(name="loc")
async def _loc(ctx):
    """Location data management command"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()


@_loc.command(name="add")
@commands.has_permissions(manage_guild=True)
async def _loc_add(ctx, *, info):
    """Adds a new location to the database

    Requires type (gym/stop), name, region name, latitude, longitude in that order.
    Optionally a true/false for ex eligibility can be provided as well."""
    channel = ctx.channel
    message = ctx.message
    loc_type = None
    name = None
    region = None
    latitude = None
    longitude = None
    ex_eligible = None
    error_msg = None
    try:
        if ',' in info:
            info_split = info.split(',')
            if len(info_split) < 5:
                error_msg = "Please provide the following when using this command: `location type, name, region, latitude, longitude, (optional) ex eligible`"
            elif len(info_split) == 5:
                loc_type, name, region, latitude, longitude = [x.strip() for x in info.split(',')]
            elif len(info_split) == 6:
                loc_type, name, region, latitude, longitude, ex_eligible = [x.strip() for x in info.split(',')]
        else:
            error_msg = "Please provide the following when using this command: `location type, name, region, latitude, longitude, (optional) ex eligible`"
    except:
        error_msg = "Please provide the following when using this command: `location type, name, region, latitude, longitude, (optional) ex eligible`"
    if error_msg is not None:
        return await channel.send(error_msg)
    data = {}
    data["coordinates"] = f"{latitude},{longitude}"
    if loc_type == "gym":
        if ex_eligible is not None:
            data["ex_eligible"] = bool(ex_eligible)
        else:
            data["ex_eligible"] = False
    data["region"] = region.lower()
    data["guild"] = str(ctx.guild.id)
    error_msg = LocationTable.create_location(name, data)
    if error_msg is None:
        success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully added {loc_type}: {name}."))
        await message.add_reaction('✅')
        return await utils.sleep_and_cleanup([success], 10)
    else:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to add {loc_type}: {name}."))
        await message.add_reaction('❌')   
        return await utils.sleep_and_cleanup([failed], 10)


@_loc.command(name="convert", aliases=["c"])
@commands.has_permissions(manage_guild=True)
async def _loc_convert(ctx, *, info):
    """Changes a pokestop into a gym

    Requires the name of a Pokestop."""
    channel = ctx.channel
    author = ctx.message.author
    stops = get_stops(ctx.guild.id, None)
    stop = await location_match_prompt(channel, author.id, info, stops)
    if not stop:
        no_stop_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No pokestop found with name **{info}**"))
        return await utils.sleep_and_cleanup([no_stop_msg], 10)
    result = await stopToGym(ctx, stop.name)
    if result[0] == 0:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to convert stop to gym."))
        await ctx.message.add_reaction('❌') 
        return await utils.sleep_and_cleanup([failed], 10)       
    else:
        success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Converted {result[0]} stop(s) to gym(s)."))
        await ctx.message.add_reaction('✅')
        return await utils.sleep_and_cleanup([success], 10)


@_loc.command(name="extoggle", aliases=["ext"])
@commands.has_permissions(manage_guild=True)
async def _loc_extoggle(ctx, *, info):
    """Toggles gym ex status

    Requires the name of a gym. Ex status can't be set directly,
    only swapped from its current state."""
    channel = ctx.channel
    author = ctx.message.author
    gyms = get_gyms(ctx.guild.id, None)
    gym = await location_match_prompt(channel, author.id, info, gyms)
    if not gym:
        no_gym_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No gym found with name {info}"))
        await asyncio.sleep(15)
        await no_gym_msg.delete()
        return
    result = await toggleEX(ctx, gym.name)
    if result == 0:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to change gym's EX status."))
        await ctx.message.add_reaction('❌')        
        await asyncio.sleep(15)
        await failed.delete()
        return
    else:
        success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully changed EX status for {result} gym(s)."))
        await ctx.message.add_reaction('✅')
        await asyncio.sleep(15)
        await success.delete()
        return


@_loc.command(name="changeregion", aliases=["cr"])
@commands.has_permissions(manage_guild=True)
async def _loc_change_region(ctx, *, info):
    """Changes the region associated with a Location.

    Requires type (stop/gym), the name of the location,
    and the name of the new region it should be assigned to."""
    channel = ctx.channel
    message = ctx.message
    author = message.author
    info = [x.strip() for x in info.split(',')]
    stop, gym = None, None
    if len(info) != 3:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Please provide (comma separated) the location type (stop or gym), name of the Pokestop or gym, and the new region it should be assigned to."))
        await message.add_reaction('❌')
        return await utils.sleep_and_cleanup([failed], 10)
    if info[0].lower() == "stop":
        stops = get_stops(ctx.guild.id, None)
        stop = await location_match_prompt(channel, author.id, info[1], stops)
        if stop is not None:
            name = stop.name
    elif info[0].lower() == "gym":
        gyms = get_gyms(ctx.guild.id, None)
        gym = await location_match_prompt(channel, author.id, info[1], gyms)
        if gym is not None:
            name = gym.name
    if not stop and not gym:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No {info[0]} found with name {info[1]}."))
        await message.add_reaction('❌')        
        return await utils.sleep_and_cleanup([failed], 10)
    result = await changeRegion(ctx, name, info[2])
    if result == 0:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to change location for {name}."))
        await message.add_reaction('❌')        
        return await utils.sleep_and_cleanup([failed], 10)
    else:
        success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully changed location for {name}."))
        await message.add_reaction('✅')
        return await utils.sleep_and_cleanup([success], 10)


@_loc.command(name="deletelocation", aliases=["del"])
@commands.has_permissions(manage_guild=True)
async def _loc_deletelocation(ctx, *, info):
    """Removes a location from the database

    Requires type (stop/gym) and the name of the location.
    Requires no confirmation, will delete as soon as the
    correct stop or gym is identified."""
    channel = ctx.channel
    message = ctx.message
    author = message.author
    info = info.split(',')
    if len(info) != 2:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Please provide (comma separated) the location type (stop or gym) and the name of the Pokestop or gym."))
        await message.add_reaction('❌')
        return await utils.sleep_and_cleanup([failed], 10)
    loc_type = info[0].lower()
    stop = None
    gym = None
    if loc_type == "stop":
        stops = get_stops(ctx.guild.id, None)
        stop = await location_match_prompt(channel, author.id, info[1], stops)
        if stop is not None:
            name = stop.name
    elif loc_type == "gym":
        gyms = get_gyms(ctx.guild.id, None)
        gym = await location_match_prompt(channel, author.id, info[1], gyms)
        if gym is not None:
            name = gym.name
    if not stop and not gym:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No {info[0]} found with name {info[1]}."))
        await message.add_reaction('❌')        
        return await utils.sleep_and_cleanup([failed], 10)
    result = await deleteLocation(ctx, loc_type, name)
    if result == 0:
        failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to delete {loc_type}: {name}."))
        await message.add_reaction('❌')        
        return await utils.sleep_and_cleanup([failed], 10)
    else:
        success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully deleted {loc_type}: {name}."))
        await message.add_reaction('✅')
        return await utils.sleep_and_cleanup([success], 10)


async def deleteLocation(ctx, type, name):
    channel = ctx.channel
    guild = ctx.guild
    deleted = 0
    with KyogreDB._db.atomic() as txn:
        try:
            locationresult = (LocationTable
                .get((LocationTable.guild == guild.id) &
                       (LocationTable.name == name)))
            location = LocationTable.get_by_id(locationresult)
            loc_reg = (LocationRegionRelation
                .get(LocationRegionRelation.location_id == locationresult))
            if type == "stop":
                deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
            elif type == "gym":
                deleted = GymTable.delete().where(GymTable.location_id == locationresult).execute()
            deleted += LocationRegionRelation.delete().where(LocationRegionRelation.id == loc_reg).execute()
            deleted += location.delete_instance()
            txn.commit()
        except Exception as e: 
            await channel.send(e)
            txn.rollback()
    return deleted


async def stopToGym(ctx, name):
    channel = ctx.channel
    guild = ctx.guild
    deleted = 0
    created = 0
    with KyogreDB._db.atomic() as txn:
        try:
            locationresult = (LocationTable
                .get((LocationTable.guild == guild.id) &
                       (LocationTable.name == name)))
            deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
            location = LocationTable.get_by_id(locationresult)
            created = GymTable.create(location = location, ex_eligible = False)
            txn.commit()
        except Exception as e: 
            await channel.send(e)
            txn.rollback()
    return (deleted, created)


async def toggleEX(ctx, name):
    channel = ctx.channel
    guild = ctx.guild
    success = 0
    with KyogreDB._db.atomic() as txn:
        try:
            locationresult = (LocationTable
                .get((LocationTable.guild == guild.id) &
                       (LocationTable.name == name)))
            location = LocationTable.get_by_id(locationresult)
            success = GymTable.update(ex_eligible = ~GymTable.ex_eligible).where(GymTable.location_id == location.id).execute()
            txn.commit()
        except Exception as e: 
            await channel.send(e)
            txn.rollback()
    return success


async def changeRegion(ctx, name, region):
    success = 0
    with KyogreDB._db.atomic() as txn:
        try:
            current = (LocationTable
                      .select(LocationTable.id.alias('loc_id'))
                      .join(LocationRegionRelation)
                      .join(RegionTable)
                      .where((LocationTable.guild == ctx.guild.id) &
                             (LocationTable.guild == RegionTable.guild) &
                             (LocationTable.name == name)))
            loc_id = current[0].loc_id
            current = (RegionTable
                       .select(RegionTable.id.alias('reg_id'))
                       .join(LocationRegionRelation)
                       .join(LocationTable)
                       .where((LocationTable.guild == ctx.guild.id) &
                              (LocationTable.guild == RegionTable.guild) &
                              (LocationTable.id == loc_id)))
            reg_id = current[0].reg_id
            deleted = LocationRegionRelation.delete().where((LocationRegionRelation.location_id == loc_id) &
                                                            (LocationRegionRelation.region_id == reg_id)).execute()
            new = (RegionTable
                   .select(RegionTable.id)
                   .where((RegionTable.name == region) &
                          (RegionTable.guild_id == ctx.guild.id)))
            success = LocationRegionRelation.create(location=loc_id, region=new[0].id)
        except Exception as e: 
            await ctx.channel.send(e)
            txn.rollback()
    return success


@Kyogre.group(name="quest")
async def _quest(ctx):
    """Quest data management command"""
    if ctx.invoked_subcommand == None:
        raise commands.BadArgument()


@_quest.command(name="info", aliases=["lookup", "get", "find"])
@checks.allowresearchreport()
async def _quest_info(ctx, *, name):
    """Look up a quest by name, returning the quest ID and details
    
    Usage: !quest info <name>"""
    channel = ctx.channel
    quest = await _get_quest(ctx, name)
    if not quest:
        return await channel.send("Unable to find quest by that name")
    await channel.send(format_quest_info(quest))


@_quest.command(name="add")
@commands.has_permissions(manage_guild=True)
async def _quest_add(ctx, *, info):
    """Add a new quest and associated reward pool, separated by comma.
    
    Usage: !quest add <name>[, reward_pool]
    
    Reward pool should be provided as a JSON string. If not provided, an empty default will be used."""
    channel = ctx.channel
    if ',' in info:
        name, pool = info.split(',', 1)
    else:
        name = info
    if '{' in name:
        return await channel.send('Please check the format of your message and try again. The name and reward pool should be separated by a comma')
    if pool:
        try:
            pool = json.loads(pool)
        except ValueError:
            return await channel.send("Error: provided reward pool is not a valid JSON string")
    try:
        new_quest = QuestTable.create(name=name, reward_pool=pool if pool else {})
    except:
        return await channel.send("Unable to add record. Please ensure the quest does not already exist with the find command.")
    await channel.send(f"Successfully added new quest: {new_quest.name} ({new_quest.id})")

@_quest.command(name="remove", aliases=["rm", "delete", "del"])
@commands.has_permissions(manage_guild=True)
async def _quest_remove(ctx, id):
    """Remove a quest by its ID
    
    Usage: !quest remove <id>"""
    channel = ctx.channel
    try:
        deleted = QuestTable.delete().where(QuestTable.id == id).execute()
    except:
        deleted = False
    if deleted:
        return await channel.send("Successfully deleted record")
    return await channel.send("Unable to delete record")


def format_quest_info(quest):
    pool = quest.reward_pool
    output = f"{quest.name} ({quest.id})\n"
    encounters = pool.get('encounters', [])
    stardust = pool.get('stardust', [])
    xp = pool.get('xp', [])
    items = pool.get('items', {})
    if encounters:
        encounters = [str(e) for e in encounters]
        output += f"\nEncounters: {', '.join(encounters).title()}"
    if stardust:
        stardust = [str(s) for s in stardust]
        output += f"\nStardust: {', '.join(stardust)}"
    if xp:
        xp = [str(x) for x in xp]
        output += f"\nExperience: {', '.join(xp)}"
    if items:
        output += "\nItems:"
        for name, quantities in items.items():
            output += f"\n\t{name.title()}: {quantities[0] if len(quantities) == 1 else str(quantities[0]) + ' - ' + str(quantities[-1])}"
    return output


@Kyogre.group(name="rewards")
@commands.has_permissions(manage_guild=True)
async def _rewards(ctx):
    """Quest reward pool data management command"""
    if not ctx.invoked_subcommand:
        raise commands.BadArgument()


@_rewards.command(name="add")
async def _rewards_add(ctx, *, info):
    """Adds a reward to reward pool for a given quest using provided comma-separated values.
    
    Usage: !rewards add <ID>, <type>, <value>
    
    ID must correspond to a valid db entry.
    If type is not encounters, stardust, or xp, it will be assumed to be an item."""
    channel = ctx.channel
    try:
        reward_id, reward_type, value = re.split(r'\s*,\s*', info)
        reward_id = int(reward_id)
        reward_type = reward_type.lower()
    except:
        return await channel.send("Error parsing input. Please check the format and try again")
    try:
        quest = QuestTable[reward_id]
    except:
        return await channel.send(f"Unable to get quest with id {reward_id}")
    pool = quest.reward_pool
    if reward_type.startswith("encounter"):
        pokemon = Pokemon.get_pokemon(Kyogre, value)
        if pokemon:
            pool.setdefault("encounters", []).append(pokemon.name.lower())
    else:
        if not value.isnumeric():
            return await channel.send("Value must be a numeric quantity")
        if reward_type == "stardust":
            pool.setdefault("stardust", []).append(int(value))
        elif reward_type == "xp":
            pool.setdefault("xp", []).append(int(value))
        else:
            pool.setdefault("items", {}).setdefault(reward_type, []).append(int(value))
    quest.reward_pool = pool
    quest.save()
    await channel.send("Successfully added reward to pool")


@_rewards.command(name="remove", aliases=["rm", "delete", "del"])
async def _rewards_remove(ctx, *, info):
    """Removes a reward to reward pool for a given quest using provided comma-separated values.
    
    Usage: !rewards remove <ID>, <type>, <value>
    
    ID must correspond to a valid db entry.
    If type is not encounters, stardust, or xp, it will be assumed to be an item."""
    channel = ctx.channel
    try:
        id, type, value = re.split(r'\s*,\s*', info)
        id = int(id)
        type = type.lower()
    except:
        return await channel.send("Error parsing input. Please check the format and try again")
    try:
        quest = QuestTable[id]
    except:
        return await channel.send(f"Unable to get quest with id {id}")
    pool = quest.reward_pool
    if type.startswith("encounter"):
        encounters = [x.lower() for x in pool["encounters"]]
        pokemon = Pokemon.get_pokemon(Kyogre, value)
        name = pokemon.name.lower()
        if pokemon:
            try:
                encounters.remove(name)
            except:
                return await channel.send(f"Unable to remove {value}")
        pool["encounters"] = encounters
    else:
        if not value.isnumeric():
            return await channel.send("Value must be a numeric quantity")
        try:
            if type == "stardust":
                pool["stardust"].remove(int(value))
            elif type == "xp":
                pool["xp"].remove(int(value))
            else:
                pool["items"][type].remove(int(value))
                if len(pool["items"][type]) == 0:
                    del pool["items"][type]
        except:
            return await channel.send(f"Unable to remove {value}")
    quest.reward_pool = pool
    quest.save()
    await channel.send("Successfully removed reward from pool")


@Kyogre.command(name="refresh_listings", hidden=True)
@commands.has_permissions(manage_guild=True)
async def _refresh_listing_channels(ctx, type, *, regions=None):
    if regions:
        regions = [r.strip() for r in regions.split(',')]
    await list_helpers.update_listing_channels(Kyogre, guild_dict, ctx.guild, type, edit=True, regions=regions)
    await ctx.message.add_reaction('\u2705')

async def _refresh_listing_channels_internal(guild, type, *, regions=None):
    if regions:
        regions = [r.strip() for r in regions.split(',')]
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, type, edit=True, regions=regions)

"""
Raid Channel Management
"""

async def print_raid_timer(channel):
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(seconds=guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['exp'] - time.time())
    timerstr = ' '
    if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('meetup',{}):
        end = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['meetup']['end']
        start = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['meetup']['start']
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
            if start:
                timerstr += "This event will start at {expiry_time}".format(expiry_time=start.strftime('%B %d at %I:%M %p (%H:%M)'))
            else:
                timerstr += "Nobody has told me a start time! Set it with **!starttime**"
            if end:
                timerstr += " | This event will end at {expiry_time}".format(expiry_time=end.strftime('%B %d at %I:%M %p (%H:%M)'))
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid':
            if end:
                timerstr += "This event will end at {expiry_time}".format(expiry_time=end.strftime('%B %d at %I:%M %p (%H:%M)'))
            else:
                timerstr += "Nobody has told me a end time! Set it with **!timerset**"
        return timerstr
    if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
        raidtype = 'egg'
        raidaction = 'hatch'
    else:
        raidtype = 'raid'
        raidaction = 'end'
    if not guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['active']:
        timerstr += "This {raidtype}'s timer has already expired as of {expiry_time}!".format(raidtype=raidtype, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    elif (guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['egglevel'] == 'EX') or (guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid'):
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
            timerstr += 'This {raidtype} will {raidaction} on {expiry}!'.format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%B %d at %I:%M %p (%H:%M)'))
        else:
            timerstr += "No one told me when the {raidtype} will {raidaction}, so I'm assuming it will {raidaction} on {expiry}!".format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%B %d at %I:%M %p (%H:%M)'))
    elif guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
        timerstr += 'This {raidtype} will {raidaction} at {expiry_time}!'.format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    else:
        timerstr += "No one told me when the {raidtype} will {raidaction}, so I'm assuming it will {raidaction} at {expiry_time}!".format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    return timerstr


async def time_to_minute_count(channel, time):
    if time.isdigit() and len(time) < 3:
        return int(time)
    elif ':' in time or len(time) > 2:
        if time.isdigit():
            time = time[:-2] + ':' + time[-2:]
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
        start = dateparser.parse(time, settings={'PREFER_DATES_FROM': 'future'})
        start = start.replace(month=now.month, day=now.day, year=now.year)
        timediff = relativedelta(start, now)
        if timediff.hours <= -10:
            start = start + datetime.timedelta(hours=12)
            timediff = relativedelta(start, now)
        raidexp = (timediff.hours * 60) + timediff.minutes + 1
        if raidexp < 0:
            await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Please enter a time in the future.'))
            return False
        return raidexp
    else:
        await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description="I couldn't understand your time format. Try again like this: **!timerset <minutes>**"))
        return False


@Kyogre.command(aliases=['ts'])
@checks.raidchannel()
async def timerset(ctx, *, timer):
    """Set the remaining duration on a raid.

    Usage: !timerset <minutes>
    Works only in raid channels, can be set or overridden by anyone.
    Kyogre displays the end time in HH:MM local time."""
    message = ctx.message
    channel = message.channel
    guild = message.guild
    author = message.author
    hourminute = False
    type = guild_dict[guild.id]['raidchannel_dict'][channel.id]['type']
    if (not checks.check_exraidchannel(ctx)) and not (checks.check_meetupchannel(ctx)):
        if type == 'egg':
            raidlevel = guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel']
            raidtype = 'Raid Egg'
            maxtime = raid_info['raid_eggs'][raidlevel]['hatchtime']
        else:
            raidlevel = utils.get_level(Kyogre, guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon'])
            raidtype = 'Raid'
            maxtime = raid_info['raid_eggs'][raidlevel]['raidtime']
        raidexp = False
        if timer.isdigit() or ':' in timer:
            raidexp = await time_to_minute_count(channel, timer)
            if raidexp is False:
                return
            if _timercheck(raidexp, maxtime):
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"That's too long. Level {raidlevel} {raidtype.capitalize()}s currently last no more than {maxtime} minutes."))
        await _timerset(channel, raidexp)
    if checks.check_exraidchannel(ctx):
        if checks.check_eggchannel(ctx) or checks.check_meetupchannel(ctx):
            now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
            timer_split = timer.lower().split()
            try:
                start = dateparser.parse(' '.join(timer_split).lower(), settings={'DATE_ORDER': 'MDY'})
            except:
                if ('am' in ' '.join(timer_split).lower()) or ('pm' in ' '.join(timer_split).lower()):
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year), '%m/%d %I:%M %p %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset** to match this format: **MM/DD HH:MM AM/PM** (You can also omit AM/PM and use 24-hour time!)")
                        return
                else:
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year), '%m/%d %H:%M %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset** to match this format: **MM/DD HH:MM AM/PM** (You can also omit AM/PM and use 24-hour time!)")
                        return
            if checks.check_meetupchannel(ctx):
                starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('start',False)
                if starttime and start < starttime:
                    await channel.send('Please enter a time after your start time.')
                    return
            diff = start - now
            total = diff.total_seconds() / 60
            if now <= start:
                await _timerset(channel, total)
            elif now > start:
                await channel.send('Please enter a time in the future.')
        else:
            await channel.send("Timerset isn't supported for EX Raids after they have hatched.")


def _timercheck(time, maxtime):
    return time > maxtime


async def _timerset(raidchannel, exptime):
    guild = raidchannel.guild
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(minutes=exptime)
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][raidchannel.id]
    raid_dict['exp'] = time.time() + (exptime * 60)
    if (not raid_dict['active']):
        await raidchannel.send('The channel has been reactivated.')
    raid_dict['active'] = True
    raid_dict['manual_timer'] = True
    topicstr = ''
    if raid_dict.get('meetup',{}):
        raid_dict['meetup']['end'] = end
        topicstr += 'Ends on {end}'.format(end=end.strftime('%B %d at %I:%M %p (%H:%M)'))
        endtime = end.strftime('%B %d at %I:%M %p (%H:%M)')
    elif raid_dict['type'] == 'egg':
        egglevel = raid_dict['egglevel']
        hatch = end
        end = hatch + datetime.timedelta(minutes=raid_info['raid_eggs'][egglevel]['raidtime'])
        topicstr += 'Hatches on {expiry}'.format(expiry=hatch.strftime('%B %d at %I:%M %p (%H:%M) | '))
        topicstr += 'Ends on {end}'.format(end=end.strftime('%B %d at %I:%M %p (%H:%M)'))
        endtime = hatch.strftime('%B %d at %I:%M %p (%H:%M)')
    else:
        topicstr += 'Ends on {end}'.format(end=end.strftime('%B %d at %I:%M %p (%H:%M)'))
        endtime = end.strftime('%B %d at %I:%M %p (%H:%M)')
    timerstr = await print_raid_timer(raidchannel)
    await raidchannel.send(timerstr)
    await raidchannel.edit(topic=topicstr)
    report_channel = Kyogre.get_channel(raid_dict['reportchannel'])
    raidmsg = await raidchannel.fetch_message(raid_dict['raidmessage'])
    reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
    for message in [raidmsg, reportmsg]:
        embed = message.embeds[0]
        embed_indices = await embed_utils.get_embed_field_indices(embed)
        if raid_dict['type'] == "raid":
            type = "expires"
        else:
            type = "hatch"
        if embed_indices[type] is not None:
            embed.set_field_at(embed_indices[type], name=embed.fields[embed_indices[type]].name, value=endtime, inline=True)
        else:
            embed.add_field(name='**Expires:**' if type == 'expires' else '**Hatches:**', value=endtime, inline=True)
        if message == raidmsg:
            try:
                await message.edit(content=message.content,embed=embed)
            except discord.errors.NotFound:
                pass
        else:
            embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices)
            try:
                await message.edit(content=message.content,embed=embed)
            except discord.errors.NotFound:
                pass
            if raid_dict.get('raidcityreport',None) is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=embed, content=city_report.content)
                    city_report = city_report.id
                except:
                    pass
    await list_helpers.update_listing_channels(Kyogre, guild_dict, raidchannel.guild, 'raid', edit=True, regions=raid_dict.get('regions', None))
    Kyogre.get_channel(raidchannel.id)


@Kyogre.command()
@checks.raidchannel()
async def timer(ctx):
    """Have Kyogre resend the expire time message for a raid.

    Usage: !timer
    The expiry time should have been previously set with !timerset."""
    timerstr = await print_raid_timer(ctx.channel)
    await ctx.channel.send(timerstr)


@Kyogre.command(aliases=['st'])
async def starttime(ctx, *, start_time=""):
    """Set a time for a group to start a raid

    Usage: !starttime [HH:MM AM/PM]
    (You can also omit AM/PM and use 24-hour time!)
    Works only in raid channels. Sends a message and sets a group start time that
    can be seen using !starttime (without a time). One start time is allowed at
    a time and is visible in !list output. Cleared with !starting."""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
    if start_time:
        exp_minutes = await time_to_minute_count(channel, start_time)
        if not exp_minutes:
            return
        if raid_dict['type'] == 'egg':
            egglevel = raid_dict['egglevel']
            mintime = (raid_dict['exp'] - time.time()) / 60
            maxtime = mintime + raid_info['raid_eggs'][egglevel]['raidtime']
        elif (raid_dict['type'] == 'raid') or (raid_dict['type'] == 'exraid'):
            mintime = 0
            maxtime = (raid_dict['exp'] - time.time()) / 60
        alreadyset = raid_dict.get('starttime', False)
        if exp_minutes > maxtime:
            return await channel.send('The raid will be over before that....')
        if exp_minutes < 0:
            return await channel.send('Please enter a time in the future.')
        if exp_minutes < mintime:
            return await channel.send('The egg will not hatch by then!')
        if alreadyset:
            query_change = await channel.send('There is already a start time of **{start}**! Do you want to change it?'
                                              .format(start=alreadyset.strftime('%I:%M %p (%H:%M)')))
            try:
                timeout = False
                res, reactuser = await utils.simple_ask(Kyogre, query_change, channel, author.id)
            except TypeError:
                timeout = True
            if timeout or res.emoji == '❎':
                await query_change.delete()
                confirmation = await channel.send('Start time change cancelled.')
                await asyncio.sleep(10)
                await confirmation.delete()
                return
            elif res.emoji == '✅':
                await query_change.delete()
                if exp_minutes > 0:
                    timeset = True
            else:
                return
        start = datetime.datetime.utcnow() + datetime.timedelta(
            hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'],
            minutes=exp_minutes)
        if (exp_minutes and start > now) or timeset:
            raid_dict['starttime'] = start
            nextgroup = start.strftime('%I:%M %p (%H:%M)')
            if raid_dict.get('meetup',{}):
                nextgroup = start.strftime('%B %d at %I:%M %p (%H:%M)')
            await channel.send('The current start time has been set to: **{starttime}**'.format(starttime=nextgroup))
            report_channel = Kyogre.get_channel(raid_dict['reportchannel'])
            raidmsg = await channel.fetch_message(raid_dict['raidmessage'])
            reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
            embed = raidmsg.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(embed)
            embed.set_field_at(embed_indices['next'],
                               name=embed.fields[embed_indices['next']].name, value=nextgroup, inline=True)
            try:
                await raidmsg.edit(content=raidmsg.content,embed=embed)
            except discord.errors.NotFound:
                pass
            try:
                embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices)
                await reportmsg.edit(content=reportmsg.content,embed=embed)
            except discord.errors.NotFound:
                pass
            if raid_dict['raidcityreport'] is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=embed, content=city_report.content)
                except discord.errors.NotFound:
                    pass
            return
    else:
        starttime = raid_dict.get('starttime', None)
        if starttime and starttime < now:
            raid_dict['starttime'] = None
            starttime = None
        if starttime:
            await channel.send('The current start time is: **{starttime}**'
                               .format(starttime=starttime.strftime('%I:%M %p (%H:%M)')))
        elif not starttime:
            await channel.send('No start time has been set, set one with **!starttime HH:MM AM/PM**! (You can also omit AM/PM and use 24-hour time!)')


@Kyogre.group(case_insensitive=True)
@checks.activechannel()
async def location(ctx):
    """Get raid location.

    Usage: !location
    Works only in raid channels. Gives the raid location link."""
    if ctx.invoked_subcommand == None:
        message = ctx.message
        guild = message.guild
        channel = message.channel
        rc_d = guild_dict[guild.id]['raidchannel_dict']
        raidmsg = await channel.fetch_message(rc_d[channel.id]['raidmessage'])
        location = rc_d[channel.id]['address']
        report_channel = Kyogre.get_channel(rc_d[channel.id]['reportcity'])
        oldembed = raidmsg.embeds[0]
        locurl = oldembed.url
        newembed = discord.Embed(title=oldembed.title, url=locurl, colour=guild.me.colour)
        for field in oldembed.fields:
            newembed.add_field(name=field.name, value=field.value, inline=field.inline)
        newembed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
        newembed.set_thumbnail(url=oldembed.thumbnail.url)
        locationmsg = await channel.send(content="Here's the current location for the raid!\nDetails: {location}".format(location=location), embed=newembed)
        await asyncio.sleep(60)
        await locationmsg.delete()


@location.command()
@checks.activechannel()
async def new(ctx, *, content):
    """Change raid location.

    Usage: !location new <gym name>
    Works only in raid channels. Updates the gym at which the raid is located."""
    message = ctx.message
    channel = message.channel
    location_split = content.lower().split()
    if len(location_split) < 1:
        await channel.send("We're missing the new location details! Usage: **!location new <new address>**")
        return
    else:
        report_channel = Kyogre.get_channel(guild_dict[message.guild.id]['raidchannel_dict'][channel.id]['reportcity'])
        if not report_channel:
            async for m in channel.history(limit=500, reverse=True):
                if m.author.id == message.guild.me.id:
                    c = 'Coordinate here'
                    if c in m.content:
                        report_channel = m.raw_channel_mentions[0]
                        break
        details = ' '.join(location_split)
        config_dict = guild_dict[message.guild.id]['configure_dict']
        regions = raid_helpers.get_channel_regions(channel, 'raid')
        gym = None
        gyms = get_gyms(message.guild.id, regions)
        if gyms:
            gym = await location_match_prompt(channel, message.author.id, details, gyms)
            if not gym:
                return await channel.send("I couldn't find a gym named '{0}'. Try again using the exact gym name!".format(details))
            details = gym.name
            newloc = gym.maps_url
            regions = [gym.region]
        else:
            newloc = create_gmaps_query(details, report_channel, type="raid")
        await entity_updates.update_raid_location(message, report_channel, channel, gym)
        return


@Kyogre.command()
@checks.activechannel()
async def duplicate(ctx):
    """A command to report a raid channel as a duplicate.

    Usage: !duplicate
    Works only in raid channels. When three users report a channel as a duplicate,
    Kyogre deactivates the channel and marks it for deletion."""
    channel = ctx.channel
    author = ctx.author
    guild = ctx.guild
    rc_d = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    t_dict = rc_d['trainer_dict']
    can_manage = channel.permissions_for(author).manage_channels
    raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',False) else "raid"
    regions = rc_d['regions']
    if can_manage:
        dupecount = 2
        rc_d['duplicate'] = dupecount
    else:
        if author.id in t_dict:
            try:
                if t_dict[author.id]['dupereporter']:
                    dupeauthmsg = await channel.send("You've already made a duplicate report for this {raidtype}!".format(raidtype=raidtype))
                    await asyncio.sleep(10)
                    await dupeauthmsg.delete()
                    return
                else:
                    t_dict[author.id]['dupereporter'] = True
            except KeyError:
                t_dict[author.id]['dupereporter'] = True
        else:
            t_dict[author.id] = {
                'status': {'maybe':0, 'coming':0, 'here':0, 'lobby':0},
                'dupereporter': True,
            }
        try:
            dupecount = rc_d['duplicate']
        except KeyError:
            dupecount = 0
            rc_d['duplicate'] = dupecount
    dupecount += 1
    rc_d['duplicate'] = dupecount
    if dupecount >= 3:
        rusure = await channel.send('Are you sure you wish to remove this {raidtype}?'.format(raidtype=raidtype))
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(Kyogre, rusure, channel, author.id)
        except TypeError:
            timeout = True
        if not timeout:
            if res.emoji == '❎':
                await rusure.delete()
                confirmation = await channel.send('Duplicate Report cancelled.')
                logger.info((('Duplicate Report - Cancelled - ' + channel.name) + ' - Report by ') + author.name)
                dupecount = 2
                guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
                await asyncio.sleep(10)
                await confirmation.delete()
                return
            elif res.emoji == '✅':
                await rusure.delete()
                await channel.send('Duplicate Confirmed')
                logger.info((('Duplicate Report - Channel Expired - ' + channel.name) + ' - Last Report by ') + author.name)
                raidmsg = await channel.fetch_message(rc_d['raidmessage'])
                reporter = raidmsg.mentions[0]
                if 'egg' in raidmsg.content:
                    egg_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports'] = egg_reports - 1
                elif 'EX' in raidmsg.content:
                    ex_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports'] = ex_reports - 1
                else:
                    raid_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports'] = raid_reports - 1
                await expire_channel(channel)
                return
        else:
            await rusure.delete()
            confirmation = await channel.send('Duplicate Report Timed Out.')
            logger.info((('Duplicate Report - Timeout - ' + channel.name) + ' - Report by ') + author.name)
            dupecount = 2
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
            await asyncio.sleep(10)
            await confirmation.delete()
    else:
        rc_d['duplicate'] = dupecount
        confirmation = await channel.send('Duplicate report #{duplicate_report_count} received.'.format(duplicate_report_count=str(dupecount)))
        logger.info((((('Duplicate Report - ' + channel.name) + ' - Report #') + str(dupecount)) + '- Report by ') + author.name)
        return


@Kyogre.command()
async def counters(ctx, *, args=''):
    """Simulate a Raid battle with Pokebattler.

    Usage: !counters [pokemon] [weather] [user]
    See !help weather for acceptable values for weather.
    If [user] is a valid Pokebattler user id, Kyogre will simulate the Raid with that user's Pokebox.
    Uses current boss and weather by default if available.
    """
    rgx = '[^a-zA-Z0-9 ]'
    channel = ctx.channel
    guild = channel.guild
    user = guild_dict[ctx.guild.id].get('trainers',{}).get(ctx.author.id,{}).get('pokebattlerid', None)
    if checks.check_raidchannel(ctx) and not checks.check_meetupchannel(ctx):
        if args:
            args_split = args.split()
            for arg in args_split:
                if arg.isdigit():
                    user = arg
                    break
        try:
            ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id].get('ctrsmessage',None))
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        pkmn = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
        if pkmn:
            if not user:
                try:
                    ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id].get('ctrsmessage',None))
                    ctrsembed = ctrsmessage.embeds[0]
                    ctrsembed.remove_field(6)
                    ctrsembed.remove_field(6)
                    await channel.send(content=ctrsmessage.content,embed=ctrsembed)
                    return
                except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                    pass
            moveset = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('moveset', 0)
            movesetstr = guild_dict[guild.id]['raidchannel_dict'][channel.id]['ctrs_dict'].get(moveset,{}).get('moveset',"Unknown Moveset")
            weather = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('weather', None)
        else:
            pkmn = next((str(p) for p in get_raidlist() if not str(p).isdigit() and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
            if not pkmn:
                await ctx.channel.send("You're missing some details! Be sure to enter a pokemon that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
                return
        if not weather:
            if args:
                weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
                weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', args.lower())), None)
        pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
        return await counters_helpers._counters(ctx, Kyogre, pkmn, user, weather, movesetstr)
    if args:
        args_split = args.split()
        for arg in args_split:
            if arg.isdigit():
                user = arg
                break
        rgx = '[^a-zA-Z0-9]'
        pkmn = next((str(p) for p in get_raidlist() if not str(p).isdigit() and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
        if not pkmn:
            pkmn = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('pokemon', None)
        weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
        weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', args.lower())), None)
        if not weather:
            weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    else:
        pkmn = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('pokemon', None)
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    if not pkmn:
        await ctx.channel.send("You're missing some details! Be sure to enter a pokemon that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
        return
    pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    await counters_helpers._counters(ctx, Kyogre, pkmn, user, weather, "Unknown Moveset")


@Kyogre.command()
@checks.activechannel()
async def weather(ctx, *, weather):
    """Sets the weather for the raid.
    Usage: !weather <weather>
    Only usable in raid channels.
    Acceptable options: none, extreme, clear, rainy, partlycloudy, cloudy, windy, snow, fog"""
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    if weather.lower() not in weather_list:
        return await ctx.channel.send("Enter one of the following weather conditions: {}".format(", ".join(weather_list)))
    else:
        raid_lobby_helpers._weather(ctx, Kyogre, guild_dict, weather)

"""
Status Management
"""

status_parse_rgx = r'^(\d+)$|^(\d+(?:[, ]+))?([\dimvu ,]+)?(?:[, ]*)([a-zA-Z ,]+)?$'
status_parser = re.compile(status_parse_rgx)


async def _parse_teamcounts(ctx, teamcounts, trainer_dict, egglevel):
    if (not teamcounts):
        if ctx.author.id in trainer_dict:
            bluecount = str(trainer_dict[ctx.author.id]['party']['mystic']) + 'm '
            redcount = str(trainer_dict[ctx.author.id]['party']['valor']) + 'v '
            yellowcount = str(trainer_dict[ctx.author.id]['party']['instinct']) + 'i '
            unknowncount = str(trainer_dict[ctx.author.id]['party']['unknown']) + 'u '
            teamcounts = ((((str(trainer_dict[ctx.author.id]['count']) + ' ') + bluecount) + redcount) + yellowcount) + unknowncount
        else:
            teamcounts = '1'
    if "all" in teamcounts.lower():
        teamcounts = "{teamcounts} {bosslist}".format(teamcounts=teamcounts,bosslist=",".join([s.title() for s in raid_info['raid_eggs'][egglevel]['pokemon']]))
        teamcounts = teamcounts.lower().replace("all","").strip()
    return status_parser.fullmatch(teamcounts)


async def _process_status_command(ctx, teamcounts):
    trainer_dict = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
    entered_interest = trainer_dict.get(ctx.author.id, {}).get('interest', [])
    egglevel = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['egglevel']
    parsed_counts = await _parse_teamcounts(ctx, teamcounts, trainer_dict, egglevel)
    errors = []
    if not parsed_counts:
        raise ValueError("I couldn't understand that format! Check the format against `!help interested` and try again.")
    totalA, totalB, groups, bosses = parsed_counts.groups()
    total = totalA or totalB
    if bosses and guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == "egg":
        entered_interest = set(entered_interest)
        bosses_list = bosses.lower().split(',')
        if isinstance(bosses_list, str):
            bosses_list = [bosses.lower()]
        for boss in bosses_list:
            pkmn = Pokemon.get_pokemon(Kyogre, boss)
            if pkmn:
                name = pkmn.name.lower()
                if name in raid_info['raid_eggs'][egglevel]['pokemon']:
                    entered_interest.add(name)
                else:
                    errors.append("{pkmn} doesn't appear in level {egglevel} raids! Please try again.".format(pkmn=pkmn.name,egglevel=egglevel))
        if errors:
            errors.append("Invalid Pokemon detected. Please check the pinned message for the list of possible bosses and try again.")
            raise ValueError('\n'.join(errors))
    elif not bosses and guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == 'egg':
        entered_interest = [p for p in raid_info['raid_eggs'][egglevel]['pokemon']]
    if total:
        total = int(total)
    elif (ctx.author.id in trainer_dict) and (sum(trainer_dict[ctx.author.id]['status'].values()) > 0):
        total = trainer_dict[ctx.author.id]['count']
    elif groups:
        total = re.sub('[^0-9 ]', ' ', groups)
        total = sum([int(x) for x in total.split()])
    else:
        total = 1
    if not groups:
        groups = ''
    teamcounts = f"{total} {groups}"
    result = await _party_status(ctx, total, teamcounts)
    return (result, entered_interest)


@Kyogre.command(aliases=['i', 'maybe'])
@checks.activechannel()
async def interested(ctx, *, teamcounts: str=None):
    """Indicate you are interested in the raid.

    Usage: !interested [count] [party] [bosses]
    Works only in raid channels. If count is omitted, assumes you are a group of 1.
    Otherwise, this command expects at least one word in your message to be a number,
    and will assume you are a group with that many people.

    Party is also optional. Format is #m #v #i #u to tell your party's teams."""
    try:
        result, entered_interest = await _process_status_command(ctx, teamcounts)
    except ValueError as e:
        return await ctx.channel.send(e)
    if isinstance(result, list):
        count = result[0]
        partylist = result[1]
        await list_helpers._maybe(ctx, Kyogre, guild_dict, raid_info, count, partylist, entered_interest)


@Kyogre.command(aliases=['c'])
@checks.activechannel()
async def coming(ctx, *, teamcounts: str=None):
    """Indicate you are on the way to a raid.

    Usage: !coming [count] [party]
    Works only in raid channels. If count is omitted, checks for previous !maybe
    command and takes the count from that. If it finds none, assumes you are a group
    of 1.
    Otherwise, this command expects at least one word in your message to be a number,
    and will assume you are a group with that many people.

    Party is also optional. Format is #m #v #i #u to tell your party's teams."""
    try:
        result, entered_interest = await _process_status_command(ctx, teamcounts)
    except ValueError as e:
        return await ctx.channel.send(e)
    if isinstance(result, list):
        count = result[0]
        partylist = result[1]
        await list_helpers._coming(ctx, Kyogre, guild_dict, raid_info, count, partylist, entered_interest)


@Kyogre.command(aliases=['h'])
@checks.activechannel()
async def here(ctx, *, teamcounts: str=None):
    """Indicate you have arrived at the raid.

    Usage: !here [count] [party]
    Works only in raid channels. If message is omitted, and
    you have previously issued !coming, then preserves the count
    from that command. Otherwise, assumes you are a group of 1.
    Otherwise, this command expects at least one word in your message to be a number,
    and will assume you are a group with that many people.

    Party is also optional. Format is #m #v #i #u to tell your party's teams."""
    try:
        result, entered_interest = await _process_status_command(ctx, teamcounts)
    except ValueError as e:
        return await ctx.channel.send(e)
    if isinstance(result, list):
        count = result[0]
        partylist = result[1]
        await list_helpers._here(ctx, Kyogre, guild_dict, raid_info, count, partylist, entered_interest)


async def _party_status(ctx, total, teamcounts):
    channel = ctx.channel
    author = ctx.author
    trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'].get(author.id, {})
    roles = [r.name.lower() for r in author.roles]
    if 'mystic' in roles:
        my_team = 'mystic'
    elif 'valor' in roles:
        my_team = 'valor'
    elif 'instinct' in roles:
        my_team = 'instinct'
    else:
        my_team = 'unknown'
    if not teamcounts:
        teamcounts = "1"
    teamcounts = teamcounts.lower().split()
    if total and teamcounts[0].isdigit():
        del teamcounts[0]
    mystic = ['mystic', 0]
    instinct = ['instinct', 0]
    valor = ['valor', 0]
    unknown = ['unknown', 0]
    team_aliases = {
        'mystic': mystic,
        'blue': mystic,
        'm': mystic,
        'b': mystic,
        'instinct': instinct,
        'yellow': instinct,
        'i': instinct,
        'y': instinct,
        'valor': valor,
        'red': valor,
        'v': valor,
        'r': valor,
        'unknown': unknown,
        'grey': unknown,
        'gray': unknown,
        'u': unknown,
        'g': unknown,
    }
    if not teamcounts and total >= trainer_dict.get('count', 0):
        trainer_party = trainer_dict.get('party', {})
        for team in trainer_party:
            team_aliases[team][1] += trainer_party[team]
    regx = re.compile('([a-zA-Z]+)([0-9]+)|([0-9]+)([a-zA-Z]+)')
    for count in teamcounts:
        if count.isdigit():
            if total:
                return await channel.send('Only one non-team count can be accepted.')
            else:
                total = int(count)
        else:
            match = regx.match(count)
            if match:
                match = regx.match(count).groups()
                str_match = match[0] or match[3]
                int_match = match[1] or match[2]
                if str_match in team_aliases.keys():
                    if int_match:
                        if team_aliases[str_match][1]:
                            return await channel.send('Only one count per team accepted.')
                        else:
                            team_aliases[str_match][1] = int(int_match)
                            continue
            return await channel.send('Invalid format, please check and try again.')
    team_total = ((mystic[1] + instinct[1]) + valor[1]) + unknown[1]
    if total:
        if int(team_total) > int(total):
            a = 'Team counts are higher than the total, double check your counts and try again. You entered **'
            b = '** total and **'
            c = '** in your party.'
            return await channel.send(((( a + str(total)) + b) + str(team_total)) + c)
        if int(total) > int(team_total):
            if team_aliases[my_team][1]:
                if unknown[1]:
                    return await channel.send('Something is not adding up! Try making sure your total matches what each team adds up to!')
                unknown[1] = total - team_total
            else:
                team_aliases[my_team][1] = total - team_total
    partylist = {'mystic':mystic[1], 'valor':valor[1], 'instinct':instinct[1], 'unknown':unknown[1]}
    result = [total, partylist]
    return result


@Kyogre.command(aliases=['l'])
@checks.activeraidchannel()
async def lobby(ctx, *, count: str=None):
    """Indicate you are entering the raid lobby.

    Usage: !lobby [message]
    Works only in raid channels. If message is omitted, and
    you have previously issued !coming, then preserves the count
    from that command. Otherwise, assumes you are a group of 1.
    Otherwise, this command expects at least one word in your message to be a number,
    and will assume you are a group with that many people."""
    try:
        if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == 'egg':
            if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['pokemon'] == '':
                await ctx.channel.send("Please wait until the raid egg has hatched before announcing you're coming or present.")
                return
    except:
        pass
    trainer_dict = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
    if count:
        if count.isdigit():
            count = int(count)
        else:
            await ctx.channel.send("I can't understand how many are in your group. Just say **!lobby** if you're by yourself, or **!lobby 5** for example if there are 5 in your group.")
            return
    elif (ctx.author.id in trainer_dict) and (sum(trainer_dict[ctx.author.id]['status'].values()) > 0):
        count = trainer_dict[ctx.author.id]['count']
    else:
        count = 1
    await _lobby(ctx.message, count)


async def _lobby(message, count):
    trainer = message.author
    guild = message.guild
    channel = message.channel
    if 'lobby' not in guild_dict[guild.id]['raidchannel_dict'][channel.id]:
        await channel.send('There is no group in the lobby for you to join! Use **!starting** if the group waiting at the raid is entering the lobby!')
        return
    trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    if count == 1:
        await channel.send('{member} is entering the lobby!'.format(member=trainer.mention))
    else:
        await channel.send('{member} is entering the lobby with a total of {trainer_count} trainers!'.format(member = trainer.mention, trainer_count=count))
        joined = guild_dict[guild.id].setdefault('trainers', {}).setdefault(regions[0], {}).setdefault(trainer.id, {}).setdefault('joined', 0) + 1
        guild_dict[guild.id]['trainers'][regions[0]][trainer.id]['joined'] = joined
    if trainer.id not in trainer_dict:
        trainer_dict[trainer.id] = {}
    trainer_dict[trainer.id]['status'] = {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': count}
    trainer_dict[trainer.id]['count'] = count
    guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict


@Kyogre.command(aliases=['x'])
@checks.raidchannel()
async def cancel(ctx):
    """Indicate you are no longer interested in a raid.

    Usage: !cancel
    Works only in raid channels. Removes you and your party
    from the list of trainers who are "otw" or "here"."""
    await list_helpers._cancel(ctx, Kyogre, guild_dict, raid_info)


@Kyogre.command(aliases=['s'])
@checks.activeraidchannel()
async def starting(ctx, team: str = ''):
    """Signal that a raid is starting.

    Usage: !starting [team]
    Works only in raid channels. Sends a message and clears the waiting list. Users who are waiting
    for a second group must reannounce with the :here: emoji or !here."""
    await raid_lobby_helpers._starting(ctx, Kyogre, guild_dict, raid_info, team)


@Kyogre.command()
@checks.activeraidchannel()
async def backout(ctx):
    """Request players in lobby to backout

    Usage: !backout
    Will alert all trainers in the lobby that a backout is requested."""
    await raid_lobby_helpers._backout(ctx, Kyogre, guild_dict)
     

"""
List Commands
"""
@Kyogre.group(name="list", aliases=['lists'], case_insensitive=True)
async def _list(ctx):
    if ctx.invoked_subcommand == None:
        listmsg = ""
        guild = ctx.guild
        channel = ctx.channel
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
        if checks.check_raidreport(ctx) or checks.check_exraidreport(ctx):
            raid_dict = guild_dict[guild.id]['configure_dict']['raid']
            if raid_dict.get('listings', {}).get('enabled', False):
                msg = await ctx.channel.send("*Raid list command disabled when listings are provided by server*")
                await asyncio.sleep(10)
                await msg.delete()
                await ctx.message.delete()
                return
            region = None
            if guild_dict[guild.id]['configure_dict'].get('regions', {}).get('enabled', False) and raid_dict.get('categories', None) == 'region':
                region = raid_dict.get('category_dict', {}).get(channel.id, None)
            listmsg = await list_helpers._get_listing_messages(Kyogre, guild_dict, 'raid', channel, region)
        elif checks.check_raidactive(ctx):
            team_list = ["mystic","valor","instinct","unknown"]
            tag = False
            team = False
            starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('starttime',None)
            meetup = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',{})
            rc_d = guild_dict[guild.id]['raidchannel_dict'][channel.id]
            list_split = ctx.message.clean_content.lower().split()
            if "tags" in list_split or "tag" in list_split:
                tag = True
            for word in list_split:
                if word in team_list:
                    team = word.lower()
                    break
            if team == "mystic" or team == "valor" or team == "instinct":
                bulletpoint = utils.parse_emoji(ctx.guild, config['team_dict'][team])
            elif team == "unknown":
                bulletpoint = '❔'
            else:
                bulletpoint = '🔹'
            if " 0 interested!" not in await list_helpers._interest(ctx, Kyogre, guild_dict, tag, team):
                listmsg += ('\n' + bulletpoint) + (await list_helpers._interest(ctx, Kyogre, guild_dict, tag, team))
            if " 0 on the way!" not in await list_helpers._otw(ctx, Kyogre, guild_dict, tag, team):
                listmsg += ('\n' + bulletpoint) + (await list_helpers._otw(ctx, Kyogre, guild_dict, tag, team))
            if " 0 waiting at the raid!" not in await list_helpers._waiting(ctx, Kyogre, guild_dict, tag, team):
                listmsg += ('\n' + bulletpoint) + (await list_helpers._waiting(ctx, Kyogre, guild_dict, tag, team))
            if " 0 in the lobby!" not in await list_helpers._lobbylist(ctx, Kyogre, guild_dict, tag, team):
                listmsg += ('\n' + bulletpoint) + (await list_helpers._lobbylist(ctx, Kyogre, guild_dict, tag, team))
            if (len(listmsg.splitlines()) <= 1):
                listmsg +=  ('\n' + bulletpoint) + (" Nobody has updated their status yet!")
            listmsg += ('\n' + bulletpoint) + (await print_raid_timer(channel))
            if starttime and (starttime > now) and not meetup:
                listmsg += '\nThe next group will be starting at **{}**'.format(starttime.strftime('%I:%M %p (%H:%M)'))
            await channel.send(listmsg)
            return
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
    listmsg = await list_helpers._interest(ctx, Kyogre, guild_dict, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def coming(ctx, tags: str = ''):
    """Lists the number and users who are coming to a raid.

    Usage: !list coming
    Works only in raid channels."""
    if tags and tags.lower() == "tags" or tags.lower() == "tag":
        tags = True
    listmsg = await list_helpers._otw(ctx, Kyogre, guild_dict, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def here(ctx, tags: str = ''):
    """List the number and users who are present at a raid.

    Usage: !list here
    Works only in raid channels."""
    if tags and tags.lower() == "tags" or tags.lower() == "tag":
        tags = True
    listmsg = await list_helpers._waiting(ctx, Kyogre, guild_dict, tags)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activeraidchannel()
async def lobby(ctx, tag=False):
    """List the number and users who are in the raid lobby.

    Usage: !list lobby
    Works only in raid channels."""
    listmsg = await list_helpers._lobbylist(ctx, Kyogre, guild_dict)
    await ctx.channel.send(listmsg)


@_list.command()
@checks.activeraidchannel()
async def bosses(ctx):
    """List each possible boss and the number of users that have RSVP'd for it.

    Usage: !list bosses
    Works only in raid channels."""
    listmsg = await list_helpers._bosslist(ctx, Kyogre, guild_dict, raid_info)
    if len(listmsg) > 0:
        await ctx.channel.send(listmsg)


@_list.command()
@checks.activechannel()
async def teams(ctx):
    """List the teams for the users that have RSVP'd to a raid.

    Usage: !list teams
    Works only in raid channels."""
    listmsg = await list_helpers.teamlist(ctx, Kyogre, guild_dict)
    await ctx.channel.send(listmsg)

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
