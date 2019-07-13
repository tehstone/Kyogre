import asyncio
import copy
import json
import os
import pickle
import sys

from kyogre.logs import init_loggers
from kyogre.errors import custom_error_handling

import discord
from discord.ext import commands
from kyogre.context import Context
from kyogre.exts.db.kyogredb import InviteRoleTable


default_exts = ['admincommands',
                'configuration',
                'getcommands',
                'inviterole',
                'locationmanagement',
                'locationmatching',
                'misc',
                'pokemon',
                'pvp',
                'questrewardmanagement',
                'raiddatahandler',
                'regions',
                'setcommands',
                'silph',
                'social',
                'subscriptions',
                'trade',
                'tutorial',
                'utilities']

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
        custom_error_handling(self, self.logger)
        self.guild_dict = {}
        self._load_data()
        self.raid_json_path = self._load_config()
        self.active_raids = []
        self.active_wilds = []
        self.active_pvp = []
        self.active_lures = []

        for ext in default_exts:
            try:
                self.load_extension(f"kyogre.exts.{ext}")
            except Exception as e:
                print(f'**Error when loading extension {ext}:**\n{type(e).__name__}: {e}')
            else:
                if 'debug' in sys.argv[1:]:
                    print(f'Loaded {ext} extension.')

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
        # Set up message catalog access
        # Load raid info
        raid_path_source = os.path.join('data', 'raid_info.json')
        with open(raid_path_source, 'r') as fd:
            self.raid_info = json.load(fd)
        # Load type information
        with open(os.path.join('data', 'defense_chart.json'), 'r') as fd:
            self.defense_chart = json.load(fd)
        with open(os.path.join('data', 'type_list.json'), 'r') as fd:
            self.type_list = json.load(fd)
        return raid_path_source

    async def on_message(self, message):
        if message.type == discord.MessageType.pins_add and message.author == self.user:
            return await message.delete()
        if not message.author.bot:
            await self.process_commands(message)

    async def process_commands(self, message):
        """Processes commands that are registered with the bot and it's groups.

        Without this being run in the main `on_message` event, commands will
        not be processed.
        """
        if message.author.bot:
            return
        if message.content.startswith('!'):
            if message.content[1] == " ":
                message.content = message.content[0] + message.content[2:]
            content_array = message.content.split(' ')
            content_array[0] = content_array[0].lower()
            # Well that's *one* way to do it
            if content_array[0][1:] in ['r1','r2','r3','r4','r5','raid1','raid2','raid3','raid4','raid5']:
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

    async def on_member_join(self, member):
        """Welcome message to the server and some basic instructions."""
        guild = member.guild
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
        destination = t_guild_dict[guild.id]['configure_dict']['invite_tracking'].get('destination', None)
        if destination and len(messages) > 0:
            notify = '\n'.join(messages)
            try:
                await self.get_channel(destination).send(notify)
            except AttributeError:
                pass
        if len(invite_codes) > 0:
            invite_roles = (InviteRoleTable
                            .select(InviteRoleTable.role)
                            .where(InviteRoleTable.invite << invite_codes))
            role_ids = [i.role for i in invite_roles]
            roles = [discord.utils.get(guild.roles, id=r) for r in role_ids]
            await member.add_roles(*roles)

        self.guild_dict[guild.id]['configure_dict']['invite_tracking']['invite_counts'] = invite_dict
        return

    async def on_guild_join(self, guild):
        owner = guild.owner
        self.guild_dict[guild.id] = {
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
        guild = after.guild
        region_dict = self.guild_dict[guild.id]['configure_dict'].get('regions',None)
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
                            notify = await self.get_channel(notify_channel).send(f"{after.mention} you have joined the {role.capitalize()} region.", delete_after=8)
                    if len(removed_roles) > 0:
                        # a single member update event should only ever have 1 role change
                        role = list(removed_roles)[0]
                        if role in regioninfo_dict.keys():
                            notify = await self.get_channel(notify_channel).send(f"{after.mention} you have left the {role.capitalize()} region.", delete_after=8)

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
