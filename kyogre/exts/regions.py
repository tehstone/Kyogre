import re

import discord
from discord.ext import commands

from kyogre import checks


class Regions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_dict = bot.guild_dict

    @commands.group(name='region', aliases=['regions'], case_insensitive=True)
    @checks.allowregion()
    async def _region(self, ctx):
        """Handles user-region settings"""
        if ctx.invoked_subcommand is None:
            raise commands.BadArgument()

    @_region.command(name="join")
    async def join(self, ctx, *, region_names):
        """Joins regional roles from the provided comma-separated list

        Examples:
        !region join kanto
        !region join kanto, johto, hoenn"""
        message = ctx.message
        guild = message.guild
        channel = message.channel
        author = message.author
        response = ""
        region_info_dict = self.guild_dict[guild.id]['configure_dict']['regions']['info']
        enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
        requested_roles = set([r for r in re.split(r'\s*,\s*', region_names.lower().replace(" ", "")) if r])
        if not requested_roles:
            return await channel.send(self._user_region_list("join", author, enabled_roles))
        valid_requests = requested_roles & enabled_roles
        invalid_requests = requested_roles - enabled_roles
        role_objs = [discord.utils.get(guild.roles, name=role) for role in valid_requests]
        if role_objs:
            try:
                await author.add_roles(*role_objs, reason="user requested region role add via ")
                await message.add_reaction('✅')
                response += "Successfully joined "
            except:
                response += "Failed joining "
            response += f"{len(valid_requests)} roles:\n{', '.join(valid_requests)}"
        if invalid_requests:
            response += f"\n\n{len(invalid_requests)} invalid roles detected:\n{', '.join(invalid_requests)}\n\n"
            response += f"Acceptable regions are: {', '.join(enabled_roles)}"
        await channel.send(response, delete_after=20)

    @_region.command(name="leave")
    async def _leave(self, ctx, *, region_names: str = ''):
        """Leaves regional roles from the provided comma-separated list

        Examples:
        !region leave kanto
        !region leave kanto, johto, hoenn"""
        message = ctx.message
        guild = message.guild
        channel = message.channel
        author = message.author
        response = ""
        region_info_dict = self.guild_dict[guild.id]['configure_dict']['regions']['info']
        enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
        requested_roles = set([r for r in re.split(r'\s*,\s*', region_names.lower().strip()) if r])
        if not requested_roles:
            return await channel.send(self._user_region_list("leave", author, enabled_roles))
        valid_requests = requested_roles & enabled_roles
        invalid_requests = requested_roles - enabled_roles
        role_objs = [discord.utils.get(guild.roles, name=role) for role in valid_requests]
        if role_objs:
            try:
                await author.remove_roles(*role_objs, reason="user requested region role remove via ")
                await message.add_reaction('✅')
                response += "Successfully left "
            except:
                response += "Failed leaving "
            response += f"{len(valid_requests)} roles:\n{', '.join(valid_requests)}"
        if invalid_requests:
            response += f"\n\n{len(invalid_requests)} invalid roles detected:\n{', '.join(invalid_requests)}\n\n"
            response += f"Acceptable regions are: {', '.join(enabled_roles)}"
        await channel.send(response, delete_after=20)

    @staticmethod
    def _user_region_list(action, author, enabled_roles):
        roles = [r.name for r in author.roles]
        response = f"Please select one or more regions separated by commas `!region {action} renton, kent`\n\n"
        if action == "join":
            response += f" Regions available to join are: {', '.join(set(enabled_roles).difference(roles)) or 'N/A'}"
        else:
            response += f" Regions available to leave are: {', '.join(set(enabled_roles).intersection(roles)) or 'N/A'}"
        return response

    @_region.command(name="list")
    async def _list(self, ctx):
        """Lists the user's active region roles

        Usage: !region list"""
        message = ctx.message
        guild = message.guild
        channel = message.channel
        author = message.author
        region_info_dict = self.guild_dict[guild.id]['configure_dict']['regions']['info']
        enabled_roles = set([r.get('role', None) for r in region_info_dict.values()])
        user_roles = set([r.name for r in author.roles])
        active_roles = user_roles & enabled_roles
        response = f"You have {len(active_roles)} active region roles:\n{', '.join(active_roles)}"
        response += f" Regions available to join are: {', '.join(set(active_roles).difference(enabled_roles)) or 'N/A'}"
        await message.add_reaction('✅')
        await channel.send(response, delete_after=20)


def setup(bot):
    bot.add_cog(Regions(bot))
