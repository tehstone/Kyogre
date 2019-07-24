import asyncio
import re

import discord
from discord.ext import commands

import peewee

from kyogre import utils, checks
from kyogre.exts.db.kyogredb import EventTable, GuildTable

class EventCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.failed_react = '❌'
        self.success_react = '✅'

    @commands.command(name='checkin', aliases=['ch', 'ci'], case_insensitive=True)
    @commands.has_permissions(manage_roles=True)
    async def _checkin(self, ctx, member: discord.Member):
        result = (EventTable.select(EventTable.eventname,
                                    EventTable.role)
                            .where((EventTable.active == True) &
                                   (EventTable.guild_id == member.guild.id)))
        roles = [r.role for r in result]
        events = [r.eventname for r in result]
        if len(roles) < 1:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("There is no active event.", delete_after=10)
        if len(roles) > 1:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("There are too many active events, please contact an admin.", delete_after=10)
        try:
            role = await self._validate_or_create_role(ctx, roles[0], eventname=events[0], checkin=True)
            if role is None:
                return
            await member.add_roles(*[role])
            await asyncio.sleep(0.1)
            if role not in member.roles:
                await ctx.message.add_reaction(self.failed_react)
                return await ctx.send(f"Failed to give event role to {member.display_name}.", delete_after=10)
        except discord.Forbidden:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send(f"Failed to give event role to to {member.display_name} because you do not have permission", delete_after=10)
        message = f"Checked in **{member.display_name}** for the **{events[0]}** event!"
        await ctx.send(embed=discord.Embed(colour=discord.Colour.green(), description=message), delete_after=10)
        await ctx.message.add_reaction(self.success_react)

    @commands.group(name='event', aliases=['ev', 'evt'], case_insensitive=True)
    @commands.has_permissions(manage_roles=True)
    async def _event(self, ctx):
        """Manage events"""
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()

    @_event.command(name='create', aliases=['add', 'c', 'a', 'new'], case_insensitive=True)
    async def _create(self, ctx, *, info):
        info = re.split(r',\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("Please provide both an invite code and a role name.", delete_after=10)
        name = info[0]
        role = await self._validate_or_create_role(ctx, info[1])
        if not role:
            return
        try:
            event, __ = EventTable.get_or_create(guild=ctx.guild.id, eventname=name, active=False, role=role.id)
            if event:
                message = f"Event **{name}** successfully created with role: **{role.name}**."
                colour = discord.Colour.green()
                reaction = self.success_react
            else:
                message = "Failed to create event. Please try again."
                colour = discord.Colour.red()
                reaction = self.failed_react
        except peewee.IntegrityError:
            message = "An event already exists by that name."
            colour = discord.Colour.red()
            reaction = self.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message), delete_after=10)
    
    @_event.command(name='updatename', aliases=['rename', 'rn', 'un', 'cn'], case_insensitive=True)
    async def _updatename(self, ctx, *, info):
        info = re.split(r',\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("Please provide both the current event name and a new event name.", delete_after=10)
        oldname = info[0]
        newname = info[1]
        updated = EventTable.update(eventname=newname).where(EventTable.eventname==oldname).execute()
        if updated == 0:
            message = "No event found by that name."
            colour = discord.Colour.red()
            reaction = self.failed_react
        elif updated == 1:
            message = f"Successfully renamed **{oldname}** to **{newname}**."
            colour = discord.Colour.green()
            reaction = self.success_react
        else:
            message = "Something went wrong."
            colour = discord.Colour.red()
            reaction = self.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message), delete_after=10)

    @_event.command(name='updaterole', aliases=['ur', 'cr'], case_insensitive=True)
    async def _updaterole(self, ctx, *, info):
        info = re.split(r',\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("Please provide both a valid event name and the new role name.", delete_after=10)
        name = info[0]
        role = await self._validate_or_create_role(ctx, info[1])
        if not role:
            return
        updated = EventTable.update(role=role.id).where(EventTable.eventname==name).execute()
        if updated == 0:
            message = "No event found by that name."
            colour = discord.Colour.red()
            reaction = self.failed_react
        elif updated == 1:
            message = f"Successfully changed role for **{name}**."
            colour = discord.Colour.green()
            reaction = self.success_react
        else:
            message = "Something went wrong."
            colour = discord.Colour.red()
            reaction = self.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message), delete_after=10)

    @_event.command(name='set_active', aliases=['set', 'sa'], case_insensitive=True)
    async def _set_active(self, ctx, *, name):
        count = EventTable.update(active=True).where(EventTable.eventname == name).execute()
        if count == 1:
            EventTable.update(active=False).where(EventTable.eventname != name).execute()
            message = f"Successfully set active event to **{name}**"
            colour = discord.Colour.green()
            reaction = self.success_react
        elif count == 0:
            message = "No event found by that name."
            colour = discord.Colour.red()
            reaction = self.failed_react
        else:
            EventTable.update(active=False).execute()
            message = "Something went wrong, all events are now inactive."
            colour = discord.Colour.red()
            reaction = self.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message), delete_after=10)

    async def _validate_or_create_role(self, ctx, role_id, eventname='', checkin=False):
        try:
            role_id = int(role_id)
            role = discord.utils.get(ctx.guild.roles, id=role_id)
        except:
            role = discord.utils.get(ctx.guild.roles, name=role_id)
        if role is None:
            try:
                if checkin:
                    role_id = "TempEventRole"
                role = await ctx.guild.create_role(name=role_id, hoist=False, mentionable=True)
            except discord.errors.HTTPException:
                pass
            if role is None:
                await ctx.message.add_reaction(self.failed_react)
                if checkin:
                    await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), 
                        description=f"Checkin failed, no role found with name: **{role_id}** and failed to create role."), delete_after=10)
                else:
                    await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), 
                        description=f"No valid role found with name or id: **{role_id}**. Failed to create role with that name."), delete_after=10)
                return None
            await ctx.invoke(self.bot.get_command('event updaterole'), info=f"{eventname}, {role.name}")
            await ctx.send(embed=discord.Embed(colour=discord.Colour.from_rgb(255, 255, 0), description=f"Created new role: **{role.name}**"), delete_after=10)
        return role

def setup(bot):
    bot.add_cog(EventCommands(bot))
