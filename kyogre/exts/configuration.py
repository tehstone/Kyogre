import copy

import discord
from discord.ext import commands

from kyogre import utils, checks
from kyogre.exts import config_items

class Configuration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(case_insensitive=True, invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def configure(self, ctx, *, configlist: str=""):
        """Kyogre Configuration

        Usage: !configure [list]
        Kyogre will DM you instructions on how to configure Kyogre for your server.
        If it is not your first time configuring, you can choose a section to jump to.
        You can also include a comma separated [list] of sections from the following:
        all, team, welcome, regions, raid, exraid, invite, counters, wild, research, meetup, subscription, archive, trade, timezone"""
        await self._configure(ctx, configlist)

    async def _configure(self, ctx, configlist):
        guild = ctx.message.guild
        owner = ctx.message.author
        try:
            await ctx.message.delete()
        except (discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        config_sessions = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('config_sessions', {}).setdefault(owner.id, 0) + 1
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['config_sessions'][owner.id] = config_sessions
        for session in self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'].keys():
            if not guild.get_member(session):
                del self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][session]
        config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(self.bot.guild_dict[guild.id]['configure_dict']))
        firstconfig = False
        all_commands = ['team', 'welcome', 'regions', 'raid', 'exraid', 'exinvite', 
                        'counters', 'wild', 'research', 'meetup', 'subscriptions', 'archive', 
                        'trade', 'timezone', 'pvp', 'join', 'lure', 'trackinvites']
        enabled_commands = []
        configreplylist = []
        config_error = False
        if not config_dict_temp['settings']['done']:
            firstconfig = True
        if configlist and not firstconfig:
            configlist = configlist.lower().replace("timezone", "settings").split(",")
            configlist = [x.strip().lower() for x in configlist]
            diff = set(configlist) - set(all_commands)
            if diff and "all" in diff:
                configreplylist = all_commands
            elif not diff:
                configreplylist = configlist
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="I'm sorry, I couldn't understand some of what you entered. Let's just start here."))
        if config_dict_temp['settings']['config_sessions'][owner.id] > 1:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="**MULTIPLE SESSIONS!**\n\nIt looks like you have **{yoursessions}** active configure sessions. I recommend you send **cancel** first and then send your request again to avoid confusing me.\n\nYour Sessions: **{yoursessions}** | Total Sessions: **{allsessions}**".format(allsessions=sum(config_dict_temp['settings']['config_sessions'].values()),yoursessions=config_dict_temp['settings']['config_sessions'][owner.id])))
        configmessage = "Welcome to the configuration for Kyogre! I will be guiding you through some steps to get me setup on your server.\n\n**Role Setup**\nBefore you begin the configuration, please make sure my role is moved to the top end of the server role hierarchy. It can be under admins and mods, but must be above team and general roles. [Here is an example](http://i.imgur.com/c5eaX1u.png)"
        if not firstconfig and not configreplylist:
            configmessage += "\n\n**Welcome Back**\nThis isn't your first time configuring. You can either reconfigure everything by replying with **all** or reply with a comma separated list to configure those commands. Example: `subscription, raid, wild`"
            for commandconfig in config_dict_temp.keys():
                if config_dict_temp[commandconfig].get('enabled',False):
                    enabled_commands.append(commandconfig)
            configmessage += "\n\n**Enabled Commands:**\n{enabled_commands}".format(enabled_commands=", ".join(enabled_commands))
            configmessage += """\n\n**All Commands:**\n**all** - To redo configuration\n\
                            **team** - For Team Assignment configuration\n**welcome** - For Welcome Message configuration\n\
                            **regions** - for region configuration\n**raid** - for raid command configuration\n\
                            **exraid** - for EX raid command configuration\n**invite** - for invite command configuration\n\
                            **counters** - for automatic counters configuration\n**wild** - for wild command configuration\n\
                            **research** - for !research command configuration\n**meetup** - for !meetup command configuration\n\
                            **subscriptions** - for subscription command configuration\n**archive** - For !archive configuration\n\
                            **trade** - For trade command configuration\n**timezone** - For timezone configuration\n\
                            **join** - For !join command configuration\n**pvp** - For !pvp command configuration\n\
                            **trackinvites** - For invite tracking configuration"""
            configmessage += '\n\nReply with **cancel** at any time throughout the questions to cancel the configure process.'
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=configmessage).set_author(name='Kyogre Configuration - {guild}'.format(guild=guild.name), icon_url=self.bot.user.avatar_url))
            while True:
                config_error = False

                def check(m):
                    return not m.guild and m.author == owner
                configreply = await self.bot.wait_for('message', check=check)
                configreply.content = configreply.content.replace("timezone", "settings")
                if configreply.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description='**CONFIG CANCELLED!**\n\nNo changes have been made.'))
                    del self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]
                    return None
                elif "all" in configreply.content.lower():
                    configreplylist = all_commands
                    break
                else:
                    configreplylist = configreply.content.lower().split(",")
                    configreplylist = [x.strip() for x in configreplylist]
                    for configreplyitem in configreplylist:
                        if configreplyitem not in all_commands:
                            config_error = True
                            break
                if config_error:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="I'm sorry I don't understand. Please reply with the choices above."))
                    continue
                else:
                    break
        elif firstconfig == True:
            configmessage += '\n\nReply with **cancel** at any time throughout the questions to cancel the configure process.'
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=configmessage).set_author(name='Kyogre Configuration - {guild}'.format(guild=guild.name), icon_url=self.bot.user.avatar_url))
            configreplylist = all_commands
        try:
            config_func_dict = {"team":config_items._configure_team,
                    "welcome":config_items._configure_welcome,
                    "regions":config_items._configure_regions,
                    "raid":config_items._configure_raid,
                    "exraid":config_items._configure_exraid,
                    "meetup":config_items._configure_meetup,
                    "exinvite":config_items._configure_exinvite,
                    "counters":config_items._configure_counters,
                    "wild":config_items._configure_wild,
                    "research":config_items._configure_research,
                    "subscriptions":config_items._configure_subscriptions,
                    "archive":config_items._configure_archive,
                    "trade":config_items._configure_trade,
                    "settings":config_items._configure_settings,
                    "pvp":config_items._configure_pvp,
                    "join":config_items._configure_join,
                    "lure":config_items._configure_lure,
                    "trackinvites":config_items._configure_trackinvites
                    }
            for item in configreplylist:
                try:
                    func = config_func_dict[item]
                    ctx = await func(ctx, self.bot)
                    if not ctx:
                        return None
                except:
                    pass
        finally:
            if ctx:
                ctx.config_dict_temp['settings']['done'] = True
                await ctx.channel.send("Config changed: overwriting config dict.")
                self.bot.guild_dict[guild.id]['configure_dict'] = ctx.config_dict_temp
                await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Alright! Your settings have been saved and I'm ready to go! If you need to change any of these settings, just type **!configure** in your server again.").set_author(name='Configuration Complete', icon_url=self.bot.user.avatar_url))
            del self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]

    @configure.command(name='all')
    async def configure_all(self, ctx):
        """All settings"""
        await self._configure(ctx, "all")

    async def _check_sessions_and_invoke(self, ctx, func_ref):
        guild = ctx.message.guild
        owner = ctx.message.author
        try:
            await ctx.message.delete()
        except (discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        if not self.bot.guild_dict[guild.id]['configure_dict']['settings']['done']:
            await self._configure(ctx, "all")
            return
        config_sessions = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'].setdefault('config_sessions',{}).setdefault(owner.id,0) + 1
        self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['config_sessions'][owner.id] = config_sessions
        if self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id] > 1:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), 
                description="**MULTIPLE SESSIONS!**\n\nIt looks like you have **{yoursessions}** active configure sessions.\
                I recommend you send **cancel** first and then send your request again to avoid confusing me.\n\n\
                Your Sessions: **{yoursessions}** | Total Sessions: **{allsessions}**"
                .format(allsessions=sum(self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'].values())
                       ,yoursessions=self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id])))
        ctx = await func_ref(ctx, self.bot)
        if ctx:
            self.bot.guild_dict[guild.id]['configure_dict'] = ctx.config_dict_temp
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="Alright! Your settings have been saved and I'm ready to go! If you need to change any of these settings, just type **!configure** in your server again.").set_author(name='Configuration Complete', icon_url=self.bot.user.avatar_url))
        del self.bot.guild_dict[guild.id]['configure_dict']['settings']['config_sessions'][owner.id]

    @configure.command(aliases=['teams'])
    async def team(self, ctx):
        """!team command settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_team)

    @configure.command()
    async def welcome(self, ctx):
        """Welcome message settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_welcome)

    @configure.command(aliases=['regions'])
    async def region(self, ctx):
        """region configuration for server"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_regions)

    @configure.command(aliases=['raids'])
    async def raid(self, ctx):
        """!raid reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_raid)

    @configure.command()
    async def exraid(self, ctx):
        """!exraid reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_exraid)

    @configure.command()
    async def exinvite(self, ctx):
        """!invite command settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_exinvite)

    @configure.command()
    async def counters(self, ctx):
        """Automatic counters settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_counters)

    @configure.command(aliases=['wilds'])
    async def wild(self, ctx):
        """!wild reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_wild)

    @configure.command()
    async def research(self, ctx):
        """!research reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_research)

    @configure.command(aliases=['event'])
    async def meetup(self, ctx):
        """!meetup reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_meetup)

    @configure.command(aliases=['sub','subs'])
    async def subscriptions(self, ctx):
        """!subscription settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_subscriptions)

    @configure.command()
    async def pvp(self, ctx):
        """!pvp settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_pvp)

    @configure.command()
    async def join(self, ctx):
        """!join settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_join)

    @configure.command()
    async def lure(self, ctx):
        """!lure settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_lure)

    @configure.command()
    async def archive(self, ctx):
        """Configure !archive command settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_archive)

    @configure.command(aliases=['settings'])
    async def timezone(self, ctx):
        """Configure timezone and other settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_settings)

    @configure.command()
    async def trade(self, ctx):
        """!trade reporting settings"""
        return await self._check_sessions_and_invoke(ctx, config_items._configure_trade)



def setup(bot):
    bot.add_cog(Configuration(bot))
