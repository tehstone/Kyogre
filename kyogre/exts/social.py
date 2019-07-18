import copy

import discord
from discord.ext import commands


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
        silph = self.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).setdefault(user.id,{}).get('silphid',None)
        if silph:
            card = "Traveler Card"
            silph = f"[{card}](https://sil.ph/{silph.lower()})"
        raids, eggs, wilds, research, joined = await self._get_profile_counts(ctx, user)
        embed = discord.Embed(title="{user}\'s Trainer Profile".format(user=user.display_name), colour=user.colour)
        embed.set_thumbnail(url=user.avatar_url)
        embed.add_field(name="Silph Road", value=f"{silph}", inline=True)
        embed.add_field(name="Pokebattler", value=f"{self.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {}).get('pokebattlerid',None)}", inline=True)
        embed.add_field(name="Raid Reports", value=f"{raids}", inline=True)
        embed.add_field(name="Egg Reports", value=f"{eggs}", inline=True)
        embed.add_field(name="Wild Reports", value=f"{wilds}", inline=True)
        embed.add_field(name="Research Reports", value=f"{research}", inline=True)
        embed.add_field(name="Raids Joined", value=f"{joined}", inline=True)
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
