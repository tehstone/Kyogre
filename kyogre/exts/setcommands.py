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
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
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

    @_set.command(aliases=['pkb', 'pb'])
    async def pokebattler(self, ctx, pbid: int = 0):
        """**Usage**: `!set pokebattler <pokebattler id>`
        Links your PokeBattler ID to your `!profile`"""
        if not pbid:
            await ctx.send('Pokebattler ID cleared!')
            try:
                del self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['pokebattlerid']
            except:
                pass
            return await ctx.message.add_reaction(self.bot.success_react)
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['pokebattlerid'] = pbid
        trainers.setdefault('info', {})[ctx.author.id] = author
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        await ctx.send(f'Pokebattler ID set to {pbid}!')
        return await ctx.message.add_reaction(self.bot.success_react)

    @_set.command()
    async def xp(self, ctx, xp: int = 0):
        """**Usage**: `!set xp <current xp>`
        Adds your current xp to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['xp'] = xp
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        embed = discord.Embed(colour=discord.Colour.green())
        if xp == 0:
            embed.description = "XP count cleared from your profile."
        else:
            embed.description = f"XP count set to {xp} on your profile."
        await ctx.send(embed=embed, delete_after=15)
        if xp > 20000000:
            quickbadge_cog = self.bot.cogs.get('QuickBadge')
            await quickbadge_cog.set_fourty(ctx)
        return await ctx.message.add_reaction(self.bot.success_react)

    @_set.command(name='friend_code', aliases=['friendcode', 'fc', 'code', 'friend'])
    async def _friend_code(self, ctx, *, code: str = None):
        """**Usage**: `!set friendcode <friend code>`
        Adds your friend code to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['code'] = code
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        embed = discord.Embed(colour=discord.Colour.green())
        if not code:
            embed.description = "Friend code cleared from your profile."
        else:
            embed.description = f"Friend code set to {code} on your profile."
        await ctx.send(embed=embed, delete_after=15)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(name='friend_code', aliases=['friendcode', 'fc', 'code', 'friend'])
    async def _friend_code_wrapper(self, ctx, *, code: str = None):
        return await ctx.invoke(self.bot.get_command('set friendcode'), ctx=ctx, code=f"{code}")

    @_set.command(name='trainername', aliases=['name', 'tn'])
    async def _trainername(self, ctx, *, name: str = None):
        """**Usage**: `!set _trainername <trainer name>`
        Set this if your trainer name is different than your discord name.
        Adds your trainer name to your `!profile`"""
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        author = trainers.setdefault('info', {}).get(ctx.author.id, {})
        author['trainername'] = name
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        embed = discord.Embed(colour=discord.Colour.green())
        if not name:
            embed.description = "Trainer name cleared from your profile."
        else:
            embed.description = f"Trainer name set to {name} on your profile."
        await ctx.send(embed=embed, delete_after=15)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(name='trainername', aliases=['name', 'tn'])
    async def _trainername_wrapper(self, ctx, *, name: str = None):
        return await ctx.invoke(self.bot.get_command('set trainername'), ctx=ctx, name=f"{name}")

    @_set.command(name='team')
    async def _team(self, ctx, *, new_team: str):
        new_team = new_team.lower()
        utilities_cog = self.bot.cogs.get('Utilities')
        team = await utilities_cog.member_has_team_set(ctx)
        if team:
            err_msg = f"{ctx.author.mention} your team is already set. Ask for help if you need to change it."
            return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=err_msg))
        team_role = discord.utils.get(ctx.guild.roles, name=new_team)
        if team_role is None:
            err_msg = f"{ctx.author.mention} sorry, I don't recognize {new_team} as a valid team."
            return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=err_msg))
        await ctx.author.add_roles(team_role)
        team_emoji = utils.parse_emoji(ctx.channel.guild, self.bot.config['team_dict'][new_team])
        success_msg = f"{ctx.author.mention} your team has been set to {team_emoji} {new_team}!"
        return await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=success_msg))

    @commands.command(name='valor')
    async def _valor(self, ctx):
        return await ctx.invoke(self.bot.get_command('set team'), new_team=f"valor")

    @commands.command(name='mystic')
    async def _mystic(self, ctx):
        return await ctx.invoke(self.bot.get_command('set team'), new_team=f"mystic")

    @commands.command(name='instinct')
    async def _instinct(self, ctx):
        return await ctx.invoke(self.bot.get_command('set team'), new_team=f"instinct")

    @commands.command(name='verify_profile', aliases=['verify'])
    async def _verify_profile(self, ctx):
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers', {})
        trainer_info = trainers.get('info', {})
        welcome_dict = self.bot.guild_dict[ctx.guild.id]['configure_dict'] \
            .get('welcome', {'enabled': False, 'welcomechan': '', 'welcomemsg': ''})
        new_user_role_id = welcome_dict.get("new_user_role", None)
        verified_role_id = welcome_dict.get("verified_role", None)
        new_user_role, verified_role = None, None
        if new_user_role_id and verified_role_id:
            new_user_role = ctx.guild.get_role(new_user_role_id)
            verified_role = ctx.guild.get_role(verified_role_id)
        profile_found, trainername_found, friendcode_found, team_found = False, False, False, False
        if ctx.author.id in trainer_info:
            profile_found = True
            author_info = trainer_info[ctx.author.id]
            if "trainername" in author_info:
                trainername_found = True
            if "code" in author_info:
                friendcode_found = True
            if "team" in author_info:
                team_found = True
            if trainername_found and friendcode_found:
                fin_message = (f"{ctx.author.mention} you have successfully set your team, trainer name, and friend code "
                               "and are now verified!\n\n"
                               f"Use the tool in #region-assignment to access the raid channels for the cities you play in.\n"
                               f"See the infographics in #kyogre-how-to to learn how to use our helpful bot Kyogre.\n\n"
                               "You can finish setting up your profile with the following:\n"
                               "`!set xp current_xp`\n`!set silph silph_trainer_name`\n`!set pokebattler pokebattler_id`"
                               "\n\nor do `!set profile` to have Kyogre walk you through it.")
                region_channel = self.bot.get_channel(538883360953729025)
                how_to_channel = self.bot.get_channel(595818446906720256)
                if region_channel and how_to_channel:
                    fin_message = (
                        f"{ctx.author.mention} you have successfully set your team, trainer name, and friend code "
                        "and are now verified!\n\n"
                        f"Use the tool in {region_channel.mention} to access the raid channels for the cities you play in.\n"
                        f"See the infographics in {how_to_channel.mention} to learn how to use our helpful bot Kyogre.\n\n"
                        "You can finish setting up your profile with the following:\n"
                        "`!set xp current_xp`\n`!set silph silph_trainer_name`\n`!set pokebattler pokebattler_id`"
                        "\n\nor do `!set profile` to have Kyogre walk you through it.")

                await ctx.send(fin_message)
                if verified_role:
                    await ctx.author.add_roles(verified_role)
                if new_user_role:
                    try:
                        await ctx.author.remove_roles(new_user_role)
                    except Exception as e:
                        self.bot.logger.warn(f"failed to remove new user role:\n{e}")
                else:
                    self.bot.logger.warn("no new user role found")
                return

        failed_message = ""
        if not profile_found:
            failed_message = "You still need to set your trainer name and your friend code like so:\n" \
                             "`!set team team_name` using 'Instinct', 'Mystic', or 'Valor'\n" \
                             "`!set trainername my_trainer_name` using your own trainer name\n" \
                             "`!set friendcode my_friendcode` using your own friend code"
        else:
            if not team_found:
                failed_message += "You still need to set your team like so:\n" \
                                  "`!set team team_name` using 'Instinct', 'Mystic', or 'Valor'\n"
            if not trainername_found:
                failed_message += "You still need to set your trainer name like so:\n" \
                                  "`!set trainername my_trainer_name` using your own trainer name\n"
            if not friendcode_found:
                failed_message += "You still need to set your friend code like so:\n" \
                                  "`!set friendcode my_friendcode` using your own friend code\n"
        return await ctx.send(failed_message)

    profile_steps = [{'prompt': "What team are you on?", 'td_key': 'team'},
             {'prompt': "What is your current xp?\n*Your Total XP, not current amount towards the next level*",
              'td_key': 'xp'},
             {'prompt': "What is your friend code?", 'td_key': 'code'},
             {'prompt': "What is your Trainer Name?", 'td_key': 'trainername'},
             {'prompt': "What is the name on your Silph Road Traveler's Card?\n<https://thesilphroad.com/card>",
              'td_key': 'silphid'},
             {'prompt': "What is your PokeBattler ID?\n<https://www.pokebattler.com/>", 'td_key': 'pokebattlerid'}]

    @_set.command(name='profile')
    async def profile(self, ctx):
        if not ctx.guild:
            return await ctx.send("Please use this command within a server.")
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'] \
            .setdefault('profile_scan_listen_channels', [])
        if ctx.channel.id not in listen_channels:
            if len(listen_channels) > 0:
                listen_channel = ctx.guild.get_channel(listen_channels[0])
                embed = discord.Embed(colour=discord.Colour.red())
                embed.description = f"Please use this command in {listen_channel.mention}."
                try:
                    await ctx.message.delete()
                except:
                    pass
                return await ctx.send(embed=embed, delete_after=15)
        await ctx.send("I will message you directly to help you get your profile set up.")
        try:
            await ctx.author.send("Let's get your profile set up!")
        except discord.Forbidden:
            embed = discord.Embed(colour=discord.Colour.red())
            embed.description = "Your discord settings prevent me from messaging you directly. " \
                                "Unable to set up profile."
            return await ctx.send(embed)
        trainer_dict_copy = copy.deepcopy(self.bot.guild_dict[ctx.guild.id].setdefault('trainers', {})
                                          .setdefault('info', {}).setdefault(ctx.author.id, {}))
        trainer_names_copy = copy.deepcopy(self.bot.guild_dict[ctx.guild.id].setdefault('trainer_names', {}))
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
                        if response.lower() in ['clear', 'skip', '"skip"', '" skip "', "'skip'", "' skip '"]:
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
                if step['td_key'] == 'trainername':
                    t_name = trainer_dict_copy.get('trainername', '')
                    try:
                        del trainer_names_copy[t_name]
                    except KeyError:
                        pass
                trainer_dict_copy[step['td_key']] = None
            elif response.lower() in ['clear', 'skip', '"skip"', '" skip "', "'skip'", "' skip '"]:
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
                            if temp_role in ctx.author.roles:
                                has_team = True
                    if not has_team:
                        team_role = discord.utils.get(ctx.guild.roles, name=response.lower())
                        if team_role is not None:
                            await ctx.author.add_roles(team_role)
                if step['td_key'] == 'trainername':
                    t_name = trainer_dict_copy.get('trainername', '')
                    try:
                        del trainer_names_copy[t_name]
                    except KeyError:
                        pass
                    trainer_names_copy[response] = ctx.author.id
                trainer_dict_copy[step['td_key']] = response
        await ctx.author.send("Great, your profile is all set!")
        self.bot.guild_dict[ctx.guild.id]['trainers']['info'][ctx.author.id] = trainer_dict_copy
        self.bot.guild_dict[ctx.guild.id]['trainer_names'] = trainer_names_copy
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
            response = await self.bot.wait_for('message', timeout=240,
                                               check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            response = None
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

    @_set.command(name='port')
    @checks.is_dev_or_owner()
    async def _port(self, ctx, port: int):
        if port:
            self.bot.port = port
        return await ctx.message.add_reaction(self.bot.success_react)


def setup(bot):
    bot.add_cog(SetCommands(bot))
