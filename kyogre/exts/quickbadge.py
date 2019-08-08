import re
import discord
from discord import PartialEmoji
from discord.ext import commands

from kyogre.exts.db.kyogredb import *


class QuickBadge(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.success_react = '✅'
        self.failed_react = '❌'
        self.quick_badge_dict_default = {'listen_channels': [],
                                         'pokenav_channel': 0,
                                         'badge_channel': 0,
                                         'badges': {}}

    @commands.command(hidden=True, aliases=['aqb'])
    @commands.has_permissions(manage_roles=True)
    async def add_quick_badge(self, ctx, badge: PartialEmoji, k_badge_id: int, p_badge_id: int):
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if len(quick_badge_dict['listen_channels']) < 1:
            await ctx.channel.send('No Quick-Badge listen channels set.', delete_after=10)
            return await ctx.message.add_reaction(self.failed_react)
        quick_badge_dict['badges'][badge.id] = {}
        quick_badge_dict['badges'][badge.id]['kyogre'] = k_badge_id
        quick_badge_dict['badges'][badge.id]['pokenav'] = p_badge_id
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'Quick-Badge {badge} added for badge with ids: {k_badge_id}, {p_badge_id}.', delete_after=10)
        return await ctx.message.add_reaction(self.success_react)

    @commands.command(hidden=True, aliases=['aqbl', 'qbl'])
    @commands.has_permissions(manage_roles=True)
    async def add_quick_badge_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            return
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        quick_badge_dict['listen_channels'].append(qbl_channel.id)
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'{qbl_channel.mention} added to Quick-Badge Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.success_react)

    @commands.command(hidden=True, aliases=['rqbl', 'dbl'])
    @commands.has_permissions(manage_roles=True)
    async def remove_quick_badge_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            return
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if qbl_channel.id in quick_badge_dict['listen_channels']:
            quick_badge_dict['listen_channels'].remove(qbl_channel.id)
            self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
            await ctx.channel.send(f'{qbl_channel.mention} removed from Quick-Badge Listen channels list.', delete_after=10)
            return await ctx.message.add_reaction(self.success_react)
        await ctx.channel.send(f'{qbl_channel.mention} not found in Quick-Badge Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.failed_react)

    @commands.command(hidden=True, aliases=['qbp', 'sqbp'])
    @commands.has_permissions(manage_roles=True)
    async def set_pokenav_channel(self, ctx, *, info):
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Please provide both a bot name and a channel name or id.", delete_after=15)
        bot_name = info[0].lower()
        qbl_channel = await self.qblc_channel_helper(ctx, ' '.join(info[1:]))
        if qbl_channel is None:
            return
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if bot_name == 'kyogre':
            quick_badge_dict['badge_channel'] = qbl_channel.id
        elif bot_name == 'pokenav':
            quick_badge_dict['pokenav_channel'] = qbl_channel.id
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f"{qbl_channel.mention} set as your guild's {bot_name.capitalize()} channel.",
                               delete_after=10)
        return await ctx.message.add_reaction(self.success_react)

    async def qblc_channel_helper(self, ctx, item):
        utilities_cog = self.bot.cogs.get('Utilities')
        if not utilities_cog:
            await ctx.channel.send('Utilities module not found, command failed.', delete_after=10)
            return await ctx.message.add_reaction(self.failed_react)
        qbl_channel = await utilities_cog.get_channel_by_name_or_id(ctx, item)
        if qbl_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.failed_react)
        return qbl_channel

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        if not guild:
            return
        quick_badge_dict = self.bot.guild_dict[guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if quick_badge_dict['pokenav_channel'] == 0 or payload.channel_id not in quick_badge_dict['listen_channels']:
            return
        
        if payload.emoji.id in quick_badge_dict['badges']:
            try:
                user = guild.get_member(message.author.id)
            except AttributeError:
                return
            k_badge_id = quick_badge_dict['badges'][payload.emoji.id]['kyogre']
            p_badge_id = quick_badge_dict['badges'][payload.emoji.id]['pokenav']
            send_channel = self.bot.get_channel(quick_badge_dict['pokenav_channel'])
            await send_channel.send(f"$gb {p_badge_id} {user.mention}")
            badge_cog = self.bot.cogs.get('Badges')
            badge_to_give = BadgeTable.get(BadgeTable.id == k_badge_id)
            reaction, embed = await badge_cog.try_grant_badge(badge_to_give, payload.guild_id,
                                                              payload.user_id, k_badge_id)
            badge_channel = self.bot.get_channel(quick_badge_dict['badge_channel'])
            await badge_channel.send(embed=embed)


def setup(bot):
    bot.add_cog(QuickBadge(bot))
