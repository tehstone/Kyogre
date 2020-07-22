import asyncio
import re

import discord
from discord.ext import commands

from kyogre import checks, utils


class Utilities(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='embed')
    @checks.serverowner_or_permissions(manage_messages=True)
    async def _embed(self, ctx, title, content=None, colour=None,
                     icon_url=None, image_url=None, thumbnail_url=None,
                     plain_msg=''):
        """Build and post an embed in the current channel.

        Note: Always use quotes to contain multiple words within one argument.
        """
        await ctx.embed(title=title, description=content, colour=colour,
                        icon=icon_url, image=image_url,
                        thumbnail=thumbnail_url, plain_msg=plain_msg)

    @staticmethod
    async def get_channel_by_name_or_id(ctx, name):
        channel = None
        # If a channel mention is passed, it won't be recognized as an int but this get will succeed
        name = utils.sanitize_name(name)
        try:
            channel = discord.utils.get(ctx.guild.text_channels, id=int(name))
        except ValueError:
            pass
        if not channel:
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

    def create_gmaps_query(self, details, channel, type="raid"):
        """Given an arbitrary string, create a Google Maps
        query using the configured hints"""
        if type == "raid" or type == "egg":
            report = "raid"
        else:
            report = type
        if "/maps" in details and "http" in details:
            mapsindex = details.find('/maps')
            newlocindex = details.rfind('http', 0, mapsindex)
            if newlocindex == -1:
                return
            newlocend = details.find(' ', newlocindex)
            if newlocend == -1:
                newloc = details[newlocindex:]
                return newloc
            else:
                newloc = details[newlocindex:newlocend + 1]
                return newloc
        details_list = details.split()
        # look for lat/long coordinates in the location details. If provided,
        # then channel location hints are not needed in the  maps query
        if re.match(r'^\s*-?\d{1,2}\.?\d*,\s*-?\d{1,3}\.?\d*\s*$',
                    details):  # regex looks for lat/long in the format similar to 42.434546, -83.985195.
            return "https://www.google.com/maps/search/?api=1&query={0}".format('+'.join(details_list))
        loc_list = self.bot.guild_dict[channel.guild.id]['configure_dict'][report]['report_channels'][channel.id].split()
        return 'https://www.google.com/maps/search/?api=1&query={0}+{1}'.format('+'.join(details_list),
                                                                                '+'.join(loc_list))

    @staticmethod
    def create_waze_query(lat, long):
        return f'https://www.waze.com/ul?ll={lat}%2C{long}&navigate=yes&zoom=17'

    @staticmethod
    def create_applemaps_query(lat, long):
        return f'http://maps.apple.com/maps?daddr={lat},{long}'

    @staticmethod
    def create_simple_gmaps_query(lat, long):
        return f'https://www.google.com/maps/search/?api=1&query={lat},{long}'

    @staticmethod
    async def reaction_delay(message, reacts, delay=0.25):
        for r in reacts:
            await asyncio.sleep(delay)
            await message.add_reaction(r)

    def can_manage(self, user):
        if checks.is_user_dev_or_owner(self.bot.config, user.id):
            return True
        for role in user.roles:
            if role.permissions.manage_nicknames:
                return True
        return False

    def raid_channels_enabled(self, guild, channel):
        enabled = True
        regions = self.get_channel_regions(channel, 'raid')
        # TODO: modify this to accomodate multiple regions once necessary
        if regions and len(regions) > 0:
            enabled_dict = self.bot.guild_dict[guild.id]['configure_dict']['raid'].setdefault('raid_channels', {})
            enabled = enabled_dict.setdefault(regions[0], True)
        return enabled

    def get_channel_regions(self, channel, channel_type):
        regions = None
        config_dict = self.bot.guild_dict[channel.guild.id]['configure_dict']
        if config_dict.get(channel_type, {}).get('enabled', None):
            regions = config_dict.get(channel_type, {}).get('report_channels', {}).get(channel.id, None)
            if regions and not isinstance(regions, list):
                regions = [regions]
        if channel_type == "raid":
            cat_dict = config_dict.get(channel_type, {}).get('category_dict', {})
            for r in cat_dict:
                if cat_dict[r] == channel.category.id:
                    regions = [config_dict.get(channel_type, {}).get('report_channels', {}).get(r, None)]
        if regions is None:
            return []
        if len(regions) < 1:
            return []
        else:
            return list(set(regions))


def setup(bot):
    bot.add_cog(Utilities(bot))
