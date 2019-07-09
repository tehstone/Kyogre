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
            'message': ctx.message,
            'guild_dict': ctx.bot.guild_dict
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

    @commands.command(name='save')
    @checks.is_owner()
    async def save_command(self, ctx):
        """Save persistent state to file.

        Usage: !save
        File path is relative to current directory."""
        try:
            await self.save(ctx.guild.id)
            self.bot.logger.info('CONFIG SAVED')
            await ctx.message.add_reaction('✅')
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)

    async def save(self, guildid):
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
            await self.save(ctx.guild.id)
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
            await self.save(ctx.guild.id)
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)
        await ctx.channel.send('Shutting down...')
        self.bot._shutdown_mode = 0
        await self.bot.logout()

    @commands.command(name='load')
    @checks.is_owner()
    async def _load(self, ctx, *extensions):
        for ext in extensions:
            try:
                self.bot.load_extension(f"kyogre.exts.{ext}")
            except Exception as e:
                error_title = '**Error when loading extension'
                await ctx.send(f'{error_title} {ext}:**\n'
                               f'{type(e).__name__}: {e}')
            else:
                await ctx.send('**Extension {ext} Loaded.**\n'.format(ext=ext))

    @commands.command(name='reload')
    @checks.is_owner()
    async def _reload(self, ctx, *extensions):
        for ext in extensions:
            try:
                self.bot.reload_extension(f"kyogre.exts.{ext}")
            except Exception as e:
                error_title = '**Error when reloading extension'
                await ctx.send(f'{error_title} {ext}:**\n'
                               f'{type(e).__name__}: {e}')
            else:
                await ctx.send('**Extension {ext} Reloaded.**\n'.format(ext=ext))

    @commands.command(name='unload')
    @checks.is_owner()
    async def _unload(self, ctx, *extensions):
        exts = [ex for ex in extensions if f"kyogre.exts.{ex}" in self.bot.extensions]
        for ex in exts:
            self.bot.unload_extension(f"kyogre.exts.{ex}")
        s = 's' if len(exts) > 1 else ''
        await ctx.send("**Extension{plural} {est} unloaded.**\n".format(plural=s, est=', '.join(exts)))

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx, user: discord.Member=None):
        """Test welcome on yourself or mentioned member.

        Usage: !welcome [@member]"""
        if (not user):
            user = ctx.author
        await self.bot.on_member_join(user)

    @commands.command(hidden=True,aliases=['opl'])
    @commands.has_permissions(manage_guild=True)
    async def outputlog(self, ctx):
        """Get current Kyogre log.

        Usage: !outputlog
        Replies with a file download of the current log file."""
        with open(os.path.join('logs', 'kyogre.log'), 'rb') as logfile:
            await ctx.send(file=discord.File(logfile, filename=f'log{int(time.time())}.txt'))


    @commands.command(aliases=['say'])
    @commands.has_permissions(manage_guild=True)
    async def announce(self, ctx, *, announce=None):
        """Repeats your message in an embed from Kyogre.

        Usage: !announce [announcement]
        If the announcement isn't added at the same time as the command, Kyogre will wait 3 minutes for a followup message containing the announcement."""
        message = ctx.message
        channel = message.channel
        guild = message.guild
        author = message.author
        announcetitle = 'Announcement'
        if announce == None:
            titlewait = await channel.send("If you would like to set a title for your announcement please reply with the title, otherwise reply with 'skip'.")
            titlemsg = await self.bot.wait_for('message', timeout=180, check=(lambda reply: reply.author == message.author))
            await titlewait.delete()
            if titlemsg != None:
                if titlemsg.content.lower() == "skip":
                    pass
                else:
                    announcetitle = titlemsg.content
                await titlemsg.delete()
            announcewait = await channel.send("I'll wait for your announcement!")
            announcemsg = await self.bot.wait_for('message', timeout=180, check=(lambda reply: reply.author == message.author))
            await announcewait.delete()
            if announcemsg != None:
                announce = announcemsg.content
                await announcemsg.delete()
            else:
                confirmation = await channel.send("You took too long to send me your announcement! Retry when you're ready.")
        embeddraft = discord.Embed(colour=guild.me.colour, description=announce)
        if ctx.invoked_with == "announce":
            title = announcetitle
            if self.bot.user.avatar_url:
                embeddraft.set_author(name=title, icon_url=self.bot.user.avatar_url)
            else:
                embeddraft.set_author(name=title)
        draft = await channel.send(embed=embeddraft)
        reaction_list = ['❔', '✅', '❎']
        owner_msg_add = ''
        if checks.is_owner_check(ctx):
            owner_msg_add = '🌎 '
            owner_msg_add += 'to send it to all servers, '
            reaction_list.insert(0, '🌎')

        def check(reaction, user):
            if user.id == author.id:
                if (str(reaction.emoji) in reaction_list) and (reaction.message.id == rusure.id):
                    return True
            return False
        msg = "That's what you sent, does it look good? React with "
        msg += "{}❔ "
        msg += "to send to another channel, "
        msg += "✅ "
        msg += "to send it to this channel, or "
        msg += "❎ "
        msg += "to cancel"
        rusure = await channel.send(msg.format(owner_msg_add))
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(self.bot, rusure, channel, author.id, react_list=reaction_list)
        except TypeError:
            timeout = True
        if not timeout:
            await rusure.delete()
            if res.emoji == '❎':
                confirmation = await channel.send('Announcement Cancelled.')
                await draft.delete()
            elif res.emoji == '✅':
                confirmation = await channel.send('Announcement Sent.')
            elif res.emoji == '❔':
                channelwait = await channel.send('What channel would you like me to send it to?')
                channelmsg = await self.bot.wait_for('message', timeout=60, check=(lambda reply: reply.author == message.author))
                if channelmsg.content.isdigit():
                    sendchannel = self.bot.get_channel(int(channelmsg.content))
                elif channelmsg.raw_channel_mentions:
                    sendchannel = self.bot.get_channel(channelmsg.raw_channel_mentions[0])
                else:
                    sendchannel = discord.utils.get(guild.text_channels, name=channelmsg.content)
                if (channelmsg != None) and (sendchannel != None):
                    announcement = await sendchannel.send(embed=embeddraft)
                    confirmation = await channel.send('Announcement Sent.')
                elif sendchannel == None:
                    confirmation = await channel.send("That channel doesn't exist! Retry when you're ready.")
                else:
                    confirmation = await channel.send("You took too long to send me your announcement! Retry when you're ready.")
                await channelwait.delete()
                await channelmsg.delete()
                await draft.delete()
            elif (res.emoji == '🌎') and checks.is_owner_check(ctx):
                failed = 0
                sent = 0
                count = 0
                recipients = {

                }
                embeddraft.set_footer(text='For support, contact us on our Discord server. Invite Code: hhVjAN8')
                embeddraft.colour = discord.Colour.lighter_grey()
                for guild in self.bot.guilds:
                    recipients[guild.name] = guild.owner
                for (guild, destination) in recipients.items():
                    try:
                        await destination.send(embed=embeddraft)
                    except discord.HTTPException:
                        failed += 1
                        logger.info('Announcement Delivery Failure: {} - {}'.format(destination.name, guild))
                    else:
                        sent += 1
                    count += 1
                logger.info('Announcement sent to {} server owners: {} successful, {} failed.'.format(count, sent, failed))
                confirmation = await channel.send('Announcement sent to {} server owners: {} successful, {} failed.').format(count, sent, failed)
            await asyncio.sleep(10)
            await confirmation.delete()
        else:
            await rusure.delete()
            confirmation = await channel.send('Announcement Timed Out.')
            await asyncio.sleep(10)
            await confirmation.delete()
        await asyncio.sleep(30)
        await message.delete()

    @commands.command()
    @checks.allowarchive()
    async def archive(self, ctx):
        """Marks a raid channel for archival.

        Usage: !archive"""
        message = ctx.message
        channel = message.channel
        await ctx.message.delete()
        self.guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['archive'] = True

def setup(bot):
    bot.add_cog(AdminCommands(bot))
