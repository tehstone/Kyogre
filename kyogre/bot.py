import asyncio
import copy
import json
import os
import pickle
import sys

from kyogre.exts.pokemon import Pokemon
from kyogre.logs import init_loggers, init_logger
from kyogre.errors import custom_error_handling

import discord
from discord.ext import commands
from kyogre.context import Context
from kyogre.exts.db.kyogredb import InviteRoleTable


default_exts = ['admincommands',
                'autobadge',
                'badges',
                'configuration',
                'counterhelpers',
                'events',
                'exraids',
                'faves',
                'gameinfo',
                'getcommands',
                'helpcommand',
                'invasions',
                'inviterole',
                'listcommands',
                'listmanagement',
                'locationmanagement',
                'locationmatching',
                'lurecommands',
                'misc',
                'nestcommands',
                'newtrainer',
                'pokemon',
                'pvp',
                'questrewardmanagement',
                'quickbadge',
                'raidauto',
                'raidavailable',
                'raidcommands',
                'raiddatahandler',
                'raidparty',
                'regions',
                'researchcommands',
                'setcommands',
                'silph',
                'social',
                'subscriptions',
                'trade',
                'tutorial',
                'utilities',
                'wildspawncommands']


def _prefix_callable(bot, msg):
    user_id = bot.user.id
    base = [f'<@!{user_id}> ', f'<@{user_id}> ']
    if msg.guild is None:
        base.append('!')
    else:
        try:
            prefix = bot.guild_dict[msg.guild.id]['configure_dict']['settings']['prefix']
        except (KeyError, AttributeError):
            prefix = None
        if not prefix:
            prefix = bot.config['default_prefix']
        base.extend(prefix)
    return base


class KyogreBot(commands.AutoShardedBot):
    """Custom Discord Bot class for Kyogre"""

    def __init__(self):
        super().__init__(command_prefix=_prefix_callable,
                         case_insensitive=True,
                         activity=discord.Game(name="Pokemon Go"))

        self.logger = init_loggers()
        self.help_logger = init_logger("help", "logs/kyogre_help.log")
        self.user_logger = init_logger("user", "logs/kyogre_user.log")
        self.gcv_logger = init_logger("gcv", "logs/gcv_api.log")
        self.scan_fail_log = init_logger("scanfail", "logs/gcv_api.log")
        custom_error_handling(self, self.logger)
        self.guild_dict = {}
        self.vision_api_enabled = False
        self.api_usage_limit = 20
        self._load_data()
        self.raid_json_path = self._load_raid_data()
        self.quest_json_path = self._load_quest_data()
        self._load_config()
        self.active_ex = []
        self.active_raids = []
        self.active_wilds = []
        self.active_pvp = []
        self.active_lures = []
        self.active_invasions = {}
        self.success_react = '✅'
        self.failed_react = '❌'
        self.thumbsup_react = '👍'
        self.empty_str = '\u200b'
        self.team_color_map = {'Mystic': discord.Colour.blue(),
                               'Valor': discord.Colour.red(),
                               'Instinct': discord.Colour.from_rgb(255, 255, 0)}
        self.saved_files = {}
        self.session = None
        self.port = 8000
        self.initial_start = True
        self.util_servers = [727602601255895050, 727602831489761291, 727603211049107547, 727607175186350130,
                             727607261589012550, 727607316245119086, 727610691980361768, 727610940081700996,
                             727611076744708167, 727612650514808914, 727612770169651340, 727612892467298334,
                             727613019923677256, 727613199305670656, 727613275419967558, 727630993254645811]
        self.leaderboard_list = ["total", "raids", "eggs", "exraids", "wild", "research", "joined", "nests"]
        self.channel_exp_minutes = 1

        for ext in default_exts:
            try:
                self.load_extension(f"kyogre.exts.{ext}")
            except Exception as e:
                print(f'**Error when loading extension {ext}:**\n{type(e).__name__}: {e}')
            else:
                if 'debug' in sys.argv[1:]:
                    print(f'Loaded {ext} extension.')
        self.boss_list = Pokemon.get_raidlist(self)
        for b in self.boss_list:
            if b.lower().startswith('alolan'):
                self.boss_list.append(b.split()[1])
        self._setup_folders()

    class RenameUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            module = module.replace("meowth", "kyogre")
            return super().find_class(module, name)

    def _load_data(self):
        try:
            with open(os.path.join('data', 'serverdict'), 'rb') as fd:
                self.guild_dict = self.RenameUnpickler(fd).load()
            self.logger.info('Serverdict Loaded Successfully')
        except OSError:
            self.logger.info('Serverdict Not Found - Looking for Backup')
            try:
                with open(os.path.join('data', 'serverdict_backup'), 'rb') as fd:
                    self.guild_dict = self.RenameUnpickler(fd).load()
                self.logger.info('Serverdict Backup Loaded Successfully')
            except OSError:
                self.logger.info('Serverdict Backup Not Found - Creating New Serverdict')
                self.guild_dict = {}
                with open(os.path.join('data', 'serverdict'), 'wb') as fd:
                    pickle.dump(self.guild_dict, fd, -1)
                self.logger.info('Serverdict Created')

    def _load_config(self):
        # Load configuration
        with open('config.json', 'r') as fd:
            self.config = json.load(fd)
        # Load type information
        with open(os.path.join('data', 'defense_chart.json'), 'r') as fd:
            self.defense_chart = json.load(fd)
        with open(os.path.join('data', 'type_list.json'), 'r') as fd:
            self.type_list = json.load(fd)

    def _load_raid_data(self):
        raid_path_source = os.path.join('data', 'raid_info.json')
        with open(raid_path_source, 'r') as fd:
            self.raid_info = json.load(fd)
            if "2" in self.raid_info['raid_eggs']:
                del self.raid_info['raid_eggs']["2"]
            if "4" in self.raid_info['raid_eggs']:
                del self.raid_info['raid_eggs']["4"]
            if "6" not in self.raid_info['raid_eggs']:
                self.raid_info['raid_eggs']["6"]= \
                {'egg': 'normal', 'egg_img': '1.png', 'pokemon': [], 'hatchtime': 60, 'raidtime': 45}
            self.raid_info['raid_eggs']["0"] = \
                {'egg': 'normal', 'egg_img': '1.png', 'pokemon': [], 'hatchtime': 60, 'raidtime': 45}
        return raid_path_source

    def _load_quest_data(self):
        return os.path.join('data', 'quest_data.json')

    @staticmethod
    def _setup_folders():
        screenshot_dirs = ['screenshots', 'screenshots/1',
                           'screenshots/2', 'screenshots/3',
                           'screenshots/4', 'screenshots/5',
                           'screenshots/no_gym', 'screenshots/not_raid',
                           'screenshots/no_tier', 'screenshots/boss',
                           'screenshots/ex', 'screenshots/profile']
        for sdir in screenshot_dirs:
            if not os.path.exists(sdir):
                os.makedirs(sdir)

    async def on_message(self, message):
        if message.type == discord.MessageType.pins_add and message.author == self.user:
            return await message.delete()
        if message.author.bot and not message.webhook_id:
            return
        if self.user.mentioned_in(message):
            await message.channel.send(content="Hi, I'm Kyogre! I'm just a bot who's here to help!")
        await self.process_commands(message)

    async def process_commands(self, message):
        """Processes commands that are registered with the bot and it's groups.

        Without this being run in the main `on_message` event, commands will
        not be processed.
        """
        if message.content.startswith('!'):
            if message.content[1] == " ":
                message.content = message.content[0] + message.content[2:]
            content_array = message.content.split(' ')
            content_array[0] = content_array[0].lower()
            # Well that's *one* way to do it
            if content_array[0][1:] in ['r1', 'r2', 'r3', 'r4', 'r5', 'raid1', 'raid2', 'raid3', 'raid4', 'raid5']:
                content_array[0] = content_array[0][:-1] + " " + content_array[0][-1]
            message.content = ' '.join(content_array)

        ctx = await self.get_context(message, cls=Context)
        if not ctx.command:
            return
        await self.invoke(ctx)

    def get_guild_prefixes(self, guild, *, local_inject=_prefix_callable):
        proxy_msg = discord.Object(id=None)
        proxy_msg.guild = guild
        return local_inject(self, proxy_msg)

    async def make_request(self, data, request_type):
        async with self.session.post(url=f'http://localhost:{self.port}/v1/{request_type}', json=data) as response:
            result = await response.json()
        return result['output']

    async def update_remote_boss_list(self):
        async with self.session.get(url=f'http://localhost:{self.port}/v1/setup') as response:
            return await response.json()

    async def on_member_join(self, member):
        """Welcome message to the server and some basic instructions."""
        guild = member.guild
        self.user_logger.info(f"{member.name}#{member.discriminator} joined."
                              f" Account created {member.created_at}. ID: {member.id}")
        invite_tracking = self.guild_dict[guild.id]['configure_dict']\
            .get('invite_tracking', {'enabled': False, 'destination': None, 'invite_counts': {}})
        if invite_tracking['enabled']:
            await self._calculate_invite_used(member)
        team_msg = ' or '.join(['**!team {0}**'.format(team)
                               for team in self.config['team_dict'].keys()])
        if not self.guild_dict[guild.id]['configure_dict']['welcome']['enabled']:
            return
        # Build welcome message
        if self.guild_dict[guild.id]['configure_dict']['welcome'].get('welcomemsg', 'default') == "default":
            admin_message = ' If you have any questions just ask an admin.'
            welcomemessage = 'Welcome to {server}, {user}! '
            if self.guild_dict[guild.id]['configure_dict']['team']['enabled']:
                welcomemessage += 'Set your team by typing {team_command}.'.format(
                    team_command=team_msg)
            welcomemessage += admin_message
        else:
            welcomemessage = self.guild_dict[guild.id]['configure_dict']['welcome']['welcomemsg']

        if self.guild_dict[guild.id]['configure_dict']['welcome']['welcomechan'] == 'dm':
            send_to = member
        elif str(self.guild_dict[guild.id]['configure_dict']['welcome']['welcomechan']).isdigit():
            send_to = discord.utils.get(guild.text_channels, id=int(self.guild_dict[guild.id]['configure_dict']['welcome']['welcomechan']))
        else:
            send_to = discord.utils.get(guild.text_channels, name=self.guild_dict[guild.id]['configure_dict']['welcome']['welcomechan'])
        if send_to:
            if welcomemessage.startswith("[") and welcomemessage.endswith("]"):
                await send_to.send(embed=discord.Embed(colour=guild.me.colour, description=welcomemessage[1:-1].format(server=guild.name, user=member.mention)))
            else:
                await send_to.send(welcomemessage.format(server=guild.name, user=member.mention))
        else:
            return

    async def on_member_remove(self, member):
        self.user_logger.info(f"{member.name}#{member.discriminator} left."
                              f" Last joined: {member.joined_at}. ID: {member.id}"
                              f" Roles: {', '.join([r.name for r in member.roles])}")

    async def _calculate_invite_used(self, member):
        guild = member.guild
        t_guild_dict = copy.deepcopy(self.guild_dict)
        invite_dict = t_guild_dict[guild.id]['configure_dict']['invite_tracking']['invite_counts']
        all_invites = await guild.invites()
        messages = []
        invite_codes = []
        for inv in all_invites:
            if inv.code in invite_dict:
                count = invite_dict.get(inv.code, inv.uses)
                if inv.uses > count:
                    messages.append(f"Using invite code: {inv.code} for: {inv.channel} created by: {inv.inviter}")
                    invite_codes.append(inv.code)
            elif inv.uses == 1:
                messages.append(f"Using new invite code: {inv.code} for: {inv.channel} created by: {inv.inviter}")
                invite_codes.append(inv.code)
            invite_dict[inv.code] = inv.uses
        notify = '\n'.join(messages)
        self.user_logger.info(notify)
        destination = t_guild_dict[guild.id]['configure_dict']['invite_tracking'].get('destination', None)
        if destination and len(messages) > 0:
            try:
                await self.get_channel(destination).send(notify)
            except AttributeError:
                pass
        if len(invite_codes) > 0:
            invite_roles = (InviteRoleTable
                            .select(InviteRoleTable.role)
                            .where(InviteRoleTable.invite << invite_codes))
            role_ids = [int(i.role) for i in invite_roles]
            roles = [discord.utils.get(guild.roles, id=r) for r in role_ids]
            self.user_logger.info(f"{', '.join([role.name for role in roles])} role auto-assigned.")
            await member.add_roles(*roles)

        self.guild_dict[guild.id]['configure_dict']['invite_tracking']['invite_counts'] = invite_dict
        return

    async def on_guild_join(self, guild):
        owner = guild.owner
        self.guild_dict[guild.id] = {
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
        await owner.send("I'm Kyogre, a Discord helper bot for Pokemon Go communities, and someone has invited me to your server! Type **!help** to see a list of things I can do, and type **!configure** in any channel of your server to begin!")

    async def on_guild_remove(self, guild):
        try:
            if guild.id in self.guild_dict:
                try:
                    del self.guild_dict[guild.id]
                except KeyError:
                    pass
        except KeyError:
            pass

    async def on_member_update(self, before, after):
        if before.bot:
            return
        teams = ["instinct", "mystic", "valor"]
        guild = after.guild
        region_dict = self.guild_dict[guild.id]['configure_dict'].get('regions', None)
        trainers_info_dict = self.guild_dict[guild.id]['trainers'].setdefault('info', {}).setdefault(after.id, {})
        prev_roles = set([r.name for r in before.roles])
        post_roles = set([r.name for r in after.roles])
        added_roles = post_roles - prev_roles
        removed_roles = prev_roles - post_roles
        for role in added_roles:
            if role.lower() in teams:
                trainers_info_dict["team"] = role.capitalize()
                self.user_logger.info(f"{after.name} was assigned team {role}.")
                return
        for role in removed_roles:
            if role.lower() in teams:
                trainers_info_dict["team"] = None
                self.user_logger.info(f"{after.name} team assignment cleared. Previous team role: {role}.")
                return
        if region_dict:
            notify_channel = region_dict.get('notify_channel', None)
            if notify_channel is not None:
                regioninfo_dict = region_dict.get('info', None)
                if regioninfo_dict:
                    notify = None
                    if len(added_roles) > 0:
                        # a single member update event should only ever have 1 role change
                        role = list(added_roles)[0]
                        if role in regioninfo_dict.keys():
                            self.user_logger.info(f"{after.name} was assigned {role} region role.")
                            return await self.get_channel(notify_channel).send(f"{after.mention} you have joined the {role.capitalize()} region.", delete_after=8)
                    if len(removed_roles) > 0:
                        # a single member update event should only ever have 1 role change
                        role = list(removed_roles)[0]
                        if role in regioninfo_dict.keys():
                            self.user_logger.info(f"{role} region role removed from {after.name}.")
                            return await self.get_channel(notify_channel).send(f"{after.mention} you have left the {role.capitalize()} region.", delete_after=8)

    async def on_message_delete(self, message):
        guild = message.guild
        channel = message.channel
        author = message.author
        if not channel or not guild:
            return
        if channel.id in self.guild_dict[guild.id]['raidchannel_dict'] and self.guild_dict[guild.id]['configure_dict']['archive']['enabled']:
            if message.content.strip() == "!archive":
                self.guild_dict[guild.id]['raidchannel_dict'][channel.id]['archive'] = True
            if self.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('archive', False):
                logs = self.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('logs', {})
                logs[message.id] = {'author_id': author.id, 'author_str': str(author),'author_avy':author.avatar_url,'author_nick':author.nick,'color_int':author.color.value,'content': message.clean_content,'created_at':message.created_at}
                self.guild_dict[guild.id]['raidchannel_dict'][channel.id]['logs'] = logs

    async def update_subs_leaderboard(self):
        await self.wait_until_ready()
        sleep_time = 3600
        while not self.is_closed():
            guilddict_chtemp = copy.deepcopy(self.guild_dict)
            # for every server in save data
            for guildid in guilddict_chtemp.keys():
                if guildid in self.util_servers:
                    continue
                self.logger.info(f"Updating subscription leaderboard for guild with id: {guildid}")
                guild = self.get_guild(guildid)
                message_id = guilddict_chtemp[guildid]['configure_dict'].get('subscriptions', {}).get(
                    'leaderboard_message', 0)
                channel_id = guilddict_chtemp[guildid]['configure_dict'].get('subscriptions', {}).get(
                    'leaderboard_channel', None)
                if channel_id is not None:
                    channel = guild.get_channel(channel_id)
                    message = None
                    try:
                        message = await channel.fetch_message(message_id)
                    except discord.errors.NotFound:
                        self.logger.info(f"Could not find previous leaderboard message with id: {message_id}")
                    try:
                        faves_cog = self.cogs.get('Faves')
                        content = await faves_cog.build_top_sub_lists(guild)
                        if message is None:
                            new_msg = await channel.send(content)
                            guilddict_chtemp[guildid]['configure_dict']['subscriptions']['leaderboard_message'] = new_msg.id
                        else:
                            await message.edit(content=content)
                        self.logger.info("Subscription leaderboard update complete.")
                    except (AttributeError, Exception) as e:
                        self.logger.info(f"Failed to update top subs leaderboard with error: {e}")
                # this is a bug. sleep time is stored per guild but the sleep and do work loop is for all guilds
                # should spawn separate loops per guild but that's low-pri until there is actually an instance
                # running on multiple guilds.
                sleep_time = guilddict_chtemp[guildid]['configure_dict'].get('subscriptions', {}).get(
                    'leaderboard_refresh_seconds', 3600)
            self.guild_dict = guilddict_chtemp

            await asyncio.sleep(sleep_time)
