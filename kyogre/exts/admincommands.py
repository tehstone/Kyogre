import errno
import io
import os
import pickle
import sys
import textwrap
import tempfile
import traceback

from contextlib import redirect_stdout

import discord
from discord.ext import commands

from kyogre import utils, checks


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True, name='mention_toggle', aliases=['mt'])
    @commands.has_permissions(manage_roles=True)
    async def mention_toggle(self, ctx, rolename):
        role = discord.utils.get(ctx.guild.roles, name=rolename)
        if role:
            await role.edit(mentionable=not role.mentionable)
            if role.mentionable:
                outcome = "on"
            else:
                outcome = "off"
            confirmation = await ctx.channel.send(f"{rolename} mention turned {outcome}")
            return await utils.sleep_and_cleanup([ctx.message, confirmation], 5)
        else:
            await ctx.message.add_reaction('❎')

    @commands.command(hidden=True, name="eval")
    @checks.is_dev_or_owner()
    async def _eval(self, ctx, *, body: str):
        """Evaluates a code"""
        env = {
            'bot': ctx.bot,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message
        }

        def cleanup_code(content):
            """Automatically removes code blocks from the code."""
            # remove ```py\n```
            if content.startswith('```') and content.endswith('```'):
                return '\n'.join(content.split('\n')[1:-1])
            # remove `foo`
            return content.strip('` \n')

        env.update(globals())
        body = cleanup_code(body)
        stdout = io.StringIO()
        to_compile = (f'async def func():\n{textwrap.indent(body, "  ")}')
        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')
        func = env['func']
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except:
                pass
            if ret is None:
                if value:
                    paginator = commands.Paginator(prefix='```py')
                    for line in textwrap.wrap(value, 80):
                        paginator.add_line(line.rstrip().replace('`', '\u200b`'))
                    for p in paginator.pages:
                        await ctx.send(p)
            else:
                ctx.bot._last_result = ret
                await ctx.send(f'```py\n{value}{ret}\n```')

    @commands.command()
    @checks.is_owner()
    async def save(self, ctx):
        """Save persistent state to file.

        Usage: !save
        File path is relative to current directory."""
        try:
            await self._save(ctx.guild.id)
            self.bot.logger.info('CONFIG SAVED')
            await ctx.message.add_reaction('✅')
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)

    async def _save(self, guildid):
        with tempfile.NamedTemporaryFile('wb', dir=os.path.dirname(os.path.join('data', 'serverdict')),
                                         delete=False) as tf:
            pickle.dump(self.bot.guild_dict, tf, -1)
            tempname = tf.name
        try:
            os.remove(os.path.join('data', 'serverdict_backup'))
        except OSError as e:
            pass
        try:
            os.rename(os.path.join('data', 'serverdict'), os.path.join('data', 'serverdict_backup'))
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        os.rename(tempname, os.path.join('data', 'serverdict'))

        location_matching_cog = self.bot.cogs.get('LocationMatching')
        if not location_matching_cog:
            await self._print(self.bot.owner, 'Pokestop and Gym data not saved!')
            return None
        stop_save = location_matching_cog.saveStopsToJson(guildid)
        gym_save = location_matching_cog.saveGymsToJson(guildid)
        if stop_save is not None:
            await self._print(self.bot.owner, f'Failed to save pokestop data with error: {stop_save}!')
        if gym_save is not None:
            await self._print(self.bot.owner, f'Failed to save gym data with error: {gym_save}!')

    async def _print(self, owner, message):
        if 'launcher' in sys.argv[1:]:
            if 'debug' not in sys.argv[1:]:
                await owner.send(message)
        print(message)
        self.bot.logger.info(message)

    @commands.command()
    @checks.is_owner()
    async def restart(self, ctx):
        """Restart after saving.

        Usage: !restart.
        Calls the save function and restarts Kyogre."""
        try:
            await self._save(ctx.guild.id)
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)
        await ctx.channel.send('Restarting...')
        self.bot._shutdown_mode = 26
        await self.bot.logout()

    @commands.command()
    @checks.is_owner()
    async def exit(self, ctx):
        """Exit after saving.

        Usage: !exit.
        Calls the save function and quits the script."""
        try:
            await self._save(ctx.guild.id)
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)
        await ctx.channel.send('Shutting down...')
        self.bot._shutdown_mode = 0
        await self.bot.logout()


def setup(bot):
    bot.add_cog(AdminCommands(bot))
