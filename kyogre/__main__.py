import asyncio
import copy
import datetime
import sys
import time

import aiohttp
import discord

from kyogre.bot import KyogreBot

from kyogre.exts.db.kyogredb import *
KyogreDB.start('data/kyogre.db')

Kyogre = KyogreBot()
logger = Kyogre.logger

guild_dict = Kyogre.guild_dict
config = Kyogre.config


async def guild_cleanup(loop=True):
    while not Kyogre.is_closed():
        guilddict_srvtemp = copy.deepcopy(guild_dict)
        logger.info('Server_Cleanup ------ BEGIN ------')
        guilddict_srvtemp = guild_dict
        dict_guild_list = []
        bot_guild_list = []
        dict_guild_delete = []
        guild_id = None
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
    while not Kyogre.is_closed():
        logger.info('message_cleanup ------ BEGIN ------')
        guild_dict = Kyogre.guild_dict
        guilddict_temp = copy.deepcopy(Kyogre.guild_dict)
        update_ids = set()
        guild_id = None
        for guildid in guilddict_temp.keys():
            if guildid in Kyogre.util_servers:
                continue
            questreport_dict = guilddict_temp[guildid].get('questreport_dict', {})
            wildreport_dict = guilddict_temp[guildid].get('wildreport_dict', {})
            report_dict_dict = {
                'questreport_dict': questreport_dict,
                'wildreport_dict': wildreport_dict,
            }
            report_edit_dict = {}
            report_delete_dict = {}
            for report_dict in report_dict_dict:
                for reportid in report_dict_dict[report_dict].keys():
                    if report_dict_dict[report_dict][reportid].get('exp', 0) <= time.time():
                        report_channel = Kyogre.get_channel(report_dict_dict[report_dict][reportid]
                                                            .get('reportchannel'))
                        if report_channel:
                            user_report = report_dict_dict[report_dict][reportid].get('reportmessage', None)
                            if user_report:
                                report_delete_dict[user_report] = {"action": "delete", "channel": report_channel}
                            if report_dict_dict[report_dict][reportid].get('expedit') == "delete":
                                report_delete_dict[reportid] = {"action": "delete", "channel": report_channel}
                            else:
                                report_edit_dict[reportid] = {"action": report_dict_dict[report_dict][reportid]
                                    .get('expedit', "edit"), "channel": report_channel}
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
                    await report_message.edit(content=report_edit_dict[messageid]['action']['content'],
                                              embed=discord.Embed(description=report_edit_dict[messageid]['action']
                                                                  .get('embedcontent'),
                                                                  colour=report_message.embeds[0].colour.value))
                    await report_message.clear_reactions()
                    update_ids.add(guildid)
                except (discord.errors.NotFound, discord.errors.Forbidden,
                        discord.errors.HTTPException, IndexError, KeyError):
                    pass
        # save server_dict changes after cleanup
        for uid in update_ids:
            guild = Kyogre.get_guild(uid)
            listmgmt_cog = Kyogre.cogs.get('ListManagement')
            await listmgmt_cog.update_listing_channels(guild, 'wild', edit=True)
            await listmgmt_cog.update_listing_channels(guild, 'research', edit=True)
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
        exraids_cog = bot.get_cog("EXRaids")
        raids_cog = bot.get_cog("RaidCommands")
        invasions_cog = bot.get_cog("Invasions")
        tasks.append(event_loop.create_task(exraids_cog.channel_cleanup()))
        tasks.append(event_loop.create_task(raids_cog.channel_cleanup()))
        tasks.append(event_loop.create_task(message_cleanup()))
        tasks.append(event_loop.create_task(bot.update_subs_leaderboard()))
        await invasions_cog.cleanup_counters()
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
    if not Kyogre.session:
        Kyogre.session = aiohttp.ClientSession()
    Kyogre.owner = discord.utils.get(
        Kyogre.get_all_members(), id=config['master'])
    if Kyogre.initial_start:
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
                    'configure_dict': {
                                'welcome': {'enabled': False, 'welcomechan': '', 'welcomemsg': ''},
                                'raid': {'enabled': False, 'report_channels': {}, 'categories': 'same',
                                         'category_dict': {}, 'raid_channels': {},
                                         'listings': {'enabled': False, 'channels': {}}, 'short_output': {}},
                                'counters': {'enabled': False, 'auto_levels': []},
                                'wild': {'enabled': False, 'report_channels': {},
                                         'listings': {'enabled': False, 'channels': {}}},
                                'research': {'enabled': False, 'report_channels': {},
                                             'listings': {'enabled': False, 'channels': {}}},
                                'archive': {'enabled': False, 'category': 'same', 'list': None},
                                'invite': {'enabled': False},
                                'team': {'enabled': False},
                                'settings': {'offset': 0, 'regional': None, 'done': False, 'prefix': None,
                                             'config_sessions': {}, 'invasion_minutes': 30, 'lure_minutes': 30},
                                'trade': {'enabled': False, 'report_channels': []},
                                'regions': {'enabled': False, 'command_channels': [], 'info': {}, 'notify_channel': None},
                                'meetup': {'enabled': False},
                                'subscriptions': {'enabled': False, 'report_channels': [], 'leaderboard_refresh_seconds': 720,
                                                  'leaderboard_message': None, 'leaderboard_channel': None,
                                                  'leaderboard_limit': 5},
                                'pvp': {'enabled': False, 'report_channels': []},
                                'join': {'enabled': False},
                                'lure': {'enabled': False, 'report_channels': {},
                                         'listings': {'enabled': False, 'channels': {}}},
                                'invite_tracking': {'enabled': False, 'destination': None, 'invite_counts': {}},
                                'quick_badge': {'listen_channels': [], 'pokenav_channel': None, 'badge_channel': None,
                                                'badges': {}, '40_role': None, '40_listen_channels': []},
                                'hideout': {'enabled': False, 'report_channels': {},
                                             'listings': {'enabled': False, 'channels': {}}}},
                    'wildreport_dict': {},
                    'questreport_dict': {},
                    'raidchannel_dict': {},
                    'exchannel_dict': {},
                    'pvp_dict': {},
                    'raid_notice_dict': {},
                    'trade_dict': {},
                    'trainers': {},
                    'trainer_names': {}
                }
            else:
                guild_dict[guild.id]['configure_dict'].setdefault('trade', {})
                guild_dict[guild.id]['configure_dict'].setdefault('regions',
                                                                  {'enabled': False, 'command_channels': [], 'info': {},
                                                                   'notify_channel': None})
                guild_dict[guild.id]['configure_dict'].setdefault('meetup', {'enabled': False})
                guild_dict[guild.id]['configure_dict'].setdefault('subscriptions',
                                                                  {'enabled': False, 'report_channels': [],
                                                                   'leaderboard_refresh_seconds': 720,
                                                                   'leaderboard_message': None,
                                                                   'leaderboard_channel': None, 'leaderboard_limit': 5})
                guild_dict[guild.id]['configure_dict'].setdefault('pvp', {'enabled': False, 'report_channels': []})
                guild_dict[guild.id]['configure_dict'].setdefault('join', {'enabled': False})
                guild_dict[guild.id]['configure_dict'].setdefault('lure', {'enabled': False, 'report_channels': {},
                                                                           'listings': {'enabled': False,
                                                                                        'channels': {}}})
                guild_dict[guild.id]['configure_dict'].setdefault('invite_tracking',
                                                                  {'enabled': False, 'destination': None,
                                                                   'invite_counts': {}})
                guild_dict[guild.id]['configure_dict'].setdefault('quick_badge',
                                                                  {'listen_channels': [], 'pokenav_channel': None,
                                                                   'badge_channel': None, 'badges': {}, '40_role': None,
                                                                   '40_listen_channels': []})
                guild_dict[guild.id]['configure_dict'].setdefault('hideout', {'enabled': False, 'report_channels': {},
                                                                               'listings': {'enabled': True,
                                                                                            'channels': {}}})
                guild_dict[guild.id].setdefault('pvp_dict', {})
                guild_dict[guild.id].setdefault('raid_notice_dict', {})
                guild_dict[guild.id].setdefault('trade_dict', {})
                guild_dict[guild.id].setdefault('exchannel_dict', {})
                try:
                    trainers = guild_dict[guild.id]['configure_dict']['trainers']
                    guild_dict[guild.id]['trainers'] = trainers
                    del guild_dict[guild.id]['configure_dict']['trainers']
                except KeyError:
                    guild_dict[guild.id].setdefault('trainers', {})
                guild_dict[guild.id].setdefault('trainer_names', {})
        except KeyError:
            guild_dict[guild.id] = {
                'configure_dict': {
                        'welcome': {'enabled': False, 'welcomechan': '', 'welcomemsg': ''},
                        'raid': {'enabled': False, 'report_channels': {}, 'categories': 'same',
                                 'category_dict': {}, 'raid_channels': {},
                                 'listings': {'enabled': False, 'channels': {}}, 'short_output': {}},
                        'counters': {'enabled': False, 'auto_levels': []},
                        'wild': {'enabled': False, 'report_channels': {},
                                 'listings': {'enabled': False, 'channels': {}}},
                        'research': {'enabled': False, 'report_channels': {},
                                     'listings': {'enabled': False, 'channels': {}}},
                        'archive': {'enabled': False, 'category': 'same', 'list': None},
                        'invite': {'enabled': False},
                        'team': {'enabled': False},
                        'settings': {'offset': 0, 'regional': None, 'done': False, 'prefix': None,
                                     'config_sessions': {}, 'invasion_minutes': 30, 'lure_minutes': 30},
                        'trade': {'enabled': False, 'report_channels': []},
                        'regions': {'enabled': False, 'command_channels': [], 'info': {}, 'notify_channel': None},
                        'meetup': {'enabled': False},
                        'subscriptions': {'enabled': False, 'report_channels': [], 'leaderboard_refresh_seconds': 720,
                                          'leaderboard_message': None, 'leaderboard_channel': None,
                                          'leaderboard_limit': 5},
                        'pvp': {'enabled': False, 'report_channels': []},
                        'join': {'enabled': False},
                        'lure': {'enabled': False, 'report_channels': {},
                                 'listings': {'enabled': False, 'channels': {}}},
                        'invite_tracking': {'enabled': False, 'destination': None, 'invite_counts': {}},
                        'quick_badge': {'listen_channels': [], 'pokenav_channel': None, 'badge_channel': None,
                                        'badges': {}, '40_role': None, '40_listen_channels': []},
                        'hideout': {'enabled': False, 'report_channels': {},
                                     'listings': {'enabled': False, 'channels': {}}}},
                'wildreport_dict': {},
                'questreport_dict': {},
                'raidchannel_dict': {},
                'exchannel_dict': {},
                'pvp_dict': {},
                'raid_notice_dict': {},
                'trade_dict': {},
                'trainers': {},
                'trainer_names': {}
            }
        owners.append(guild.owner)
    help_cog = Kyogre.cogs.get('HelpCommand')
    help_cog.set_avatar(Kyogre.user.avatar_url)
    if Kyogre.initial_start:
        await _print(Kyogre.owner, "{server_count} servers connected.\n{member_count} members found."
                     .format(server_count=guilds, member_count=users))
        Kyogre.initial_start = False
        await maint_start(Kyogre)
    else:
        logger.warn("Bot failed to resume")

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
