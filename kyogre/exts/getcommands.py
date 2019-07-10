import functools
import textwrap

import discord
from discord.ext import commands


class GetCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='get', case_insensitive=True)
    @commands.has_permissions(manage_guild=True)
    async def _get(self, ctx):
        """Get a setting value"""
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()

    @_get.command()
    @commands.has_permissions(manage_guild=True)
    async def prefix(self, ctx):
        """Get server prefix."""
        prefix = self.bot.get_guild_prefixes(ctx.guild)
        await ctx.channel.send('Prefix for this server is: `{}`'.format(prefix))

    def _get_prefix(self, message):
        guild = message.guild
        try:
            prefix = self.bot.guild_dict[guild.id]['configure_dict']['settings']['prefix']
        except (KeyError, AttributeError):
            prefix = None
        if not prefix:
            prefix = self.bot.config['default_prefix']
        return commands.when_mentioned_or(prefix)(self.bot, message)

    @_get.command()
    @commands.has_permissions(manage_guild=True)
    async def perms(self, ctx, channel_id = None):
        """Show Kyogre's permissions for the guild and channel."""
        channel = discord.utils.get(ctx.bot.get_all_channels(), id=channel_id)
        guild = channel.guild if channel else ctx.guild
        channel = channel or ctx.channel
        guild_perms = guild.me.guild_permissions
        chan_perms = channel.permissions_for(guild.me)
        req_perms = discord.Permissions(268822608)

        embed = discord.Embed(colour=ctx.guild.me.colour)
        embed.set_author(name='Bot Permissions', icon_url="https://i.imgur.com/wzryVaS.png")

        wrap = functools.partial(textwrap.wrap, width=20)
        names = [wrap(channel.name), wrap(guild.name)]
        if channel.category:
            names.append(wrap(channel.category.name))
        name_len = max(len(n) for n in names)
        def same_len(txt):
            return '\n'.join(txt + ([' '] * (name_len-len(txt))))
        names = [same_len(n) for n in names]
        chan_msg = [f"**{names[0]}** \n{channel.id} \n"]
        guild_msg = [f"**{names[1]}** \n{guild.id} \n"]
        def perms_result(perms):
            data = []
            meet_req = perms >= req_perms
            result = "**PASS**" if meet_req else "**FAIL**"
            data.append(f"{result} - {perms.value} \n")
            true_perms = [k for k, v in dict(perms).items() if v is True]
            false_perms = [k for k, v in dict(perms).items() if v is False]
            req_perms_list = [k for k, v in dict(req_perms).items() if v is True]
            true_perms_str = '\n'.join(true_perms)
            if not meet_req:
                missing = '\n'.join([p for p in false_perms if p in req_perms_list])
                meet_req_result = "**MISSING**"
                data.append(f"{meet_req_result} \n{missing} \n")
            if true_perms_str:
                meet_req_result = "**ENABLED**"
                data.append(f"{meet_req_result} \n{true_perms_str} \n")
            return '\n'.join(data)
        guild_msg.append(perms_result(guild_perms))
        chan_msg.append(perms_result(chan_perms))
        embed.add_field(name='GUILD', value='\n'.join(guild_msg))
        if channel.category:
            cat_perms = channel.category.permissions_for(guild.me)
            cat_msg = [f"**{names[2]}** \n{channel.category.id} \n"]
            cat_msg.append(perms_result(cat_perms))
            embed.add_field(name='CATEGORY', value='\n'.join(cat_msg))
        embed.add_field(name='CHANNEL', value='\n'.join(chan_msg))

        try:
            await ctx.send(embed=embed)
        except discord.errors.Forbidden:
            # didn't have permissions to send a message with an embed
            try:
                msg = "I couldn't send an embed here, so I've sent you a DM"
                await ctx.send(msg)
            except discord.errors.Forbidden:
                # didn't have permissions to send a message at all
                pass
            await ctx.author.send(embed=embed)


def setup(bot):
    bot.add_cog(GetCommands(bot))