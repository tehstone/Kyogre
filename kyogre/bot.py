import json
import os
import pickle
import sys

from kyogre.logs import init_loggers
from kyogre.errors import custom_error_handling

import discord
from discord.ext import commands
from kyogre.context import Context

default_exts = ['raiddatahandler', 'tutorial', 'silph', 'utilities',
                'pokemon', 'trade', 'locationmatching', 'inviterole',
                'admincommands', 'setcommands', 'getcommands']

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
        self.raid_path_source = self._load_config()

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

    async def process_commands(self, message):
        """Processes commands that are registed with the bot and it's groups.

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
