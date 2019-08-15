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
from kyogre.exts.bosscp import boss_cp_chart

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
        category = discord.utils.get(guild.categories,
                                     id=guild_dict[guild.id]['configure_dict'][report]['category_dict'][channel.id])
        return category
    elif catsort == "level":
        category = discord.utils.get(guild.categories,
                                     id=guild_dict[guild.id]['configure_dict'][report]['category_dict'][level])
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
    name = utils.sanitize_name(name+gym.name)[:32]
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
                                elif not pokemon and egglevel == "5" and guild_dict[guild.id]['configure_dict']['settings'].get('regional','').lower() in raid_info['raid_eggs']["5"]['pokemon']:
                                    pokemon = str(Pokemon.get_pokemon(Kyogre, guild_dict[guild.id]['configure_dict']['settings']['regional']))
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
            del guild_dict[guild.id]['raidchannel_dict'][channel.id]
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
                    guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
                for trainer in trainer_dict.keys():
                    user = guild.get_member(trainer)
                    maybe_list.append(user.mention)
                h = 'hatched-'
                new_name = h if h not in channel.name else ''
                new_name += channel.name
                await channel.edit(name=new_name)
                await channel.send("**This egg has hatched!**\n\nTrainers {trainer_list}: \
                \nUse **!raid <pokemon>** to set the Raid Boss\
                \nor **!timerset** to reset the hatch timer. \
                \nThis channel will be deactivated until I get an update.".format(trainer_list=', '.join(maybe_list)))
            delete_time = (guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] + (45 * 60)) - time.time()
            expiremsg = '**This level {level} raid egg has expired!**'.format(
                level=guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel'])
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
                pokemon=guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon'].capitalize(), raidtype=raidtype)
        await asyncio.sleep(delete_time)
        # If the channel has already been deleted from the dict, someone
        # else got to it before us, so don't do anything.
        # Also, if the channel got reactivated, don't do anything either.
        try:
            if (not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']) and (not Kyogre.is_closed()):
                try:
                    short_id = guild_dict[guild.id]['raidchannel_dict'][channel.id]['short']
                    if short_id is not None:
                        region = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('regions', [None])[0]
                        if region is not None:
                            so_channel_id = guild_dict[guild.id]['configure_dict']['raid'].setdefault('short_output', {}).get(region, None)
                            if so_channel_id is not None:
                                so_channel = Kyogre.get_channel(so_channel_id)
                                if so_channel is not None:
                                    so_message = await so_channel.fetch_message(short_id)
                                    await so_message.delete()
                except Exception as err:
                    logger.info("Short message delete failed" + err)
                if dupechannel:
                    try:
                        report_channel = Kyogre.get_channel(
                            guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                        reportmsg = await report_channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                        await reportmsg.delete()
                    except:
                        pass
                else:
                    try:
                        report_channel = Kyogre.get_channel(
                            guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                        reportmsg = await report_channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                        await reportmsg.edit(embed=discord.Embed(description=expiremsg, colour=channel.guild.me.colour))
                        await reportmsg.clear_reactions()
                        await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=True, regions=guild_dict[guild.id]['raidchannel_dict'][channel.id].get('regions', None))
                    except:
                        pass
                    # channel doesn't exist anymore in serverdict
                archive = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('archive',False)
                logs = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('logs', {})
                channel_exists = Kyogre.get_channel(channel.id)
                if channel_exists == None:
                    return
                elif not archive and not logs:
                    try:
                        del guild_dict[guild.id]['raidchannel_dict'][channel.id]
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
                        category = guild_dict[guild.id]['configure_dict'].get('archive', {}).get('category', 'same')
                        if category == 'same':
                            newcat = channel.category
                        else:
                            newcat = guild.get_channel(category)
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
                        del guild_dict[guild.id]['raidchannel_dict'][channel.id]
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
            admin_commands_cog = Kyogre.cogs.get('AdminCommands')
            if not admin_commands_cog:
                return None
            await admin_commands_cog.save(guildid)
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
            await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'wild', edit=True)
            await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'research', edit=True)
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


async def maint_start():
    tasks = []
    try:
        tasks.append(event_loop.create_task(channel_cleanup()))
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
    await maint_start()


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
                        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Couldn't find gym with name: {gymmsg.clean_content}")
                    else:
                        location = gym.name
                        raid_channel_ids = get_existing_raid(guild, gym)
                        if raid_channel_ids:
                            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
                            if guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]:
                                await channel.send(
                                    embed=discord.Embed(
                                        colour=discord.Colour.red(),
                                        description=f"A raid has already been reported for {gym.name}"))
                                Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Raid already reported.")
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
                await _timerset(raid_channel, raidexp)
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
            await changeraid_internal(None, guild, raid_channel, bossmsg.clean_content)
            if not bossmsg.clean_content.isdigit():
                await _timerset(raid_channel, 45)
            await _refresh_listing_channels_internal(guild, "raid")
            success_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                 description="Raid Tier / Boss updated"))
            await bosswait.delete()
            await bossmsg.delete()
    else:
        return

"""
Admin Commands
"""
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
    regions = guild_dict[guild.id]['configure_dict']['regions']['info'].keys()
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
        raid_channel_name += utils.sanitize_name(raid_dict['address'])[:32]
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
            if raid_dict.get('raidcityreport', None) is not None:
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




"""
Miscellaneous
"""
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
        await ctx.channel.send('My roles are ranked lower than the following team roles: '
                               '**{higher_roles_list}**\nPlease get an admin to move my roles above them!'
                               .format(higher_roles_list=', '.join(high_roles)))
        return
    role = None
    team_split = content.lower().split()
    entered_team = team_split[0]
    entered_team = ''.join([i for i in entered_team if i.isalpha()])
    if entered_team in lowercase_roles:
        index = lowercase_roles.index(entered_team)
        role = discord.utils.get(guild.roles, name=guild_roles[index])
    if 'harmony' in lowercase_roles:
        index = lowercase_roles.index('harmony')
        harmony = discord.utils.get(guild.roles, name=guild_roles[index])
    # Check if user already belongs to a team role by
    # getting the role objects of all teams in team_dict and
    # checking if the message author has any of them.    for team in guild_roles:
    for team in guild_roles:
        temp_role = discord.utils.get(guild.roles, name=team)
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
            await ctx.channel.send('{team_role} is not configured as a role on this server. '
                                   'Please contact an admin for assistance.'.format(team_role=team))
            return
    # Check if team is one of the three defined in the team_dict
    if entered_team not in config['team_dict'].keys():
        await ctx.channel.send('"{entered_team}" isn\'t a valid team! Try {available_teams}'
                               .format(entered_team=entered_team, available_teams=team_msg))
        return
    # Check if the role is configured on the server
    elif role == None:
        await ctx.channel.send('The "{entered_team}" role isn\'t configured on this server! Contact an admin!'
                               .format(entered_team=entered_team))
    else:
        try:
            if harmony and (harmony in ctx.author.roles):
                await ctx.author.remove_roles(harmony)
            await ctx.author.add_roles(role)
            await ctx.channel.send('Added {member} to Team {team_name}! {team_emoji}'
                                   .format(member=ctx.author.mention, team_name=role.name.capitalize(),
                                           team_emoji=utils.parse_emoji(guild, config['team_dict'][entered_team])))
            await ctx.author.send("Now that you've set your team, "
                                  "head to <#538883360953729025> to set up your desired regions")
        except discord.Forbidden:
            await ctx.channel.send("I can't add roles!")


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
Reporting
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
    raid_notice_msg = await channel.send(content=('{trainer} is available for Raids!')
                                         .format(trainer=trainer.display_name), embed=raid_notice_embed)
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
    await message.delete()


@Kyogre.command(aliases=['ex'])
@checks.allowexraidreport()
async def exraid(ctx, *, location:commands.clean_content(fix_channel_mentions=True) = ""):
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
    timestamp = (message.created_at + datetime.timedelta(
        hours=config_dict['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
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
            return await message.channel.send("I couldn't find a gym named '{0}'. "
                                              "Try again using the exact gym name!".format(raid_details))
        raid_channel_ids = get_existing_raid(message.guild, gym, only_ex=True)
        if raid_channel_ids:
            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
            return await message.channel.send(f"A raid has already been reported for "
                                              f"{gym.name}. Coordinate in {raid_channel.mention}")
        raid_details = gym.name
        raid_gmaps_link = gym.maps_url
        regions = [gym.region]
    else:
        utilities_cog = Kyogre.cogs.get('Utilities')
        raid_gmaps_link = utilities_cog.create_gmaps_query(raid_details, message.channel, type="exraid")
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
    raid_embed = discord.Embed(title='Click here for directions to the coming raid!',
                               url=raid_gmaps_link, colour=message.guild.me.colour)
    if len(egg_info['pokemon']) > 1:
        raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'
                             .format(bosslist1='\n'.join(boss_list[::2])), inline=True)
        raid_embed.add_field(name='\u200b', value='{bosslist2}'
                             .format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
    else:
        raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist}'
                             .format(bosslist=''.join(boss_list)), inline=True)
        raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
    raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
    raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**', inline=True)
    raid_embed.set_footer(text='Reported by {author} - {timestamp}'
                          .format(author=message.author, timestamp=timestamp),
                          icon_url=message.author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    if config_dict['invite']['enabled']:
        invitemsgstr = "Use the **!invite** command to gain access and coordinate"
        invitemsgstr2 = " after using **!invite** to gain access"
    else:
        invitemsgstr = "Coordinate"
        invitemsgstr2 = ""
    raidreport = await channel.send(content='EX raid egg reported by {member}! Details: {location_details}. '
                                            '{invitemsgstr} in {raid_channel}'
                                    .format(member=message.author.mention, location_details=raid_details,
                                            invitemsgstr=invitemsgstr, raid_channel=raid_channel.mention),
                                    embed=raid_embed)
    await asyncio.sleep(1)
    raidmsg = "EX raid reported by {member} in {citychannel}! Details: {location_details}. " \
              "Coordinate here{invitemsgstr2}!\n\nClick the question mark reaction to get help on the " \
              "commands that work in here.\n\nThis channel will be deleted five minutes after the timer expires."\
        .format(member=message.author.display_name, citychannel=message.channel.mention,
                location_details=raid_details, invitemsgstr2=invitemsgstr2)
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.add_reaction('\u2754')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('🚫')
    await asyncio.sleep(0.25)
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
    await raid_channel.send(content='Hey {member}, if you can, set the time left until the egg hatches using '
                                    '**!timerset <date and time>** so others can check it with **!timer**. '
                                    '**<date and time>** can just be written exactly how it appears on your '
                                    'EX Raid Pass.'.format(member=message.author.mention))
    ex_reports = guild_dict[message.guild.id].setdefault('trainers', {}).setdefault(regions[0], {})\
                     .setdefault(message.author.id, {}).setdefault('ex_reports', 0) + 1
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
            if guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone" \
                    or (guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "same"
                        and rc_dict[channelid]['reportcity'] == channel.id):
                exraid_channel = bot.get_channel(channelid)
                if exraid_channel.mention != '#deleted-channel':
                    exraidcount += 1
                    exraidlist += (('\n**' + str(exraidcount)) + '.**   ') + exraid_channel.mention
                    exraid_dict[str(exraidcount)] = exraid_channel
    if exraidcount == 0:
        await channel.send('No EX Raids have been reported in this server! Use **!exraid** to report one!')
        return
    exraidchoice = await channel.send("{0}, you've told me you have an invite to an EX Raid, and I'm just "
                                      "going to take your word for it! The following {1} EX Raids have been "
                                      "reported:\n{2}\nReply with **the number** (1, 2, etc) of the EX Raid "
                                      "you have been invited to. If none of them match your invite, type 'N' "
                                      "and report it with **!exraid**"
                                      .format(author.mention, str(exraidcount), exraidlist))
    reply = await bot.wait_for('message', check=(lambda message: (message.author == author)))
    if reply.content.lower() == 'n':
        await exraidchoice.delete()
        exraidmsg = await channel.send('Be sure to report your EX Raid with **!exraid**!')
    elif (not reply.content.isdigit()) or (int(reply.content) > exraidcount):
        await exraidchoice.delete()
        exraidmsg = await channel.send("I couldn't tell which EX Raid you meant! Try the **!invite** command again,"
                                       " and make sure you respond with the number of the channel that matches!")
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
        exraidmsg = await channel.send('Alright {0}, you can now send messages in {1}! Make sure you let the trainers'
                                       ' in there know if you can make it to the EX Raid!')\
            .format(author.mention, exraid_channel.mention)
        await list_helpers._maybe(ctx, Kyogre, guild_dict, raid_info, 0, None)
    else:
        await exraidchoice.delete()
        exraidmsg = await channel.send("I couldn't understand your reply! Try the **!invite** command again!")
    return await utils.sleep_and_cleanup([ctx.message, reply, exraidmsg], 30)


@Kyogre.command()
@checks.allowmeetupreport()
async def meetup(ctx, *, location:commands.clean_content(fix_channel_mentions=True) = ""):
    """Report an upcoming event.

    Usage: !meetup <location>
    Kyogre will insert the details (really just everything after the species name) into a
    Google maps link and post the link to the same channel the report was made in.

    Finally, Kyogre will create a separate channel for the report, for the purposes of organizing the event."""
    await _meetup(ctx, location)

async def _meetup(ctx, location):
    message = ctx.message
    channel = message.channel
    timestamp = (message.created_at + datetime.timedelta(
        hours=guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
    event_split = location.split()
    if len(event_split) <= 0:
        await channel.send('Give more details when reporting! Usage: **!meetup <location>**')
        return
    raid_details = ' '.join(event_split)
    raid_details = raid_details.strip()
    utilities_cog = Kyogre.cogs.get('Utilities')
    raid_gmaps_link = utilities_cog.create_gmaps_query(raid_details, message.channel, type="meetup")
    raid_channel_name = 'meetup-'
    raid_channel_name += utils.sanitize_name(raid_details)[:32]
    raid_channel_category = get_category(message.channel,"EX", category_type="meetup")
    raid_channel = await message.guild.create_text_channel(raid_channel_name,
                                                           overwrites=message.channel.overwrites,
                                                           category=raid_channel_category)
    ow = raid_channel.overwrites_for(raid_channel.guild.default_role)
    ow.send_messages = True
    try:
        await raid_channel.set_permissions(raid_channel.guild.default_role, overwrite = ow)
    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
        pass
    raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/misc/meetup.png?cache=0'
    raid_embed = discord.Embed(title='Click here for directions to the event!',
                               url=raid_gmaps_link, colour=message.guild.me.colour)
    raid_embed.add_field(name='**Event Location:**', value=raid_details, inline=True)
    raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
    raid_embed.add_field(name='**Event Starts:**', value='Set with **!starttime**', inline=True)
    raid_embed.add_field(name='**Event Ends:**', value='Set with **!timerset**', inline=True)
    raid_embed.set_footer(text='Reported by {author} - {timestamp}'
                          .format(author=message.author.display_name, timestamp=timestamp),
                          icon_url=message.author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    raidreport = await channel.send(content='Meetup reported by {member}! Details: {location_details}. '
                                            'Coordinate in {raid_channel}'
                                    .format(member=message.author.display_name,
                                            location_details=raid_details,
                                            raid_channel=raid_channel.mention),
                                    embed=raid_embed)
    await asyncio.sleep(1)
    raidmsg = "Meetup reported by {member} in {citychannel}! Details: {location_details}. Coordinate here!" \
              "\n\nTo update your status, choose from the following commands: **!maybe**, **!coming**, **!here**," \
              " **!cancel**. If you are bringing more than one trainer/account, add in the number of accounts total," \
              " teams optional, on your first status update.\nExample: `!coming 5 2m 2v 1i`\n\nTo see the list of " \
              "trainers who have given their status:\n**!list interested**, **!list coming**, **!list here** or use" \
              " just **!list** to see all lists. Use **!list teams** to see team distribution.\n\nSometimes I'm not" \
              " great at directions, but I'll correct my directions if anybody sends me a maps link or uses " \
              "**!location new <address>**. You can see the location of the event by using **!location**\n\n" \
              "You can set the start time with **!starttime <MM/DD HH:MM AM/PM>** (you can also omit AM/PM and " \
              "use 24-hour time) and access this with **!starttime**.\nYou can set the end time with " \
              "**!timerset <MM/DD HH:MM AM/PM>** and access this with **!timer**.\n\nThis channel will be deleted" \
              " five minutes after the timer expires."\
        .format(member=message.author.display_name, citychannel=message.channel.mention, location_details=raid_details)
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
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[raid_channel.guild.id]['configure_dict']['settings']['offset'])
    await raid_channel.send(content='Hey {member}, if you can, set the time that the event '
                                    'starts with **!starttime <date and time>** and also set the '
                                    'time that the event ends using **!timerset <date and time>**.'
                            .format(member=message.author.mention))
    event_loop.create_task(expiry_check(raid_channel))


"""
Data Management Commands
"""
@Kyogre.group(name="reports")
@commands.has_permissions(manage_guild=True)
async def _reports(ctx):
    """Report data management command"""
    if ctx.invoked_subcommand is None:
        raise commands.BadArgument()


@_reports.command(name="list", aliases=["ls"])
async def _reports_list(ctx, *, list_type):
    """Lists the current active reports of the specified type, optionally for one or more regions"""
    valid_types = ['raid', 'research']
    channel = ctx.channel
    list_type = list_type.lower()
    if list_type not in valid_types:
        await channel.send(f"'{list_type}' is either invalid or unsupported. "
                           f"Please use one of the following: {', '.join(valid_types)}")
    await ctx.channel.send(f"This is a {list_type} listing")


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
