import copy
import datetime

from discord.ext import commands

from kyogre import utils, checks
from kyogre.exts.pokemon import Pokemon


class SetCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='set', case_insensitive=True)
    async def _set(self, ctx):
        """Changes a setting."""
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()

    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def regional(self, ctx, regional):
        """Changes server regional pokemon."""
        regional = regional.lower()
        if regional == "reset" and checks.is_dev_or_owner(ctx):
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
        if (not ((- 12) <= timezone <= 14)):
            await ctx.channel.send("I couldn't convert your answer to an appropriate timezone! Please double check what you sent me and resend a number from **-12** to **12**.")
            return
        self._set_timezone(ctx.guild, timezone)
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=self.bot.guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
        await ctx.channel.send("Timezone has been set to: `UTC{offset}`\nThe current time is **{now}**".format(
            offset=timezone, now=now.strftime("%H:%M")))


    def _set_timezone(self, guild, timezone):
        self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'] = timezone


    @_set.command()
    @commands.has_permissions(manage_guild=True)
    async def prefix(self, ctx, prefix=None):
        """Changes server prefix."""
        if prefix == 'clear':
            prefix = None
        prefix = prefix.strip()
        self._set_prefix(ctx.guild, prefix)
        if prefix != None:
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
            return

        silph_cog = self.bot.cogs.get('Silph')
        if not silph_cog:
            return await ctx.send(
                "The Silph Extension isn't accessible at the moment, sorry!")

        async with ctx.typing():
            card = await silph_cog.get_silph_card(silph_user)
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

    @_set.command()
    async def pokebattler(self, ctx, pbid: int = 0):
        """**Usage**: `!set silph <pokebattler id>`
        Links your PokeBattler ID to your `!profile`"""
        if not pbid:
            await ctx.send('Pokebattler ID cleared!')
            try:
                del self.bot.guild_dict[ctx.guild.id]['trainers'].setdefault('info', {})[ctx.author.id]['pokebattlerid']
            except:
                pass
            return
        trainers = self.bot.guild_dict[ctx.guild.id].get('trainers',{})
        author = trainers.setdefault('info', {}).get(ctx.author.id,{})
        author['pokebattlerid'] = pbid
        trainers.setdefault('info', {})[ctx.author.id] = author
        self.bot.guild_dict[ctx.guild.id]['trainers'] = trainers
        await ctx.send('Pokebattler ID set to {pbid}!'.format(pbid=pbid))


def setup(bot):
    bot.add_cog(SetCommands(bot))
