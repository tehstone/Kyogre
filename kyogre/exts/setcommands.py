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
            await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! Please double check what you sent me and resend a number from **-12** to **12**.")
            return
        if not ((- 12) <= timezone <= 14):
            await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! Please double check what you sent me and resend a number from **-12** to **12**.")
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

    profile_steps = [{'prompt': "What is your current xp?", 'td_key': 'xp'},
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
        for step in self.profile_steps:
            response = await self._profile_step(ctx, step)
            if response is None:
                return await ctx.author.send("You took too long to reply, profile setup cancelled.")
            if response.lower() == 'clear':
                trainer_dict_copy[step['td_key']] = None
            elif response.lower() == 'skip':
                continue
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
                trainer_dict_copy[step['td_key']] = response
        await ctx.author.send("Great, your profile is all set!")
        self.bot.guild_dict[ctx.guild.id]['trainers']['info'][ctx.author.id] = trainer_dict_copy
        return await ctx.invoke(self.bot.get_command('profile'), user=ctx.author)
    
    async def _profile_step(self, ctx, step):
        embed = discord.Embed(colour = self.bot.user.colour)
        description = step["prompt"]
        description += '\n\nReply with "clear" to remove this item from your profile. Reply with "skip" to continue to the next item.'
        embed.description = description
        await ctx.author.send(embed=embed)
        try:
            response = await self.bot.wait_for('message', timeout=60,
                                               check=(lambda reply: reply.author == ctx.message.author))
        except asyncio.TimeoutError:
            pass
        if response is None:
            return None
        return response.clean_content

    @_set.command(name='currentlocation', aliases=['cl', 'mylocation'])
    async def _location(self, ctx, *, info):
        info = re.split(r',*\s+', info)
        if len(info) < 2:
            return await ctx.send("Please provide both latitude and longitude.")
        
        pass

def setup(bot):
    bot.add_cog(SetCommands(bot))
