import datetime
from dateutil.relativedelta import relativedelta

import discord
from discord.ext import commands

from kyogre import checks, utils


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
        """**Usage**: `!join/invite [region]`
        Returns the set invite link.
        Provide a region name to get the invite link for that region."""
        channel = ctx.message.channel
        guild = ctx.message.guild
        join_dict = self.bot.guild_dict[guild.id]['configure_dict'].setdefault('join')
        if join_dict.get('enabled', False):
            if region in join_dict:
                return await channel.send(join_dict[region])
            else:
                return await channel.send(join_dict['general'])

    @commands.command()
    @checks.allowteam()
    async def team(self, ctx, *, content):
        """Set your team role.

        Usage: !team <team name>
        The team roles have to be created manually beforehand by the server administrator."""
        guild = ctx.guild
        toprole = guild.me.top_role.name
        position = guild.me.top_role.position
        team_msg = ' or '.join(['**!team {0}**'.format(team) for team in self.bot.config['team_dict'].keys()])
        high_roles = []
        guild_roles = []
        lowercase_roles = []
        harmony = None
        for role in guild.roles:
            if (role.name.lower() in self.bot.config['team_dict']) and (role.name not in guild_roles):
                guild_roles.append(role.name)
        lowercase_roles = [element.lower() for element in guild_roles]
        for team in self.bot.config['team_dict'].keys():
            if team.lower() not in lowercase_roles:
                try:
                    temp_role = await guild.create_role(name=team.lower(), hoist=False, mentionable=True)
                    guild_roles.append(team.lower())
                except discord.errors.HTTPException:
                    await ctx.channel.send('Maximum guild roles reached.')
                    return
                if temp_role.position > position:
                    high_roles.append(temp_role.name)
        if high_roles:
            await ctx.channel.send('My roles are ranked lower than the following team roles: '
                                   '**{higher_roles_list}**\nPlease get an admin to move my roles above them!'
                                   .format(higher_roles_list=', '.join(high_roles)))
            return
        role = None
        team_split = content.lower().split()
        entered_team = team_split[0]
        entered_team = ''.join([i for i in entered_team if i.isalpha()])
        if entered_team in lowercase_roles:
            index = lowercase_roles.index(entered_team)
            role = discord.utils.get(guild.roles, name=guild_roles[index])
        if 'harmony' in lowercase_roles:
            index = lowercase_roles.index('harmony')
            harmony = discord.utils.get(guild.roles, name=guild_roles[index])
        # Check if user already belongs to a team role by
        # getting the role objects of all teams in team_dict and
        # checking if the message author has any of them.    for team in guild_roles:
        for team in guild_roles:
            temp_role = discord.utils.get(guild.roles, name=team)
            if temp_role:
                # and the user has this role,
                if (temp_role in ctx.author.roles) and (harmony not in ctx.author.roles):
                    # then report that a role is already assigned
                    await ctx.channel.send('You already have a team role!')
                    return
                if role and (role.name.lower() == 'harmony') and (harmony in ctx.author.roles):
                    # then report that a role is already assigned
                    await ctx.channel.send('You are already in Team Harmony!')
                    return
            # If the role isn't valid, something is misconfigured, so fire a warning.
            else:
                await ctx.channel.send('{team_role} is not configured as a role on this server. '
                                       'Please contact an admin for assistance.'.format(team_role=team))
                return
        # Check if team is one of the three defined in the team_dict
        if entered_team not in self.bot.config['team_dict'].keys():
            await ctx.channel.send('"{entered_team}" isn\'t a valid team! Try {available_teams}'
                                   .format(entered_team=entered_team, available_teams=team_msg))
            return
        # Check if the role is configured on the server
        elif role is None:
            await ctx.channel.send('The "{entered_team}" role isn\'t configured on this server! Contact an admin!'
                                   .format(entered_team=entered_team))
        else:
            try:
                if harmony and (harmony in ctx.author.roles):
                    await ctx.author.remove_roles(harmony)
                await ctx.author.add_roles(role)
                await ctx.channel.send('Added {member} to Team {team_name}! {team_emoji}'
                                       .format(member=ctx.author.mention, team_name=role.name.capitalize(),
                                               team_emoji=utils.parse_emoji(guild, self.bot.config['team_dict'][entered_team])))
                await ctx.author.send("Now that you've set your team, "
                                      "head to <#538883360953729025> to set up your desired regions")
            except discord.Forbidden:
                await ctx.channel.send("I can't add roles!")


def setup(bot):
    bot.add_cog(Misc(bot))
