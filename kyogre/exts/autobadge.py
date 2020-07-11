import asyncio

import discord
from discord.ext import commands

from kyogre.exts.db.kyogredb import AutoBadgeTable, BadgeTable, BadgeAssignmentTable


class AutoBadge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quick_badge_dict_default = {'listen_channels': [],
                                         '40_listen_channels': [],
                                         '40_role': None,
                                         'pokenav_channel': 0,
                                         'badge_channel': 0,
                                         'badges': {}}

    @commands.command(hidden=True, name='addautobadge', aliases=['aub'])
    @commands.has_permissions(manage_guild=True)
    async def _add_auto_badge(self, ctx, stat: str, count: int, badge_id: int):
        errors = self._check_add_errors(ctx, stat, count, badge_id)
        if len(errors) > 0:
            return await self._fail_out(ctx, '\n'.join(errors))
        __, created = AutoBadgeTable.get_or_create(guild_id=ctx.guild.id, stat=stat, threshold=count, badge=badge_id)
        if not created:
            return await self._fail_out(ctx, 'Auto badge already exists')
        else:
            return await ctx.message.add_reaction(self.bot.success_react)

    def _check_add_errors(self, ctx, stat, count, badge_id):
        errors = []
        if stat not in self.bot.leaderboard_list:
            errors.append(f"{stat} is not a valid leaderboard type and cannot be tracked.")
        if count < 1:
            errors.append("Count must be greater than 0.")
        if badge_id < 1:
            errors.append("Invalid badge id, must be greater than 0.")
        else:
            try:
                badge_to_give = BadgeTable.get(BadgeTable.id == badge_id)
            except:
                badge_to_give = None
            if not badge_to_give:
                errors.append(f"No badge found with id {badge_id}")
            elif badge_to_give.guild_id != ctx.guild.id:
                errors.append(f"Badge {badge_id} is not available on this server.")
        return errors

    async def _fail_out(self, ctx, message):
        await ctx.message.add_reaction(self.bot.failed_react)
        return await ctx.channel.send(
            embed=discord.Embed(colour=discord.Colour.red(),
                                description=message),
            delete_after=15)

    @commands.command(hidden=True, name='deleteautobadge', aliases=['dub'])
    @commands.has_permissions(manage_guild=True)
    async def _delete_auto_badge(self, ctx, auto_badge_id: int):
        deleted = AutoBadgeTable.delete().where((AutoBadgeTable.id == auto_badge_id) &
                                                (AutoBadgeTable.guild_id == ctx.guild.id)).execute()
        if deleted > 0:
            return await ctx.message.add_reaction(self.bot.success_react)
        else:
            return await self._fail_out(ctx, f'Failed to delete auto badge with id {auto_badge_id}.')

    @commands.command(name='checkab')
    @commands.has_permissions(manage_guild=True)
    async def _check_auto_badges(self, ctx):
        social_cog = self.bot.cogs.get('Social')
        regions = list(self.bot.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys())
        full_leaderboard = social_cog.full_leaderboard_list(ctx, regions, "total")
        all_raids = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['raids'] + i[1]['eggs'])))
        research = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['research'])))
        wild = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['wild'])))
        nests = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['nests'])))
        joined = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['joined'])))
        total = dict(sorted(full_leaderboard.items(), key=lambda i: (i[1]['raids'] + i[1]['eggs'] + i[1]['wild']
                                                                     + i[1]['nests'] + i[1]['exraids'])))
        sorted_boards = {'all_raids': all_raids,
                         'research': research,
                         'wild': wild,
                         'nests': nests,
                         'joined': joined,
                         'total': total
                         }

        result = (AutoBadgeTable.select().where(AutoBadgeTable.guild_id == ctx.guild.id))
        assignment_results = {}
        for r in result:
            if r.stat == 'raids' or r.stat == 'eggs':
                board = 'all_raids'
            else:
                board = r.stat
            outcome = await self._check_single(ctx, sorted_boards[board], r)
            assignment_results[r.badge] = outcome

        sent = 0
        quick_badge_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict'] \
            .get('quick_badge', self.quick_badge_dict_default)
        badge_channel = None
        if quick_badge_dict['badge_channel'] != 0:
            badge_channel = self.bot.get_channel(quick_badge_dict['badge_channel'])
        for badge in assignment_results.keys():
            outcome = assignment_results[badge]
            if len(outcome["assigned"]) < 1:
                continue
            if outcome["success"] == False and outcome["partial"] == False:
                self.bot.logger.info(f"Failed to assign badge {badge} on server {ctx.guild.name} ({ctx.guild.id})"
                                     f"to {len(outcome['assigned'])} trainers. This was a complete error.")
                continue
            if outcome["partial"] == True:
                errored = set(outcome["errored"])
                assigned = set(outcome["assigned"])
                success = list(assigned - errored)
                self.bot.logger.info(f"Failed to assign badge {badge} on server {ctx.guild.name} ({ctx.guild.id})"
                                     f"to {len(errored)} trainers. This was only a partial error.")
            else:
                success = outcome["assigned"]
            if badge_channel:
                badge_to_give = BadgeTable.get(BadgeTable.id == badge)
                embed = discord.Embed(colour=discord.Colour.green())
                send_emoji = self.bot.get_emoji(badge_to_give.emoji)
                embed.set_thumbnail(url=send_emoji.url)
                embed.title = "Congratulations Trainers!"
                description = f"The following trainers have earned {send_emoji} **{badge_to_give.name}**!\n"
                mentions = ""
                exceeded = False
                for tid in success:
                    member = ctx.guild.get_member(tid)
                    if member:
                        if len(description) + len(f"{member.display_name}\n") > 2000:
                            exceeded = True
                        if not exceeded:
                            description += f"{member.display_name}\n"
                            mentions += f"{member.mention} "
                embed.description = description
                embed.add_field(name="Badge Requirements", value=f"*{badge_to_give.description}*")
                sent += 1
                await badge_channel.send(embed=embed)
                mentions_msg = await badge_channel.send(mentions)
                await asyncio.sleep(2)
                if exceeded:
                    await badge_channel.send("Additional trainers also earned this badge.")
                await mentions_msg.delete()
        if sent == 0:
            await ctx.channel.send("No new badge assignments.")

    async def _check_single(self, ctx, leaderboard, autobadge):
        if autobadge.stat == 'raids' or autobadge.stat == 'eggs':
            qualified = dict(filter(lambda elem:
                                    elem[1]['raids'] + elem[1]['eggs'] > autobadge.threshold, leaderboard.items()))
        else:
            qualified = dict(filter(lambda elem: elem[1][autobadge.stat] > autobadge.threshold, leaderboard.items()))
        already_earned = set()
        earned_badges = (BadgeAssignmentTable.select(BadgeAssignmentTable.trainer)
                         .where(BadgeAssignmentTable.badge_id == autobadge.badge))
        for e in earned_badges:
            already_earned.add(e.trainer)
        qualified_list = set(qualified.keys())
        to_assign = qualified_list - already_earned
        badge_cog = self.bot.cogs.get('Badges')
        to_assign = list(to_assign)
        if len(to_assign) > 0:
            result = await badge_cog.grant_to_many(ctx, autobadge.badge, to_assign)
            result["assigned"] = to_assign
        else:
            result = {"assigned": []}
        return result


def setup(bot):
    bot.add_cog(AutoBadge(bot))
