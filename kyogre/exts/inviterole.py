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
        self.success_react = '✅'
        self.failed_react = '❌'

    @commands.group(name="inviterole", aliases=["ir"])
    @commands.has_permissions(manage_roles=True)
    async def inviterole(self, ctx):
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()
    
    @inviterole.command(name='add', aliases=['create'])
    @commands.has_permissions(manage_roles=True)
    async def _add(self, ctx, *, info):
        """**Usage**: `!inviterole/ir add <code> <role>`
        Sets a role to be assigned to users joining with the provided code
        Code must be the last part of a discord invite link
        role must be a role set up on the server."""
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("Please provide both an invite code and a role name.", delete_after=10)
        invite_code = info[0]
        role_id = info[1]
        invite = await self._validate_invite_code(ctx, invite_code)
        if not invite:
            return
        role = await self._validate_role(ctx, role_id)
        if not role:
            return
        try:
            inviterole, __ = InviteRoleTable.get_or_create(guild=ctx.guild.id, invite=invite.code, role=role.id)
            if inviterole:
                message = f"Invite role assignment successfully created for invite code: **{invite_code}**.\nThe **{role.name}** role will be assigned."
                colour = discord.Colour.green()
                reaction = self.success_react
            else:
                message = "Failed to create invite role assignment. Please try again."
                colour = discord.Colour.red()
                reaction = self.failed_react
        except peewee.IntegrityError:
            message = f"""An invite role assignment already exists for invite code: **{invite.code}**\n
                          Use the **!inviterole update** command to change its role assignment.
                          Or the **!inviterole delete** command to remove it before adding a new assignment."""
            colour = discord.Colour.red()
            reaction = self.failed_react
        await ctx.message.add_reaction(reaction)
        response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)

    @inviterole.command(name='remove', aliases=['rm', 'rem', 'del', 'delete'])
    @commands.has_permissions(manage_roles=True)
    async def _remove(self, ctx, invite_code):
        """**Usage**: `!inviterole/ir remove <code>`
        Deletes the role assignment for the code provided.
        Code must be the last part of a discord invite link."""
        invites = await ctx.guild.invites()
        invite = await self._validate_invite_code(ctx, invite_code)
        if not invite:
            return
        query = InviteRoleTable.delete().where(InviteRoleTable.invite == invite_code)
        deleted = query.execute()
        if not deleted or deleted == 0:
            message = "No invite role assignments deleted. Please try again."
            colour = discord.Colour.red()
            reaction = self.failed_react
        else:
            message = f"Deleted {deleted} invite role assignment(s) successfully with invite code: **{invite_code}**."
            colour = discord.Colour.green()
            reaction = self.success_react
        await ctx.message.add_reaction(reaction)
        response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))
        return await utils.sleep_and_cleanup([response], 12)

    @inviterole.command(name='update', aliases=['up', 'ud', 'change', 'ch'])
    @commands.has_permissions(manage_roles=True)
    async def _update(self, ctx, *, info):
        """**Usage**: `!inviterole/ir update/up <code> <role>`
        Updates the role assignment for the code provided
        Code must be the last part of a discord invite link.
        Role must be a role set up on the server."""
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("Please provide both an invite code and a role name.", delete_after=10)
        invite_code = info[0]
        role_id = info[1]
        invite = await self._validate_invite_code(ctx, invite_code)
        if not invite:
            return
        role = await self._validate_role(ctx, role_id)
        if not role:
            return
        try:
            invite_role = InviteRoleTable.get(InviteRoleTable.invite == invite_code)
            invite_role.role = role.id
            invite_role.save()
            message = f"Invite role assignment successfully updated for invite code: **{invite_code}**.\nThe **{role.name}** role will now be assigned."
            colour = discord.Colour.green()
            reaction = self.success_react
        except:
            message = "Failed to update invite role assignment. Please try again."
            colour = discord.Colour.red()
            reaction = self.failed_react
        finally:
            await ctx.message.add_reaction(reaction)
            response = await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))
            return await utils.sleep_and_cleanup([response], 12)

    @inviterole.command(name='list', aliases=['l', 'li'])
    @commands.has_permissions(manage_roles=True)
    async def _list(self, ctx):
        """**Usage**: `!inviterole/ir list`
        Lists all invite role assignments created."""
        invite_roles = (InviteRoleTable
                        .select(InviteRoleTable.invite,
                                InviteRoleTable.role)
                        .where(InviteRoleTable.guild_id == ctx.guild.id))
        inviterole_pairs = [f"<https://discord.gg/> {r.invite}   {discord.utils.get(ctx.guild.roles, id=r.role)}" for r in invite_roles]
        return await ctx.send("\n".join(inviterole_pairs))

    async def _validate_invite_code(self, ctx, code):
        invites = await ctx.guild.invites()
        invite = discord.utils.get(invites, code=code)
        if not invite:
            await ctx.message.add_reaction(self.failed_react)
            no_invite = await ctx.channel.send(f"No valid invite found with code: {code}. Please try again.", delete_after=10)
            return None
        return invite

    async def _validate_role(self, ctx, role_id):
        try:
            role_id = int(role_id)
            role = discord.utils.get(ctx.guild.roles, id=role_id)
        except:
            role = discord.utils.get(ctx.guild.roles, name=role_id)
        if role is None:
            await ctx.message.add_reaction(self.failed_react)
            no_role = await ctx.channel.send(f"No valid role found with name or id: {role_id}. Please try again.", delete_after=10)
            return None
        return role

def setup(bot):
    bot.add_cog(InviteRoleCog(bot))
