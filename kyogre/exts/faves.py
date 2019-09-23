from discord.ext import commands

from kyogre.exts.db.kyogredb import *


class Faves(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True, aliases=['tsq'])
    @commands.has_permissions(manage_roles=True)
    async def testsql(self, ctx):
        for sub_type in ['research', 'wild', 'pokemon']:
            result = (SubscriptionTable
                      .select(SubscriptionTable.target, fn.Count(SubscriptionTable.target).alias('count'))
                      .where(SubscriptionTable.type == sub_type)
                      .group_by(SubscriptionTable.target)
                      .order_by(SQL('count').desc())
                      .limit(10))
            result_str = f"**{sub_type}** subscriptions:\n"
            for r in result:
                result_str += f"target: {r.target}, count: {r.count}\n"
            await ctx.send(result_str)

    async def build_top_sub_lists(self, guild):
        results = {}
        out_results = {'research': {},
                       'wild': {}}
        # get the count of all subs for these 3 categories
        for sub_type in ['research', 'wild', 'pokemon']:
            results[sub_type] = self._get_top_subs_per_type([sub_type])
        # preload the outgoing results with research and wild counts
        for sub_type in ['research', 'wild']:
            for r in results[sub_type]:
                out_results[sub_type][r.target] = r.count
        # 'pokemon' type subs count for both wild and research so add those counts to the outgoing
        for r in results['pokemon']:
            if r.target in out_results['research']:
                out_results['research'][r.target] += r.count
            else:
                out_results['research'][r.target] = r.count
            if r.target in out_results['wild']:
                out_results['wild'][r.target] += r.count
            else:
                out_results['wild'][r.target] = r.count
        # pull the configured limit from the config_dict, use default of 10 if none found
        limit = self.bot.guild_dict[guild.id]['configure_dict'].get('subscriptions', {}).get('leaderboard_limit', 10)
        # sort and limit the outgoing
        out_results['research'] = sorted(out_results['research'].items(), key=lambda t: t[1], reverse=True)[:limit]
        out_results['wild'] = sorted(out_results['wild'].items(), key=lambda t: t[1], reverse=True)[:limit]
        # build the final leaderboard message
        leaderboard_str = '**Top Subscriptions per type**\n'
        leaderboard_str += self._build_category_list(out_results, 'wild', '\n**Wild Spawns**\n')
        leaderboard_str += self._build_category_list(out_results, 'research', '\n**Research Rewards**\n')
        return leaderboard_str

    @staticmethod
    def _build_category_list(results, category, header):
        leaderboard_str = header
        for i in range(0, len(results[category])):
            t_emoji = ''
            if i >= 10:
                t_emoji += str(round(i/10)) + '\u20e3'
            t_emoji += str(i % 10) + '\u20e3'
            leaderboard_str += t_emoji
            leaderboard_str += f" {results[category][i][0]} ({results[category][i][1]})\n"
        return leaderboard_str

    @staticmethod
    def _get_top_subs_per_type(sub_type=None, count=0):
        result = (SubscriptionTable
                  .select(SubscriptionTable.target, fn.Count(SubscriptionTable.target).alias('count'))
                  .group_by(SubscriptionTable.target)
                  .order_by(SQL('count').desc())
                  .limit(count)
                  )
        if sub_type is None or sub_type[0].lower() == 'all':
            return result
        return result.where(SubscriptionTable.type << sub_type)


def setup(bot):
    bot.add_cog(Faves(bot))
