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
            for attachment in message.attachments:
                file = await image_utils.image_pre_check(attachment)
                return await self.parse_ex_pass(ctx, file)

    async def parse_ex_pass(self, ctx, file):
        ex_info = await image_scan.check_gym_ex(file)
        if not ex_info['gym']:
            return await ctx.channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"Could not determine gym name from EX Pass screenshot."))
        region = None
        if ex_info['location']:
            location = ex_info['location'].split(',')
            all_regions = list(self.bot.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys())
            p_region = location[0].strip()
            if p_region in all_regions:
                region = p_region
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gyms = location_matching_cog.get_gyms(ctx.guild.id, [region])
            gym = await location_matching_cog.match_prompt(ctx.channel, ctx.author.id, ex_info['gym'], gyms)
        if ex_info['date']:
            date_split = ex_info['date'].split()
            month, day = date_split[0], date_split[0]
            month = month_map[month]
            date_key = str(month) + str(day)


def setup(bot):
    bot.add_cog(EXRaids(bot))
