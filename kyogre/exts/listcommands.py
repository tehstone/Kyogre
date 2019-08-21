import asyncio
import copy
import datetime

import discord
from discord.ext import commands

from kyogre import checks, utils


class ListCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="list", aliases=['lists'], case_insensitive=True)
    async def _list(self, ctx):
        if ctx.invoked_subcommand is None:
            listmsg = ""
            guild = ctx.guild
            channel = ctx.channel
            now = datetime.datetime.utcnow() + datetime.timedelta(
                hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
            if checks.check_raidreport(ctx) or checks.check_exraidreport(ctx):
                raid_dict = self.bot.guild_dict[guild.id]['configure_dict']['raid']
                if raid_dict.get('listings', {}).get('enabled', False):
                    msg = await ctx.channel.send("*Raid list command disabled when listings are provided by server*")
                    await asyncio.sleep(10)
                    await msg.delete()
                    await ctx.message.delete()
                    return
                region = None
                if self.bot.guild_dict[guild.id]['configure_dict'].get('regions', {}).get('enabled', False) \
                        and raid_dict.get('categories', None) == 'region':
                    region = raid_dict.get('category_dict', {}).get(channel.id, None)
                listmgmt_cog = self.bot.cogs.get('ListManagement')
                listmsg = await listmgmt_cog.get_listing_messages('raid', channel, region)
            elif checks.check_raidactive(ctx):
                newembed = discord.Embed(colour=discord.Colour.purple(), title="Trainer Status List")
                blue_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['mystic'])
                red_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['valor'])
                yellow_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['instinct'])
                team_emojis = {'instinct': yellow_emoji, 'mystic': blue_emoji, 'valor': red_emoji, 'unknown': "❔"}
                team_list = ["mystic", "valor", "instinct", "unknown"]
                status_list = ["maybe", "coming", "here"]
                trainer_dict = copy.deepcopy(self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
                status_dict = {'maybe': {'total': 0, 'trainers': {}}, 'coming': {'total': 0, 'trainers': {}},
                               'here': {'total': 0, 'trainers': {}}, 'lobby': {'total': 0, 'trainers': {}}}
                for trainer in trainer_dict:
                    for status in status_list:
                        if trainer_dict[trainer]['status'][status]:
                            status_dict[status]['trainers'][trainer] = {'mystic': 0, 'valor': 0, 'instinct': 0,
                                                                        'unknown': 0}
                            for team in team_list:
                                if trainer_dict[trainer]['party'][team] > 0:
                                    status_dict[status]['trainers'][trainer][team] = trainer_dict[trainer]['party'][
                                        team]
                                    status_dict[status]['total'] += trainer_dict[trainer]['party'][team]
                for status in status_list:
                    embed_value = None
                    if status_dict[status]['total'] > 0:
                        embed_value = u"\u200B"
                        for trainer in status_dict[status]['trainers']:
                            member = channel.guild.get_member(trainer)
                            if member is not None:
                                embed_value += f"{member.display_name} "
                                for team in status_dict[status]['trainers'][trainer]:
                                    embed_value += team_emojis[team] * status_dict[status]['trainers'][trainer][team]
                                embed_value += "\n"
                    if embed_value is not None:
                        newembed.add_field(name=f'**{status.capitalize()}**', value=embed_value, inline=True)
                if len(newembed.fields) < 1:
                    newembed.description = "No one has RSVPd for this raid yet."
                await channel.send(embed=newembed)
            else:
                raise checks.errors.CityRaidChannelCheckFail()

    @_list.command()
    @checks.activechannel()
    async def interested(self, ctx, tags: str = ''):
        """Lists the number and users who are interested in the raid.

        Usage: !list interested
        Works only in raid channels."""
        if tags and tags.lower() == "tags" or tags.lower() == "tag":
            tags = True
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.interest(ctx, self.bot, tags)
        await ctx.channel.send(listmsg)

    @_list.command()
    @checks.activechannel()
    async def coming(self, ctx, tags: str = ''):
        """Lists the number and users who are coming to a raid.

        Usage: !list coming
        Works only in raid channels."""
        if tags and tags.lower() == "tags" or tags.lower() == "tag":
            tags = True
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.otw(ctx, self.bot, tags)
        await ctx.channel.send(listmsg)

    @_list.command()
    @checks.activechannel()
    async def here(self, ctx, tags: str = ''):
        """List the number and users who are present at a raid.

        Usage: !list here
        Works only in raid channels."""
        if tags and tags.lower() == "tags" or tags.lower() == "tag":
            tags = True
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.waiting(ctx, self.bot, tags)
        await ctx.channel.send(listmsg)

    @_list.command()
    @checks.activeraidchannel()
    async def lobby(self, ctx, tag=False):
        """List the number and users who are in the raid lobby.

        Usage: !list lobby
        Works only in raid channels."""
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.lobbylist(ctx, self.bot)
        await ctx.channel.send(listmsg)

    @_list.command()
    @checks.activeraidchannel()
    async def bosses(self, ctx):
        """List each possible boss and the number of users that have RSVP'd for it.

        Usage: !list bosses
        Works only in raid channels."""
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.bosslist(ctx, self.bot)
        if len(listmsg) > 0:
            await ctx.channel.send(listmsg)

    @_list.command()
    @checks.activechannel()
    async def teams(self, ctx):
        """List the teams for the users that have RSVP'd to a raid.

        Usage: !list teams
        Works only in raid channels."""
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        listmsg = await listmgmt_cog.teamlist(ctx, self.bot)
        await ctx.channel.send(listmsg)


def setup(bot):
    bot.add_cog(ListCommands(bot))
