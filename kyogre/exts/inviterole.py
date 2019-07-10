import asyncio
import functools
import re

import discord
from discord.ext import commands

import peewee

from kyogre import utils, checks
from kyogre.exts.db.kyogredb import *


class InviteRoleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="inviterole", aliases=["ir"])
    @commands.has_permissions(manage_roles=True)
    async def inviterole(self, ctx):
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()
    
    @inviterole.command(name='add', aliases=['create'])
    @commands.has_permissions(manage_roles=True)
    async def _add(self, ctx, *, info):
        info = re.split(r'\s*,\s*', info)
        invite_code = info[0]
        role_id = info[1]
        check_invite = await self._validate_invite_code(ctx, invite_code)
        if not check_invite[0]:
            return await utils.sleep_and_cleanup([check_invite[1]], 10)
        invite = check_invite[0]
        check_role = await self._validate_role(ctx, role_id)
        if not check_role[0]:
            return await utils.sleep_and_cleanup([check_role[1]], 10)
        role = check_role[0]
        try:
            inviterole, __ = InviteRoleTable.get_or_create(guild=ctx.guild.id, invite=invite.code, role=role.id)
            if inviterole:
                message = f"Invite role assignment successfully created for invite code: **{invite_code}**.\nThe **{role.name}** role will be assigned."
                colour = discord.Colour.green()
                reaction = '✅'
            else:
                message = "Failed to create invite role assignment. Please try again."
                colour = discord.Colour.red()
                reaction = '❌'
        except peewee.IntegrityError:
            message = f"""An invite role assignment already exists for invite code: **{invite.code}**\n
                          Use the **!inviterole update** command to change its role assignment.
                          Or the **!inviterole delete** command to remove it before adding a new assignment."""
            colour = discord.Colour.red()
            reaction = '❌'
        await ctx.message.add_reaction(reaction)
        response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))
        return await utils.sleep_and_cleanup([response], 12)

    @inviterole.command(name='remove', aliases=['rm', 'rem', 'del', 'delete'])
    @commands.has_permissions(manage_roles=True)
    async def _remove(self, ctx, invite_code):
        invites = await ctx.guild.invites()
        check_invite = await self._validate_invite_code(ctx, invite_code)
        if not check_invite[0]:
            return await utils.sleep_and_cleanup([check_invite[1]], 10)
        invite = check_invite[0]
        query = InviteRoleTable.delete().where(InviteRoleTable.invite == invite_code)
        deleted = query.execute()
        if not deleted or deleted == 0:
            message = "No invite role assignments deleted. Please try again."
            colour = discord.Colour.red()
            reaction = '❌'
        else:
            message = f"Deleted {deleted} invite role assignment(s) successfully with invite code: **{invite_code}**."
            colour = discord.Colour.green()
            reaction = '✅'
        await ctx.message.add_reaction(reaction)
        response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))
        return await utils.sleep_and_cleanup([response], 12)

    @inviterole.command(name='update', aliases=['up', 'ud', 'change', 'ch'])
    @commands.has_permissions(manage_roles=True)
    async def _update(self, ctx, *, info):
        info = re.split(r'\s*,\s*', info)
        invite_code = info[0]
        role_id = info[1]
        check_invite = await self._validate_invite_code(ctx, invite_code)
        if not check_invite[0]:
            return await utils.sleep_and_cleanup([check_invite[1]], 10)
        invite = check_invite[0]
        check_role = await self._validate_role(ctx, role_id)
        if not check_role[0]:
            return await utils.sleep_and_cleanup([check_role[1]], 10)
        role = check_role[0]
        try:
            invite_role = InviteRoleTable.get(InviteRoleTable.invite == invite_code)
            invite_role.role = role.id
            invite_role.save()
            message = f"Invite role assignment successfully updated for invite code: **{invite_code}**.\nThe **{role.name}** role will now be assigned."
            colour = discord.Colour.green()
            reaction = '✅'
        except:
            message = "Failed to update invite role assignment. Please try again."
            colour = discord.Colour.red()
            reaction = '❌'
        finally:
            await ctx.message.add_reaction(reaction)
            response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))
            return await utils.sleep_and_cleanup([response], 12)

    @staticmethod
    async def _validate_invite_code(ctx, code):
        invites = await ctx.guild.invites()
        invite = discord.utils.get(invites, code=code)
        if not invite:
            await ctx.message.add_reaction('❌')
            no_invite = await ctx.channel.send(f"No valid invite found with code: {code}. Please try again.")
            return (None, no_invite)
        return (invite, None)

    @staticmethod
    async def _validate_role(ctx, role_id):
        try:
            role_id = int(role_id)
            role = discord.utils.get(ctx.guild.roles, id=role_id)
        except:
            role = discord.utils.get(ctx.guild.roles, name=role_id)
        if role is None:
            await ctx.message.add_reaction('❌')
            no_role = await ctx.channel.send(f"No valid role found with name or id: {role_id}. Please try again.")
            return (None, no_role)
        return (role, None)

def setup(bot):
    bot.add_cog(InviteRoleCog(bot))
