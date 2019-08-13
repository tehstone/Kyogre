import asyncio
import copy
import datetime
import re

import discord
from discord.ext import commands

from kyogre import utils, checks
from kyogre.exts.pokemon import Pokemon


class SetCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='set', case_insensitive=True)
    async def _set(self, ctx):
        """Changes a setting."""
        if ctx.invoked_subcommand is None:
            raise commands.BadArgument()

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def regional(self, ctx, regional):
        """Changes server regional pokemon."""
        regional = regional.lower()
        if regional == "reset" and checks.is_dev_or_owner():
            msg = "Are you sure you want to clear all regionals?"
            question = await ctx.channel.send(msg)
            try:
                timeout = False
                res, reactuser = await utils.simple_ask(self.bot, question, ctx.message.channel, ctx.message.author.id)
            except TypeError:
                timeout = True
            await question.delete()
            if timeout or res.emoji == '❎':
                return
            elif res.emoji == '✅':
                pass
            else:
                return
            guild_dict_copy = copy.deepcopy(self.bot.guild_dict)
            for guildid in guild_dict_copy.keys():
                self.bot.guild_dict[guildid]['configure_dict']['settings']['regional'] = None
            return
        elif regional == 'clear':
            regional = None
            self._set_regional(ctx.guild, regional)
            await ctx.message.channel.send("Regional raid boss cleared!")
            return
        regional = Pokemon.get_pokemon(self.bot, regional)
        if regional.is_raid:
            self._set_regional(ctx.guild, regional)
            await ctx.message.channel.send(f"Regional raid boss set to **{regional.name}**!")
        else:
            await ctx.message.channel.send("That Pokemon doesn't appear in raids!")
            return

    def _set_regional(self, guild, regional):
        self.bot.guild_dict[guild.id]['configure_dict']['settings']['regional'] = regional

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def timezone(self, ctx, *, timezone: str = ''):
        """Changes server timezone."""
        try:
            timezone = float(timezone)
        except ValueError:
            await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! "
                                   "Please double check what you sent me and resend a number from **-12** to **12**.")
            return
        if not ((- 12) <= timezone <= 14):
            await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! "
                                   "Please double check what you sent me and resend a number from **-12** to **12**.")
            return
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset'] = timezone
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset'])
        await ctx.channel.send("Timezone has been set to: `UTC{offset}`\nThe current time is **{now}**".format(
            offset=timezone, now=now.strftime("%H:%M")))        

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def lureminutes(self, ctx, *, minutes: int):
        """Changes lure expiration minutes."""
        
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['lure_minutes'] = minutes
        await ctx.channel.send(f"Lure expiration time changed to {minutes}.")

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def invasionminutes(self, ctx, *, minutes: int):
        """Changes Team Rocket Takeover expiration minutes."""
        
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['invasion_minutes'] = minutes
        await ctx.channel.send(f"Team Rocket Takeover expiration time changed to {minutes}.")

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def prefix(self, ctx, prefix=None):
        """Changes server prefix."""
        if prefix == 'clear':
            prefix = None
        prefix = prefix.strip()
        self._set_prefix(ctx.guild, prefix)
        if prefix is not None:
            await ctx.channel.send('Prefix has been set to: `{}`'.format(prefix))
        else:
            default_prefix = self.bot.config['default_prefix']
            await ctx.channel.send('Prefix has been reset to default: `{}`'.format(default_prefix))

    def _set_prefix(self, guild, prefix):
        self.bot.guild_dict[guild.id]['configure_dict']['settings']['prefix'] = prefix

    @_set.command()
    async def silph(self, ctx, silph_user: str = None):
        """**Usage**: `!set silph <silph username>`
        Links your Silph Trainer Card to your `!profile`"""
        if not silph_user:
            await ctx.send('Silph Road Travelers Card cleared!')
            try:
                del self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['silphid']
            except:
                pass
            card = await self._silph(ctx, silph_user)

            if not card:
                return await ctx.send('Silph Card for {silph_user} not found.'.format(silph_user=silph_user))

            if not card.discord_name:
                return await ctx.send(
                    'No Discord account found linked to this Travelers Card!')

            if card.discord_name != str(ctx.author):
                return await ctx.send(
                    'This Travelers Card is linked to another Discord account!')
        try:
            offset = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset']
        except KeyError:
            offset = None

        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id,{})
        author['silphid'] = silph_user
        trainers.setdefault('info', {})[ctx.author.id] = author
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers

        await ctx.send(
            'This Travelers Card has been successfully linked to you!',
            embed=card.embed(offset))

    async def _silph(self, ctx, silph_user):
        silph_cog = self.bot.cogs.get('Silph')
        if not silph_cog:
            return await ctx.send(
                "The Silph Extension isn't accessible at the moment, sorry!")

        async with ctx.typing():
            return await silph_cog.get_silph_card(silph_user)

    @_set.command(aliases=['pkb'])
    async def pokebattler(self, ctx, pbid: int = 0):
        """**Usage**: `!set pokebattler <pokebattler id>`
        Links your PokeBattler ID to your `!profile`"""
        if not pbid:
            await ctx.send('Pokebattler ID cleared!')
            try:
                del self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['pokebattlerid']
            except:
                pass
            return
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['pokebattlerid'] = pbid
        trainers.setdefault('info', {})[ctx.author.id] = author
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        await ctx.send('Pokebattler ID set to {pbid}!'.format(pbid=pbid))

    @_set.command()
    async def xp(self, ctx, xp: int = 0):
        """**Usage**: `!set xp <current xp>`
        Adds your current xp to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['xp'] = xp
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        return await ctx.message.add_reaction('✅')

    @_set.command(name='friendcode', aliases=['friend_code', 'fc', 'code'])
    async def friend_code(self, ctx, *, code: str = None):
        """**Usage**: `!set friendcode <friend code>`
        Adds your friend code to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['code'] = code
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        return await ctx.message.add_reaction('✅')

    @_set.command(name='trainername', aliases=['name', 'tn'])
    async def _trainername(self, ctx, *, name: str):
        """**Usage**: `!set _trainername <trainer name>`
        Set this if your trainer name is different than your discord name.
        Adds your trainer name to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['trainername'] = name
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        return await ctx.message.add_reaction('✅')

    profile_steps = [{'prompt': "What team are you on?", 'td_key': 'team'},
                     {'prompt': "What is your current xp?", 'td_key': 'xp'},
                     {'prompt': "What is your friend code?", 'td_key': 'code'},
                     {'prompt': "What is your Trainer Name?", 'td_key': 'trainername'},
                     {'prompt': "What is the name on your Silph Road Traveler's Card?", 'td_key': 'silphid'},
                     {'prompt': "What is your PokeBattler ID?", 'td_key': 'pokebattlerid'}]

    @_set.command(name='profile')
    async def profile(self, ctx):
        if not ctx.guild:
            return await ctx.send("Please use this command within a server.")
        await ctx.send("I will message you directly to help you get your profile set up.")
        trainer_dict_copy = copy.deepcopy(self.bot.guild_dict[ctx.guild.id].setdefault('trainers', {})
                                          .setdefault('info', {}).setdefault(ctx.author.id, {}))
        team_role_names = [r.lower() for r in self.bot.team_color_map.keys()]
        for step in self.profile_steps:
            if step['td_key'] == 'team':
                if 'team' in trainer_dict_copy and trainer_dict_copy['team'] is not None:
                    continue
                while True:
                    response = await self._profile_step(ctx, step)
                    if response is None:
                        break
                    if response.lower() not in team_role_names:
                        if response.lower() == 'clear' or response.lower() == 'skip':
                            break
                        if response.lower() == 'cancel' or response.lower() == 'exit':
                            return await ctx.author.send("Profile setup cancelled.")
                        await ctx.author.send(f'**{response}** is not a valid team. Please respond with one of the '
                                              f'following: **{", ".join(team_role_names)}**')
                    else:
                        break
            else:
                response = await self._profile_step(ctx, step)
            if response is None:
                self.bot.help_logger.info(f"{ctx.author.name} took to long on profile step: {step['prompt']}.")
                return await ctx.author.send("You took too long to reply, profile setup cancelled.")
            if response.lower() == 'clear':
                trainer_dict_copy[step['td_key']] = None
            elif response.lower() == 'skip':
                continue
            elif response.lower() == 'cancel' or response.lower() == 'exit':
                self.bot.help_logger.info(f"{ctx.author.name} cancelled on profile step: {step['prompt']}.")
                return await ctx.author.send("Profile setup cancelled.")
            else:
                if step['td_key'] == 'silphid':
                    card = await self._silph(ctx, response)
                    if not card:
                        await ctx.author.send('Silph Card for {silph_user} not found.'.format(silph_user=response))
                        continue
                    if not card.discord_name:
                        await ctx.author.send('No Discord account found linked to this Travelers Card!')
                        continue
                    if card.discord_name != str(ctx.author):
                        await ctx.author.send('This Travelers Card is linked to another Discord account!')
                        continue
                if step['td_key'] == 'team':
                    has_team = False
                    for team in team_role_names:
                        temp_role = discord.utils.get(ctx.guild.roles, name=team)
                        if temp_role:
                            # and the user has this role,
                            if (temp_role in ctx.author.roles):
                                has_team = True
                    if not has_team:
                        team_role = discord.utils.get(ctx.guild.roles, name=response.lower())
                        if team_role is not None:
                            await ctx.author.add_roles(team_role)
                trainer_dict_copy[step['td_key']] = response
        await ctx.author.send("Great, your profile is all set!")
        self.bot.guild_dict[ctx.guild.id]['trainers']['info'][ctx.author.id] = trainer_dict_copy
        return await ctx.invoke(self.bot.get_command('profile'), user=ctx.author)
    
    async def _profile_step(self, ctx, step):
        embed = discord.Embed(colour=self.bot.user.colour)
        embed.title = step["prompt"]
        description = '\n\nReply with "**clear**" to remove this item from your profile. \n' \
                       'Reply with "**skip**" to continue to the next item. \n' \
                       'Reply with "**cancel**" to exit profile setup.'
        embed.description = description
        await ctx.author.send(embed=embed)
        try:
            response = await self.bot.wait_for('message', timeout=60,
                                               check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            response = None
            pass
        if response is None:
            return None
        return response.clean_content

    @_set.command(name='currentlocation', aliases=['loc', 'location'])
    async def _location(self, ctx, *, info):
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Please provide both latitude and longitude.", delete_after=15)
        try:
            lat = float(info[0])
            lon = float(info[1])
        except ValueError:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Latitude and Longitude must be provided in the following form: "
                                  "`47.23456, -122.65432`", delete_after=15)
        self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})\
            .setdefault(ctx.author.id, {})['location'] = (lat, lon)
        await ctx.message.add_reaction(self.bot.success_react)
    
    @_set.command(name='distance', aliases=['dis'])
    async def _distance(self, ctx, *, info):
        try:
            distance = float(info)
        except ValueError:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Please provide a number of miles.", delete_after=15)
        self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})\
            .setdefault(ctx.author.id, {})['distance'] = distance
        await ctx.message.add_reaction(self.bot.success_react)

    @_set.command(name='short_output', aliases=['so'])
    async def _short_output(self, ctx, *, info):
        guild = ctx.guild
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("Please provide both a region name and a channel name or id.", delete_after=15)
        region = info[0].lower()
        channel_info = ' '.join(info[1:]).lower()
        region_names = self.bot.guild_dict[guild.id]['configure_dict'].get('regions', {}).get('info', None)
        if not region_names:
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send("No regions have been configured for this server.", delete_after=15)
        if region not in region_names.keys():
            await ctx.message.add_reaction(self.bot.failed_react)
            return await ctx.send(f"No region with name: **{region}** found in this server's configuration.",
                                  delete_after=15)
        if channel_info == "none":
            self.bot.guild_dict[guild.id]['configure_dict']['raid'].setdefault('short_output', {})[region] = None
            msg = f"Short output channel removed for **{region}**."
        else:
            channel = None
            name = utils.sanitize_name(channel_info)
            # If a channel mention is passed, it won't be recognized as an int but this for get will succeed
            try:
                channel = discord.utils.get(guild.text_channels, id=int(name))
            except ValueError:
                pass
            if not channel:
                channel = discord.utils.get(guild.text_channels, name=name)
            if not channel:
                await ctx.message.add_reaction(self.bot.failed_react)
                return await ctx.send(f"No channel with name or id: **{channel_info}** "
                                      f"found in this server's channel list.", delete_after=15)
            self.bot.guild_dict[guild.id]['configure_dict']['raid'].setdefault('short_output', {})[region] = channel.id
            msg = f"Short output channel for **{region}** set to **{channel.mention}**"
        await ctx.message.add_reaction(self.bot.success_react)
        return await ctx.send(msg, delete_after=15)


def setup(bot):
    bot.add_cog(SetCommands(bot))
