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
        """**Usage**: `!badge add <emoji>, <badge name>, [<badge description], [create in pokenav]`
        **Aliases**: `create, cr, new`
        Emoji and name are required with a comma between each. Description is optional
        Optionally can provide "false/no" to prevent badge from being created in Pokenav as well.
        By default, badge will be created on both bots
        """
        info = re.split(r',\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Must provide at least an emoji and badge name, and optionally badge description.",
                                  delete_after=10)
        converter = commands.PartialEmojiConverter()
        try:
            badge_emoji = await converter.convert(ctx, info[0].strip())
        except:
            badge_emoji = None
        if not badge_emoji:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Could not find that emoji.", delete_after=10)
        badge_name = info[1]
        badge_desc = ''
        create_in_pokenav = True
        if len(info) > 2:
            badge_desc = info[2]
            if len(info) > 3:
                if info[3].lower() == 'false' or info[3].lower() == 'no':
                    create_in_pokenav = False
        try:
            new_badge, __ = BadgeTable.get_or_create(name=badge_name, description=badge_desc,
                                                     emoji=badge_emoji.id, active=True)
            if new_badge:
                send_emoji = self.bot.get_emoji(badge_emoji.id)
                message = f"{send_emoji} {badge_name} (#{new_badge.id}) successfully created!"
                colour = discord.Colour.green()
                reaction = self.bot.success_react
                quick_badge_config = self.bot.guild_dict[ctx.guild.id]['configure_dict'].get('quick_badge', None)
                if create_in_pokenav and quick_badge_config is not None:
                    pokenav_channel_id = quick_badge_config['pokenav_channel']
                    pokenav_channel = self.bot.get_channel(pokenav_channel_id)
                    await pokenav_channel.send(f'$create badge {badge_emoji} "{badge_name}" "{badge_desc}"')
            else:
                message = "Failed to create badge. Please try again."
                colour = discord.Colour.red()
                reaction = self.bot.failed_react
        except peewee.IntegrityError:
            message = f"""A badge already exists with the same name, description, and emoji."""
            colour = discord.Colour.red()
            reaction = self.bot.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))

    @_badge.command(name='toggle_available', aliases=['tg'])
    @commands.has_permissions(manage_roles=True)
    async def _toggle_available(self, ctx, badge_id: int = 0):
        updated = BadgeTable.update(active=~BadgeTable.active).where(BadgeTable.id == badge_id).execute()
        result = BadgeTable.select(BadgeTable.name, BadgeTable.active).where(BadgeTable.id == badge_id)
        if updated == 0:
            message = "No badge found by that id."
            colour = discord.Colour.red()
            reaction = self.bot.failed_react
        elif updated == 1:
            av = "available" if result[0].active else "unavailable"
            message = f"**{result[0].name}** is now *{av}*."
            colour = discord.Colour.green()
            reaction = self.bot.success_react
        else:
            message = "Something went wrong."
            colour = discord.Colour.red()
            reaction = self.bot.failed_react
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message))

    @_badge.command(name='info')
    async def _info(self, ctx, badge_id: int = 0):
        try:
            count = (BadgeAssignmentTable.select()
                     .where(BadgeAssignmentTable.badge_id == badge_id)
                     .count())
        except:
            self.bot.logger.error(f"Failed to pull badge assignment count for badge: {badge_id}")
            count = 0
        result = (BadgeTable.select(BadgeTable.id,
                                    BadgeTable.name,
                                    BadgeTable.description,
                                    BadgeTable.emoji,
                                    BadgeTable.active).where(BadgeTable.id == badge_id))
        if count == 1:
            count_str = f"{count} trainer has earned this badge."
        elif count > 1:
            count_str = f"{count} trainers have earned this badge."
        else:
            count_str = "No one has earned this badge yet!"
        badge = result[0]
        send_emoji = self.bot.get_emoji(badge.emoji)
        title = f"(*#{badge.id}*) {badge.name}"
        message = f"{badge.description}"
        if badge.active:
            footer = "This badge is currently available."
        else:
            footer = "This badge is not currently available."
        embed = discord.Embed(colour=self.bot.user.colour, title=title, description=message)
        embed.add_field(name=self.bot.empty_str, value=count_str)
        embed.set_footer(text=footer)
        embed.set_thumbnail(url=send_emoji.url)
        await ctx.send(embed=embed)

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
            reaction, embed = await self.try_grant_badge(badge_to_give, ctx.guild.id, member.id, badge_id)
        else:
            embed = discord.Embed(colour=colour, description="Could not find a badge with that name.")
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=embed)

    async def try_grant_badge(self, badge, guild_id, member_id, badge_id):
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(member_id)
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        try:
            guild_obj, __ = GuildTable.get_or_create(snowflake=guild_id)
            trainer_obj, __ = TrainerTable.get_or_create(snowflake=member.id, guild=guild_id)
            new_badge, __ = BadgeAssignmentTable.get_or_create(trainer=member.id, badge=badge_id)
            if new_badge:
                send_emoji = self.bot.get_emoji(badge.emoji)
                message = f"{member.display_name} has been given {send_emoji} **{badge.name}**!"
                colour = discord.Colour.green()
                reaction = self.bot.success_react
            else:
                message = "Failed to give badge. Please try again."
        except peewee.IntegrityError:
            message = f"{member.display_name} already has the **{badge.name}** badge!"
        embed = discord.Embed(colour=colour, description=message)
        return (reaction, embed)

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
                    count = BadgeAssignmentTable.insert_many(trainer_ids,
                                                             fields=[BadgeAssignmentTable.badge_id,
                                                                     BadgeAssignmentTable.trainer])\
                            .on_conflict_ignore().execute()
                message = f"Could not assign the badge to: {', '.join(errored)}"
            except Exception as e:
                self.bot.logger.error(e)
                await ctx.message.add_reaction(self.bot.failed_react)
                return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                                  description="Completely failed"), delete_after=12)
            if len(errored) > 0:
                colour = discord.Colour.from_rgb(255, 255, 0)
                await ctx.message.add_reaction(self.bot.failed_react)
                await ctx.message.add_reaction(self.bot.success_react)
                return await ctx.channel.send(embed=discord.Embed(colour=colour, description=message), delete_after=12)
            colour = discord.Colour.green()
            message = f"Successfully granted badge to {count} trainers."
            await ctx.message.add_reaction(self.bot.success_react)
            return await ctx.channel.send(embed=discord.Embed(colour=colour, description=message))

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
    async def _badges(self, ctx, user: discord.Member = None):
        """**Usage**: `!badges [user]`
        Shows all badges earned by whomever sent the command or for the user provided."""
        if not user:
            user = ctx.message.author
        badges = self.get_badges(user.id)
        embed = discord.Embed(title=f"{user.display_name} has earned {len(badges)} badges", colour=user.colour)
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
