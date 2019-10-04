import os
import requests
import shutil
import time

import discord
from discord.ext import commands

from kyogre.exts.db.kyogredb import *
from kyogre import testident

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
            results[sub_type] = self._get_top_subs_per_type(guild.id, [sub_type])
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
        # Update the top subs table used to count personal stats when a report is made
        self._update_top_subs_table(guild.id, out_results)
        # build the final leaderboard message
        leaderboard_str = '**The following lists are the most popular Subscriptions per type**\n'
        leaderboard_str += self._build_category_list(out_results, 'wild', '\n**Wild Spawns**\n')
        leaderboard_str += self._build_category_list(out_results, 'research', '\n**Research Rewards**\n')
        sub_channel_ids = self.bot.guild_dict[guild.id]['configure_dict']\
            .get('subscriptions', {}).get('report_channels', [])
        if len(sub_channel_ids) > 0:
            channel_str = ''
            for channel_id in sub_channel_ids:
                sub_channel = guild.get_channel(channel_id)
                channel_str += f" {sub_channel.mention}"
            leaderboard_str += "\nIf you'd like to set up notifications for the Pokemon you're hoping to catch "
            leaderboard_str += f"you can set up subscriptions of your own in {channel_str}."
            leaderboard_str += "\nComing soon: Reporting things from this list will count for extra points towards "
            leaderboard_str += "your personal leaderboard scores!"
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
    def _get_top_subs_per_type(guild_id, sub_type=None, count=0):
        result = (SubscriptionTable
                  .select(SubscriptionTable.target, fn.Count(SubscriptionTable.target).alias('count'))
                  .where(SubscriptionTable.guild_id == guild_id)
                  .group_by(SubscriptionTable.target)
                  .order_by(SQL('count').desc())
                  .limit(count)
                  )
        if sub_type is None or sub_type[0].lower() == 'all':
            return result
        return result.where(SubscriptionTable.type << sub_type)

    def _update_top_subs_table(self, guild_id, out_results):
        try:
            # First clear out previous entries
            TopSubsTable.delete().where(TopSubsTable.guild_id == guild_id).execute()
            data = []
            # Build data set from new entries
            for key in out_results.keys():
                [data.append((guild_id, i[0], key, i[1])) for i in out_results[key]]
            # Push data to db
            TopSubsTable.insert_many(data, fields=[TopSubsTable.guild_id, TopSubsTable.pokemon,
                                                   TopSubsTable.type, TopSubsTable.count])\
                .execute()
        except Exception as e:
            self.bot.logger.info(f"Failed to update Top Subs Table with error: {e}")

    @staticmethod
    def get_report_points(guild_id, pokemon_list, report_type):
        pokemon_list = [p.name.capitalize() for p in pokemon_list]
        points = 1
        result = (TopSubsTable
                  .select(TopSubsTable.pokemon, TopSubsTable.count)
                  .where(TopSubsTable.guild_id == guild_id)
                  .where(TopSubsTable.type == report_type.lower())
                  .where(TopSubsTable.pokemon << pokemon_list))
        for r in result:
            points += round(r.count/5)
        return points

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id not in [530460439591518218, 629456197501583381] \
                or not self.bot.vision_api_enabled \
                or len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None)):
            return
        await self._process_message_attachments(message)

    async def _process_message_attachments(self, message):
        # TODO Determine if it's worth handling multiple attachments and refactor to accomodate
        file = self._save_image(message.attachments[0])
        if file is None:
            return
        tier = self._determine_raid(file)
        await message.channel.send(tier)
        if tier.startswith("none"):
            self._cleanup_file(file, "screenshots/not_raid")
        else:
            self._cleanup_file(file, f"screenshots/{tier[4]}")
        # if tier == 0:
        #     self._cleanup_file(file, "screenshots/not_raid")
        #     return await message.add_reaction(self.bot.failed_react)
        # raid_info = await self._call_cloud(file)
        # if raid_info["gym"] is None:
        #     self._cleanup_file(file, "screenshots/gcvapi_failed")
        #     return await message.channel.send(
        #         embed=discord.Embed(
        #             colour=discord.Colour.red(),
        #             description="Could not determine gym name from screenshot, unable to create raid channel. "
        #                         "Please report using the command instead: `!r <boss/tier> <gym name> <time>`"))
        #     pass
        # Determine current time based on raid_info["phone"] or just use current time
        # Determine hatch time based on raid_info["egg"] or use default

    def _save_image(self, attachment):
        url = attachment.url
        __, file_extension = os.path.splitext(attachment.filename)
        if not url.startswith('https://cdn.discordapp.com/attachments'):
            return None
        r = requests.get(url, stream=True)
        filename = f"{attachment.id}{file_extension}"
        filepath = os.path.join('screenshots', filename)
        with open(filepath, 'wb') as out_file:
            shutil.copyfileobj(r.raw, out_file)
        self.bot.saved_files[filename] = {"time": round(time.time()), "fullpath": filepath}
        return filepath

    def _determine_raid(self, file):
        # here we call the ident code which will return probabilities for
        # each tier, and none.
        # If None is the highest probability: return 0
        # Else return tier with highest probability
        return testident.determine_tier(file)

    async def _call_cloud(self, file):
        # Hook into cloud api call and process data returned into correct format
        # {"phone": "3:10", "egg": "0:45:47", "gym": ""}
        # The three keys here are required, any and all can be None
        return {"phone": "3:10", "egg": "0:45:47", "gym": None}

    @staticmethod
    def _cleanup_file(file, dst):
        filename = os.path.split(file)[1]
        dest = os.path.join(dst, filename)
        shutil.move(file, dest)


def setup(bot):
    bot.add_cog(Faves(bot))
