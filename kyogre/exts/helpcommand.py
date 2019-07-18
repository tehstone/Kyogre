import discord
from discord.ext import commands

from kyogre import checks


class MyHelpCommand(commands.DefaultHelpCommand):

    mappings = {"reportchannel": ["raid", "wild", "research", "lure"],
                "raidchannel": {"status": ["interested", "coming", "here"],
                                "time": ["starttime", "timerset"],
                                "other": ["list", "lobby", "starting"]
                                },
                "admin": []
                }

    def __init__(self, guild_dict):
        super().__init__()
        self.guild_dict = guild_dict
        self.avatar = None

    async def send_bot_help(self, mapping):
        mapping_all = {}
        for cog in mapping:
            if cog is None:
                for com in mapping[None]:
                    mapping_all[com.qualified_name] = com
            else:
                for com in cog.__cog_commands__:
                    mapping_all[com.qualified_name] = com
        dest = self.get_destination()

        if checks.check_report(self.context):
            commands = self.mappings["reportchannel"]
            help_embed = discord.Embed(colour=discord.Colour.orange(), description="**Help for Reporting Channels**")
            for com in commands:
                try:
                    command = mapping_all[com]
                    embed_value = f"\n**Command Aliases**: `{', '.join(command.aliases)}`\n{command.help}"
                    help_embed.add_field(name=f"**{command.brief}**", value=embed_value, inline=False)
                except KeyError:
                    print(com)
            return await dest.send(embed=help_embed)
        elif self.is_raid_channel(self.context.guild.id, self.context.channel.id):
            help_embed = discord.Embed(colour=discord.Colour.orange())
            if self.avatar is not None:
                help_embed.set_author(name="Help for Raid Channels", icon_url=self.avatar)
            else:
                help_embed.set_author(name="Help for Raid Channels")
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
            help_embed.set_footer(text="For more help, please contact a @helper")
            return await dest.send(embed=help_embed)
        elif checks.has_role(self.context, "Admin"):
            print("Is admin")
            return await super().send_bot_help(mapping)
        else:
            return await super().send_bot_help(mapping)


    def get_opening_note(self):
        note = "Use `{prefix}{command_name} [command]` for more info on a command.\n" \
             + "You can also use `{prefix}{command_name} [category]` for more info on a category."
        note += "\nPing a @helper, @OfficerJenny, or @Admin if you need more assistance"
        return note

    def get_command_signature(self, command):

        print(dir(command))
        return '{0.clean_prefix}{1.qualified_name} {1.signature}'.format(self, command)        

    def is_raid_channel(self, guild_id, channel_id):
        raid_channels = self.guild_dict[guild_id].get('raidchannel_dict',{}).keys()
        return channel_id in raid_channels


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
