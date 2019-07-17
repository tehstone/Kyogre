import discord
from discord.ext import commands

from kyogre import checks


class MyHelpCommand(commands.DefaultHelpCommand):

    mappings = {"reportchannel": ["raid", "wild", "research", "lure"],
                "raidchannel": {}}

    def __init__(self, guild_dict):
        super().__init__()
        self.guild_dict = guild_dict

    async def send_bot_help(self, mapping):
        mapping_all = {}
        for cog in mapping:
            if cog is None:
                for com in mapping[None]:
                    #print("    " + com.qualified_name)
                    mapping_all[com.qualified_name] = com
            else:
                print(cog.__cog_name__)
                for com in cog.__cog_commands__:
                    #print("    " + com.qualified_name)
                    mapping_all[com.qualified_name] = com
        dest = self.get_destination()

        if checks.check_report(self.context):
            commands = self.mappings["reportchannel"]
            help_embed = embed=discord.Embed(colour=discord.Colour.orange(), description="**Help for Reporting Channels**")
            for com in commands:
                try:
                    command = mapping_all[com]
                    embed_value = f"\n**Command Aliases**: `{', '.join(command.aliases)}`\n{command.help}"
                    help_embed.add_field(name=f"**{command.brief}**", value=embed_value, inline=False)
                    #help_embed.add_field(name='\u200b', value='\u200b', inline=False)
                except KeyError:
                    print(com)
            return await dest.send(embed=help_embed)
        elif self.is_raid_channel(self.context.guild.id, self.context.channel.id):
            print("yes!")
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
        bot.help_command = MyHelpCommand(bot.guild_dict)
        bot.help_command.cog = self


    def cog_unload(self):
        self.bot.help_command = self._original_help_command


def setup(bot):
    bot.add_cog(HelpCommand(bot))
