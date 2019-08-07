import copy

import discord
from discord.ext import commands

from kyogre.exts.db.kyogredb import *


class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_dict = bot.guild_dict

    @commands.command(hidden=True)
    async def profile(self, ctx, user: discord.Member = None):
        """**Usage**: `!profile [user]`
        Displays a user's social and reporting profile. Don't include a name to view your own."""
        if not user:
            user = ctx.message.author
        trainer_info = self.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).setdefault(user.id,{})
        silph = trainer_info.get('silphid', None)
        if silph:
            card = "Traveler Card"
            silph = f"[{card}](https://sil.ph/{silph.lower()})"
        else:
            silph = "not set"
        pokebattlerid = trainer_info.get('pokebattlerid', None)
        pkb = str(pokebattlerid) if pokebattlerid else 'not set'
        xp = trainer_info.get('xp', 0)
        try:
            xp = int(xp)
        except ValueError:
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
            colour = self.bot.team_color_map[team]
            team_url = f"https://github.com/tehstone/Kyogre/blob/master/images/teams/{team.lower()}.png?raw=true"
        raids, eggs, wilds, research, joined = await self._get_profile_counts(ctx, user)
        badge_cog = self.bot.cogs.get('Badges')
        badges = badge_cog.get_badge_emojis(user.id)
        badge_str = self.bot.empty_str
        for b in badges:
            badge_str += f" {b}"
        embed = discord.Embed(colour=colour)
        embed.set_author(name=user.display_name, icon_url=user.avatar_url)
        if team_url:
            embed.set_thumbnail(url=team_url)
        embed.add_field(name="XP", value=f"{xp_msg}", inline=True)
        embed.add_field(name="Friend Code", value=f"{code_msg}")
        embed.add_field(name="Trainer Name", value=f"{name_msg}")
        embed.add_field(name="Silph Road", value=f"{silph}")
        embed.add_field(name="Pokebattler", value=f"{pkb}")
        embed.add_field(name="Raid Reports", value=f"{raids}")
        embed.add_field(name="Egg Reports", value=f"{eggs}")
        embed.add_field(name="Wild Reports", value=f"{wilds}")
        embed.add_field(name="Research Reports", value=f"{research}")
        embed.add_field(name="Raids Joined", value=f"{joined}")
        embed.add_field(name="Badges earned", value=f"{badge_str}", inline=False)
        embed.set_footer(text='Do "!set profile" to get your profile set up!')
        await ctx.send(embed=embed)

    async def _get_profile_counts(self, ctx, user):
        regions = self.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys()
        raids, eggs, wilds, research, joined = 0, 0, 0, 0, 0
        for region in regions:
            raids += self.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('raid_reports',0)
            eggs += self.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('egg_reports',0)
            wilds += self.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('wild_reports',0)
            research += self.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('research_reports',0)
            joined += self.guild_dict[ctx.guild.id]['trainers'].setdefault(region, {}).setdefault(user.id,{}).get('joined',0)
        return [raids, eggs, wilds, research, joined]

    @commands.command()
    async def leaderboard(self, ctx, type="total", region=None):
        """**Usage**: `!leaderboard [type] [region]`
        Accepted types: raids, eggs, wilds, research, joined
        Region must be any configured region"""
        guild = ctx.guild
        leaderboard = {}
        rank = 1
        field_value = ""
        typelist = ["total", "raids", "eggs", "exraids", "wilds", "research", "joined"]
        type = type.lower()
        regions = list(self.guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
        if type not in typelist:
            if type in regions:
                region = type
                type = "total"
            else:
                return await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Leaderboard type not supported. Please select from: **{', '.join(typelist)}**"))
        if region is not None:
            region = region.lower()
            if region in regions:
                regions = [region]
            else:
                return await ctx.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No region found with name {region}"))
        for region in regions:
            trainers = copy.deepcopy(self.guild_dict[guild.id]['trainers'].setdefault(region, {}))
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
                trainer_stats = {'trainer':trainer, 'total':total_reports, 'raids':raids, 'wilds':wilds, 'research':research, 'exraids':exraids, 'eggs':eggs, 'joined':joined}
                if trainer_stats[type] > 0 and user:
                    if trainer in leaderboard:
                        leaderboard[trainer] = self.combine_dicts(leaderboard[trainer], trainer_stats)
                    else:
                        leaderboard[trainer] = trainer_stats
        leaderboardlist = []
        for key, value in leaderboard.items():
            leaderboardlist.append(value)
        leaderboardlist = sorted(leaderboardlist,key= lambda x: x[type], reverse=True)[:10]
        embed = discord.Embed(colour=guild.me.colour)
        leaderboard_title = f"Reporting Leaderboard ({type.title()})"
        if len(regions) == 1:
            leaderboard_title += f" {region.capitalize()}"
        embed.set_author(name=leaderboard_title, icon_url=self.bot.user.avatar_url)
        for trainer in leaderboardlist:
            user = guild.get_member(int(trainer['trainer']))
            if user:
                if self.guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                    field_value += "Raids: **{raids}** | Eggs: **{eggs}** | ".format(raids=trainer['raids'], eggs=trainer['eggs'])
                if self.guild_dict[guild.id]['configure_dict']['exraid']['enabled']:
                    field_value += "EX Raids: **{exraids}** | ".format(exraids=trainer['exraids'])
                if self.guild_dict[guild.id]['configure_dict']['wild']['enabled']:
                    field_value += "Wilds: **{wilds}** | ".format(wilds=trainer['wilds'])
                if self.guild_dict[guild.id]['configure_dict']['research']['enabled']:
                    field_value += "Research: **{research}** | ".format(research=trainer['research'])
                if self.guild_dict[guild.id]['configure_dict']['raid']['enabled']:
                    field_value += "Raids Joined: **{joined}** | ".format(joined=trainer['joined'])
                embed.add_field(name=f"{rank}. {user.display_name} - {type.title()}: **{trainer[type]}**", value=field_value[:-3], inline=False)
                field_value = ""
                rank += 1
        if len(embed.fields) == 0:
            embed.add_field(name="No Reports", value="Nobody has made a report or this report type is disabled.")
        await ctx.send(embed=embed)

    @staticmethod
    def combine_dicts(a, b):
        for key,value in a.items():
            if key != 'trainer':
                a[key] = a[key] + b[key]
        return a

def setup(bot):
    bot.add_cog(Social(bot))
