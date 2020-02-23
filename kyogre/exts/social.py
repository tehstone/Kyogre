import copy

import discord
from discord.ext import commands

from kyogre import utils


class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True)
    async def profile(self, ctx, user: discord.Member = None):
        """**Usage**: `!profile [user]`
        Displays a user's social and reporting profile. Don't include a name to view your own."""
        if not user:
            user = ctx.message.author
        trainer_info = self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).setdefault(user.id, {})
        silph = trainer_info.get('silphid', None)
        if silph:
            card = "Traveler Card"
            silph = f"[{card}](https://sil.ph/{silph.lower()})"
        else:
            silph = None
        pokebattlerid = trainer_info.get('pokebattlerid', None)
        pkb = str(pokebattlerid) if pokebattlerid else None
        xp = trainer_info.get('xp', 0)
        try:
            xp = xp.replace(',', '')
        except AttributeError:
            pass
        try:
            xp = int(xp)
        except (ValueError, TypeError):
            xp = 0
        xp_msg = f'{xp:,d}' if xp > 0 else 'not set'
        trainer_name = trainer_info.get('trainername', None)
        trainer_code = trainer_info.get('code', None)
        code_msg = trainer_code if trainer_code is not None else 'not set'
        name_msg = trainer_name if trainer_name is not None else 'not set'
        team = trainer_info.get('team', None)
        if team is None:
            colour = user.colour
            team_url = None
        else:
            colour = self.bot.team_color_map[team.capitalize()]
            team_url = f"https://github.com/tehstone/Kyogre/blob/master/images/teams/{team.lower()}.png?raw=true"
        raids, eggs, wilds, research, joined, nests = await self._get_profile_counts(ctx, user)
        badge_cog = self.bot.cogs.get('Badges')
        badges = badge_cog.get_badge_emojis(ctx.guild.id, user.id)
        badge_str = self.bot.empty_str
        badges = utils.list_chunker(badges, 4)
        for c in badges:
            for b in c:
                badge_str += f"{b} "
            if len(badge_str) > 910:
                break
            badge_str += '\n'
        embed = discord.Embed(colour=colour)
        embed.set_author(name=user.display_name, icon_url=user.avatar_url)
        if team_url:
            embed.set_thumbnail(url=team_url)
        embed.add_field(name="XP", value=f"{xp_msg}", inline=True)
        embed.add_field(name="Friend Code", value=f"{code_msg}")
        embed.add_field(name="Trainer Name", value=f"{name_msg}")
        if silph is not None:
            embed.add_field(name="Silph Road", value=f"{silph}")
        if pkb is not None:
            embed.add_field(name="Pokebattler", value=f"{pkb}")
        if len(embed.fields) % 2 == 1:
            embed.add_field(name='\u200b', value='\u200b')
        embed.add_field(name="Badges earned", value=f"{badge_str}")
        stats_str = f"Raid Reports: {raids}\nEgg Reports: {eggs}\nWild Points: {wilds}\n" \
            f"Research Points: {research}\nRaids Joined: {joined}\nNest Reports: {nests}\n"
        embed.add_field(name="Kyogre Stats", value=stats_str)
        embed.set_footer(text='Do "!set profile" to update your profile!')
        await ctx.send(embed=embed)

    async def _get_profile_counts(self, ctx, user):
        regions = self.bot.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys()
        raids, eggs, wilds, research, joined, nests = 0, 0, 0, 0, 0, 0
        for region in regions:
            raids += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {})\
                .setdefault(user.id, {}).get('raid_reports', 0)
            eggs += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {})\
                .setdefault(user.id, {}).get('egg_reports', 0)
            wilds += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {})\
                .setdefault(user.id, {}).get('wild_reports', 0)
            research += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {})\
                .setdefault(user.id, {}).get('research_reports', 0)
            joined += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {})\
                .setdefault(user.id, {}).get('joined', 0)
        nests += self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('nests', {}) \
            .setdefault(user.id, 0)
        return [raids, eggs, wilds, research, joined, nests]

    @commands.command(name='leaderboard', aliases=['lb', 'board'])
    async def leaderboard(self, ctx, board_type="total", region=None):
        """**Usage**: `!leaderboard [type] [region]`
        Accepted types: raids, eggs, wilds, research, joined, nests
        Region must be any configured region"""
        guild = ctx.guild
        leaderboard = {}
        rank = 1
        field_value = ""
        typelist = ["total", "raids", "eggs", "exraids", "wild", "research", "joined", "nests"]
        board_type = board_type.lower()
        regions = list(self.bot.guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
        if board_type not in typelist:
            if board_type in regions:
                region = board_type
                board_type = "total"
            else:
                self.bot.help_logger.info(f"User: {ctx.author.name}, "
                                          f"channel: {ctx.channel}, error: {board_type} leaderboard is invalid.")
                return await ctx.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description=f"Leaderboard type not supported. Please select from: **{', '.join(typelist)}**"))
        if region is not None:
            region = region.lower()
            if region in regions:
                regions = [region]
            else:
                self.bot.help_logger.info(f"User: {ctx.author.name}, "
                                          f"channel: {ctx.channel}, error: {region} region is invalid.")
                return await ctx.send(embed=discord.Embed(
                    colour=discord.Colour.red(), description=f"No region found with name {region}"))
        for region in regions:
            trainers = copy.deepcopy(self.bot.guild_dict[guild.id]['trainers'].setdefault(region, {}))
            for trainer in trainers.keys():
                user = guild.get_member(trainer)
                if user is None:
                    continue
                raids, wilds, exraids, eggs, research, joined = 0, 0, 0, 0, 0, 0
                
                raids += trainers[trainer].setdefault('raid_reports', 0)
                wilds += trainers[trainer].setdefault('wild_reports', 0)
                exraids += trainers[trainer].setdefault('ex_reports', 0)
                eggs += trainers[trainer].setdefault('egg_reports', 0)
                research += trainers[trainer].setdefault('research_reports', 0)
                joined += trainers[trainer].setdefault('joined', 0)
                total_reports = raids + wilds + exraids + eggs + research + joined
                trainer_stats = {'trainer': trainer, 'total': total_reports, 'raids': raids,
                                 'wild': wilds, 'research': research, 'exraids': exraids,
                                 'eggs': eggs, 'joined': joined, 'nests': 0}
                if trainer_stats[board_type] > 0 and user:
                    if trainer in leaderboard:
                        leaderboard[trainer] = self.combine_dicts(leaderboard[trainer], trainer_stats)
                    else:
                        leaderboard[trainer] = trainer_stats
        nest_reports = self.bot.guild_dict[guild.id]['trainers'].setdefault('nests', {})
        for trainer in nest_reports.keys():
            user = guild.get_member(trainer)
            if user is None:
                continue
            nests = self.bot.guild_dict[guild.id]['trainers'].setdefault('nests', {}).setdefault(user.id, 0)
            if trainer in leaderboard:
                leaderboard[trainer]['nests'] = nests
            else:
                leaderboard[trainer] = {'trainer': trainer, 'total': nests, 'raids': 0,
                                        'wild': 0, 'research': 0, 'exraids': 0,
                                        'eggs': 0, 'joined': 0, 'nests': nests}
        leaderboardlist = []
        for key, value in leaderboard.items():
            leaderboardlist.append(value)
        leaderboardlist = sorted(leaderboardlist, key=lambda x: x[board_type], reverse=True)[:10]
        embed = discord.Embed(colour=guild.me.colour)
        leaderboard_title = f"Reporting Leaderboard ({board_type.title()})"
        if len(regions) == 1:
            leaderboard_title += f" {region.capitalize()}"
        embed.set_author(name=leaderboard_title, icon_url=self.bot.user.avatar_url)
        description = ''
        for trainer in leaderboardlist:
            user = guild.get_member(int(trainer['trainer']))
            if user:
                if self.bot.guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                    field_value += "Raids: **{raids}** | Eggs: **{eggs}** | "\
                        .format(raids=trainer['raids'], eggs=trainer['eggs'])
                if self.bot.guild_dict[guild.id]['configure_dict']['exraid']['enabled']:
                    field_value += "EX Raids: **{exraids}** | ".format(exraids=trainer['exraids'])
                if self.bot.guild_dict[guild.id]['configure_dict']['wild']['enabled']:
                    field_value += "Wild Points: **{wilds}** | ".format(wilds=trainer['wild'])
                if self.bot.guild_dict[guild.id]['configure_dict']['research']['enabled']:
                    field_value += "Research Points: **{research}** | ".format(research=trainer['research'])
                if self.bot.guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                    field_value += "Raids Joined: **{joined}** | ".format(joined=trainer['joined'])
                field_value += "Nests: **{nests}** | ".format(nests=trainer['nests'])
                if board_type == 'total':
                    embed.add_field(name=f"{rank}. {user.display_name} - {board_type.title()}: "
                                         f"**{trainer[board_type]}**\n", value=field_value[:-3], inline=False)
                    field_value = ""
                else:
                    if board_type == 'joined':
                        description += f"{rank}. **{user.display_name}** - " \
                                       f"Raids {board_type.title()}: **{trainer[board_type]}**\n"
                    elif board_type == 'wild' or board_type == 'research':
                        description += f"{rank}. **{user.display_name}** - " \
                                       f"{board_type.title()} Points: **{trainer[board_type]}**\n"
                    else:
                        description += f"{rank}. **{user.display_name}** - " \
                                       f"{board_type.title()} Reported: **{trainer[board_type]}**\n"
                rank += 1
        if len(embed.fields) == 0:
            if len(description) > 0:
                embed.description = description
            else:
                embed.add_field(name="No Reports", value="Nobody has made a report or this report type is disabled.")
        await ctx.send(embed=embed)

    @staticmethod
    def combine_dicts(a, b):
        for key, value in a.items():
            if key != 'trainer':
                a[key] = a[key] + b[key]
        return a

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def reset_board(self, ctx, *, user=None, board_type=None):
        guild = ctx.guild
        trainers = self.bot.guild_dict[guild.id]['trainers']
        tgt_string = ""
        tgt_trainer = None
        if user:
            converter = commands.MemberConverter()
            for argument in user.split():
                try:
                    await ctx.channel.send(argument)
                    tgt_trainer = await converter.convert(ctx, argument)
                    tgt_string = tgt_trainer.display_name
                except:
                    tgt_trainer = None
                    tgt_string = "every user"
                if tgt_trainer:
                    user = user.replace(argument, "").strip()
                    break
            for argument in user.split():
                if "raid" in argument.lower():
                    board_type = "raid_reports"
                    break
                elif "egg" in argument.lower():
                    board_type = "egg_reports"
                    break
                elif "ex" in argument.lower():
                    board_type = "ex_reports"
                    break
                elif "wild" in argument.lower():
                    board_type = "wild_reports"
                    break
                elif "res" in argument.lower():
                    board_type = "research_reports"
                    break
                elif "join" in argument.lower():
                    board_type = "joined"
                    break
                elif "nest" in argument.lower():
                    board_type = "nests"
                    break
        if not board_type:
            board_type = "total_reports"
        if tgt_string == "":
            tgt_string = "all report types and all users"
        msg = "Are you sure you want to reset the **{type}** report stats for **{target}**?".format(type=board_type,
                                                                                                    target=tgt_string)
        question = await ctx.channel.send(msg)
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(self.bot, question, ctx.message.channel, ctx.message.author.id)
        except TypeError:
            timeout = True
            res = None
        await question.delete()
        if timeout or res.emoji == '❎':
            return
        elif res.emoji == '✅':
            pass
        else:
            return
        regions = self.bot.guild_dict[guild.id]['configure_dict']['regions']['info'].keys()
        for region in regions:
            trainers.setdefault(region, {})
            for trainer in trainers[region]:
                if tgt_trainer:
                    trainer = tgt_trainer.id
                if board_type == "total_reports":
                    for rtype in trainers[region][trainer]:
                        trainers[region][trainer][rtype] = 0
                else:
                    type_score = trainers[region][trainer].get(board_type, 0)
                    type_score = 0
                if tgt_trainer:
                    await ctx.send(
                        "{trainer}'s report stats have been cleared!".format(trainer=tgt_trainer.display_name))
                    return
        await ctx.send("This server's report stats have been reset!")

    @commands.command(name='whois', aliases=['who'])
    async def _who_is(self, ctx, trainer):
        trainer_names_copy = copy.deepcopy(self.bot.guild_dict[ctx.guild.id].setdefault('trainer_names', {}))
        trainer_list = []
        for k in trainer_names_copy.keys():
            if trainer == k:
                user = ctx.guild.get_member(trainer_names_copy[k])
                return await ctx.send(f"You're probably looking for {user.mention}")
            trainer_list.append(k)
        matches = utils.get_match(trainer_list, trainer, score_cutoff=75, isPartial=True, limit=5)
        if not isinstance(matches, list):
            matches = [matches]
        if len(matches) < 2:
            if matches[0][0] is None:
                return await ctx.send("No trainers found with a name similar to that")
            return await ctx.send(f"You might be looking for {matches[0][0]}")
        else:
            match_names = [m[0] for m in matches]
            return await ctx.send(f"You might be looking for {' or '.join(match_names)}")


def setup(bot):
    bot.add_cog(Social(bot))
