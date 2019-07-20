import discord
from discord.ext import commands

import peewee

from kyogre.exts.db.kyogredb import *


class Badge:
    def __init__(self, id, name, description, emoji, active):
        self.id = id
        self.name = name
        self.description = description
        self.emoji = emoji
        self.active = active
    

class Badges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='badge', aliases=['bg'])
    @commands.has_permissions(manage_roles=True)
    async def _badge(self, ctx):
        if ctx.invoked_subcommand is None:
            raise commands.BadArgument()

    @_badge.command(name='add', aliases=['create', 'cr', 'new'])
    @commands.has_permissions(manage_roles=True)
    async def _add(self, ctx, *, info):
        info = re.split(r',\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Must provide at least an emoji and badge name, and optionally badge description.",
                                  delete_after=10)
        converter = commands.PartialEmojiConverter()
        try:
            badge_emoji = await converter.convert(ctx, info[0])
        except:
            badge_emoji = None
        if not badge_emoji:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Could not find that emoji.", delete_after=10)
        badge_name = info[1]
        badge_desc = ''
        if len(info) > 2:
            badge_desc = info[2]
        try:
            new_badge, __ = BadgeTable.get_or_create(name=badge_name, description=badge_desc,
                                                     emoji=badge_emoji.id, active=True)
            if new_badge:
                send_emoji = self.bot.get_emoji(badge_emoji.id)
                message = f"{send_emoji} {badge_name} (#{new_badge.id}) successfully created!"
                colour = discord.Colour.green()
                reaction = self.bot.success_react
            else:
                message = "Failed to create badge. Please try again."
                colour = discord.Colour.red()
                reaction = self.bot.failed_react
        except peewee.IntegrityError:
            message = f"""A badge already exists with the same name, description, and emoji."""
            colour = discord.Colour.red()
            reaction = self.bot.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)

    @commands.command(name='grant_badge', aliases=['give', 'gb'])
    @commands.has_permissions(manage_roles=True)
    async def _grant_badge(self, ctx, badge_id: int = 0, *, member):
        """**Usage**: `!grant_badge/give/gb <badge_id> <member>`
        Gives the provided badge to the provided user."""
        converter = commands.MemberConverter()
        try:
            member = await converter.convert(ctx, member)
        except:
            member = None
        if badge_id == 0 or member is None:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Must provide a badge id and Trainer name.", delete_after=10)
        badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        if badge_to_give:
            try:
                guild_obj, __ = GuildTable.get_or_create(snowflake=ctx.guild.id)
                trainer_obj, __ = TrainerTable.get_or_create(snowflake=member.id, guild=ctx.guild.id)
                new_badge, __ = BadgeAssignmentTable.get_or_create(trainer=member.id, badge=badge_id)
                if new_badge:
                    send_emoji = self.bot.get_emoji(badge_to_give.emoji)
                    message = f"{member.display_name} has been given {send_emoji} **{badge_to_give.name}**!"
                    colour = discord.Colour.green()
                    reaction = self.bot.success_react
                else:
                    message = "Failed to give badge. Please try again."
            except peewee.IntegrityError:
                message = f"{member.display_name} already has the **{badge_to_give.name}** badge!"
        else:
            message = "Could not find a badge with that name."
        await ctx.message.add_reaction(reaction)
        await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)

    @commands.command(name='grant_to_role', aliases=['givetr', 'gbtr'])
    @commands.has_permissions(manage_roles=True)
    async def _grant_to_role(self, ctx, badge_id: int = 0, *, role):
        """**Usage**: `!grant_to_role/givetr/gbtr <badge_id> <rolename>`
        Gives the provided badge to all users assigned to the provided role."""
        converter = commands.RoleConverter()
        try:
            role = await converter.convert(ctx, role)
        except:
            role = None
        if badge_id == 0 or role is None:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Must provide a badge id and Role name.", delete_after=10)
        badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
        if badge_to_give:
            try:
                trainer_ids = []
                errored = []
                guild_obj, __ = GuildTable.get_or_create(snowflake=ctx.guild.id)
                for trainer in role.members:
                    try:
                        trainer_obj, __ = TrainerTable.get_or_create(snowflake=trainer.id, guild=ctx.guild.id)
                        trainer_ids.append((badge_to_give.id, trainer_obj.snowflake))
                    except:
                        errored.append(trainer.id)
                with KyogreDB._db.atomic():
                    BadgeAssignmentTable.insert_many(trainer_ids,
                                                     fields=[BadgeAssignmentTable.badge_id,
                                                             BadgeAssignmentTable.trainer]).execute()
                message = f"Could not assign the badge to: {', '.join(errored)}"
            except:
                await ctx.message.add_reaction(self.bot.failed_react)
                return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                           description="Completely failed"), delete_after=12)
            if len(errored) > 0:
                colour = discord.Colour.from_rgb(255, 255, 0)
                await ctx.message.add_reaction(self.bot.failed_react)
                await ctx.message.add_reaction(self.bot.success_react)
                return await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)
            colour = discord.Colour.green()
            message = "Successfully granted badge."
            await ctx.message.add_reaction(self.bot.success_react)
            return await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)

    @commands.command(name="available_badges", aliases=['avb'])
    async def _available(self, ctx):
        """**Usage**: `!available_badges/avb`
        Lists all badges that are currently available."""
        result = (BadgeTable
                  .select(BadgeTable.id,
                          BadgeTable.name,
                          BadgeTable.description,
                          BadgeTable.emoji,
                          BadgeTable.active))
        result = result.objects(Badge)
        result = [r for r in result if r.active]
        embed = discord.Embed(title="Badges currently available", colour=discord.Colour.purple())
        for r in result:
            send_emoji = self.bot.get_emoji(r.emoji)
            name = f"{send_emoji} {r.name} (#{r.id})"
            embed.add_field(name=name, value=f"     {r.description}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="badges")
    async def _badges(self, ctx):
        """**Usage**: `!badges`
        Shows all badges earned by whomever sent the command."""
        author = ctx.message.author
        badges = self.get_badges(author.id)
        embed = discord.Embed(title=f"{author.display_name} has earned {len(badges)} badges", colour=author.colour)
        description = ''
        for b in badges:
            emoji = self.bot.get_emoji(b.emoji)
            description += f"{emoji} {b.name} *(#{b.id})*\n"
        embed.description = description
        await ctx.send(embed=embed)

    def get_badge_emojis(self, user):
        result = (BadgeTable
                  .select(BadgeTable.emoji)
                  .join(BadgeAssignmentTable, on=(BadgeTable.id == BadgeAssignmentTable.badge_id))
                  .where(BadgeAssignmentTable.trainer == user))
        return [self.bot.get_emoji(r.emoji) for r in result]

    @staticmethod
    def get_badges(user):
        result = (BadgeTable
                  .select(BadgeTable.id,
                          BadgeTable.name,
                          BadgeTable.description,
                          BadgeTable.emoji,
                          BadgeTable.active)
                  .join(BadgeAssignmentTable, on=(BadgeTable.id == BadgeAssignmentTable.badge_id))
                  .where(BadgeAssignmentTable.trainer == user))
        return result.objects(Badge)


def setup(bot):
    bot.add_cog(Badges(bot))
