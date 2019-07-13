import datetime
from dateutil.relativedelta import relativedelta

import discord
from discord.ext import commands

from kyogre import checks


class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='uptime')
    async def cmd_uptime(self, ctx):
        "Shows Kyogre's uptime"
        guild = ctx.guild
        channel = ctx.channel
        embed_colour = guild.me.colour or discord.Colour.lighter_grey()
        uptime_str = await self._uptime()
        embed = discord.Embed(colour=embed_colour, icon_url=self.bot.user.avatar_url)
        embed.add_field(name='Uptime', value=uptime_str)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            await channel.send('I need the `Embed links` permission to send this')

    async def _uptime(self):
        'Shows info about Kyogre'
        time_start = self.bot.uptime
        time_now = datetime.datetime.now()
        ut = relativedelta(time_now, time_start)
        (ut.years, ut.months, ut.days, ut.hours, ut.minutes)
        if ut.years >= 1:
            uptime = '{yr}y {mth}m {day}d {hr}:{min}'.format(yr=ut.years, mth=ut.months, day=ut.days, hr=ut.hours, min=ut.minutes)
        elif ut.months >= 1:
            uptime = '{mth}m {day}d {hr}:{min}'.format(mth=ut.months, day=ut.days, hr=ut.hours, min=ut.minutes)
        elif ut.days >= 1:
            uptime = '{day} days {hr} hrs {min} mins'.format(day=ut.days, hr=ut.hours, min=ut.minutes)
        elif ut.hours >= 1:
            uptime = '{hr} hrs {min} mins {sec} secs'.format(hr=ut.hours, min=ut.minutes, sec=ut.seconds)
        else:
            uptime = '{min} mins {sec} secs'.format(min=ut.minutes, sec=ut.seconds)
        return uptime

    @commands.command()
    async def about(self, ctx):
        'Shows info about Kyogre'
        repo_url = 'https://github.com/klords/Kyogre'
        owner = self.bot.owner
        channel = ctx.channel
        uptime_str = await self._uptime()
        yourserver = ctx.message.guild.name
        yourmembers = len(ctx.message.guild.members)
        embed_colour = ctx.guild.me.colour or discord.Colour.lighter_grey()
        about = "I'm Kyogre! A Pokemon Go helper bot for Discord!\n\nI'm a variant of the open-source Kyogre bot made by FoglyOgly.\n\nFor questions or feedback regarding Kyogre, please contact us on [our GitHub repo]({repo_url})\n\n".format(repo_url=repo_url)
        member_count = 0
        guild_count = 0
        for guild in self.bot.guilds:
            guild_count += 1
            member_count += len(guild.members)
        embed = discord.Embed(colour=embed_colour, icon_url=self.bot.user.avatar_url)
        embed.add_field(name='About Kyogre', value=about, inline=False)
        embed.add_field(name='Owner', value=owner)
        if guild_count > 1:
            embed.add_field(name='Servers', value=guild_count)
            embed.add_field(name='Members', value=member_count)
        embed.add_field(name="Your Server", value=yourserver)
        embed.add_field(name="Your Members", value=yourmembers)
        embed.add_field(name='Uptime', value=uptime_str)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            await channel.send('I need the `Embed links` permission to send this')

    @commands.command(aliases=["invite"])
    @checks.allowjoin()
    async def join(self, ctx, region='general'):
        channel = ctx.message.channel
        guild = ctx.message.guild
        join_dict = self.bot.guild_dict[guild.id]['configure_dict'].setdefault('join')
        if join_dict.get('enabled', False):
            if region in join_dict:
                return await channel.send(join_dict[region])
            else:
                return await channel.send(join_dict['general'])

def setup(bot):
    bot.add_cog(Misc(bot))
