import discord
from discord.ext import commands

from kyogre import checks


class MyHelpCommand(commands.DefaultHelpCommand):

    mappings = {"reportchannel": ["raid", "wild", "research", "lure"],
                "raidchannel": {"status": ["interested", "coming", "here", "cancel"],
                                "time": ["starttime", "timerset"],
                                "other": ["list", "lobby", "starting", "backout", "shout", "weather", "counters"]
                                },
                "pvp": ["pvp available", "pvp add", "pvp remove"],
                "subscriptions": ["subscription list", "subscription add", "subscription remove"],
                "helper": [],
                "mod": ["mention_toggle", "addjoin", "inviterole add", "inviterole update", 
                "inviterole remove", "inviterole list"],
                "server_admin": ["announce", "grantroles", "ungrantroles"],
                "bot_admin": ["configure", "save", "exit", "restart", "welcome", "outputlog"],
                "debug": ["outputlog"]
                }

    def __init__(self, guild_dict):
        super().__init__()
        self.guild_dict = guild_dict
        self.avatar = None

    @staticmethod
    def _build_all_mapping(mapping):
        mapping_all = {}
        for cog in mapping:
            if cog is None:
                for com in mapping[None]:
                    mapping_all[com.qualified_name] = com
            else:
                for com in cog.__cog_commands__:
                    mapping_all[com.qualified_name] = com
        return mapping_all

    async def send_bot_help(self, mapping):
        mapping_all = self._build_all_mapping(mapping)
        dest = self.get_destination()
        help_embeds = []
        if checks.check_report(self.context):
            commands = self.mappings["reportchannel"]
            help_embed = self._basic_embed_setup("Help for Reporting Channels")
            for com in commands:
                try:
                    command = mapping_all[com]
                    embed_value = f"\n**Command Aliases**: `{', '.join(command.aliases)}`\n{command.help}"
                    help_embed.add_field(name=f"**{command.brief}**", value=embed_value, inline=False)
                except KeyError:
                    print(com)
            help_embed.set_footer(text=self.get_closing_note())
            return await dest.send(embed=help_embed)
        elif checks.check_raidchannel(self.context):
            help_embed = self._basic_embed_setup("Help for Raid Channels")
            status_val = "`!interested/coming/here/i/c/h`\nCan optionally include total party size and team counts:\n" \
                         "`!i 2` or `!i 3 1m 1v 1i`"
            help_embed.add_field(name="RSVP Commands", value=status_val)
            time_val = "`!timerset/ts <minutes>` to set the hatch/expire time\n" \
                       "`!starttime/st <minutes>` to set the time your group will start"
            help_embed.add_field(name="Time Commands", value=time_val)
            lobby_val = "`!list` to view all RSVPs\n`!starting/s` to start a lobby\n`!lobby` to join a lobby" \
                        "once it's started."
            help_embed.add_field(name="Raid Lobby Commands", value=lobby_val)
            other_val = "`!counters` to view information about the best counters for the raid boss\n" \
                        "`!weather <weathertype>` to set the current weather. Must be one of:\n" \
                        "`clear, sunny, rainy, partlycloudy, cloudy, windy, snow, fog`\n"
            help_embed.add_field(name="Other Commands", value=other_val)
            help_embed.set_footer(text=self.get_closing_note())
            return await dest.send(embed=help_embed)
        elif checks.check_subscriptionchannel(self.context):
            return await dest.send(embed=self._generate_subscription_help(mapping_all))
        elif checks.check_pvpchannel(self.context):
            return await dest.send(embed=self._generate_pvp_help(mapping_all))
        for role in self.context.author.roles:
            if role.name == "Dev":
                help_embeds.append(self._create_mapping_embed(mapping_all, "bot_admin"))
            if role.name == "Admin":
                help_embeds.append(self._create_mapping_embed(mapping_all, "server_admin"))
            if role.name == "OfficerJenny" or role.name == "Admin":
                help_embeds.append(self._create_mapping_embed(mapping_all, "mod"))
            if role.name == "helper" or role.name == "OfficerJenny" or role.name == "Admin":
                pass
        if len(help_embeds) > 0:
            for embed in help_embeds:
                await dest.send(embed=embed)
            return
        else:
            return await super().send_bot_help(mapping)

    async def send_command_help(self, command):
        dest = self.get_destination()
        help_embed = None
        for com_set in self.mappings["raidchannel"]:
            if command.name in self.mappings["raidchannel"][com_set]:
                help_embed = self._generate_command_help(command)
                return await dest.send(embed=help_embed)
        if command.qualified_name in self.mappings["pvp"] or command.qualified_name in self.mappings["subscriptions"]:
            help_embed = self._generate_command_help(command)
            return await dest.send(embed=help_embed)

        return await super().send_command_help(command)

    def _generate_command_help(self, command):
        help_embed = self._basic_embed_setup(f"Help for {command.qualified_name}")
        help_embed = discord.Embed(colour=discord.Colour.orange())
        help_embed.description = command.help
        help_embed.set_footer(text=self.get_closing_note(short=True))
        return help_embed

    def _generate_subscription_help(self, mapping):
        description = "To start a guided subscription management session,\nsimply use `!sub`\n\n"
        description += "**View all current subscriptions**:\n`!sub list`\n\n"
        description += "**Add a subscription**: `!sub add <type> <target>`\n"
        description += "**Example**: `!sub add raid Machamp`\n\n"
        description += "**Remove a subscription**: `!sub rem <type> <target>`\n"
        description += "**Example**: `!sub rem raid Machamp`\n\n"
        description += "**Remove all subscriptions of a type**: `!sub rem <type> all`\n"
        description += "**Remove all subscriptions**: `!sub rem all all`\n\n"
        description += "**Available types are**:\n"
        description += "pokemon, raid, research, wild, gym, item, lure"
        help_embed = self._basic_embed_setup("Help for Subscriptions")
        help_embed.description = description
        return help_embed

    def _generate_pvp_help(self, mapping):
        help_embed = self._basic_embed_setup(f"Help for PvP")
        for com in mapping:
            if com.startswith("pvp "):
                try:
                    command = mapping[com]
                    if len(command.aliases) > 0:
                        embed_value = f"\n**Command Aliases**: `{', '.join(command.aliases)}`\n{command.help}"
                    else: embed_value = f"{command.help}"
                    help_embed.add_field(name=f"**{command.brief}**", value=embed_value, inline=False)
                except KeyError:
                    print(com)
        return help_embed

    def _create_mapping_embed(self, mapping, item):
        help_embed = self._basic_embed_setup(f"Help for {item}s")
        for com in self.mappings[item]:
            try:
                command = mapping[com]
                help_embed.add_field(name=f"**{command.qualified_name}**", value=command.help, inline=False)
            except KeyError:
                print(com)
        return help_embed

    def _basic_embed_setup(self, title):
        help_embed = discord.Embed(colour=discord.Colour.orange())
        if self.avatar is not None:
            help_embed.set_author(name=f"{title}", icon_url=self.avatar)
        else:
            help_embed.set_author(name=f"{title}")
        return help_embed

    def get_closing_note(self, short=False):
        note = "Ping a @helper, @OfficerJenny, or @Admin if you need more assistance"
        if not short:
            note = f'Use "{self.clean_prefix}help [command]" for more info on a command. ' + note
        return note

    def get_command_signature(self, command):
        return '{0.clean_prefix}{1.qualified_name} {1.signature}'.format(self, command)


class HelpCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        self.user = bot.user
        self.help_command = bot.help_command = MyHelpCommand(bot.guild_dict)
        bot.help_command.cog = self

    def set_avatar(self, avatar):
        self.help_command.avatar = avatar

    def cog_unload(self):
        self.bot.help_command = self._original_help_command


def setup(bot):
    bot.add_cog(HelpCommand(bot))
