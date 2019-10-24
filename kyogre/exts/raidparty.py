import asyncio
import copy
import datetime
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, embed_utils, utils
from kyogre.exts.pokemon import Pokemon


class RaidParty(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status_parser = re.compile(r'^(w*\d+)$|^(\d+(?:[, ]+))?([\dimvu ,]+)?(?:[, ]*)([a-zA-Z ,]+)?$')

    async def _parse_teamcounts(self, ctx, teamcounts, trainer_dict, egglevel):
        if not teamcounts:
            if ctx.author.id in trainer_dict:
                bluecount = str(trainer_dict[ctx.author.id]['party']['mystic']) + 'm '
                redcount = str(trainer_dict[ctx.author.id]['party']['valor']) + 'v '
                yellowcount = str(trainer_dict[ctx.author.id]['party']['instinct']) + 'i '
                unknowncount = str(trainer_dict[ctx.author.id]['party']['unknown']) + 'u '
                teamcounts = ((((str(trainer_dict[ctx.author.id]['count']) + ' ') + bluecount) + redcount) + yellowcount) + unknowncount
            else:
                teamcounts = '1'
        if "all" in teamcounts.lower():
            teamcounts = "{teamcounts} {bosslist}"\
                .format(teamcounts=teamcounts,
                        bosslist=",".join([s.title() for s in self.bot.raid_info['raid_eggs'][egglevel]['pokemon']]))
            teamcounts = teamcounts.lower().replace("all", "").strip()
        return self.status_parser.fullmatch(teamcounts)

    async def process_status_command(self, ctx, teamcounts, trainer_dict, egglevel):
        eta = None
        if teamcounts is not None:
            if teamcounts.lower().find('eta') > -1:
                idx = teamcounts.lower().find('eta')
                eta = teamcounts[idx:]
                teamcounts = teamcounts[:idx]
        guild = ctx.guild
        entered_interest = trainer_dict.get(ctx.author.id, {}).get('interest', [])
        parsed_counts = await self._parse_teamcounts(ctx, teamcounts, trainer_dict, egglevel)
        errors = []
        if not parsed_counts:
            raise ValueError("I couldn't understand that format! "
                             "Check the format against `!help interested` and try again.")
        totalA, totalB, groups, bosses = parsed_counts.groups()
        total = totalA or totalB
        if egglevel == 'EX':
            pass
        elif bosses and self.bot.guild_dict[guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == "egg":
            entered_interest = set(entered_interest)
            bosses_list = bosses.lower().split(',')
            if isinstance(bosses_list, str):
                bosses_list = [bosses.lower()]
            for boss in bosses_list:
                pkmn = Pokemon.get_pokemon(self.bot, boss)
                if pkmn:
                    name = pkmn.name.lower()
                    if name in self.bot.raid_info['raid_eggs'][egglevel]['pokemon']:
                        entered_interest.add(name)
                    else:
                        errors.append("{pkmn} doesn't appear in level {egglevel} raids! Please try again."
                                      .format(pkmn=pkmn.name, egglevel=egglevel))
            if errors:
                errors.append("Invalid Pokemon detected. Please check the pinned message "
                              "for the list of possible bosses and try again.")
                raise ValueError('\n'.join(errors))
        elif not bosses and self.bot.guild_dict[guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == 'egg':
            entered_interest = [p for p in self.bot.raid_info['raid_eggs'][egglevel]['pokemon']]
        if total:
            if total[0] == 'w':
                total = total[1:]
            total = int(total)
        elif (ctx.author.id in trainer_dict) and (sum(trainer_dict[ctx.author.id]['status'].values()) > 0):
            total = trainer_dict[ctx.author.id]['count']
        elif groups:
            total = re.sub('[^0-9 ]', ' ', groups)
            total = sum([int(x) for x in total.split()])
        else:
            total = 1
        if not groups:
            groups = ''
        teamcounts = f"{total} {groups}"
        result = await self._party_status(ctx, total, teamcounts, trainer_dict)
        return (result, entered_interest, eta)

    @commands.command()
    @checks.activechannel()
    async def shout(self, ctx, *, shout_message="\u200b"):
        """Notifies all trainers who have RSVPd for the raid of your message
        
        **Usage**: `!shout <message>`
        Kyogre will notify all trainers who have expressed interest and include your message.
        This command has a 2 minute cooldown. 
        If it is used again within those 2 minutes the other trainers will not be notified.
        """
        message = ctx.message
        author = message.author
        guild = message.guild
        channel = message.channel
        cooldown_time = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('cooldown', 0)
        cooldown = False
        if cooldown_time > int(time.time()):
            cooldown = True
        else:
            self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['cooldown'] = int(time.time()) + 120
        trainer_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        trainer_list = []
        embed = discord.Embed(colour=discord.Colour.green())
        for trainer in trainer_dict:
            if trainer != author.id:
                if cooldown:
                    trainer_list.append(guild.get_member(trainer).display_name)
                    embed.set_footer(text="Cooldown in effect, users will not be pinged.")
                else:
                    trainer_list.append(guild.get_member(trainer).mention)
        if len(trainer_list) > 0:
            message = "Hey " + ', '.join(trainer_list) + "!"
            embed.add_field(name=f"Message from {author.display_name}", value=shout_message)
            await channel.send(content=message, embed=embed)
        else:
            await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                   title="There is no one here to hear you!"))
        await message.delete()

    @commands.command(name='interested', aliases=['i', 'maybe'])
    @checks.activechannel()
    async def interested(self, ctx, *, teamcounts: str = None):
        """Indicate you are interested in the raid.

        **Usage**: `!interested/i [count] [party]`

        Count must be a number. If count is omitted, assumes you are a group of 1.
        **Example**: `!i 2`

        Party must be a number plus a team.
        **Example**: `!i 3 1i 1m 1v`"""
        try:
            trainer_dict = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
            egglevel = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['egglevel']
            result, entered_interest, eta = await self.process_status_command(ctx, teamcounts, trainer_dict, egglevel)
        except ValueError as e:
            return await ctx.channel.send(e)
        if isinstance(result, list):
            count = result[0]
            partylist = result[1]
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.maybe(ctx, count, partylist, eta, entered_interest)

    @commands.command(aliases=['c'])
    @checks.activechannel()
    async def coming(self, ctx, *, teamcounts: str = None):
        """Indicate you are on the way to a raid.

        **Usage**: `!coming/c [count] [party]`

        Count must be a number. If count is omitted, assumes you are a group of 1.
        **Example**: `!c 2`

        Party must be a number plus a team.
        **Example**: `!c 3 1i 1m 1v`"""
        try:
            trainer_dict = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
            egglevel = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['egglevel']
            result, entered_interest, eta = await self.process_status_command(ctx, teamcounts, trainer_dict, egglevel)
        except ValueError as e:
            return await ctx.channel.send(e)
        if isinstance(result, list):
            count = result[0]
            partylist = result[1]
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.coming(ctx, count, partylist, eta, entered_interest)

    @commands.command(aliases=['h'])
    @checks.activechannel()
    async def here(self, ctx, *, teamcounts: str = None):
        """Indicate you have arrived at the raid.

        **Usage**: `!here/h [count] [party]`
        Count must be a number. If count is omitted, assumes you are a group of 1.

        **Example**: `!h 2`
        Party must be a number plus a team.
        **Example**: `!h 3 1i 1m 1v`"""
        try:
            trainer_dict = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
            egglevel = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['egglevel']
            result, entered_interest, eta = await self.process_status_command(ctx, teamcounts, trainer_dict, egglevel)
        except ValueError as e:
            return await ctx.channel.send(e)
        if isinstance(result, list):
            count = result[0]
            partylist = result[1]
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.here(ctx, count, partylist, entered_interest)

    async def _party_status(self, ctx, total, teamcounts, trainer_dict):
        channel = ctx.channel
        author = ctx.author
        trainer_dict = trainer_dict.get(author.id, {})
        roles = [r.name.lower() for r in author.roles]
        if 'mystic' in roles:
            my_team = 'mystic'
        elif 'valor' in roles:
            my_team = 'valor'
        elif 'instinct' in roles:
            my_team = 'instinct'
        else:
            my_team = 'unknown'
        if not teamcounts:
            teamcounts = "1"
        teamcounts = teamcounts.lower().split()
        if total and teamcounts[0].isdigit():
            del teamcounts[0]
        mystic = ['mystic', 0]
        instinct = ['instinct', 0]
        valor = ['valor', 0]
        unknown = ['unknown', 0]
        team_aliases = {
            'mystic': mystic,
            'blue': mystic,
            'm': mystic,
            'b': mystic,
            'instinct': instinct,
            'yellow': instinct,
            'i': instinct,
            'y': instinct,
            'valor': valor,
            'red': valor,
            'v': valor,
            'r': valor,
            'unknown': unknown,
            'grey': unknown,
            'gray': unknown,
            'u': unknown,
            'g': unknown,
        }
        if not teamcounts and total >= trainer_dict.get('count', 0):
            trainer_party = trainer_dict.get('party', {})
            for team in trainer_party:
                team_aliases[team][1] += trainer_party[team]
        regx = re.compile('([a-zA-Z]+)([0-9]+)|([0-9]+)([a-zA-Z]+)')
        for count in teamcounts:
            if count.isdigit():
                if total:
                    return await channel.send('Only one non-team count can be accepted.')
                else:
                    total = int(count)
            else:
                match = regx.match(count)
                if match:
                    match = regx.match(count).groups()
                    str_match = match[0] or match[3]
                    int_match = match[1] or match[2]
                    if str_match in team_aliases.keys():
                        if int_match:
                            if team_aliases[str_match][1]:
                                return await channel.send('Only one count per team accepted.')
                            else:
                                team_aliases[str_match][1] = int(int_match)
                                continue
                return await channel.send('Invalid format, please check and try again.')
        team_total = ((mystic[1] + instinct[1]) + valor[1]) + unknown[1]
        if total:
            if int(team_total) > int(total):
                a = 'Team counts are higher than the total, double check your counts and try again. You entered **'
                b = '** total and **'
                c = '** in your party.'
                return await channel.send(((( a + str(total)) + b) + str(team_total)) + c)
            if int(total) > int(team_total):
                if team_aliases[my_team][1]:
                    unknown[1] = total - team_total
                else:
                    team_aliases[my_team][1] = total - team_total
        partylist = {'mystic': mystic[1], 'valor': valor[1], 'instinct': instinct[1], 'unknown': unknown[1]}
        result = [total, partylist]
        return result

    @commands.command(aliases=['l'])
    @checks.activeraidchannel()
    async def lobby(self, ctx, *, count: str = None):
        """Used to join an in-progress lobby started with `!starting`

        **Usage**: `!lobby [count]`
        Count must be a number. If count is omitted, assumes you are a group of 1."""
        try:
            if self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['type'] == 'egg':
                if self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['pokemon'] == '':
                    await ctx.channel.send("Please wait until the raid egg has hatched "
                                           "before announcing you're coming or present.")
                    return
        except:
            pass
        trainer_dict = self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict']
        if count:
            if count.isdigit():
                count = int(count)
            else:
                await ctx.channel.send("I can't understand how many are in your group. Just say **!lobby** if you're "
                                       "by yourself, or **!lobby 5** for example if there are 5 in your group.")
                return
        elif (ctx.author.id in trainer_dict) and (sum(trainer_dict[ctx.author.id]['status'].values()) > 0):
            count = trainer_dict[ctx.author.id]['count']
        else:
            count = 1
        await self._lobby(ctx.message, count)

    async def _lobby(self, message, count):
        trainer = message.author
        guild = message.guild
        channel = message.channel
        if 'lobby' not in self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]:
            await channel.send('There is no group in the lobby for you to join!\n\
            Use **!starting** if the group waiting at the raid is entering the lobby!')
            return
        trainer_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        if count == 1:
            await channel.send('{member} is entering the lobby!'.format(member=trainer.mention))
        else:
            await channel.send('{member} is entering the lobby with a total of {trainer_count} trainers!'
                               .format(member=trainer.mention, trainer_count=count))
            utils_cog = self.bot.cogs.get('Utilities')
            regions = utils_cog.get_channel_regions(channel, 'raid')
            joined = self.bot.guild_dict[guild.id].setdefault('trainers', {})\
                         .setdefault(regions[0], {})\
                         .setdefault(trainer.id, {})\
                         .setdefault('joined', 0) + 1
            self.bot.guild_dict[guild.id]['trainers'][regions[0]][trainer.id]['joined'] = joined
        if trainer.id not in trainer_dict:
            trainer_dict[trainer.id] = {}
        trainer_dict[trainer.id]['status'] = {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': count}
        trainer_dict[trainer.id]['count'] = count
        self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
        regions = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.update_listing_channels(channel.guild, 'raid', edit=True, regions=regions)

    @commands.command(aliases=['x'])
    @checks.raidchannel()
    async def cancel(self, ctx):
        """Indicate you are no longer interested in a raid or that you are backing out of a lobby.

        **Usage**: `!cancel/x`
        Removes you and your party from the list of trainers who are "coming" or "here".
        Or removes you and your party from the active lobby."""
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.cancel(ctx)

    @commands.command(aliases=['s'])
    @checks.activeraidchannel()
    async def starting(self, ctx, team: str = ''):
        """Signal that a raid is starting.

        **Usage**: `!starting/s [team]`
        Sends a message notifying all trainers who are at the raid and clears the waiting list.
        Starts a 2 minute lobby countdown during which time trainers can join this lobby using `!lobby`.
        Users who are waiting for a second group must reannounce with `!here`."""
        guild_dict = self.bot.guild_dict
        channel = ctx.channel
        guild = ctx.guild
        ctx_startinglist = []
        team_list = []
        ctx.team_names = ["mystic", "valor", "instinct", "unknown"]
        team = team if team and team.lower() in ctx.team_names else "all"
        ctx.trainer_dict = copy.deepcopy(guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
        regions = guild_dict[guild.id]['raidchannel_dict'][channel.id]['regions']
        if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('type', None) == 'egg':
            if guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 < datetime.datetime.now().timestamp():
                starting_str = "Please tell me which raid boss has hatched before starting your lobby."
            else:
                starting_str = "How can you start when the egg hasn't hatched!?"
            await channel.send(starting_str)
            return
        if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('lobby', False):
            starting_str = "Please wait for the group in the lobby to enter the raid."
            await channel.send(starting_str)
            return
        trainer_joined = False
        for trainer in ctx.trainer_dict:
            count = ctx.trainer_dict[trainer]['count']
            user = guild.get_member(trainer)
            if team in ctx.team_names:
                if ctx.trainer_dict[trainer]['party'][team]:
                    team_list.append(user.id)
                teamcount = ctx.trainer_dict[trainer]['party'][team]
                herecount = ctx.trainer_dict[trainer]['status']['here']
                lobbycount = ctx.trainer_dict[trainer]['status']['lobby']
                if ctx.trainer_dict[trainer]['status']['here'] and (user.id in team_list):
                    ctx.trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here': herecount - teamcount,
                                                           'lobby': lobbycount + teamcount}
                    trainer_joined = True
                    ctx_startinglist.append(user.mention)
            else:
                if ctx.trainer_dict[trainer]['status']['here'] and (user.id in team_list or team == "all"):
                    ctx.trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': count}
                    trainer_joined = True
                    ctx_startinglist.append(user.mention)
            if trainer_joined:
                joined = guild_dict[guild.id].setdefault('trainers', {}).setdefault(regions[0], {})\
                             .setdefault(trainer, {}).setdefault('joined', 0) + 1
                guild_dict[guild.id]['trainers'][regions[0]][trainer]['joined'] = joined

        if len(ctx_startinglist) == 0:
            starting_str = "How can you start when there's no one waiting at this raid!?"
            await channel.send(starting_str)
            return
        guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = ctx.trainer_dict
        starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('starttime', None)
        if starttime:
            timestr = ' to start at **{}** '.format(starttime.strftime('%I:%M %p (%H:%M)'))
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['starttime'] = None
        else:
            timestr = ' '
        starting_str = 'Starting - The group that was waiting{timestr}is starting the raid! ' \
                       'Trainers {trainer_list}, if you are not in this group and are waiting for the next group, ' \
                       'please respond with {here_emoji} or **!here**. If you need to ask those that just started ' \
                       'to back out of their lobby, use **!backout**'\
            .format(timestr=timestr, trainer_list=', '.join(ctx_startinglist),
                    here_emoji=utils.parse_emoji(guild, self.bot.config['here_id']))
        guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby'] = {"exp": time.time() + 120, "team": team}
        if starttime:
            starting_str += '\n\nThe start time has also been cleared, new groups can set a new start time with' \
                            ' **!starttime HH:MM AM/PM** (You can also omit AM/PM and use 24-hour time!).'
            report_channel = self.bot.get_channel(guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
            raidmsg = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidmessage'])
            reportmsg = await report_channel.fetch_message(
                guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
            embed = raidmsg.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(embed)
            embed.set_field_at(embed_indices["next"], name="**Next Group**", value="Set with **!starttime**",
                               inline=True)
            try:
                await raidmsg.edit(content=raidmsg.content, embed=embed)
            except discord.errors.NotFound:
                pass
            try:
                await reportmsg.edit(content=reportmsg.content, embed=embed)
            except discord.errors.NotFound:
                pass
        await channel.send(starting_str)
        action_time = round(ctx.message.created_at.timestamp())
        ctx.bot.loop.create_task(self.lobby_countdown(ctx, team, action_time))
        regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            await listmgmt_cog.update_listing_channels(channel.guild, 'raid', edit=True, regions=regions)
        raid_cog = self.bot.cogs.get('RaidCommands')
        await raid_cog.add_db_raid_action(channel, "lobby start", action_time)

    async def lobby_countdown(self, ctx, team, action_time):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        lobby_duration = 120
        await asyncio.sleep(lobby_duration)
        if ('lobby' not in guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]) or (
                time.time() < guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['lobby']['exp']):
            return
        ctx_lobbycount = 0
        trainer_delete_list = []
        for trainer in ctx.trainer_dict:
            if ctx.trainer_dict[trainer]['status']['lobby']:
                ctx_lobbycount += ctx.trainer_dict[trainer]['status']['lobby']
                trainer_delete_list.append(trainer)
        if ctx_lobbycount > 0:
            await ctx.channel.send('The group of {count} in the lobby has entered the raid! Wish them luck!'.format(
                count=str(ctx_lobbycount)))
        for trainer in trainer_delete_list:
            if team in ctx.team_names:
                herecount = ctx.trainer_dict[trainer]['status'].get('here', 0)
                teamcount = ctx.trainer_dict[trainer]['party'][team]
                ctx.trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here': herecount - teamcount,
                                                       'lobby': ctx_lobbycount}
                ctx.trainer_dict[trainer]['party'][team] = 0
                ctx.trainer_dict[trainer]['count'] = ctx.trainer_dict[trainer]['count'] - teamcount
            else:
                del ctx.trainer_dict[trainer]
        try:
            del guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['lobby']
        except KeyError:
            pass
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.edit_party(ctx, ctx.channel, ctx.author)
        guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'] = ctx.trainer_dict
        regions = guild_dict[ctx.channel.guild.id]['raidchannel_dict'][ctx.channel.id].get('regions', None)
        if regions:
            await listmgmt_cog.update_listing_channels(ctx.guild, 'raid', edit=True, regions=regions)
        raid_cog = self.bot.cogs.get('RaidCommands')
        action_time += lobby_duration
        await raid_cog.add_db_raid_action(ctx.channel, "lobby complete", action_time)

    @commands.command()
    @checks.activeraidchannel()
    async def backout(self, ctx):
        """Request players in lobby to backout

        **Usage**: `!backout`
        Will alert all trainers in the lobby that a backout is requested.
        Those trainers can exit the lobby with `!cancel`."""
        guild_dict = self.bot.guild_dict
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = channel.guild
        trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        if (author.id in trainer_dict) and (trainer_dict[author.id]['status']['lobby']):
            count = trainer_dict[author.id]['count']
            trainer_dict[author.id]['status'] = {'maybe': 0, 'coming': 0, 'here': count, 'lobby': 0}
            lobby_list = []
            for trainer in trainer_dict:
                count = trainer_dict[trainer]['count']
                if trainer_dict[trainer]['status']['lobby']:
                    user = guild.get_member(trainer)
                    lobby_list.append(user.mention)
                    trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here': count, 'lobby': 0}
            if not lobby_list:
                await channel.send("There's no one else in the lobby for this raid!")
                try:
                    del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
                except KeyError:
                    pass
                return
            await channel.send('Backout - {author} has indicated that the group consisting of {lobby_list} and the '
                               'people with them has backed out of the lobby! If this is inaccurate, please use '
                               '**!lobby** or **!cancel** to help me keep my lists accurate!'
                               .format(author=author.mention, lobby_list=', '.join(lobby_list)))
            try:
                del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
            except KeyError:
                pass
        else:
            lobby_list = []
            trainer_list = []
            for trainer in trainer_dict:
                if trainer_dict[trainer]['status']['lobby']:
                    user = guild.get_member(trainer)
                    lobby_list.append(user.mention)
                    trainer_list.append(trainer)
            if (not lobby_list):
                await channel.send("There's no one in the lobby for this raid!")
                return

            backoutmsg = await channel.send(
                'Backout - {author} has requested a backout! If one of the following trainers reacts with the '
                'check mark, I will assume the group is backing out of the raid lobby as requested! {lobby_list}'
                    .format(author=author.mention, lobby_list=', '.join(lobby_list)))
            try:
                timeout = False
                res, reactuser = await utils.simple_ask(self.bot, backoutmsg, channel, trainer_list, react_list=['✅'])
            except TypeError:
                timeout = True
            if not timeout and res.emoji == '✅':
                for trainer in trainer_list:
                    count = trainer_dict[trainer]['count']
                    if trainer in trainer_dict:
                        trainer_dict[trainer]['status'] = {'maybe': 0, 'coming': 0, 'here': count, 'lobby': 0}
                await channel.send('{user} confirmed the group is backing out!'.format(user=reactuser.mention))
                try:
                    del guild_dict[guild.id]['raidchannel_dict'][channel.id]['lobby']
                except KeyError:
                    pass
            else:
                return


def setup(bot):
    bot.add_cog(RaidParty(bot))
