import asyncio
import re
import discord
from discord import PartialEmoji
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import *


class NestCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.nest_dict_default = {'listen_channels': [],
                                  }

    @commands.command(hidden=True, aliases=['anl'])
    @commands.has_permissions(manage_roles=True)
    async def add_nest_listen_channel(self, ctx, item):
        nl_channel = await self.channel_helper(ctx, item)
        if nl_channel is None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Channel not found: {item}.")
            await ctx.channel.send(f'Channel not found: {item}. Could not set nest listen channel', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        nest_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('nests', self.nest_dict_default)
        listen_channels = nest_dict.get('listen_channels', [])
        if nl_channel.id in listen_channels:
            await ctx.channel.send(f'Channel already in nest listen channel list', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        listen_channels.append(nl_channel.id)
        nest_dict['listen_channels'] = listen_channels
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['nests'] = nest_dict
        await ctx.channel.send(f'{nl_channel.mention} added to nest Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    async def channel_helper(self, ctx, item):
        utilities_cog = self.bot.cogs.get('Utilities')
        if not utilities_cog:
            await ctx.channel.send('Utilities module not found, command failed.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        channel = await utilities_cog.get_channel_by_name_or_id(ctx, item)
        if channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        return channel

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        ctx = await self.bot.get_context(message)
        guild = message.guild
        if not guild:
            return
        try:
            utilities_cog = self.bot.cogs.get('Utilities')
            if not utilities_cog.can_manage(guild.get_member(payload.user_id)):
                return
        except:
            pass
        react_user = guild.get_member(payload.user_id)
        if not utils.can_manage(react_user, self.bot.config):
            return
        nest_dict = self.bot.guild_dict[guild.id]['configure_dict']\
            .get('nests', self.nest_dict_default)
        if payload.channel_id not in nest_dict['listen_channels']:
            return
        if str(payload.emoji) == self.bot.success_react:
            try:
                target_user = ctx.guild.get_member(ctx.message.author.id)
            except AttributeError:
                return
            nests = self.bot.guild_dict[guild.id]['trainers'].setdefault('nests', {})\
                .setdefault(target_user.id, 0) + 1
            self.bot.guild_dict[guild.id]['trainers']['nests'][target_user.id] = nests


def setup(bot):
    bot.add_cog(NestCommands(bot))
