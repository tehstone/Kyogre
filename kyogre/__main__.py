import asyncio
import copy
import datetime
import sys
import time

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
            guild_id = guildid
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
                        print(f"report chan: {report_channel.id}")
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
        await asyncio.sleep(30)
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
        tasks.append(event_loop.create_task(bot.update_subs_leaderboard()))
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
                    'configure_dict': {
                        'welcome': {'enabled': False, 'welcomechan': '', 'welcomemsg': ''},
                        'want': {'enabled': False, 'report_channels': []},
                        'raid': {'enabled': False, 'report_channels': {}, 'categories': 'same', 'category_dict': {}},
                        'exraid': {'enabled': False, 'report_channels': {}, 'categories': 'same',
                                   'category_dict': {}, 'permissions': 'everyone'},
                        'wild': {'enabled': False, 'report_channels': {}},
                        'lure': {'enabled': False, 'report_channels': {}},
                        'counters': {'enabled': False, 'auto_levels': []},
                        'research': {'enabled': False, 'report_channels': {}},
                        'archive': {'enabled': False, 'category': 'same', 'list': None},
                        'invite': {'enabled': False},
                        'team': {'enabled': False},
                        'settings': {'offset': 0, 'regional': None, 'done': False,
                                     'prefix': None, 'config_sessions': {}}
                    },
                    'wildreport_dict:': {},
                    'questreport_dict': {},
                    'raidchannel_dict': {},
                    'trainers': {}
                }
            else:
                guild_dict[guild.id]['configure_dict'].setdefault('trade', {})
        except KeyError:
            guild_dict[guild.id] = {
                'configure_dict': {
                    'welcome': {'enabled': False, 'welcomechan': '', 'welcomemsg': ''},
                    'want': {'enabled': False, 'report_channels': []},
                    'raid': {'enabled': False, 'report_channels': {}, 'categories': 'same', 'category_dict': {}},
                    'exraid': {'enabled': False, 'report_channels': {}, 'categories': 'same',
                               'category_dict': {}, 'permissions': 'everyone'},
                    'wild': {'enabled': False, 'report_channels': {}},
                    'lure': {'enabled': False, 'report_channels': {}},
                    'counters': {'enabled': False, 'auto_levels': []},
                    'research': {'enabled': False, 'report_channels': {}},
                    'archive': {'enabled': False, 'category': 'same', 'list': None},
                    'invite': {'enabled': False},
                    'team': {'enabled': False},
                    'settings': {'offset': 0, 'regional': None, 'done': False,
                                 'prefix': None, 'config_sessions': {}}
                },
                'wildreport_dict:': {},
                'questreport_dict': {},
                'raidchannel_dict': {},
                'trainers': {}
            }
        owners.append(guild.owner)
    help_cog = Kyogre.cogs.get('HelpCommand')
    help_cog.set_avatar(Kyogre.user.avatar_url)
    await _print(Kyogre.owner, "{server_count} servers connected.\n{member_count} members found."
                 .format(server_count=guilds, member_count=users))
    await maint_start(Kyogre)


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
