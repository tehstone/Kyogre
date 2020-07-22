import asyncio

import discord
from discord.ext import commands

import peewee

from kyogre.exts.db.kyogredb import *
from kyogre import utils


class Badge:
    def __init__(self, id, name, description, emoji, active, message=None):
        self.id = id
        self.name = name
        self.description = description
        self.emoji = emoji
        self.active = active
        self.message = message
    

class Badges(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='badge', aliases=['bg'])
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
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient badge info: {info}.")
            return await ctx.send("Must provide at least an emoji and badge name, and optionally badge description.",
                                  delete_after=10)
        converter = commands.PartialEmojiConverter()
        try:
            badge_emoji = await converter.convert(ctx, info[0].strip())
        except:
            badge_emoji = None
        if not badge_emoji:
            await ctx.message.add_reaction(self.bot.failed_react)
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No emoji found: {info[0]}.")
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
            new_badge, __ = BadgeTable.get_or_create(guild=ctx.guild.id,
                                                     name=badge_name, description=badge_desc,
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
                await self._update_single_internal(ctx, new_badge.id)
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
        """**Usage**: `!badge toggle_available <badge id>`
        **Alias**: `tg`
        Toggle the availability status of the badge with provided id.
        Available badges are listed with the `avb` command, unavailable badges are only displayed for trainers who have
        earned them.
        """
        badge_to_update = BadgeTable.get(BadgeTable.id == badge_id)
        if badge_to_update.guild_id != ctx.guild.id:
            message = f"No badge found with id {badge_id} found on this server."
            colour = discord.Colour.red()
            reaction = self.bot.failed_react
        else:
            badge_to_update.active = not badge_to_update.active
            badge_to_update.save()
            av = "available" if badge_to_update.active else "unavailable"
            message = f"**{badge_to_update.name}** is now *{av}*."
            colour = discord.Colour.green()
            reaction = self.bot.success_react
            await self._update_single_internal(ctx, badge_id)
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=discord.Embed(colour=colour, description=message))

    @_badge.command(name='info')
    async def _info(self, ctx, badge_id: int = 0):
        """**Usage**: `!badge info <badge id>`
        Displays information about the badge with provided id.
        """
        __, embed, __ = await self._badge_info_internal(ctx, badge_id)
        return await ctx.send(embed=embed)

    async def _badge_info_internal(self, ctx, badge_id):
        try:
            count = (BadgeAssignmentTable.select()
                     .where(BadgeAssignmentTable.badge_id == badge_id)
                     .count())
        except:
            self.bot.logger.error(f"Failed to pull badge assignment count for badge: {badge_id}")
            count = 0
        result = (BadgeTable.select(BadgeTable.id,
                                    BadgeTable.guild_id,
                                    BadgeTable.name,
                                    BadgeTable.description,
                                    BadgeTable.emoji,
                                    BadgeTable.active,
                                    BadgeTable.message).where(BadgeTable.id == badge_id))
        if count == 1:
            count_str = f"*{count}* trainer has earned this badge."
        elif count > 1:
            count_str = f"*{count}* trainers have earned this badge."
        else:
            count_str = "No one has earned this badge yet!"
        try:
            badge = result[0]
        except:
            return 1, discord.Embed(colour=discord.Colour.red(), description=f"No badge found with id {badge_id}"), None
        send_emoji = self.bot.get_emoji(badge.emoji)
        title = f"(*#{badge.id}*) {badge.name}"
        message = f"{badge.description}"
        if badge.guild_id != ctx.guild.id:
            footer = "This badge is awarded on a different server."
        else:
            if badge.active:
                footer = "This badge is currently available."
            else:
                footer = "This badge is not currently available."
        embed = discord.Embed(colour=self.bot.user.colour, title=title, description=message)
        embed.add_field(name=self.bot.empty_str, value=count_str)
        embed.set_footer(text=footer)
        embed.set_thumbnail(url=send_emoji.url)
        b_message = badge.message
        return 0, embed, b_message

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
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient info.")
            return await ctx.send("Must provide a badge id and Trainer name.", delete_after=10)
        try:
            badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
        except:
            badge_to_give = None
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        if badge_to_give:
            if badge_to_give.guild.snowflake != ctx.guild.id:
                embed = discord.Embed(colour=colour,
                                      description=f"No badge with id {badge_id} found on this server.")
            else:
                reaction, embed = await self.try_grant_badge(ctx, badge_to_give, member.id, badge_id)
        else:
            embed = discord.Embed(colour=colour, description="Could not find a badge with that id.")
        await ctx.message.add_reaction(reaction)
        if reaction == self.bot.success_react:
            await ctx.send(content=f"{member.mention}", embed=embed)
        else:
            await ctx.send(embed=embed)

    async def try_grant_badge(self, ctx, badge, member_id, badge_id):
        guild = self.bot.get_guild(ctx.guild.id)
        member = guild.get_member(member_id)
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        embed = None
        try:
            __, __ = GuildTable.get_or_create(snowflake=guild.id)
            __, __ = TrainerTable.get_or_create(snowflake=member.id, guild=guild.id)
            new_badge, created = BadgeAssignmentTable.get_or_create(trainer=member.id, badge=badge_id)
            if new_badge:
                if created:
                    embed = discord.Embed(colour=discord.Colour.green())
                    send_emoji = self.bot.get_emoji(badge.emoji)
                    embed.set_thumbnail(url=send_emoji.url)
                    embed.title = f"Congratulations {member.display_name}"
                    embed.description = f"{member.display_name} has earned {send_emoji} **{badge.name}**!"
                    embed.add_field(name="Badge Requirements", value=f"*{badge.description}*")
                    reaction = self.bot.success_react
                    await self._update_single_internal(ctx, badge.id)
                else:
                    message = f"{member.display_name} already has the **{badge.name}** badge."
            else:
                message = "Failed to give badge. Please try again."
        except peewee.IntegrityError:
            message = f"{member.display_name} already has the **{badge.name}** badge!"
        if not embed:
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
        result = await self.grant_to_many(ctx, badge_id, role.members)
        if result["success"] == False:
            await ctx.message.add_reaction(self.bot.failed_react)
            if result["partial"] == False:
                return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                                  description="Completely failed"), delete_after=12)
            colour = discord.Colour.from_rgb(255, 255, 0)
            await ctx.message.add_reaction(self.bot.success_react)
            return await ctx.channel.send(embed=discord.Embed(colour=colour, description=result['message']),
                                          delete_after=12)
        else:
            await ctx.message.add_reaction(self.bot.success_react)
            return await ctx.channel.send(embed=discord.Embed(
                colour=discord.Colour.green(), description=f"Successfully granted badge to "
                                                           f"{result['count']} trainers."))

    async def grant_to_many(self, ctx, badge_id, trainers):
        badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
        result = {"success": True, "message": None, "partial": False, "count": 0, "errored": []}
        if badge_to_give:
            if badge_to_give.guild.snowflake != ctx.guild.id:
                result["success"] = False
                result["message"] = f"No badge with id {badge_id} found on this server."
                return result
            try:
                trainer_ids = []
                errored = []
                __, __ = GuildTable.get_or_create(snowflake=ctx.guild.id)
                for trainer in trainers:
                    try:
                        trainer_obj, __ = TrainerTable.get_or_create(snowflake=trainer, guild=ctx.guild.id)
                        trainer_ids.append((badge_to_give.id, trainer_obj.snowflake))
                    except:
                        errored.append(trainer)
                count = 0
                with KyogreDB._db.atomic():
                    for chunk in chunked(trainer_ids, 200):
                        count += BadgeAssignmentTable.insert_many(chunk,
                                                          fields=[BadgeAssignmentTable.badge_id,
                                                                  BadgeAssignmentTable.trainer]).execute()

                message = f"Could not assign the badge {badge_to_give.name} ({badge_id}) to: {', '.join(errored)}"
            except Exception as e:
                self.bot.logger.error(e)
                result["success"] = False
                result["message"] = "Completely failed"
                return result

            if len(errored) > 0:
                result["success"] = False
                result["partial"] = True
                result["message"] = message
                result["errored"] = errored
                return result

            await self._update_single_internal(ctx, badge_id)
            result["count"] = count
            return result

    @commands.command(name='revoke_badge', aliases=['rb'])
    @commands.has_permissions(manage_roles=True)
    async def _revoke_badge(self, ctx, badge_id: int = 0, *, member):
        """**Usage**: `!revoke_badge/rb <badge_id> <member>`
        Revokes the provided badge from the provided user."""
        converter = commands.MemberConverter()
        try:
            member = await converter.convert(ctx, member)
        except:
            member = None
        if badge_id == 0 or member is None:
            await ctx.message.add_reaction(self.bot.failed_react)
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient info.")
            return await ctx.send("Must provide a badge id and Trainer name.", delete_after=10)
        try:
            badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
        except:
            badge_to_give = None
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        if badge_to_give:
            if badge_to_give.guild.snowflake != ctx.guild.id:
                embed = discord.Embed(colour=colour,
                                      description=f"No badge with id {badge_id} found on this server.")
            else:
                reaction, embed = await self.try_revoke_badge(badge_to_give, ctx.guild.id, member.id, badge_id, ctx)
        else:
            embed = discord.Embed(colour=colour, description="Could not find a badge with that id.")
        await ctx.message.add_reaction(reaction)
        await ctx.send(embed=embed, delete_after=20)

    async def try_revoke_badge(self, badge, guild_id, member_id, badge_id, ctx):
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(member_id)
        colour = discord.Colour.red()
        reaction = self.bot.failed_react
        embed = None
        try:
            __, __ = GuildTable.get_or_create(snowflake=guild_id)
            __, __ = TrainerTable.get_or_create(snowflake=member.id, guild=guild_id)
            # Check that trainer has this badge
            result = (BadgeAssignmentTable
                      .select()
                      .where((BadgeAssignmentTable.trainer == member.id) &
                             (BadgeAssignmentTable.badge == badge_id))
                      .count()
                      )
            if result < 1:
                message = f"{member.display_name} does not have the **{badge.name}** badge!"
                embed = discord.Embed(colour=colour, description=message)
                return reaction, embed
            # Try to remove badge
            result = (BadgeAssignmentTable.delete()
                     .where((BadgeAssignmentTable.trainer == member.id) &
                            (BadgeAssignmentTable.badge == badge_id))
                     .execute()
                    )
            if result > 0:
                reaction = self.bot.success_react
                send_emoji = self.bot.get_emoji(badge.emoji)
                message = f"Revoked {send_emoji} **{badge.name}** from **{member.display_name}**"
                colour = discord.Colour.green()
                await self._update_single_internal(ctx, badge.id)
            else:
                message = "Failed to revoke the badge"
        except peewee.IntegrityError:
            message = "Failed to revoke the badge"
        if not embed:
            embed = discord.Embed(colour=colour, description=message)
        return (reaction, embed)
    
    @commands.command(name='grant_multiple_badges', aliases=['gmb'])
    @commands.has_permissions(manage_roles=True)
    async def _grant_multiple_badges(self, ctx, *, info):
        """**Usage**: `!grant_multiple_badges/gmb`
        Gives a list of badges by ID to the provided user.
        **Example**: `!gmb 1 2 3, @tehstone`"""
        info_split = info.split(',')
        if len(info_split) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient info.")
            return await ctx.send("Must provide badge ids, comma, then Trainer name.\nFor example: `!gmb 1 2 3 @tehstone`", delete_after=10)
        badge_ids = info_split[0].split(' ')
        converter = commands.MemberConverter()
        try:
            member = ''.join(info_split[1:])
            member = await converter.convert(ctx, member.strip())
        except:
            member = None
        if member is None:
            await ctx.message.add_reaction(self.bot.failed_react)
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient info.")
            return await ctx.send("Must provide badge ids, comma, then Trainer name.\n`!gmb 1 2 3, @tehstone`", delete_after=10)
        failed = {}
        success = {}
        for bid in badge_ids:
            try:
                badge_to_give = BadgeTable.get(BadgeTable.id == bid)
            except:
                badge_to_give = None
            if badge_to_give:
                if badge_to_give.guild.snowflake != ctx.guild.id:
                    failed[bid] = f"No badge with id {bid} found on this server."
                else:
                    reaction, embed = await self.try_grant_badge(ctx, badge_to_give, member.id, bid)
                    if reaction == self.bot.failed_react:
                        failed[bid] = embed.description
                    else:
                        success[bid] = (self.bot.get_emoji(badge_to_give.emoji), badge_to_give.name)
            else:
                failed[bid] = f"Could not find a badge with id {bid}."
        if len(failed) > 0:
            await ctx.message.add_reaction(self.bot.failed_react)
            description = 'Failed to give:\n'
            for item in failed.items():
                description += f"Badge {item[0]}: {item[1]}\n"
            embed = discord.Embed(colour=discord.Colour.red(), description=description)
            await ctx.send(embed=embed)
        if len(success) > 0:
            await ctx.message.add_reaction(self.bot.success_react)
            description = "You've earned:\n"
            for item in success.items():
                description += f"{item[1][0]} **{item[1][1]}**!\n"
            embed = discord.Embed(colour=discord.Colour.green())
            embed.title = f"Congratulations {member.display_name}!"
            embed.description = description
            await ctx.send(content=f"{member.mention}", embed=embed)
            await self._update_single_internal(ctx, bid)

    @commands.command(name="available_badges", aliases=['avb'])
    @commands.has_permissions(manage_guild=True)
    async def _available(self, ctx):
        """**Usage**: `!available_badges/avb`
        Lists all badges that are currently available."""
        return await self._list_badges(ctx, True, "The following badges currently available:")

    @commands.command(name="all_badges", aliases=['aab'])
    @commands.has_permissions(manage_guild=True)
    async def _all_badges(self, ctx):
        """**Usage**: `!all_badges/aab`
        Lists all badges."""
        return await self._list_badges(ctx, False, "All created badges")

    async def _list_badges(self, ctx, available, title):
        result = (BadgeTable
                  .select(BadgeTable.id,
                          BadgeTable.name,
                          BadgeTable.description,
                          BadgeTable.emoji,
                          BadgeTable.active)
                  .where(BadgeTable.guild == ctx.guild.id))
        result = result.objects(Badge)
        if available:
            result = [r for r in result if r.active]
        fields = []
        for r in result:
            send_emoji = self.bot.get_emoji(r.emoji)
            name = f"{send_emoji} {r.name} (#{r.id})"
            if not available:
                if not r.active:
                    name += " - *retired*"
            fields.append((name, f"\t\t{r.description}"))
        chunked_fields = list(utils.list_chunker(fields, 20))
        if len(chunked_fields) < 1:
            return await ctx.send(embed=discord.Embed(title="No badges found for this server.",
                                                      colour=discord.Colour.purple()))
        for sub_list in chunked_fields:
            embed = discord.Embed(title=title, colour=discord.Colour.purple())
            for field in sub_list:
                embed.add_field(name=field[0], value=f"{self.bot.empty_str}{field[1]}", inline=False)
            await ctx.send(embed=embed)

    @commands.command(name="badges")
    async def _badges(self, ctx, user: discord.Member = None):
        """**Usage**: `!badges [user]`
        Shows all badges earned by whomever sent the command or for the user provided."""
        if not user:
            user = ctx.message.author
        badges = self.get_badges(ctx.guild.id, user.id)
        embed = discord.Embed(title=f"{user.display_name} has earned {len(badges)} badges", colour=user.colour)
        description = ''
        for b in badges:
            emoji = self.bot.get_emoji(b.emoji)
            description += f"{emoji} {b.name} *(#{b.id})*\n"
            if len(description) > 1900:
                embed.description = description
                await ctx.send(embed=embed)
                embed = discord.Embed(colour=user.colour)
                description = ''
        embed.description = description
        await ctx.send(embed=embed)

    def get_badge_emojis(self, guild_id, user):
        result = (BadgeTable
                  .select(BadgeTable.emoji)
                  .join(BadgeAssignmentTable, on=(BadgeTable.id == BadgeAssignmentTable.badge_id))
                  .where((BadgeAssignmentTable.trainer == user) &
                         (BadgeTable.guild_id == guild_id)))
        return [self.bot.get_emoji(r.emoji) for r in result]

    @staticmethod
    def get_badges(guild_id, user):
        result = (BadgeTable
                  .select(BadgeTable.id,
                          BadgeTable.name,
                          BadgeTable.description,
                          BadgeTable.emoji,
                          BadgeTable.active)
                  .join(BadgeAssignmentTable, on=(BadgeTable.id == BadgeAssignmentTable.badge_id))
                  .where((BadgeAssignmentTable.trainer == user) &
                         (BadgeTable.guild_id == guild_id)))
        return result.objects(Badge)

    @commands.command(name="badge_leader", aliases=['bl'])
    async def badge_leader(self, ctx):
        """
        Shows the 10 Trainers with the most Badges earned on this server.
        """
        result = (BadgeAssignmentTable
                  .select(BadgeAssignmentTable.trainer, fn.Count(BadgeAssignmentTable.trainer).alias('count'))
                  .join(BadgeTable, on=(BadgeTable.id == BadgeAssignmentTable.badge_id))
                  .where(BadgeTable.guild_id == ctx.guild.id)
                  .group_by(BadgeAssignmentTable.trainer)
                  .order_by(SQL('count').desc())
                  .limit(10)
                  )
        output = ""
        for r in result:
            trainer = ctx.guild.get_member(r.trainer)
            output += f"**{trainer.display_name}** - {r.count} badges.\n"
        embed = discord.Embed(title=f"Here are the top 10 badge earners on this server", colour=discord.Colour.purple())
        embed.description = output
        await ctx.send(embed=embed)

    @commands.command(name='set_badge_list_channel', aliases=['sblc'])
    async def _set_badge_list_channel(self, ctx, channel):
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('badge_list_channel', None)
        utilities_cog = self.bot.cogs.get('Utilities')
        sblc_channel = await utilities_cog.get_channel_by_name_or_id(ctx, channel)
        if sblc_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        update_channel = sblc_channel.id
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['badge_list_channel'] = update_channel
        await ctx.channel.send(f'{sblc_channel.mention} set as badge list channel.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(name='refresh_badge_list', aliases=['rbl'])
    async def _refresh_badge_list(self, ctx):
        channel = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].get('badge_list_channel', None)
        utilities_cog = self.bot.cogs.get('Utilities')
        blc_channel = await utilities_cog.get_channel_by_name_or_id(ctx, str(channel))
        if blc_channel is None:
            await ctx.channel.send('Badge list channel not set or could not be found.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        blc_channel = await utils.clone_and_position(blc_channel, delete=True)
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['badge_list_channel'] = blc_channel.id
        result = (BadgeTable.select(BadgeTable.id,
                                    BadgeTable.guild_id,
                                    BadgeTable.name,
                                    BadgeTable.description,
                                    BadgeTable.emoji,
                                    BadgeTable.active))
        for r in result:
            count = (BadgeAssignmentTable.select()
                     .where(BadgeAssignmentTable.badge_id == r.id)
                     .count())
            if count == 1:
                count_str = f"*{count}* trainer has earned this badge."
            elif count > 1:
                count_str = f"*{count}* trainers have earned this badge."
            else:
                count_str = "No one has earned this badge yet!"
            send_emoji = self.bot.get_emoji(r.emoji)
            title = f"(*#{r.id}*) {r.name}"
            message = f"{r.description}"
            if r.guild_id != ctx.guild.id:
                footer = "This badge is awarded on a different server."
            else:
                if r.active:
                    footer = "This badge is currently available."
                else:
                    footer = "This badge is not currently available."
            embed = discord.Embed(colour=self.bot.user.colour, title=title, description=message)
            embed.add_field(name=self.bot.empty_str, value=count_str)
            embed.set_footer(text=footer)
            if send_emoji is not None:
                embed.set_thumbnail(url=send_emoji.url)
            message = await blc_channel.send(embed=embed)
            r.message = message.id
            r.save()
            await asyncio.sleep(1.1)

    @commands.command(name='update_single_badge_listing', aliases=['usbl'])
    async def _update_single_badge_listing(self, ctx, badge_id):
        status = await self._update_single_internal(ctx, badge_id)
        if status == 0:
            await ctx.message.add_reaction(self.bot.success_react)
        else:
            await ctx.message.add_reaction(self.bot.failed_react)

    async def _update_single_internal(self, ctx, badge_id):
        channel = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('badge_list_channel', None)
        utilities_cog = self.bot.cogs.get('Utilities')
        sblc_channel = await utilities_cog.get_channel_by_name_or_id(ctx, str(channel))
        if sblc_channel is None:
            await ctx.channel.send('Badge list channel not set or could not be found.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        status, embed, message_id = await self._badge_info_internal(ctx, badge_id)
        if status == 0:
            try:
                old_message = await sblc_channel.fetch_message(message_id)
            except:
                old_message = None
            try:
                if old_message is None:
                    new_message = await sblc_channel.send(embed=embed)
                    with KyogreDB._db.atomic() as txn:
                        try:
                            BadgeTable.update(message=new_message.id).where(BadgeTable.message == message_id).execute()
                            txn.commit()
                        except Exception:
                            self.bot.logger.info("Failed to message id for badge listing.")
                            txn.rollback()
                else:
                    await old_message.edit(embed=embed)
            except:
                status = 1
        return status


def setup(bot):
    bot.add_cog(Badges(bot))

