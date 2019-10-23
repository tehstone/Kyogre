import os
import time

from PIL import Image

import discord
from discord.ext import commands

from kyogre import image_scan, testident, utils, checks, image_utils
from kyogre.context import Context

month_map = {"January": 1,
             "February": 2,
             "March": 3,
             "April": 4,
             "May": 5,
             "June": 6,
             "July": 7,
             "August": 8,
             "September": 9,
             "October": 10,
             "November": 11,
             "December": 12}


class EXRaids(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self.bot.get_context(message, cls=Context)
        if len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None))\
                or message.author == self.bot.user:
            return
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']\
            .setdefault('ex_scan_listen_channels', [])
        if message.channel.id in listen_channels:
            await message.add_reaction('🤔')
            file = await image_utils.image_pre_check(message.attachments[0])
            gym, date_key, start_time = await self.parse_ex_pass(ctx, file)
            if not gym or not date_key:
                return await ctx.channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description=f"Could not determine gym name or pass date from EX Pass screenshot."))
            return await self._process_ex_request(ctx, gym, start_time, date_key)

    async def parse_ex_pass(self, ctx, file):
        ex_info = await image_scan.check_gym_ex(file)
        if not ex_info['gym']:
            return None, None, None
        region, gym, date_key, start_time = None, None, None, None
        if ex_info['location']:
            location = ex_info['location'].split(',')
            all_regions = list(self.bot.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys())
            p_region = location[0].strip().lower()
            if p_region in all_regions:
                region = [p_region]
            else:
                region = all_regions
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gyms = location_matching_cog.get_gyms(ctx.guild.id, region)
            gym = await location_matching_cog.match_prompt(ctx.channel, ctx.author.id, ex_info['gym'], gyms)
        if ex_info['date']:
            date_split = ex_info['date'].split()
            month, day = date_split[0], date_split[0]
            month = month_map[month]
            date_key = f"{str(month)}_{str(day)}"
            start_time = date_split[2]
        return gym, date_key, start_time

    async def _process_ex_request(self, ctx, gym, start_time, date_key):
        category_id = await self._get_or_create_category(ctx, date_key)
        category = ctx.guild.get_channel(category_id)
        ex_channel = await self._create_ex_channel(ctx, gym, start_time, category)
        date_str = date_key.replace('_', ' ')
        report_message_text = f"EX Raid at {gym.name} on {date_str} starting at {time}.\n" \
                              f"If you have an invite to this raid, RSVP in: {ex_channel.mention}"
        report_message = await ex_channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                   description=report_message_text))
        ex_dict = self.bot.guild_dict[ctx.guild.id]['exchannel_dict'][category_id]['channels']
        ex_raid_dict = {
            "hatch": None,
            "expire": None,
            "type": "exraid",
            "level": "exraid",
            "pokemon": None,
            "gym": gym.id,
            "report_channel": ctx.channel,
            "report_message": report_message.id,
            "channel_message": None,
            "trainer_dict": {},
        }
        ex_dict[ex_channel.id] = ex_raid_dict

    async def _get_or_create_category(self, ctx, date_key):
        ex_dict = self.bot.guild_dict[ctx.guild.id].setdefault('exchannel_dict', {})
        categories = ex_dict.keys()
        for cat in categories:
            if date_key == ex_dict[cat]['date_key']:
                return cat
        name = date_key.replace('_', ' ')
        category = await ctx.guild.create_category(f"{name} EX Raids")
        ex_dict[category.id] = {'date_key': date_key, 'channels': {}}
        return category.id

    async def _create_ex_channel(self, ctx, gym, start_time, cat):
        channel_overwrite_dict = ctx.channel.overwrites
        kyogre_overwrite = {
            self.bot.user: discord.PermissionOverwrite(send_messages=True, read_messages=True, manage_roles=True,
                                                       manage_channels=True, manage_messages=True, add_reactions=True,
                                                       external_emojis=True, read_message_history=True,
                                                       embed_links=True, mention_everyone=True, attach_files=True)}
        channel_overwrite_dict.update(kyogre_overwrite)
        name = start_time.replace(':', '')
        name = utils.sanitize_name(name + gym.name)[:36]
        return await ctx.guild.create_text_channel(name, overwrites=channel_overwrite_dict, category=cat)

def setup(bot):
    bot.add_cog(EXRaids(bot))
