import re

import discord
from discord.ext import commands

from kyogre import checks, utils

class Utilities(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='embed')
    @checks.serverowner_or_permissions(manage_message=True)
    async def _embed(self, ctx, title, content=None, colour=None,
                     icon_url=None, image_url=None, thumbnail_url=None,
                     plain_msg=''):
        """Build and post an embed in the current channel.

        Note: Always use quotes to contain multiple words within one argument.
        """
        await ctx.embed(title=title, description=content, colour=colour,
                        icon=icon_url, image=image_url,
                        thumbnail=thumbnail_url, plain_msg=plain_msg)

    async def get_channel_by_name_or_id(self, ctx, item):
        channel = None
        if item.isdigit():
            channel = discord.utils.get(ctx.guild.text_channels, id=int(item))
        if not channel:
            item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
            item = item.replace(" ","-")
            name = await utils.letter_case(ctx.guild.text_channels, item.lower())
            channel = discord.utils.get(ctx.guild.text_channels, name=name)
        if channel:
            guild_channel_list = []
            for textchannel in ctx.guild.text_channels:
                guild_channel_list.append(textchannel.id)
            diff = set([channel.id]) - set(guild_channel_list)
        else:
            diff = True
        if diff:
            return None
        return channel

def setup(bot):
    bot.add_cog(Utilities(bot))
