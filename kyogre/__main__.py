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
                    user = channel.guild.get_member(trainer)
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


@Kyogre.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def clearstatus(ctx):
    """Clears raid channel status lists.

    Usage: !clearstatus
    Only usable by admins."""
    msg = "Are you sure you want to clear all status for this raid? " \
          "Everybody will have to RSVP again. If you are wanting to " \
          "clear one user's status, use `!setstatus <user> cancel`"
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
    valid_status_list = ['interested', 'i', 'maybe', 'coming', 'c', 'here', 'h', 'cancel', 'x']
    if status not in valid_status_list:
        await ctx.message.channel.send("{status} is not a valid status!".format(status=status))
        return
    ctx.message.author = member
    ctx.message.content = "{}{} {}".format(ctx.prefix, status, status_counts)
    await ctx.bot.process_commands(ctx.message)

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
                                           team_emoji=utils.parse_emoji(ctx.guild, config['team_dict'][entered_team])))
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
def get_existing_raid(guild, location, only_ex = False):
    """returns a list of channel ids for raids reported at the location provided"""
    report_dict = {k: v for k, v in guild_dict[guild.id]['raidchannel_dict'].items()
                   if ((v.get('egglevel', '').lower() != 'ex')
                   if not only_ex else (v.get('egglevel', '').lower() == 'ex'))}
    def matches_existing(report):
        # ignore meetups
        if report.get('meetup', {}):
            return False
        return report.get('gym', None) and report['gym'].name.lower() == location.name.lower()
    return [channel_id for channel_id, report in report_dict.items() if matches_existing(report)]


@Kyogre.command(name="raid", aliases=['r', 're', 'egg', 'regg', 'raidegg', '1', '2', '3', '4', '5'],
    brief="Report an ongoing raid or a raid egg.")
@checks.allowraidreport()
async def _raid(ctx, pokemon, *, location:commands.clean_content(fix_channel_mentions=True) = "",
                weather = None, timer = None):
    """**Usage**: `!raid <raid tier/pokemon> <gym name> [time]`
    Kyogre will attempt to find a gym with the name you provide and create a separate channel for the raid report, for the purposes of organizing the raid."""
    if ctx.invoked_with.isdigit():
        content = f"{ctx.invoked_with} {pokemon} {location} {weather if weather is not None else ''} " \
            f"{timer if timer is not None else ''}"
        new_channel = await _raidegg(ctx, content)
    else:
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
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                      description='Give more details when reporting! '
                                                                  'Usage: **!raid <pokemon name> <location>**'))
    if raid_split[0] == 'egg':
        await _raidegg(ctx, content)
        return
    if fromegg:
        eggdetails = guild_dict[guild.id]['raidchannel_dict'][channel.id]
        egglevel = eggdetails['egglevel']
        if raid_split[0].lower() == 'assume':
            if config['allow_assume'][egglevel] == 'False':
                return await channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description='**!raid assume** is not allowed for this level egg.'))
            if not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                await _eggtoraid(ctx, raid_split[1].lower(), channel, author)
                return
            else:
                await _eggassume(" ".join(raid_split), channel, author)
                return
        elif (raid_split[0] == "alolan" and len(raid_split) > 2) or (raid_split[0] != "alolan" and len(raid_split) > 1):
            if (raid_split[0] not in Pokemon.get_forms_list() and len(raid_split) > 1):
                return await channel.send(
                    embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description='Please report new raids in a reporting channel.'))
        elif not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
            eggtoraid = True
        ## This is a hack but it allows users to report the just hatched boss
        ## before Kyogre catches up with hatching the egg.
        elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 < datetime.datetime.now().timestamp():
            eggtoraid = True
        else:            
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Please wait until the egg has hatched before changing it to an open raid!'))
    raid_pokemon = Pokemon.get_pokemon(Kyogre, content)
    pkmn_error = None
    pkmn_error_dict = {'not_pokemon': "I couldn't determine the Pokemon in your report.\n"
                                      "What raid boss or raid tier are you reporting?",
                       'not_boss': 'That Pokemon does not appear in raids!\nWhat is the correct Pokemon?',
                       'ex': ("The Pokemon {pokemon} only appears in EX Raids!\nWhat is the correct Pokemon?")
                           .format(pokemon=str(raid_pokemon).capitalize()),
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
                await channel.send(embed=discord.Embed(
                    colour=discord.Colour.light_grey(),
                    description="You took too long to reply. Raid report cancelled."))
                await pkmnquery_msg.delete()
                return
            if pokemon_msg.clean_content.lower() == "cancel":
                await pkmnquery_msg.delete()
                await pokemon_msg.delete()
                await channel.send(embed=discord.Embed(colour=discord.Colour.light_grey(),
                                                       description="Raid report cancelled."))
                return
            if pokemon_msg.clean_content.isdigit():
                if 0 < int(pokemon_msg.clean_content) <= 5:
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
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    raidexp = await utils.time_to_minute_count(guild_dict, channel, raid_split[-1], False)
    if raidexp:
        del raid_split[-1]
        if _timercheck(raidexp, raid_info['raid_eggs'][raid_pokemon.raid_level]['raidtime']):
            time_embed = discord.Embed(description="That's too long. Level {raidlevel} Raids currently last no "
                                                   "more than {hatchtime} minutes...\nExpire time will not be set."
                                       .format(raidlevel=raid_pokemon.raid_level,
                                               hatchtime=raid_info['raid_eggs'][raid_pokemon.raid_level]['hatchtime']),
                                       colour=discord.Colour.red())
            await channel.send(embed=time_embed)
            raidexp = False
    else:
        await channel.send(
            embed=discord.Embed(colour=discord.Colour.orange(),
                                description='Could not determine expiration time. Using default of 45 minutes'))
    raid_details = ' '.join(raid_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    rgx = '[^a-zA-Z0-9]'
    weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
    if not weather:
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    raid_pokemon.weather = weather
    raid_details = raid_details.replace(str(weather), '', 1)
    if raid_details == '':
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
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
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                      description='Please report new raids in a reporting channel.'))
    
    guild = message.guild
    author = message.author
    raidexp = False
    hourminute = False
    raidegg_split = content.split()
    if raidegg_split[0].lower() == 'egg':
        del raidegg_split[0]
    if len(raidegg_split) <= 1:
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raidegg <level> <location>**'))
    if raidegg_split[0].isdigit():
        egg_level = int(raidegg_split[0])
        del raidegg_split[0]
    else:
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. '
                        'Type **!help** raidegg for more info.'))
    raidexp = await utils.time_to_minute_count(guild_dict, channel, raidegg_split[-1], False)
    if raidexp:
        del raidegg_split[-1]
        if _timercheck(raidexp, raid_info['raid_eggs'][str(egg_level)]['hatchtime']):
            await channel.send("That's too long. Level {raidlevel} Raid Eggs "
                               "currently last no more than {hatchtime} minutes..."
                               .format(raidlevel=egg_level,
                                       hatchtime=raid_info['raid_eggs'][str(egg_level)]['hatchtime']))
            return
    else:
        await channel.send(
            embed=discord.Embed(colour=discord.Colour.orange(),
                                description='Could not determine hatch time. Using default of 60 minutes'))
    raid_details = ' '.join(raidegg_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), 
            description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. '
                        'Type **!help** raidegg for more info.'))
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
    timestamp = (message.created_at + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
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
                    return await channel.send(embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description=f"I couldn't find a gym named '{raid_details}'. "
                        f"Try again using the exact gym name!"))
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
                    msg += f"\nCoordinate in the raid channel: {raid_channel.mention}"
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
        utilities_cog = Kyogre.cogs.get('Utilities')
        raid_gmaps_link = utilities_cog.create_gmaps_query(raid_details, channel, type="raid")
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
    raid_embed = discord.Embed(title='Click here for directions to the raid!',
                               url=raid_gmaps_link,
                               colour=guild.me.colour)
    enabled = raid_helpers.raid_channels_enabled(guild, channel, guild_dict)
    if gym:
        gym_info = f"**{raid_details}**\n{'_EX Eligible Gym_' if gym.ex_eligible else ''}"
        raid_embed.add_field(name='**Gym:**', value=gym_info, inline=False)
    cp_range = ''
    if raid_report:
        if enabled:
            if str(raid_pokemon).lower() in boss_cp_chart:
                cp_range = boss_cp_chart[str(raid_pokemon).lower()]
            weak_str = utils.types_to_str(guild, raid_pokemon.weak_against.keys(), Kyogre.config)
            raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                .format(pokemon=str(raid_pokemon), 
                        pokemonnumber=str(raid_pokemon.id), 
                        type=utils.types_to_str(guild, raid_pokemon.types, Kyogre.config), 
                        cprange='\n'+cp_range, 
                        inline=True))
            raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=weak_str))
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**')
            raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**')
        raid_img_url = raid_pokemon.img_url
        msg = entity_updates.build_raid_report_message(gym, 'raid', raid_pokemon.name, '0',
                                                       raidexp, raid_channel, guild_dict)
    else:
        if enabled:
            if len(egg_info['pokemon']) > 1:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'
                                     .format(bosslist1='\n'.join(boss_list[::2])), inline=True)
                raid_embed.add_field(name='\u200b', value='{bosslist2}'
                                     .format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
            else:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist}'
                                     .format(bosslist=''.join(boss_list)), inline=True)
                raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
            raid_embed.add_field(name='**Hatches:**', value='Set with **!timerset**', inline=True)
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
        raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'\
            .format(str(egg_img))
        msg = entity_updates.build_raid_report_message(gym, 'egg', '', level, raidexp, raid_channel, guild_dict)
    if enabled:
        raid_embed.set_footer(text='Reported by {author} - {timestamp}'
                              .format(author=author.display_name, timestamp=timestamp),
                              icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    report_embed = raid_embed
    embed_indices = await embed_utils.get_embed_field_indices(report_embed)
    report_embed = await embed_utils.filter_fields_for_report_embed(report_embed, embed_indices)
    raidreport = await channel.send(content=msg, embed=report_embed)
    short_output_channel_id = guild_dict[guild.id]['configure_dict']['raid'].setdefault('short_output', {}).get(gym.region, None)
    if short_output_channel_id:
        send_level = 0
        if raid_pokemon:
            if raid_pokemon.raid_level:
                send_level = int(raid_pokemon.raid_level)
        else:
            if level:
                send_level = int(level)
        if send_level >= 4:
            short_output_channel = Kyogre.get_channel(short_output_channel_id)
            await short_output_channel.send(f"Raid Reported: {raid_channel.mention}")
    await asyncio.sleep(1)
    raid_embed.add_field(name='**Tips:**', value='`!i` if interested\n`!c` if on the way\n`!h` '
                                                 'when you arrive\n`!x` to cancel your status\n'
                                                 '`!s` to signal lobby start', inline=True)
    ctrsmessage_id = None
    if raid_report:
        raidmsg = "{pokemon} raid reported at {location_details} gym by {member} in {citychannel}. " \
                  "Coordinate here!\n\nClick the question mark reaction" \
                  " to get help on the commands that work in this channel."\
            .format(pokemon=str(raid_pokemon), member=author.display_name,
                    citychannel=channel.mention, location_details=raid_details)
        if str(level) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
            try:
                ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
                ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                          "Update weather with **!weather**. If you know the moveset of the boss, " \
                          "you can react to this message with the matching emoji and I will update the counters."
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
        raid_reports = guild_dict[guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                           .setdefault(author.id, {}).setdefault('raid_reports', 0) + 1
        guild_dict[guild.id]['trainers'][gym.region][author.id]['raid_reports'] = raid_reports
        raid_details = {'pokemon': raid_pokemon,
                        'tier': raid_pokemon.raid_level,
                        'ex-eligible': gym.ex_eligible if gym else False,
                        'location': raid_details,
                        'regions': gym_regions}
    else:
        raidmsg = "Level {level} raid egg reported at {location_details} gym by {member} in {citychannel}. " \
                  "Coordinate here!\n\nClick the question mark reaction to get help " \
                  "on the commands that work in this channel."\
            .format(level=level, member=author.display_name, citychannel=channel.mention, location_details=raid_details)
        egg_reports = guild_dict[message.guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                          .setdefault(author.id, {}).setdefault('egg_reports', 0) + 1
        guild_dict[message.guild.id]['trainers'][gym.region][author.id]['egg_reports'] = egg_reports
        raid_details = {'tier': level,
                        'ex-eligible': gym.ex_eligible if gym else False,
                        'location': raid_details,
                        'regions': gym_regions}
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.add_reaction('\u2754')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('🚫')
    await asyncio.sleep(0.25)
    await raidmessage.pin()
    raid_dict['raidmessage'] = raidmessage.id
    raid_dict['raidreport'] = raidreport.id
    raid_dict['raidcityreport'] = None
    if ctrsmessage_id is not None:
        raid_dict['ctrsmessage'] = ctrsmessage_id
        raid_dict['ctrs_dict'] = ctrs_dict
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict
    if raidexp is not False:
        await _timerset(raid_channel, raidexp, False)
    else:
        await raid_channel.send(content='Hey {member}, if you can, set the time left on the raid using '
                                        '**!timerset <minutes>** so others can check it with **!timer**.'
                                .format(member=author.mention))
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=False, regions=gym_regions)
    subscriptions_cog = Kyogre.cogs.get('Subscriptions')
    if enabled:
        await subscriptions_cog.send_notifications_async('raid', raid_details, raid_channel, [author.id])
    else:
        await subscriptions_cog.send_notifications_async('raid', raid_details, channel, [author.id])
    await raidreport.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await raidreport.add_reaction('🚫')
    await asyncio.sleep(0.25)
    if other_region:
        region_command_channels = guild_dict[guild.id]['configure_dict']['regions'].setdefault('command_channels', [])
        channel_text = ''
        if len(region_command_channels) > 0:
            channel_text = ' in '
            for c in region_command_channels:
                channel_text += Kyogre.get_channel(c).mention
        region_msg = f'Hey {author.mention}, **{gym.name}** is in the **{gym_regions[0].capitalize()}** ' \
            f'region. Your report was successful, but please consider joining that region{channel_text} ' \
            f'to report raids at this gym in the future'
        embed = discord.Embed(colour=discord.Colour.gold(), description=region_msg)
        embed.set_footer(text=f"If you believe this region assignment is incorrect, "
        f"please contact {guild.owner.display_name}")
        await channel.send(embed=embed)
        raidcityreport = await report_channel.send(content=msg, embed=report_embed)
        raid_dict['raidcityreport'] = raidcityreport.id
        await raidcityreport.add_reaction('\u270f')
        await asyncio.sleep(0.25)
        await raidcityreport.add_reaction('🚫')
        await asyncio.sleep(0.25)
    if not raid_report:
        if len(raid_info['raid_eggs'][str(level)]['pokemon']) == 1:
            await _eggassume('assume ' + raid_info['raid_eggs'][str(level)]['pokemon'][0], raid_channel)
        elif level == "5" and guild_dict[raid_channel.guild.id]['configure_dict']['settings']\
                .get('regional', None) in raid_info['raid_eggs']["5"]['pokemon']:
            await _eggassume('assume ' + guild_dict[raid_channel.guild.id]['configure_dict']['settings']['regional'],
                             raid_channel)
    event_loop.create_task(expiry_check(raid_channel))
    return raid_channel


async def _eggassume(args, raid_channel):
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
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {raid_pokemon.name} does not appear in raids!'))
    elif raid_pokemon.name.lower() not in raid_info['raid_eggs'][egglevel]['pokemon']:
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {raid_pokemon.name} does not hatch from level {egglevel} raid eggs!'))
    eggdetails['pokemon'] = raid_pokemon.name
    oldembed = raid_message.embeds[0]
    raid_gmaps_link = oldembed.url
    enabled = raid_helpers.raid_channels_enabled(raid_channel.guild, raid_channel, guild_dict)
    if enabled:
        embed_indices = await embed_utils.get_embed_field_indices(oldembed)
        raid_embed = discord.Embed(title='Click here for directions to the raid!',
                                   url=raid_gmaps_link,
                                   colour=raid_channel.guild.me.colour)
        raid_embed.add_field(name=(oldembed.fields[embed_indices["gym"]].name),
                             value=oldembed.fields[embed_indices["gym"]].value, inline=True)
        cp_range = ''
        if raid_pokemon.name.lower() in boss_cp_chart:
            cp_range = boss_cp_chart[raid_pokemon.name.lower()]
        raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                             .format(pokemon=raid_pokemon.name, pokemonnumber=str(raid_pokemon.id),
                                     type=utils.types_to_str(raid_channel.guild, raid_pokemon.types, Kyogre.config),
                                     cprange='\n'+cp_range, inline=True))
        raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                             .format(weakness_list=utils.types_to_str(raid_channel.guild,
                                                                      raid_pokemon.weak_against, Kyogre.config)))
        if embed_indices["next"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["next"]].name),
                                 value=oldembed.fields[embed_indices["next"]].value, inline=True)
        if embed_indices["hatch"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["hatch"]].name),
                                 value=oldembed.fields[embed_indices["hatch"]].value, inline=True)
        if embed_indices["tips"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["tips"]].name),
                                 value=oldembed.fields[embed_indices["tips"]].value, inline=True)

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
        if eggdetails.get('raidcityreport', None) is not None:
            report_city_channel = Kyogre.get_channel(eggdetails['reportcity'])
            city_report = await report_city_channel.fetch_message(eggdetails['raidcityreport'])
            try:
                await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
                city_report = city_report.id
            except discord.errors.NotFound:
                city_report = None
    if str(egglevel) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                  "Update weather with **!weather**. If you know the moveset of the boss, " \
                  "you can react to this message with the matching emoji and I will update the counters."
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
            city_report = await reportcitychannel.fetch_message(eggdetails.get('raidcityreport',0))
        except (discord.errors.NotFound, discord.errors.HTTPException):
            city_report = None
    starttime = eggdetails.get('starttime',None)
    duplicate = eggdetails.get('duplicate',0)
    archive = eggdetails.get('archive',False)
    meetup = eggdetails.get('meetup',{})
    raid_match = pkmn.is_raid
    if not raid_match:
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {pkmn.full_name} does not appear in raids!'))
    if (egglevel.isdigit() and int(egglevel) > 0) or egglevel == 'EX':
        raidexp = eggdetails['exp'] + 60 * raid_info['raid_eggs'][str(egglevel)]['raidtime']
    else:
        raidexp = eggdetails['exp']
    end = datetime.datetime.utcfromtimestamp(raidexp) + datetime.timedelta(
        hours=guild_dict[raid_channel.guild.id]['configure_dict']['settings']['offset'])
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
        raidreportcontent = 'The egg has hatched into a {pokemon} raid at {location_details} gym.'\
            .format(pokemon=entered_raid.capitalize(), location_details=egg_address)
        enabled = raid_helpers.raid_channels_enabled(raid_channel.guild, raid_channel, guild_dict)
        if enabled:
            raidreportcontent += 'Coordinate in the raid channel: {raid_channel}'\
                .format(raid_channel=raid_channel.mention)
        raidmsg = "The egg reported in {citychannel} hatched into a {pokemon} raid! Details: {location_details}. " \
                  "Coordinate here!\n\nClick the question mark react to get help on the commands that work in here." \
                  "\n\nThis channel will be deleted five minutes after the timer expires."\
            .format(citychannel=reportcitychannel.mention,
                    pokemon=entered_raid.capitalize(),
                    location_details=egg_address)
    elif egglevel == 'EX':
        hatchtype = 'exraid'
        if guild_dict[raid_channel.guild.id]['configure_dict']['invite']['enabled']:
            invitemsgstr = "Use the **!invite** command to gain access and coordinate"
            invitemsgstr2 = " after using **!invite** to gain access"
        else:
            invitemsgstr = "Coordinate"
            invitemsgstr2 = ""
        raidreportcontent = 'The EX egg has hatched into a {pokemon} raid! Details: {location_details}. ' \
                            '{invitemsgstr} coordinate in {raid_channel}'\
            .format(pokemon=entered_raid.capitalize(),
                    location_details=egg_address,
                    invitemsgstr=invitemsgstr,
                    raid_channel=raid_channel.mention)
        raidmsg = "{pokemon} EX raid reported in {citychannel}! Details: {location_details}. Coordinate here" \
                  "{invitemsgstr2}!\n\nClick the question mark reaction to get help on the commands " \
                  "that work in here.\n\nThis channel will be deleted five minutes after the timer expires."\
            .format(pokemon=entered_raid.capitalize(),
                    citychannel=reportcitychannel.mention,
                    location_details=egg_address,
                    invitemsgstr2=invitemsgstr2)
    raid_channel_name = utils.sanitize_name(pkmn.name.lower() + '_' + egg_address)[:32]
    embed_indices = await embed_utils.get_embed_field_indices(oldembed)
    raid_embed = discord.Embed(title='Click here for directions to the raid!',
                               url=raid_gmaps_link,
                               colour=raid_channel.guild.me.colour)
    cp_range = ''
    if pkmn.name.lower() in boss_cp_chart:
        cp_range = boss_cp_chart[pkmn.name.lower()]
    raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                         .format(pokemon=pkmn.name, pokemonnumber=str(pkmn.id),
                                 type=utils.types_to_str(raid_channel.guild, pkmn.types, Kyogre.config),
                                 cprange='\n'+cp_range, inline=True))
    raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                         .format(weakness_list=utils.types_to_str(raid_channel.guild, pkmn.weak_against, Kyogre.config))
                         , inline=True)
    raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
    raid_embed.set_thumbnail(url=pkmn.img_url)
    await raid_channel.edit(name=raid_channel_name, topic=end.strftime('Ends at %I:%M %p (%H:%M)'))
    trainer_list = []
    trainer_dict = copy.deepcopy(guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'])
    for trainer in trainer_dict.keys():
        try:
            user = raid_channel.guild.get_member(trainer)
        except (discord.errors.NotFound, AttributeError):
            continue
        if (trainer_dict[trainer].get('interest', None)) \
                and (entered_raid.lower() not in trainer_dict[trainer]['interest']):
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['status'] =\
                {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0}
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['party'] =\
                {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['count'] = 1
        else:
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['interest'] = []
    await asyncio.sleep(1)
    trainer_count = list_helpers.determine_trainer_count(trainer_dict)
    status_embed = list_helpers.build_status_embed(raid_channel.guild, Kyogre, trainer_count)
    for trainer in trainer_dict.keys():
        if (trainer_dict[trainer]['status']['maybe']) \
                or (trainer_dict[trainer]['status']['coming']) \
                or (trainer_dict[trainer]['status']['here']):
            try:
                user = raid_channel.guild.get_member(trainer)
                trainer_list.append(user.mention)
            except (discord.errors.NotFound, AttributeError):
                continue
    trainers = ' ' + ', '.join(trainer_list) if trainer_list else ''
    await raid_channel.send(content="Trainers{trainer}: The raid egg has just hatched into a {pokemon} raid!"
                            .format(trainer=trainers, pokemon=entered_raid.title()), embed=raid_embed)
    raid_details = {'pokemon': pkmn, 'tier': pkmn.raid_level,
                    'ex-eligible': False if eggdetails['gym'] is None else eggdetails['gym'].ex_eligible,
                    'location': eggdetails['address'], 'regions': eggdetails['regions']}
    new_status = None
    subscriptions_cog = Kyogre.cogs.get('Subscriptions')
    if enabled:
        last_status = guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await raid_channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        if status_embed is not None:
            new_status = await raid_channel.send(embed=status_embed)
            guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['last_status'] = new_status.id
        await subscriptions_cog.send_notifications_async('raid', raid_details, raid_channel,
                                                         [author] if author else [])
    else:
        await subscriptions_cog.send_notifications_async('raid', raid_details, reportchannel,
                                                         [author] if author else [])
    if embed_indices["gym"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["gym"]].name,
                             value=oldembed.fields[embed_indices["gym"]].value, inline=True)
    if embed_indices["next"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["next"]].name,
                             value=oldembed.fields[embed_indices["next"]].value, inline=True)
    if meetup:
        raid_embed.add_field(name=oldembed.fields[3].name, value=end.strftime('%I:%M %p (%H:%M)'), inline=True)
    else:
        raid_embed.add_field(name='**Expires:**', value=end.strftime(' %I:%M %p (%H:%M)'), inline=True)
    if embed_indices["tips"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["tips"]].name,
                             value=oldembed.fields[embed_indices["tips"]].value, inline=True)
    for field in oldembed.fields:
        m = 'maybe'
        c = 'coming'
        h = 'here'
        if (m in field.name.lower()) or (c in field.name.lower()) or (h in field.name.lower()):
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
    if eggdetails.get('raidcityreport', None) is not None:
        try:
            await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
        except (discord.errors.NotFound, AttributeError):
            city_report = None
    if str(egglevel) in guild_dict[raid_channel.guild.id]['configure_dict']['counters']['auto_levels'] \
            and not eggdetails.get('pokemon', None):
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, raid_channel.guild, pkmn, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                  "Update weather with **!weather**. If you know the moveset of the boss, you can react " \
                  "to this message with the matching emoji and I will update the counters."
        ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
        ctrsmessage_id = ctrsmessage.id
        await ctrsmessage.pin()
        for moveset in ctrs_dict:
            await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
            await asyncio.sleep(0.25)
    else:
        ctrs_dict = eggdetails.get('ctrs_dict', {})
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
        'reporter': reporter,
        'last_status': new_status.id if new_status is not None else None
    }
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['starttime'] = starttime
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['duplicate'] = duplicate
    guild_dict[raid_channel.guild.id]['raidchannel_dict'][raid_channel.id]['archive'] = archive
    if author:
        raid_reports = guild_dict[raid_channel.guild.id].setdefault('trainers',{}).setdefault(regions[0], {})\
                           .setdefault(author.id,{}).setdefault('raid_reports',0) + 1
        guild_dict[raid_channel.guild.id]['trainers'][regions[0]][author.id]['raid_reports'] = raid_reports
        await list_helpers._edit_party(ctx, Kyogre, guild_dict, raid_info, raid_channel, author)
    await list_helpers.update_listing_channels(Kyogre, guild_dict, raid_channel.guild,
                                               'raid', edit=False, regions=regions)
    await asyncio.sleep(1)
    event_loop.create_task(expiry_check(raid_channel))


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
Raid Channel Management
"""
async def print_raid_timer(channel):
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(
        seconds=guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['exp'] - time.time())
    timerstr = ' '
    if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('meetup',{}):
        end = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['meetup']['end']
        start = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['meetup']['start']
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
            if start:
                timerstr += "This event will start at {expiry_time}"\
                    .format(expiry_time=start.strftime('%I:%M %p (%H:%M)'))
            else:
                timerstr += "Nobody has told me a start time! Set it with **!starttime**"
            if end:
                timerstr += " | This event will end at {expiry_time}"\
                    .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid':
            if end:
                timerstr += "This event will end at {expiry_time}"\
                    .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
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
        timerstr += "This {raidtype}'s timer has already expired as of {expiry_time}!"\
            .format(raidtype=raidtype, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    elif (guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['egglevel'] == 'EX') \
            or (guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid'):
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
            timerstr += 'This {raidtype} will {raidaction} on {expiry}!'\
                .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
        else:
            timerstr += "No one told me when the {raidtype} will {raidaction}, " \
                        "so I'm assuming it will {raidaction} on {expiry}!"\
                .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
    elif guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
        timerstr += 'This {raidtype} will {raidaction} at {expiry_time}!'\
            .format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    else:
        timerstr += "No one told me when the {raidtype} will {raidaction}, " \
                    "so I'm assuming it will {raidaction} at {expiry_time}!"\
            .format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    return timerstr


@Kyogre.command(aliases=['ts'])
@checks.raidchannel()
async def timerset(ctx, *, timer):
    """Set the remaining duration on a raid.
    
    **Usage**: `!timerset/ts [HH:MM] or [minutes]`
    If using the HH:MM format, provide the time the egg hatches or raid expires
    Otherwise, provide the number of minutes until the egg hatches or raid expires.
    **Examples**: `!timerset 10:32`  `!ts 20`"""
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
        raidexp = await utils.time_to_minute_count(guild_dict, channel, timer)
        if raidexp is False:
            return
        if _timercheck(raidexp, maxtime):
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"That's too long. Level {raidlevel} {raidtype.capitalize()}s "
                f"currently last no more than {maxtime} minutes."))
        await _timerset(channel, raidexp)
    if checks.check_exraidchannel(ctx):
        if checks.check_eggchannel(ctx) or checks.check_meetupchannel(ctx):
            now = datetime.datetime.utcnow() + datetime.timedelta(
                hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
            timer_split = timer.lower().split()
            try:
                start = dateparser.parse(' '.join(timer_split).lower(), settings={'DATE_ORDER': 'MDY'})
            except:
                if ('am' in ' '.join(timer_split).lower()) or ('pm' in ' '.join(timer_split).lower()):
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year),
                                                           '%m/%d %I:%M %p %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset**"
                                           " to match this format: **MM/DD HH:MM AM/PM** "
                                           "(You can also omit AM/PM and use 24-hour time!)")
                        return
                else:
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year),
                                                           '%m/%d %H:%M %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset** to "
                                           "match this format: **MM/DD HH:MM AM/PM** "
                                           "(You can also omit AM/PM and use 24-hour time!)")
                        return
            if checks.check_meetupchannel(ctx):
                starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('start', False)
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


async def _timerset(raidchannel, exptime, print=True):
    guild = raidchannel.guild
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(minutes=exptime)
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][raidchannel.id]
    raid_dict['exp'] = time.time() + (exptime * 60)
    if not raid_dict['active']:
        await raidchannel.send('The channel has been reactivated.')
    raid_dict['active'] = True
    raid_dict['manual_timer'] = True
    topicstr = ''
    if raid_dict.get('meetup',{}):
        raid_dict['meetup']['end'] = end
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = end.strftime('%I:%M %p (%H:%M)')
    elif raid_dict['type'] == 'egg':
        egglevel = raid_dict['egglevel']
        hatch = end
        end = hatch + datetime.timedelta(minutes=raid_info['raid_eggs'][egglevel]['raidtime'])
        topicstr += 'Hatches at {expiry}'.format(expiry=hatch.strftime('%I:%M %p (%H:%M) | '))
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = hatch.strftime('%I:%M %p (%H:%M)')
    else:
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = end.strftime('%I:%M %p (%H:%M)')
    if print:
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
            embed.set_field_at(embed_indices[type], name=embed.fields[embed_indices[type]].name, value=endtime)
        else:
            embed.add_field(name='**Expires:**' if type == 'expires' else '**Hatches:**', value=endtime)
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
            if raid_dict.get('raidcityreport', None) is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=embed, content=city_report.content)
                    city_report = city_report.id
                except:
                    pass
    await list_helpers.update_listing_channels(Kyogre, guild_dict, raidchannel.guild,
                                               'raid', edit=True, regions=raid_dict.get('regions', None))
    Kyogre.get_channel(raidchannel.id)


@Kyogre.command()
@checks.raidchannel()
async def timer(ctx):
    """Have Kyogre resend the expire time message for a raid.

    **Usage**: `!timer`
    The expiry time should have been previously set with `!timerset`."""
    timerstr = await print_raid_timer(ctx.channel)
    await ctx.channel.send(timerstr)


@Kyogre.command(aliases=['st'])
async def starttime(ctx, *, start_time=""):
    """Set a time for a group to start a raid

    **Usage**: `!starttime/st [HH:MM] or [minutes]`
    If using the HH:MM format, provide the time the group will start
    Otherwise, provide the number of minutes until the group will start
    **Examples**: `!starttime 10:32`  `!st 20`

    Only one start time is allowed at a time and is visible in `!list` output. 
    Cleared with `!starting.`"""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
    if start_time:
        exp_minutes = await utils.time_to_minute_count(guild_dict, channel, start_time)
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
                nextgroup = start.strftime('%I:%M %p (%H:%M)')
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
            if raid_dict.get('raidcityreport', None) is not None:
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
            await channel.send('No start time has been set, set one with **!starttime HH:MM AM/PM**! '
                               '(You can also omit AM/PM and use 24-hour time!)')


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
        locationmsg = await channel.send(content="Here's the current location for the raid!\nDetails: {location}"
                                         .format(location=location), embed=newembed)
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
        regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
        gym = None
        gyms = get_gyms(message.guild.id, regions)
        if gyms:
            gym = await location_match_prompt(channel, message.author.id, details, gyms)
            if not gym:
                return await channel.send("I couldn't find a gym named '{0}'. Try again using the exact gym name!"
                                          .format(details))
            details = gym.name
            newloc = gym.maps_url
            regions = [gym.region]
        else:
            utilities_cog = Kyogre.cogs.get('Utilities')
            newloc = utilities_cog.create_gmaps_query(details, report_channel, type="raid")
        await entity_updates.update_raid_location(Kyogre, guild_dict, message, report_channel, channel, gym)
        return


@Kyogre.command()
@checks.activechannel()
async def duplicate(ctx):
    """A command to report a raid channel as a duplicate.

    **Usage**: `!duplicate`
    When three users report a channel as a duplicate,
    Kyogre deactivates the channel and marks it for deletion."""
    channel = ctx.channel
    author = ctx.author
    guild = ctx.guild
    rc_d = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    t_dict = rc_d['trainer_dict']
    can_manage = channel.permissions_for(author).manage_channels
    raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', False) else "raid"
    regions = rc_d['regions']
    if can_manage:
        dupecount = 2
        rc_d['duplicate'] = dupecount
    else:
        if author.id in t_dict:
            try:
                if t_dict[author.id]['dupereporter']:
                    dupeauthmsg = await channel.send("You've already made a duplicate report for this {raidtype}!"
                                                     .format(raidtype=raidtype))
                    await asyncio.sleep(10)
                    await dupeauthmsg.delete()
                    return
                else:
                    t_dict[author.id]['dupereporter'] = True
            except KeyError:
                t_dict[author.id]['dupereporter'] = True
        else:
            t_dict[author.id] = {
                'status': {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0},
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
        confirmation = await channel.send('Duplicate report #{duplicate_report_count} received.'
                                          .format(duplicate_report_count=str(dupecount)))
        logger.info((((('Duplicate Report - ' + channel.name) + ' - Report #')
                      + str(dupecount)) + '- Report by ') + author.name)
        return


@Kyogre.command()
async def counters(ctx, *, args=''):
    """Simulate a Raid battle with Pokebattler.

    **Usage**: `!counters [pokemon] [weather] [user]`
    See `!help` weather for acceptable values for weather.
    If [user] is a valid Pokebattler user id, Kyogre will simulate the Raid with that user's Pokebox.
    Uses current boss and weather by default if available.
    """
    rgx = '[^a-zA-Z0-9 ]'
    channel = ctx.channel
    guild = channel.guild
    user = guild_dict[ctx.guild.id].get('trainers',{}).setdefault('info', {})\
                                   .get(ctx.author.id,{}).get('pokebattlerid', None)
    if checks.check_raidchannel(ctx) and not checks.check_meetupchannel(ctx):
        if args:
            args_split = args.split()
            for arg in args_split:
                if arg.isdigit():
                    user = arg
                    break
        try:
            ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]
                                                      .get('ctrsmessage',None))
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        pkmn = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
        if pkmn:
            if not user:
                try:
                    ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]
                                                              .get('ctrsmessage',None))
                    ctrsembed = ctrsmessage.embeds[0]
                    ctrsembed.remove_field(6)
                    ctrsembed.remove_field(6)
                    await channel.send(content=ctrsmessage.content,embed=ctrsembed)
                    return
                except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                    pass
            moveset = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('moveset', 0)
            movesetstr = guild_dict[guild.id]['raidchannel_dict'][channel.id]\
            .get('ctrs_dict', {'enabled': False, 'auto_levels': []})\
            .get(moveset, {}).get('moveset', "Unknown Moveset")
            weather = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('weather', None)
        else:
            pkmn = next((str(p) for p in Pokemon.get_raidlist() if not str(p).isdigit()
                         and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
            if not pkmn:
                await ctx.channel.send("You're missing some details! Be sure to enter a pokemon"
                                       " that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
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
        pkmn = next((str(p) for p in Pokemon.get_raidlist() if not str(p).isdigit()
                     and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
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
        await ctx.channel.send("You're missing some details! Be sure to enter a "
                               "pokemon that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
        return
    pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    await counters_helpers._counters(ctx, Kyogre, pkmn, user, weather, "Unknown Moveset")


@Kyogre.command()
@checks.activechannel()
async def weather(ctx, *, weather):
    """Sets the weather for the raid.

    **Usage**: !weather <weather>
    
    Acceptable options: none, extreme, clear, rainy, partlycloudy, cloudy, windy, snow, fog"""
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    if weather.lower() not in weather_list:
        return await ctx.channel.send("Enter one of the following weather conditions: {}".format(", ".join(weather_list)))
    else:
        await raid_lobby_helpers._weather(ctx, Kyogre, guild_dict, weather)

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
        teamcounts = "{teamcounts} {bosslist}"\
            .format(teamcounts=teamcounts,
                    bosslist=",".join([s.title() for s in raid_info['raid_eggs'][egglevel]['pokemon']]))
        teamcounts = teamcounts.lower().replace("all","").strip()
    return status_parser.fullmatch(teamcounts)


async def _process_status_command(ctx, teamcounts):
    trainer_dict = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
    entered_interest = trainer_dict.get(ctx.author.id, {}).get('interest', [])
    egglevel = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['egglevel']
    parsed_counts = await _parse_teamcounts(ctx, teamcounts, trainer_dict, egglevel)
    errors = []
    if not parsed_counts:
        raise ValueError("I couldn't understand that format! "
                         "Check the format against `!help interested` and try again.")
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
                    errors.append("{pkmn} doesn't appear in level {egglevel} raids! Please try again."
                                  .format(pkmn=pkmn.name,egglevel=egglevel))
        if errors:
            errors.append("Invalid Pokemon detected. Please check the pinned message "
                          "for the list of possible bosses and try again.")
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


@Kyogre.command()
@checks.activechannel()
async def shout(ctx, *, shout_message="\u200b"):
    """Notifies all trainers who have RSVPd for the raid of your message
    
    **Usage**: `!shout <message>`
    Kyogre will notify all trainers who have expressed interest and include your message.
    This command has a 2 minute cooldown. 
    If it is used again within those 2 minutes the other trainers will not be notified.
    """
    message = ctx.message
    author = message.author
    guild = message.guild
    channel = message.channel
    cooldown_time = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('cooldown', 0)
    cooldown = False
    if cooldown_time > int(time.time()):
        cooldown = True
    else:
        guild_dict[guild.id]['raidchannel_dict'][channel.id]['cooldown'] = int(time.time()) + 120
    trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    trainer_list = []
    embed = discord.Embed(colour=discord.Colour.green())
    for trainer in trainer_dict:
        if trainer != author.id:
            if cooldown:
                trainer_list.append(guild.get_member(trainer).display_name)
                embed.set_footer(text="Cooldown in effect, users will not be pinged.")
            else:
                trainer_list.append(guild.get_member(trainer).mention)
    if len(trainer_list) > 0:
        message = "Hey " + ', '.join(trainer_list) + "!"
        embed.add_field(name=f"Message from {author.display_name}", value=shout_message)
        await channel.send(content=message, embed=embed)
    else:
        await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                               title="There is no one here to hear you!"))
    await message.delete()


@Kyogre.command(name='interested', aliases=['i', 'maybe'])
@checks.activechannel()
async def interested(ctx, *, teamcounts: str = None):
    """Indicate you are interested in the raid.

    **Usage**: `!interested/i [count] [party]`

    Count must be a number. If count is omitted, assumes you are a group of 1.
    **Example**: `!i 2`

    Party must be a number plus a team.
    **Example**: `!i 3 1i 1m 1v`"""
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

    **Usage**: `!coming/c [count] [party]`

    Count must be a number. If count is omitted, assumes you are a group of 1.
    **Example**: `!c 2`

    Party must be a number plus a team.
    **Example**: `!c 3 1i 1m 1v`"""
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

    **Usage**: `!here/h [count] [party]`
    Count must be a number. If count is omitted, assumes you are a group of 1.

    **Example**: `!h 2`
    Party must be a number plus a team.
    **Example**: `!h 3 1i 1m 1v`"""
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
                    return await channel.send('Something is not adding up! Try making sure '
                                              'your total matches what each team adds up to!')
                unknown[1] = total - team_total
            else:
                team_aliases[my_team][1] = total - team_total
    partylist = {'mystic':mystic[1], 'valor':valor[1], 'instinct':instinct[1], 'unknown':unknown[1]}
    result = [total, partylist]
    return result


@Kyogre.command(aliases=['l'])
@checks.activeraidchannel()
async def lobby(ctx, *, count: str = None):
    """Used to join an in-progress lobby started with `!starting`

    **Usage**: `!lobby [count]`
    Count must be a number. If count is omitted, assumes you are a group of 1."""
    try:
        if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == 'egg':
            if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['pokemon'] == '':
                await ctx.channel.send("Please wait until the raid egg has hatched "
                                       "before announcing you're coming or present.")
                return
    except:
        pass
    trainer_dict = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
    if count:
        if count.isdigit():
            count = int(count)
        else:
            await ctx.channel.send("I can't understand how many are in your group. Just say **!lobby** if you're "
                                   "by yourself, or **!lobby 5** for example if there are 5 in your group.")
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
        await channel.send('There is no group in the lobby for you to join!\
        Use **!starting** if the group waiting at the raid is entering the lobby!')
        return
    trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    if count == 1:
        await channel.send('{member} is entering the lobby!'.format(member=trainer.mention))
    else:
        await channel.send('{member} is entering the lobby with a total of {trainer_count} trainers!'
                           .format(member=trainer.mention, trainer_count=count))
        regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
        joined = guild_dict[guild.id].setdefault('trainers', {})\
                     .setdefault(regions[0], {})\
                     .setdefault(trainer.id, {})\
                     .setdefault('joined', 0) + 1
        guild_dict[guild.id]['trainers'][regions[0]][trainer.id]['joined'] = joined
    if trainer.id not in trainer_dict:
        trainer_dict[trainer.id] = {}
    trainer_dict[trainer.id]['status'] = {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': count}
    trainer_dict[trainer.id]['count'] = count
    guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
    regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
    if regions:
        await list_helpers.update_listing_channels(Kyogre, guild_dict, channel.guild,
                                                   'raid', edit=True, regions=regions)


@Kyogre.command(aliases=['x'])
@checks.raidchannel()
async def cancel(ctx):
    """Indicate you are no longer interested in a raid or that you are backing out of a lobby.

    **Usage**: `!cancel/x`
    Removes you and your party from the list of trainers who are "coming" or "here".
    Or removes you and your party from the active lobby."""
    await list_helpers._cancel(ctx, Kyogre, guild_dict, raid_info)


@Kyogre.command(aliases=['s'])
@checks.activeraidchannel()
async def starting(ctx, team: str = ''):
    """Signal that a raid is starting.

    **Usage**: `!starting/s [team]`
    Sends a message notifying all trainers who are at the raid and clears the waiting list.
    Starts a 2 minute lobby countdown during which time trainers can join this lobby using `!lobby`.
    Users who are waiting for a second group must reannounce with `!here`."""
    await raid_lobby_helpers._starting(ctx, Kyogre, guild_dict, raid_info, team)


@Kyogre.command()
@checks.activeraidchannel()
async def backout(ctx):
    """Request players in lobby to backout

    **Usage**: `!backout`
    Will alert all trainers in the lobby that a backout is requested.
    Those trainers can exit the lobby with `!cancel`."""
    await raid_lobby_helpers._backout(ctx, Kyogre, guild_dict)
     

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
