import asyncio
import re
import discord
from discord import PartialEmoji
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import *


class QuickBadge(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.thumbsup_react = '👍'
        self.quick_badge_dict_default = {'listen_channels': [],
                                         '40_listen_channels': [],
                                         '40_role': None,
                                         'pokenav_channel': 0,
                                         'badge_channel': 0,
                                         'badges': {}}

    @commands.command(hidden=True, aliases=['aqb'])
    @commands.has_permissions(manage_roles=True)
    async def add_quick_badge(self, ctx, badge: PartialEmoji, k_badge_id: int, p_badge_id: int):
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if len(quick_badge_dict['listen_channels']) < 1:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No quickbadge listen channel set.")
            await ctx.channel.send('No Quick-Badge listen channels set.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        quick_badge_dict['badges'][badge.id] = {}
        quick_badge_dict['badges'][badge.id]['kyogre'] = k_badge_id
        quick_badge_dict['badges'][badge.id]['pokenav'] = p_badge_id
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'Quick-Badge {badge} added for badge with ids: {k_badge_id}, {p_badge_id}.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(hidden=True, aliases=['afl'])
    @commands.has_permissions(manage_roles=True)
    async def add_forty_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Channel not found: {item}.")
            await ctx.channel.send(f'Channel not found: {item}. Could not set level 40 listen channel', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        listen_channels = quick_badge_dict.get('40_listen_channels', [])
        if qbl_channel.id in listen_channels:
            await ctx.channel.send(f'Channel already in level 40 listen channel list', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        listen_channels.append(qbl_channel.id)
        quick_badge_dict['40_listen_channels'] = listen_channels
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'{qbl_channel.mention} added to level 40 Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(hidden=True, aliases=['rfl'])
    @commands.has_permissions(manage_roles=True)
    async def remove_forty_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Channel not found: {item}.")
            await ctx.channel.send(f'Channel not found: {item}. Could not remove level 40 listen channel', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        listen_channels = quick_badge_dict.get('40_listen_channels', [])
        if qbl_channel.id in listen_channels:
            listen_channels.remove(qbl_channel.id)
            quick_badge_dict['40_listen_channels'] = listen_channels
            self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
            await ctx.channel.send(f'{qbl_channel.mention} removed from level 40 listen channels list.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.success_react)
        await ctx.channel.send(f'{qbl_channel.mention} not found in level 40 listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.failed_react)

    @commands.command(hidden=True, aliases=['sfl'])
    @commands.has_permissions(manage_roles=True)
    async def set_forty_role(self, ctx, role_id):
        role_id = utils.sanitize_name(role_id)
        try:
            role_id = int(role_id)
            role = discord.utils.get(ctx.guild.roles, id=role_id)
        except:
            role = discord.utils.get(ctx.guild.roles, name=role_id)
        if role is None:
            try:
                role = await ctx.guild.create_role(name=role_id, hoist=False, mentionable=True)
            except discord.errors.HTTPException:
                pass
            if role is None:
                await ctx.message.add_reaction(self.bot.failed_react)
                return await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), 
                    description=f"Unable to find or create role with name or id: **{role_id}**."), delete_after=10)
            await ctx.send(embed=discord.Embed(colour=discord.Colour.from_rgb(255, 255, 0), description=f"Created new role: **{role.name}**"), delete_after=10)
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        quick_badge_dict.setdefault('40_role', role.id)
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'Level 40 auto-assign role set to **{role.name}**.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(hidden=True, aliases=['aqbl', 'qbl'])
    @commands.has_permissions(manage_roles=True)
    async def add_quick_badge_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Channel not found: {item}.")
            await ctx.channel.send(f'Channel not found: {item}. Could not set quick badge listen channel', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        quick_badge_dict['listen_channels'].append(qbl_channel.id)
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
        await ctx.channel.send(f'{qbl_channel.mention} added to Quick-Badge Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(hidden=True, aliases=['rqbl', 'dbl'])
    @commands.has_permissions(manage_roles=True)
    async def remove_quick_badge_listen_channel(self, ctx, item):
        qbl_channel = await self.qblc_channel_helper(ctx, item)
        if qbl_channel is None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Channel not found: {item}.")
            await ctx.channel.send(f'Channel not found: {item}. Could not remove listen channel', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if qbl_channel.id in quick_badge_dict['listen_channels']:
            quick_badge_dict['listen_channels'].remove(qbl_channel.id)
            self.bot.guild_dict[ctx.guild.id]['configure_dict']['quick_badge'] = quick_badge_dict
            await ctx.channel.send(f'{qbl_channel.mention} removed from Quick-Badge Listen channels list.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.success_react)
        await ctx.channel.send(f'{qbl_channel.mention} not found in Quick-Badge Listen channels list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.failed_react)

    @commands.command(hidden=True, aliases=['qbp', 'sqbp'])
    @commands.has_permissions(manage_roles=True)
    async def set_pokenav_channel(self, ctx, *, info):
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Bot name or channel info missing: {info}.")
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
        return await ctx.message.add_reaction(self.bot.success_react)

    async def qblc_channel_helper(self, ctx, item):
        utilities_cog = self.bot.cogs.get('Utilities')
        if not utilities_cog:
            await ctx.channel.send('Utilities module not found, command failed.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        qbl_channel = await utilities_cog.get_channel_by_name_or_id(ctx, item)
        if qbl_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
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
        try:
            utilities_cog = self.bot.cogs.get('Utilities')
            if not utilities_cog.can_manage(guild.get_member(payload.user_id)):
                return
        except:
            pass
        quick_badge_dict = self.bot.guild_dict[guild.id]['configure_dict']\
            .get('quick_badge', self.quick_badge_dict_default)
        if quick_badge_dict['pokenav_channel'] == 0 \
            or (payload.channel_id not in quick_badge_dict['listen_channels']
                and payload.channel_id not in quick_badge_dict.get('40_listen_channels', [])):
            return
        if payload.emoji.id in quick_badge_dict['badges']:
            try:
                target_user = guild.get_member(message.author.id)
            except AttributeError:
                return
            k_badge_id = quick_badge_dict['badges'][payload.emoji.id]['kyogre']
            p_badge_id = quick_badge_dict['badges'][payload.emoji.id]['pokenav']
            send_channel = self.bot.get_channel(quick_badge_dict['pokenav_channel'])
            badge_cog = self.bot.cogs.get('Badges')
            badge_to_give = BadgeTable.get(BadgeTable.id == k_badge_id)

            react_user = guild.get_member(payload.user_id)
            if not checks.is_user_owner_check(self.bot.config, react_user):
                check_message_str = f"{react_user.mention} do you want to give badge " \
                                    f"{badge_to_give.name} to {message.author.name}?"
                badge_check = await channel.send(check_message_str)
                try:
                    timeout = False
                    res, reactuser = await utils.simple_ask(self.bot, badge_check, channel, react_user.id)
                except TypeError:
                    timeout = True
                await badge_check.delete()
                if timeout or res.emoji == self.bot.failed_react:
                    return

            reaction, embed = await badge_cog.try_grant_badge(badge_to_give, payload.guild_id,
                                                              message.author.id, k_badge_id)
            if reaction == self.bot.success_react:
                await send_channel.send(f"$gb {p_badge_id} {target_user.mention}")
            badge_channel = self.bot.get_channel(quick_badge_dict['badge_channel'])
            await badge_channel.send(embed=embed)
        elif str(payload.emoji) == self.thumbsup_react \
                and payload.channel_id in quick_badge_dict.get('40_listen_channels', []):
            try:
                target_user = guild.get_member(message.author.id)
            except AttributeError:
                return
            forty_role_id = self.bot.guild_dict[guild.id]['configure_dict']\
                .get('quick_badge', self.quick_badge_dict_default).get('40_role', None)
            if forty_role_id is None:
                return
            forty_role = discord.utils.get(guild.roles, id=forty_role_id)
            if forty_role is None:
                return
            await target_user.add_roles(*[forty_role])
            await asyncio.sleep(0.1)
            if forty_role in target_user.roles:
                await channel.send(f"{target_user.mention} has been verified as level 40!")


def setup(bot):
    bot.add_cog(QuickBadge(bot))
