import asyncio
import re
import discord
from discord import PartialEmoji
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import *


class Faves(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True, aliases=['tsq'])
    @commands.has_permissions(manage_roles=True)
    async def testsql(self, ctx):
        for sub_type in ['research', 'wild', 'pokemon']:
            result = (SubscriptionTable
                      .select(SubscriptionTable.target, fn.Count(SubscriptionTable.target).alias('count'))
                      .where(SubscriptionTable.type == sub_type)
                      .group_by(SubscriptionTable.target)
                      .order_by(SQL('count').desc())
                      .limit(10))
            result_str = f"**{sub_type}** subscriptions:\n"
            for r in result:
                result_str += f"target: {r.target}, count: {r.count}\n"
            await ctx.send(result_str)


def setup(bot):
    bot.add_cog(Faves(bot))
