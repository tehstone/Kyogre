import asyncio
import errno
import io
import json
import os
import pickle
import re
import sys
import textwrap
import tempfile
import time
import traceback

from contextlib import redirect_stdout

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.pokemon import Pokemon


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.failed_react = '❌'
        self.success_react = '✅'

    async def cog_command_error(self, ctx, error):
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            ctx.resolved = True
            return await ctx.send_help(ctx.command)
            # if ctx.command.qualified_name == 'tag':
            #     await ctx.send_help(ctx.command)
            # else:
            #     await ctx.send(error)

    @commands.command(hidden=True, name='mentiontoggle', aliases=['mt'])
    @commands.has_permissions(manage_roles=True)
    async def mention_toggle(self, ctx, rolename):
        """**Usage**: `!mention_toggle/mt <role>`
        Enables or disables the "role can be tagged" setting for the role provided.
        """
        role = discord.utils.get(ctx.guild.roles, name=rolename)
        if role is None:
            role = discord.utils.get(ctx.guild.roles, name=rolename.lower())
        if role is None:
            role = discord.utils.get(ctx.guild.roles, name=rolename.capitalize())
        if role:
            await role.edit(mentionable=not role.mentionable)
            if role.mentionable:
                outcome = "on"
            else:
                outcome = "off"
            confirmation = await ctx.channel.send(f"{rolename} mention turned {outcome}")
            return await utils.sleep_and_cleanup([ctx.message, confirmation], 5)
        else:
            await ctx.message.add_reaction(self.failed_react)

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
        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'
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
        """**Usage**: `!save`
        Save persistent state to file, path is relative to current directory."""
        try:
            await self.save(ctx.guild.id)
            self.bot.logger.info('CONFIG SAVED')
            await ctx.message.add_reaction('✅')
        except Exception as err:
            await self._print(self.bot.owner, 'Error occurred while trying to save!')
            await self._print(self.bot.owner, err)

    async def save(self, guildid):
        try:
            with tempfile.NamedTemporaryFile('wb', dir=os.path.dirname(os.path.join('data', 'serverdict')),
                                             delete=False) as tf:
                pickle.dump(self.bot.guild_dict, tf, 4)
                tempname = tf.name
            try:
                os.remove(os.path.join('data', 'serverdict_backup'))
            except OSError:
                os.remove(os.path.join('data', tempname))
            try:
                os.rename(os.path.join('data', 'serverdict'), os.path.join('data', 'serverdict_backup'))
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            os.rename(tempname, os.path.join('data', 'serverdict'))
        except Exception as e:
            self.bot.logger.error(f"Failed to save serverdict. Error: {str(e)}")
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        if not location_matching_cog:
            await self._print(self.bot.owner, 'Pokestop and Gym data not saved!')
            return None
        stop_save = location_matching_cog.save_stops_to_json(guildid)
        gym_save = location_matching_cog.save_gyms_to_json(guildid)
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
        """**Usage**: `!restart`
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
        """**Usage**: `!exit`
        Calls the save function and shuts down the bot.
        **Note**: If running bot through docker, Kyogre will likely restart."""
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

    @commands.command(name='reload', aliases=['rl'])
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
    async def welcome(self, ctx, user: discord.Member = None):
        """**Usage**: `!welcome [@member]`
        Test welcome on yourself or mentioned member"""
        if not user:
            user = ctx.author
        await self.bot.on_member_join(user)

    @commands.command(hidden=True, aliases=['opl'])
    @commands.has_permissions(manage_guild=True)
    async def outputlog(self, ctx):
        """**Usage**: `!outputlog`
        Replies with a file download of the current log file."""
        with open(os.path.join('logs', 'kyogre.log'), 'rb') as logfile:
            await ctx.send(file=discord.File(logfile, filename=f'log{int(time.time())}.txt'))
        with open(os.path.join('logs', 'kyogre_help.log'), 'rb') as logfile:
            await ctx.send(file=discord.File(logfile, filename=f'help_log{int(time.time())}.txt'))
        with open(os.path.join('logs', 'kyogre_user.log'), 'rb') as logfile:
            await ctx.send(file=discord.File(logfile, filename=f'user_log{int(time.time())}.txt'))

    @commands.command(aliases=['say'])
    @commands.has_permissions(manage_guild=True)
    async def announce(self, ctx, *, announce=None):
        """**Usage**: `!announce/say [message]`
        Prompts to provide a title, if no message provided will prompt for message,
        prompts for destination channel.
        """
        message = ctx.message
        channel = message.channel
        guild = message.guild
        author = message.author
        announcetitle = 'Announcement'
        if announce is None:
            titlewait = await channel.send("If you would like to set a title for your announcement "
                                           "please reply with the title, otherwise reply with 'skip'.")
            titlemsg = await self.bot.wait_for('message', timeout=180,
                                               check=(lambda reply: reply.author == message.author))
            await titlewait.delete()
            if titlemsg is not None:
                if titlemsg.content.lower() == "skip":
                    pass
                else:
                    announcetitle = titlemsg.content
                await titlemsg.delete()
            announcewait = await channel.send("I'll wait for your announcement!")
            announcemsg = await self.bot.wait_for('message', timeout=180,
                                                  check=(lambda reply: reply.author == message.author))
            await announcewait.delete()
            if announcemsg is not None:
                announce = announcemsg.content
                await announcemsg.delete()
            else:
                confirmation = await channel.send("You took too long to send me your announcement! "
                                                  "Retry when you're ready.")
        embeddraft = discord.Embed(colour=guild.me.colour, description=announce)
        if ctx.invoked_with == "announce":
            title = announcetitle
            if self.bot.user.avatar_url:
                embeddraft.set_author(name=title, icon_url=self.bot.user.avatar_url)
            else:
                embeddraft.set_author(name=title)
        draft = await channel.send(embed=embeddraft)
        reaction_list = ['❔', self.success_react, self.failed_react]
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
        msg += f"{self.success_react} "
        msg += "to send it to this channel, or "
        msg += f"{self.failed_react} "
        msg += "to cancel"
        rusure = await channel.send(msg.format(owner_msg_add))
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(self.bot, rusure, channel, author.id, react_list=reaction_list)
        except TypeError:
            timeout = True
        if not timeout:
            await rusure.delete()
            if res.emoji == self.failed_react:
                confirmation = await channel.send('Announcement Cancelled.')
                await draft.delete()
            elif res.emoji == self.success_react:
                confirmation = await channel.send('Announcement Sent.')
            elif res.emoji == '❔':
                channelwait = await channel.send('What channel would you like me to send it to?')
                channelmsg = await self.bot.wait_for('message', timeout=60,
                                                     check=(lambda reply: reply.author == message.author))
                if channelmsg.content.isdigit():
                    sendchannel = self.bot.get_channel(int(channelmsg.content))
                elif channelmsg.raw_channel_mentions:
                    sendchannel = self.bot.get_channel(channelmsg.raw_channel_mentions[0])
                else:
                    sendchannel = discord.utils.get(guild.text_channels, name=channelmsg.content)
                if (channelmsg is not None) and (sendchannel is not None):
                    announcement = await sendchannel.send(embed=embeddraft)
                    confirmation = await channel.send('Announcement Sent.')
                elif sendchannel is None:
                    confirmation = await channel.send("That channel doesn't exist! Retry when you're ready.")
                else:
                    confirmation = await channel.send("You took too long to send me your announcement! "
                                                      "Retry when you're ready.")
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
                        self.bot.logger.info('Announcement Delivery Failure: {} - {}'.format(destination.name, guild))
                    else:
                        sent += 1
                    count += 1
                self.bot.logger.info('Announcement sent to {} server owners: {} successful, {} failed.'
                                     .format(count, sent, failed))
                confirmation = await channel.send('Announcement sent to {} server owners: {} successful, {} failed.')\
                    .format(count, sent, failed)
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
        self.bot.guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['archive'] = True

    @commands.command()
    @checks.is_owner()
    async def reload_json(self, ctx):
        """Reloads the JSON files for the server

        Usage: !reload_json
        Useful to avoid a full restart if boss list changed"""
        self.bot._load_config()
        await ctx.message.add_reaction(self.success_react)

    @commands.command()
    @checks.is_dev_or_owner()
    async def raid_json(self, ctx, level=None, *, newlist=None):
        'Edits or displays raid_info.json\n\n    Usage: !raid_json [level] [list]'
        msg = ''
        if (not level) and (not newlist):
            for level in self.bot.raid_info['raid_eggs']:
                msg += '\n**Level {level} raid list:** `{raidlist}` \n'\
                    .format(level=level, raidlist=self.bot.raid_info['raid_eggs'][level]['pokemon'])
                for pkmn in self.bot.raid_info['raid_eggs'][level]['pokemon']:
                    p = Pokemon.get_pokemon(self, pkmn)
                    msg += '{name} ({number})'.format(name=str(p), number=p.id)
                    msg += ' '
                msg += '\n'
            return await ctx.channel.send(msg)
        elif level in self.bot.raid_info['raid_eggs'] and (not newlist):
            msg += '**Level {level} raid list:** `{raidlist}` \n'\
                .format(level=level, raidlist=self.bot.raid_info['raid_eggs'][level]['pokemon'])
            for pkmn in self.bot.raid_info['raid_eggs'][level]['pokemon']:
                p = Pokemon.get_pokemon(self, pkmn)
                msg += '{name} ({number})'.format(name=str(p), number=p.id)
                msg += ' '
            msg += '\n'
            return await ctx.channel.send(msg)
        elif level in self.bot.raid_info['raid_eggs'] and newlist:
            newlist = [re.sub(r'\'', '', item).strip() for item in newlist.strip('[]').split(',')]
            try:
                monlist = [Pokemon.get_pokemon(self, name).name.lower() for name in newlist]
            except:
                return await ctx.channel.send("I couldn't understand the list you supplied! "
                                              "Please use a comma-separated list of Pokemon species names.")
            msg += 'I will replace this:\n'
            msg += '**Level {level} raid list:** `{raidlist}` \n'\
                .format(level=level, raidlist=self.bot.raid_info['raid_eggs'][level]['pokemon'])
            for pkmn in self.bot.raid_info['raid_eggs'][level]['pokemon']:
                p = Pokemon.get_pokemon(self, pkmn)
                msg += '{name} ({number})'.format(name=p.name, number=p.id)
                msg += ' '
            msg += '\n\nWith this:\n'
            msg += '**Level {level} raid list:** `{raidlist}` \n'.format(level=level, raidlist=monlist)
            for p in monlist:
                p = Pokemon.get_pokemon(self, p)
                msg += '{name} ({number})'.format(name=p.name, number=p.id)
                msg += ' '
            msg += '\n\nContinue?'
            question = await ctx.channel.send(msg)
            try:
                timeout = False
                res, reactuser = await utils.simple_ask(self, question, ctx.channel, ctx.author.id)
            except TypeError:
                timeout = True
            if timeout or res.emoji == self.failed_react:
                return await ctx.channel.send("Configuration cancelled!")
            elif res.emoji == self.success_react:
                with open(os.path.join('data', 'raid_info.json'), 'r') as fd:
                    data = json.load(fd)
                data['raid_eggs'][level]['pokemon'] = monlist
                with open(os.path.join('data', 'raid_info.json'), 'w') as fd:
                    json.dump(data, fd, indent=2, separators=(', ', ': '))
                self.bot._load_config()
                await question.clear_reactions()
                await question.add_reaction(self.success_react)
                return await ctx.channel.send("Configuration successful!")
            else:
                return await ctx.channel.send("I'm not sure what went wrong, but configuration is cancelled!")

    @commands.command(aliases=["aj"], hidden=True)
    @checks.allowjoin()
    async def addjoin(self, ctx, link, region='general'):
        """**Usage**: `!addjoin/aj <discord invite link> [region]`
        Adds a join link for the region provided so it can be access with
        `!join <region>`. If no region is provided, will set the default
        invite link. Be careful not to change the default link unintentionally!
        """
        await ctx.message.delete()
        if self.can_manage(ctx.message.author):
            guild = ctx.message.guild
            join_dict = self.bot.guild_dict[guild.id]['configure_dict'].setdefault('join')
            if not join_dict.get('enabled', False):
                join_dict['enabled'] = True
                if 'general' not in join_dict:
                    join_dict['general'] = "No general invite link has been set."
            join_dict[region] = link
            if region == 'general':
                await ctx.channel.send("General invite link set.")
            else:
                await ctx.channel.send(f"Invite link set for the **{region}** region")

    def can_manage(self, user):
        if checks.is_user_dev_or_owner(self.bot.config, user.id):
            return True
        for role in user.roles:
            if role.permissions.manage_messages:
                return True
        return False

    @commands.command(aliases=["smc"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def set_modqueue_channel(self, ctx, item):
        utilities_cog = self.bot.cogs.get('Utilities')
        if not utilities_cog:
            await ctx.channel.send('Utilities module not found, command failed.', delete_after=10)
            return await ctx.message.add_reaction(self.failed_react)
        mq_channel = await utilities_cog.get_channel_by_name_or_id(ctx, item)
        if mq_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.failed_react)
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['modqueue'] = mq_channel.id
        await ctx.channel.send(f'Mod queue channel set to {mq_channel.mention}.', delete_after=10)
        return await ctx.message.add_reaction(self.success_react)
    
    @commands.command(name="grantroles", aliases=["gr"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def _grantroles(self, ctx, member: discord.Member, roles: commands.Greedy[discord.Role]):
        """**Usage**: `!grantroles/gr <member> <role(s)>`
        Provide a username followed by 1 or a list of role names
        and those roles will be assigned to that user."""
        if len(roles) < 1:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("No roles provided, must include at least 1 role with "
                                  "only a space between role names")
        await ctx.trigger_typing()
        rolenames = []
        try:
            await member.add_roles(*roles)
            await asyncio.sleep(0.5)
            failed = []
            for role in roles:
                rolenames.append(role.name)
                if role not in member.roles:
                    await ctx.message.add_reaction(self.failed_react)
                    failed.append(role.name)
            if len(failed) > 0:
                return await ctx.send(f"Failed to add the roles: {', '.join(failed)} to {member.display_name}.",
                                      delete_after=10)
            else:
                await ctx.message.add_reaction(self.success_react)
                return await ctx.send(f"Granted {', '.join(rolenames)} to {member.display_name}", delete_after=10)
            success = role in member.roles
        except discord.Forbidden:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send(f"Failed to grant {', '.join(rolenames)} to {member.display_name} "
                                  f"because you do not have permission", delete_after=10)

    @commands.command(name="ungrantroles", aliases=["ug"], hidden=True)
    @commands.has_permissions(administrator=True)
    async def _ungrantroles(self, ctx, member: discord.Member, roles: commands.Greedy[discord.Role]):
        """**Usage**: `!ungrantroles/ug <member> <role(s)>`
        Provide a username followed by 1 or a list of role names
        and those roles will be removed from that user."""
        if len(roles) < 1:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send("No roles provided, must include at least 1 role with "
                                  "only a space between role names")
        await ctx.trigger_typing()
        rolenames = []
        try:
            await member.remove_roles(*roles)
            await asyncio.sleep(0.5)
            failed = []
            for role in roles:
                rolenames.append(role.name)
                if role in member.roles:
                    await ctx.message.add_reaction(self.failed_react)
                    failed.append(role.name)
            if len(failed) > 0:
                return await ctx.send(f"Failed to remove the roles: {', '.join(failed)} "
                                      f"from {member.display_name}.", delete_after=10)
            else:
                await ctx.message.add_reaction(self.success_react)
                return await ctx.send(f"Removed {', '.join(rolenames)} from {member.display_name}", delete_after=10)
        except discord.Forbidden:
            await ctx.message.add_reaction(self.failed_react)
            return await ctx.send(f"Failed to remove {', '.join(rolenames)} from {member.display_name} "
                                  f"because you do not have permission", delete_after=10)

    @commands.command(name="refresh_listings", hidden=True)
    @commands.has_permissions(manage_guild=True)
    async def _refresh_listing_channels(self, ctx, list_type, *, regions=None):
        if regions:
            regions = [r.strip() for r in regions.split(',')]
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.update_listing_channels(ctx.guild, list_type, edit=True, regions=regions)
        await ctx.message.add_reaction('\u2705')


def setup(bot):
    bot.add_cog(AdminCommands(bot))
