import asyncio
import copy
import datetime
import itertools
import time

from aiohttp import ClientOSError
from operator import itemgetter

import discord
from discord.ext import commands

from kyogre.exts.pokemon import Pokemon
from kyogre.exts.db.kyogredb import *
from kyogre import constants, embed_utils, utils


class ListManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_listing_messages(self, list_type, channel, region=None):
        if list_type == 'raid':
            return await self._get_raid_listing_messages(channel, region)
        elif list_type == 'wild':
            return await self._get_wild_listing_messages(channel, region)
        elif list_type == 'research':
            return await self._get_research_listing_messages(channel, region)
        elif list_type == 'lure':
            return await self._get_lure_listing_messages(channel, region)
        elif list_type == 'hideout':
            return await self._get_invasion_listing_messages(channel, region)
        else:
            return None

    async def _get_raid_listing_messages(self, channel, region=None):
        """
        listings_enabled | region_set | result
        ======================================
                Y        |      Y     |   get for region only (regional listings configured)
                Y        |      N     |   get for all regions (listings configured -- one channel)
                N        |      Y     |   normal list for region only (list command enabled in regional channel)
                N        |      N     |   normal list (all regions -- list command enabled)
        """
        guild_dict = self.bot.guild_dict
        guild = channel.guild
        listmsg_list = []
        listmsg = ""
        now = datetime.datetime.utcnow() \
              + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
        listing_dict = guild_dict[guild.id]['configure_dict']['raid'].get('listings', {})
        listing_enabled = listing_dict.get('enabled', False)
        rc_d = guild_dict[guild.id]['raidchannel_dict']
        if region:
            cty = region
        else:
            cty = channel.name
        egg_dict = {'1': {}, '2': {}, '3': {}, '4': {}, '5': {}}
        raid_dict = {'1': {}, '2': {}, '3': {}, '4': {}, '5': {}}
        exraid_list = []
        event_list = []
        for r in rc_d:
            if region:
                reportlocation = rc_d[r].get('regions', [])
            elif listing_enabled and 'channel' in listing_dict:
                reportlocation = [self.bot.get_channel(listing_dict['channel']).name]
            else:
                reportlocation = [self.bot.get_channel(rc_d[r]['reportcity']).name]
            if not reportlocation:
                continue
            if (cty in reportlocation) and rc_d[r]['active'] and discord.utils.get(guild.text_channels, id=r):
                exp = rc_d[r]['exp']
                type = rc_d[r]['type']
                level = rc_d[r]['egglevel']
                if (type == 'egg') and level.isdigit():
                    egg_dict[level][r] = exp
                elif rc_d[r].get('meetup', {}):
                    event_list.append(r)
                elif type == 'exraid' or level == 'EX':
                    exraid_list.append(r)
                else:
                    egglevel = Pokemon.get_pokemon(self.bot, rc_d[r]['pokemon']).raid_level
                    raid_dict[egglevel][r] = exp

        def list_output(raid):
            trainer_dict = rc_d[raid]['trainer_dict']
            rchan = self.bot.get_channel(raid)
            end = datetime.datetime.utcfromtimestamp(rc_d[raid]['exp']) + datetime.timedelta(
                hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
            output = ''
            start_str = ''
            t_emoji = ''
            ex_eligibility = ''
            trainer_count = {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
            for trainer in rc_d[raid]['trainer_dict'].keys():
                if not guild.get_member(trainer):
                    continue
                for stat in trainer_dict[trainer]['status']:
                    if trainer_dict[trainer]['status'][stat] > 0 and stat != 'lobby':
                        for team in trainer_dict[trainer]['party']:
                            trainer_count[team] += trainer_dict[trainer]['party'][team]
            if not rc_d[raid]['manual_timer']:
                assumed_str = ' (assumed)'
            else:
                assumed_str = ''
            starttime = rc_d[raid].get('starttime', None)
            meetup = rc_d[raid].get('meetup', {})
            if starttime and starttime > now and not meetup:
                start_str = '\n\t\t**Next Group**: {}'.format(starttime.strftime('%I:%M%p'))
            else:
                pass
            egglevel = rc_d[raid]['egglevel']
            if egglevel.isdigit() and (int(egglevel) > 0):
                t_emoji = str(egglevel) + '\u20e3'
                expirytext = '**Hatches**: {expiry}{is_assumed}' \
                    .format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
            elif ((rc_d[raid]['egglevel'] == 'EX') or (rc_d[raid]['type'] == 'exraid')) and not meetup:
                expirytext = '**Hatches**: {expiry}{is_assumed}' \
                    .format(expiry=end.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
            elif meetup:
                meetupstart = meetup['start']
                meetupend = meetup['end']
                expirytext = ""
                if meetupstart:
                    expirytext += ' - Starts: {expiry}{is_assumed}' \
                        .format(expiry=meetupstart.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
                if meetupend:
                    expirytext += " - Ends: {expiry}{is_assumed}" \
                        .format(expiry=meetupend.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
                if not meetupstart and not meetupend:
                    expirytext = ' - Starts: {expiry}{is_assumed}' \
                        .format(expiry=end.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
            else:
                expirytext = '**Expires**: {expiry}{is_assumed}' \
                    .format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
            boss = Pokemon.get_pokemon(self.bot, rc_d[raid].get('pokemon', ''))
            if not t_emoji and boss:
                t_emoji = str(boss.raid_level) + '\u20e3'
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gym_id = rc_d[raid].get('gym', None)
            gym = location_matching_cog.get_gym_by_id(guild.id, gym_id)
            gym_note = ''
            if gym:
                ex_eligibility = ' *EX-Eligible* ' if gym.ex_eligible else ''
                if gym.note is not None:
                    gym_note = f"\n**Note**: {gym.note}"
            utils_cog = self.bot.cogs.get('Utilities')
            enabled = utils_cog.raid_channels_enabled(guild, rchan)
            if enabled:
                blue_emoji = utils.parse_emoji(rchan.guild, self.bot.config['team_dict']['mystic'])
                red_emoji = utils.parse_emoji(rchan.guild, self.bot.config['team_dict']['valor'])
                yellow_emoji = utils.parse_emoji(rchan.guild, self.bot.config['team_dict']['instinct'])
                team_emoji_dict = {'mystic': blue_emoji, 'valor': red_emoji, 'instinct': yellow_emoji, 'unknown': '❔'}
                total_count_list = []
                for team in trainer_count:
                    if trainer_count[team] > 0:
                        total_count_list.append(f"{team_emoji_dict[team]}:{trainer_count[team]}")
                total_count = " | ".join(total_count_list)
                if len(total_count) < 1:
                    total_count = '0'
                # sum([ctx_maybecount, ctx_comingcount, ctx_herecount, ctx_lobbycount])
                output += f'\t{t_emoji} {rchan.mention}{ex_eligibility}{gym_note}\n\t\t{expirytext}{start_str}' \
                          f' | **Trainer Count**: {total_count}\n'
            else:
                channel_name = rchan.name.replace('_', ': ').replace('-', ' ').title()
                map_url = gym.maps_url
                try:
                    map_url = gym.maps_url
                except:
                    pass
                output += f'\t{t_emoji} **{channel_name}** {ex_eligibility}\n{expirytext}' \
                          f'{gym_note}\n[Click for directions]({map_url})\n'
            return output

        def process_category(listmsg_list, listmsg, category_title, category_list):
            listmsg += f"**{category_title}:**\n"
            for r in category_list:
                new_msg = list_output(r)
                if len(listmsg) + len(new_msg) < constants.MAX_MESSAGE_LENGTH:
                    listmsg += new_msg
                else:
                    listmsg_list.append(listmsg)
                    listmsg = f"**{category_title}:** (continued)\n"
                    listmsg += new_msg
            listmsg += '\n'
            return listmsg

        activeraidnum = len(raid_dict) + len(egg_dict)
        if not listing_enabled:
            activeraidnum += len(exraid_list) + len(event_list)
        report_str = ""
        if region:
            reporting_channels = await self.get_region_reporting_channels(guild, region)
            if len(reporting_channels) > 0:
                report_channel = guild.get_channel(reporting_channels[0])
                report_str = f"Report a new raid in {report_channel.mention}\n"
        if activeraidnum:
            listmsg += f"**Current eggs and raids reported in {cty.capitalize()}**\n"
            if region:
                listmsg += report_str
            listmsg += "\n"
            if egg_dict:
                for level in egg_dict:
                    if len(egg_dict[level].items()) > 0:
                        listmsg = process_category(listmsg_list, listmsg, f"Level {level} Eggs",
                                                   [r for (r, __) in
                                                   sorted(egg_dict[level].items(), key=itemgetter(1))])
            if raid_dict:
                for level in raid_dict:
                    if len(raid_dict[level].items()) > 0:
                        listmsg = process_category(listmsg_list, listmsg, f"Active Level {level} Raids",
                                                   [r for (r, __) in
                                                   sorted(raid_dict[level].items(), key=itemgetter(1))])
        else:
            listmsg = 'No active raids! Report one with **!raid <name> <location> [weather] [timer]**.'
            if region:
                listmsg += "\n" + report_str
        listmsg_list.append(listmsg)
        return listmsg_list

    async def _get_wild_listing_messages(self, channel, region=None):
        guild_dict = self.bot.guild_dict
        guild = channel.guild
        if region:
            loc = region
        else:
            loc = channel.name
        wild_dict = copy.deepcopy(guild_dict[guild.id].get('wildreport_dict', {}))
        wild_dict = dict(sorted(wild_dict.items(), key=lambda i: (i[1]['pokemon'], i[1]['location'])))
        wildctr = 0
        listmsg_list = []
        listmsg = f"**Here are the active wild reports for {loc.capitalize()}**\n"
        for wildid in wild_dict:
            newmsg = ""
            try:
                report_channel = guild.get_channel(wild_dict[wildid]['reportchannel'])
            except:
                continue
            utils_cog = self.bot.cogs.get('Utilities')
            if not region or region in utils_cog.get_channel_regions(report_channel, 'wild'):
                try:
                    await report_channel.fetch_message(wildid)
                    newmsg += '\n🔹'
                    newmsg += "**Pokemon**: {perfect}{pokemon}, **Location**: [{location}]({url})" \
                        .format(pokemon=wild_dict[wildid]['pokemon'].title(),
                                location=wild_dict[wildid]['location'].title(),
                                url=wild_dict[wildid].get('url', None),
                                perfect="💯 " if wild_dict[wildid]['perfect'] else "")
                    if len(listmsg) + len(newmsg) < constants.MAX_MESSAGE_LENGTH:
                        listmsg += newmsg
                    else:
                        listmsg_list.append(listmsg)
                        listmsg = newmsg
                    wildctr += 1
                except discord.errors.NotFound:
                    continue
        if wildctr == 0:
            listmsg = "There are no active wild pokemon. Report one with **!wild <pokemon> <location>**"
        listmsg_list.append(listmsg)
        return listmsg_list

    async def _get_research_listing_messages(self, channel, region=None):
        guild_dict = self.bot.guild_dict
        guild = channel.guild
        if region:
            loc = region
        else:
            loc = channel.name
        research_dict = copy.deepcopy(guild_dict[guild.id].setdefault('questreport_dict', {}))
        research_dict = dict(sorted(research_dict.items(), key=lambda i: (i[1]['quest'],
                                                                          i[1]['reward'],
                                                                          i[1]['location'])))
        questctr = 0
        listmsg_list = []
        listmsg = f"**Here are the active research reports for {loc.capitalize()}**\n"
        current_category = ""
        for questid in research_dict:
            newmsg = ""
            try:
                report_channel = guild.get_channel(research_dict[questid]['reportchannel'])
            except:
                continue
            utils_cog = self.bot.cogs.get('Utilities')

            if not region or region in utils_cog.get_channel_regions(report_channel, 'research'):
                try:
                    await report_channel.fetch_message(questid)  # verify quest message exists
                    cat = research_dict[questid]['quest'].title()
                    if current_category != cat:
                        current_category = cat
                        newmsg += f"\n\n**{current_category}**"
                    newmsg += '\n\t🔹'
                    newmsg += "**Reward**: {reward}, **Pokestop**: [{location}]({url})" \
                        .format(location=research_dict[questid]['location'].title(),
                                reward=research_dict[questid]['reward'].title(),
                                url=research_dict[questid].get('url', None))
                    if len(listmsg) + len(newmsg) < constants.MAX_MESSAGE_LENGTH:
                        listmsg += newmsg
                    else:
                        listmsg_list.append(listmsg)
                        if current_category not in newmsg:
                            newmsg = f"**({current_category} continued)**"
                        listmsg = "research " + newmsg
                    questctr += 1
                except discord.errors.NotFound:
                    continue
        if questctr == 0:
            listmsg = "There are no active research reports. Report one with **!research**"
        listmsg_list.append(listmsg)
        return listmsg_list

    async def _update_hideout_listings(self, channel, regions, edit):
        if not isinstance(regions, list):
            regions = [regions]
        for region in regions:
            region_dict = self.bot.guild_dict[channel.guild.id]['configure_dict'] \
                                             ['hideout']['listings']['channels'][region]
            embeds = await self._get_invasion_listing_messages(channel, region)
            for leader in region_dict['messages']:
                message_id = region_dict['messages'][leader]
                sent = False
                try:
                    old_message = await channel.fetch_message(message_id)
                    if edit:
                        await old_message.edit(embed=embeds[leader])
                        sent = True
                    else:
                        await old_message.delete()
                except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.NotFound):
                    pass
                if not sent:
                    new_message = await channel.send(embed=embeds[leader])
                    region_dict['messages'][leader] = new_message.id

    async def _get_invasion_listing_messages(self, channel, region=None):
        epoch = datetime.datetime(1970, 1, 1)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        day_start = (datetime.datetime.utcnow() + datetime.timedelta(hours=offset)) \
            .replace(hour=6, minute=0, second=0, microsecond=0)
        day_end = day_start + datetime.timedelta(hours=16)
        day_start = (day_start - epoch).total_seconds()
        day_end = (day_end - epoch).total_seconds()
        results = {}
        leader_list = [None, 'giovanni', 'arlo', 'cliff', 'sierra']
        utils_cog = self.bot.cogs.get('Utilities')
        embeds = {}
        for leader in leader_list:
            result = (TrainerReportRelation.select(
                TrainerReportRelation.id,
                TrainerReportRelation.created,
                LocationTable.id.alias('location_id'),
                LocationTable.name.alias('location_name'),
                HideoutTable.rocket_leader.alias('leader'),
                HideoutTable.first_pokemon,
                HideoutTable.second_pokemon,
                HideoutTable.third_pokemon,
                LocationTable.latitude,
                LocationTable.longitude,
                TrainerReportRelation.message,
                TrainerReportRelation.trainer)
                      .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
                      .join(LocationRegionRelation, on=(LocationTable.id == LocationRegionRelation.location_id))
                      .join(RegionTable, on=(RegionTable.id == LocationRegionRelation.region_id))
                      .join(HideoutTable, on=(TrainerReportRelation.id == HideoutTable.trainer_report_id))
                      .where((RegionTable.name == region) &
                             (TrainerReportRelation.created > day_start) &
                             (TrainerReportRelation.created < day_end) &
                             (TrainerReportRelation.cancelled != True) &
                             (HideoutTable.rocket_leader == leader))
                      .order_by(TrainerReportRelation.created))

            results[leader] = [r for r in result.objects(HideoutInstance)]
        for leader in leader_list:
            hideout_embed = discord.Embed(colour=discord.Colour.red())
            hideout_embed.description = ''
            # todo store these in db and make easily updateable
            lineups = {'arlo': {1: ['scyther'],
                                2: ['gyarados', 'crobat', 'magnezone'],
                                3: ['charizard', 'dragonite', 'scyzor']},
                       'cliff': {1: ['meowth'],
                                 2: ['sandslash', 'snorlax', 'flygon'],
                                 3: ['infernape', 'torterra', 'tyranitar']},
                       'sierra': {1: ['sneasel'],
                                  2: ['hypno', 'sableye', 'lapras'],
                                  3: ['alakazam', 'houndoom', 'gardevoir']},
                       'giovanni': {1: ['persian'],
                                    2: ['dugtrio', 'rhydon', 'hippowdon'],
                                    3: ['articuno']}}
            counters = {'arlo': '**Melmetal**, **Mewtwo**, **Blaziken**',
                        'cliff': '**Lucario**, **Regice**, **Swampert**',
                        'sierra': '**Lucario**, **Melmetal**, **Tyranitar**',
                        'giovanni': '**Tyranitar**, **Swampert**, **Lucario**'
            }
            guides = {'arlo': 'https://pokemongohub.net/post/guide/rocket-leader-arlo-counters/',
                      'cliff': 'https://pokemongohub.net/post/guide/rocket-leader-cliff-counters/',
                      'sierra': 'https://pokemongohub.net/post/guide/rocket-leader-sierra-counters/',
                      'giovanni': 'https://pokemongohub.net/post/guide/rocket-boss-giovanni-counters/'
            }
            if leader:
                hideout_embed.title = f"Rocket Leader {leader.capitalize()}"
                hideout_embed.url = guides[leader]
                counters_text = f"Best general counters: {counters[leader]}"
                hideout_embed.add_field(name="Click Leader Name for full counters guide", value=counters_text)
                lineup_text = f"{lineups[leader][1][0].capitalize()}\n"
                lineup_text += f"+ {' or '.join([l.capitalize() for l in lineups[leader][2]])}\n"
                lineup_text += f"+ {' or '.join([l.capitalize() for l in lineups[leader][3]])}"
                hideout_embed.add_field(name="Lineup", value=lineup_text)
                hideout_embed.set_thumbnail(
                    url=f"https://github.com/tehstone/Kyogre/blob/master/images/misc/{leader.lower()}.png?raw=true")
            else:
                hideout_embed.title = "Unknown Rocket Leader"
                hideout_embed.set_thumbnail(
                    url=f"https://github.com/tehstone/Kyogre/blob/master/images/misc/rocket_logo.png?raw=true")
            if len(results[leader]) < 1:
                hideout_embed.add_field(name='No locations reported yet!',
                                        value='Report one with command `!rocket`')
            else:
                hideout_embed.add_field(name='\u200b',
                                        value='**Locations reported today:**'
                                        , inline=False)
                for hideout in results[leader]:
                    gmaps_link = utils_cog.create_simple_gmaps_query(hideout.latitude, hideout.longitude)
                    loc_name = hideout.location_name
                    pokemon_id_list = [hideout.first_pokemon, hideout.second_pokemon, hideout.third_pokemon]
                    pokemon_names = ''
                    for p_id in pokemon_id_list:
                        if p_id:
                            pkmn = Pokemon.get_pokemon(self.bot, p_id)
                            pokemon_names += f'{pkmn.name.capitalize()} '
                        else:
                            pokemon_names += '*Unknown* '
                    embed_val = f'[Directions]({gmaps_link})\n {pokemon_names}\n'
                    hideout_embed.add_field(name=f'**{loc_name}**', value=embed_val)
            embeds[leader] = hideout_embed
        return embeds

    async def _get_lure_listing_messages(self, channel, region=None):
        guild_dict = self.bot.guild_dict
        guild = channel.guild
        if region:
            loc = region
        else:
            loc = channel.name
        lurectr = 0
        listmsg_list = []
        listmsg = f"**Here are the active lures in {loc.capitalize()}**\n"
        current_category = ""
        current = datetime.datetime.utcnow() \
                  + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
        expiration_seconds = guild_dict[guild.id]['configure_dict']['settings']['lure_minutes'] * 60
        current = round(current.timestamp())
        result = (TrainerReportRelation.select(
            TrainerReportRelation.created,
            LocationTable.name.alias('location_name'),
            LureTypeTable.name.alias('lure_type'),
            LocationTable.latitude,
            LocationTable.longitude)
                  .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
                  .join(LocationRegionRelation, on=(LocationTable.id == LocationRegionRelation.location_id))
                  .join(RegionTable, on=(RegionTable.id == LocationRegionRelation.region_id))
                  .join(LureTable, on=(TrainerReportRelation.id == LureTable.trainer_report_id))
                  .join(LureTypeRelation, on=(LureTable.id == LureTypeRelation.lure_id))
                  .join(LureTypeTable, on=(LureTypeTable.id == LureTypeRelation.type_id))
                  .where((RegionTable.name == region) &
                         (TrainerReportRelation.created + expiration_seconds > current))
                  .order_by(TrainerReportRelation.created))

        result = result.objects(LureInstance)
        for lure in result:
            exp = lure.created + expiration_seconds
            exp = datetime.datetime.utcfromtimestamp(exp)
            newmsg = ""
            try:
                type = lure.lure_type
                if current_category != type:
                    current_category = type
                    newmsg += f"\n\n**{current_category.capitalize()}**"
                newmsg += ('\n\t🔹')
                stop_url = utils.simple_gmaps_query(lure.latitude, lure.longitude)
                newmsg += f"**Pokestop**: [{lure.location_name}]({stop_url}) - " \
                          f"Expires: {exp.strftime('%I:%M')} (approx.)."
                if len(listmsg) + len(newmsg) < constants.MAX_MESSAGE_LENGTH:
                    listmsg += newmsg
                else:
                    listmsg_list.append(listmsg)
                    if current_category not in newmsg:
                        newmsg = f"**({current_category} continued)**"
                    listmsg = "lure " + newmsg
                lurectr += 1
            except discord.errors.NotFound:
                continue
        if lurectr == 0:
            listmsg = "There are no active lures. Report one with **!lure**"
        listmsg_list.append(listmsg)
        return listmsg_list

    async def interest(self, ctx, tag=False, team=False):
        guild_dict = self.bot.guild_dict
        ctx_maybecount = 0
        now = datetime.datetime.utcnow() \
              + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
        trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
        maybe_exstr = ''
        maybe_list = []
        name_list = []
        for trainer in trainer_dict.keys():
            user = ctx.guild.get_member(trainer)
            if (trainer_dict[trainer]['status']['maybe']) and user and team == False:
                ctx_maybecount += trainer_dict[trainer]['status']['maybe']
                if trainer_dict[trainer]['status']['maybe'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    maybe_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['status']['maybe']))
                    maybe_list.append('{name} **({count})**'
                                      .format(name=user.mention, count=trainer_dict[trainer]['status']['maybe']))
            elif (trainer_dict[trainer]['status']['maybe']) and user and team and trainer_dict[trainer]['party'][team]:
                if trainer_dict[trainer]['status']['maybe'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    maybe_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                    maybe_list.append('{name} **({count})**'
                                      .format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
                ctx_maybecount += trainer_dict[trainer]['party'][team]

        if ctx_maybecount > 0:
            if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and (tag == True):
                maybe_exstr = ' including {trainer_list} and the people with them! ' \
                              'Let them know if there is a group forming'.format(trainer_list=', '.join(maybe_list))
            else:
                maybe_exstr = ' including {trainer_list} and the people with them! ' \
                              'Let them know if there is a group forming'.format(trainer_list=', '.join(name_list))
        listmsg = ' {trainer_count} interested{including_string}!' \
            .format(trainer_count=str(ctx_maybecount), including_string=maybe_exstr)
        return listmsg

    async def maybe(self, ctx, count, party, eta, entered_interest=None):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        channel = ctx.channel
        author = ctx.author
        trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        if not party:
            party = self.determine_simple_party(author, count)
        message = f"**{author.display_name}** is interested!"
        if eta is not None:
            message += f" {eta}"
        await ctx.message.delete()
        last_status = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        if author.id not in trainer_dict:
            trainer_dict[author.id] = {}
        if entered_interest:
            trainer_dict[author.id]['interest'] = list(entered_interest)
        trainer_dict[author.id]['status'] = {'maybe': count, 'coming': 0, 'here': 0, 'lobby': 0}
        trainer_dict[author.id]['count'] = count
        trainer_dict[author.id]['party'] = party
        await self.edit_party(ctx, channel, author)
        trainer_count = self.determine_trainer_count(trainer_dict)
        embed = self.build_status_embed(channel.guild, trainer_count)
        new_status = await channel.send(content=message, embed=embed)
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
        regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            await self.update_listing_channels(channel.guild, 'raid', edit=True, regions=regions)

    async def otw(self, ctx, tag=False, team=False):
        guild_dict = self.bot.guild_dict
        ctx_comingcount = 0
        now = datetime.datetime.utcnow() \
              + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
        trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
        otw_exstr = ''
        otw_list = []
        name_list = []
        for trainer in trainer_dict.keys():
            user = ctx.guild.get_member(trainer)
            if (trainer_dict[trainer]['status']['coming']) and user and not team:
                ctx_comingcount += trainer_dict[trainer]['status']['coming']
                if trainer_dict[trainer]['status']['coming'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    otw_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['status']['coming']))
                    otw_list.append('{name} **({count})**'
                                    .format(name=user.mention, count=trainer_dict[trainer]['status']['coming']))
            elif (trainer_dict[trainer]['status']['coming']) and user and team and trainer_dict[trainer]['party'][team]:
                if trainer_dict[trainer]['status']['coming'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    otw_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                    otw_list.append('{name} **({count})**'
                                    .format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
                ctx_comingcount += trainer_dict[trainer]['party'][team]

        if ctx_comingcount > 0:
            if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and tag == True:
                otw_exstr = ' including {trainer_list} and the people with them! ' \
                            'Be considerate and wait for them if possible'.format(trainer_list=', '.join(otw_list))
            else:
                otw_exstr = ' including {trainer_list} and the people with them! ' \
                            'Be considerate and wait for them if possible'.format(trainer_list=', '.join(name_list))
        listmsg = ' {trainer_count} on the way{including_string}!' \
            .format(trainer_count=str(ctx_comingcount), including_string=otw_exstr)
        return listmsg

    async def coming(self, ctx, count, party, eta, entered_interest=None):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        channel = ctx.channel
        author = ctx.author
        trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        if not party:
            party = self.determine_simple_party(author, count)
        message = f"**{author.display_name}** is on their way!"
        if eta is not None:
            message += f" {eta}"
        await ctx.message.delete()
        last_status = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        if author.id not in trainer_dict:
            trainer_dict[author.id] = {}
        trainer_dict[author.id]['status'] = {'maybe': 0, 'coming': count, 'here': 0, 'lobby': 0}
        trainer_dict[author.id]['count'] = count
        trainer_dict[author.id]['party'] = party
        if entered_interest:
            trainer_dict[author.id]['interest'] = entered_interest
        await self.edit_party(ctx, channel, author)
        trainer_count = self.determine_trainer_count(trainer_dict)
        embed = self.build_status_embed(channel.guild, trainer_count)
        new_status = await channel.send(content=message, embed=embed)
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
        regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            await self.update_listing_channels(channel.guild, 'raid', edit=True, regions=regions)

    async def waiting(self, ctx, tag=False, team=False):
        guild_dict = self.bot.guild_dict
        ctx_herecount = 0
        now = datetime.datetime.utcnow() \
              + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
        raid_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id])
        trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
        here_exstr = ''
        here_list = []
        name_list = []
        for trainer in trainer_dict.keys():
            user = ctx.guild.get_member(trainer)
            print(trainer_dict[trainer]['status']['here'])
            if (trainer_dict[trainer]['status']['here']) and user and not team:
                ctx_herecount += trainer_dict[trainer]['status']['here']
                if trainer_dict[trainer]['status']['here'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    here_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['status']['here']))
                    here_list.append('{name} **({count})**'
                                     .format(name=user.mention, count=trainer_dict[trainer]['status']['here']))
            elif (trainer_dict[trainer]['status']['here']) and user and team and trainer_dict[trainer]['party'][team]:
                if trainer_dict[trainer]['status']['here'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    here_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                    here_list.append('{name} **({count})**'
                                     .format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
                ctx_herecount += trainer_dict[trainer]['party'][team]
                if raid_dict.get('lobby', {"team": "all"})['team'] == team \
                        or raid_dict.get('lobby', {"team": "all"})['team'] == "all":
                    ctx_herecount -= trainer_dict[trainer]['status']['lobby']
        raidtype = "event" if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id].get('meetup',
                                                                                               False) else "raid"
        if ctx_herecount > 0:
            if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and tag:
                here_exstr = " including {trainer_list} and the people with them! " \
                             "Be considerate and let them know if and when you'll be there" \
                    .format(trainer_list=', '.join(here_list))
            else:
                here_exstr = " including {trainer_list} and the people with them! " \
                             "Be considerate and let them know if and when you'll be there" \
                    .format(trainer_list=', '.join(name_list))
        listmsg = ' {trainer_count} waiting at the {raidtype}{including_string}!' \
            .format(trainer_count=str(ctx_herecount), raidtype=raidtype, including_string=here_exstr)
        return listmsg

    @staticmethod
    def determine_simple_party(member, count):
        allblue = 0
        allred = 0
        allyellow = 0
        allunknown = 0
        for role in member.roles:
            if role.name.lower() == 'mystic':
                allblue = count
                break
            elif role.name.lower() == 'valor':
                allred = count
                break
            elif role.name.lower() == 'instinct':
                allyellow = count
                break
        else:
            allunknown = count
        return {'mystic': allblue, 'valor': allred, 'instinct': allyellow, 'unknown': allunknown}

    @staticmethod
    def determine_trainer_count(trainer_dict):
        trainer_count = {'maybe': {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0},
                         'coming': {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0},
                         'here': {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0},
                         'lobby': {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}}

        for trainer in trainer_dict:
            for stat in trainer_dict[trainer]['status']:
                if trainer_dict[trainer]['status'][stat] > 0:
                    for team in trainer_dict[trainer]['party']:
                        trainer_count[stat][team] += trainer_dict[trainer]['party'][team]
        return trainer_count

    def build_status_embed(self, guild, trainer_count):
        blue_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['mystic'])
        red_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['valor'])
        yellow_emoji = utils.parse_emoji(guild, self.bot.config['team_dict']['instinct'])
        team_emojis = {'instinct': yellow_emoji, 'mystic': blue_emoji, 'valor': red_emoji, 'unknown': "❔"}
        all_count = 0
        embed = discord.Embed(colour=discord.Colour.purple(), title="Current Trainer Counts")
        for stat in trainer_count:
            status = stat.capitalize()
            count = 0
            count_str = ''
            for team in trainer_count[stat]:
                team_count = trainer_count[stat][team]
                count += team_count
                count_str += (team_emojis[team] * team_count)
            if count > 0:
                embed.add_field(name=status, value=count_str)
            all_count += count
        embed.set_footer(text="For full raid details, scroll to the top of this channel")
        if all_count == 0:
            return None
        return embed

    async def here(self, ctx, count, party, entered_interest=None):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        channel = ctx.channel
        author = ctx.author
        lobbymsg = ''
        trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
        raidtype = "event" if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('meetup',
                                                                                               False) else "raid"
        try:
            if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['lobby']:
                lobbymsg += '\nThere is a group already in the lobby! Use **!lobby** to join them ' \
                            'or **!backout** to request a backout! Otherwise, you may have to wait for the next group!'
        except KeyError:
            pass
        if not party:
            party = self.determine_simple_party(author, count)
        message = f"**{author.display_name}** is at the raid!"
        await ctx.message.delete()
        last_status = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        if author.id not in trainer_dict:
            trainer_dict[author.id] = {}
        trainer_dict[author.id]['status'] = {'maybe': 0, 'coming': 0, 'here': count, 'lobby': 0}
        trainer_dict[author.id]['count'] = count
        trainer_dict[author.id]['party'] = party
        if entered_interest:
            trainer_dict[author.id]['interest'] = entered_interest
        await self.edit_party(ctx, channel, author)
        trainer_count = self.determine_trainer_count(trainer_dict)
        embed = self.build_status_embed(channel.guild, trainer_count)
        new_status = await channel.send(content=message, embed=embed)
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
        regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            await self.update_listing_channels(channel.guild, 'raid', edit=True, regions=regions)

    async def cancel(self, ctx):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        channel = ctx.channel
        author = ctx.author
        guild = channel.guild
        raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', False) else "raid"
        await ctx.message.delete()
        try:
            trainer_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'][author.id]
        except KeyError:
            await channel.send('{member} has no status to cancel!'.format(member=author.name))
            return
        message = ''
        if trainer_dict['status']['maybe']:
            if trainer_dict['count'] == 1:
                message = '**{member}** is no longer interested!'.format(member=author.display_name)
            else:
                message = '**{member}** and their total of {trainer_count} trainers are no longer interested!' \
                    .format(member=author.display_name, trainer_count=trainer_dict['count'])
        if trainer_dict['status']['here']:
            if trainer_dict['count'] == 1:
                message = '**{member}** has left the {raidtype}!'.format(member=author.display_name, raidtype=raidtype)
            else:
                message = '**{member}** and their total of {trainer_count} trainers have left the {raidtype}!' \
                    .format(member=author.display_name, trainer_count=trainer_dict['count'], raidtype=raidtype)
        if trainer_dict['status']['coming']:
            if trainer_dict['count'] == 1:
                message = '**{member}** is no longer on their way!'.format(member=author.display_name)
            else:
                message = '**{member}** and their total of {trainer_count} trainers are no longer on their way!' \
                    .format(member=author.display_name, trainer_count=trainer_dict['count'])
        if trainer_dict['status']['lobby']:
            if trainer_dict['count'] == 1:
                message = '**{member}** has backed out of the lobby!'.format(member=author.display_name)
            else:
                message = '**{member}** and their total of {trainer_count} trainers have backed out of the lobby!' \
                    .format(member=author.display_name, trainer_count=trainer_dict['count'])
        last_status = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        trainer_dict['status'] = {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0}
        trainer_dict['party'] = {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
        trainer_dict['interest'] = []
        trainer_dict['count'] = 1
        await self.edit_party(ctx, channel, author)
        trainer_count = self.determine_trainer_count(
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
        embed = self.build_status_embed(channel.guild, trainer_count)
        new_status = await channel.send(content=message, embed=embed)
        guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
        regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
        if regions:
            await self.update_listing_channels(guild, 'raid', edit=True, regions=regions)

    async def edit_party(self, ctx, channel, author=None):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        raid_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]
        egglevel = raid_dict['egglevel']
        if egglevel != "0":
            boss_dict = {}
            boss_list = []
            display_list = []
            for entry in raid_info['raid_eggs'][egglevel]['pokemon']:
                p = Pokemon.get_pokemon(self.bot, entry)
                boss_list.append(p)
                boss_dict[p.name] = {"type": utils.types_to_str(channel.guild, p.types, self.bot.config), "total": 0}
        team_list = ["mystic", "valor", "instinct", "unknown"]
        status_list = ["maybe", "coming", "here"]
        trainer_dict = copy.deepcopy(raid_dict['trainer_dict'])
        status_dict = {'maybe': {'total': 0, 'trainers': {}}, 'coming': {'total': 0, 'trainers': {}},
                       'here': {'total': 0, 'trainers': {}}, 'lobby': {'total': 0, 'trainers': {}}}
        for trainer in trainer_dict:
            for status in status_list:
                if trainer_dict[trainer]['status'][status]:
                    status_dict[status]['trainers'][trainer] = {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
                    for team in team_list:
                        if trainer_dict[trainer]['party'][team] > 0:
                            status_dict[status]['trainers'][trainer][team] = trainer_dict[trainer]['party'][team]
                            status_dict[status]['total'] += trainer_dict[trainer]['party'][team]
            if egglevel != "0":
                for boss in boss_list:
                    if boss.name.lower() in trainer_dict[trainer].get('interest', []):
                        boss_dict[boss.name]['total'] += int(trainer_dict[trainer]['count'])
        if egglevel != "0":
            for boss in boss_list:
                if boss_dict[boss.name]['total'] > 0:
                    bossstr = "{name} ({number}) {types} : **{count}**" \
                        .format(name=boss.name, number=boss.id,
                                types=boss_dict[boss.name]['type'],
                                count=boss_dict[boss.name]['total'])
                    display_list.append(bossstr)
                elif boss_dict[boss.name]['total'] == 0:
                    bossstr = "{name} ({number}) {types}" \
                        .format(name=boss.name, number=boss.id, types=boss_dict[boss.name]['type'])
                    display_list.append(bossstr)
        try:
            raidmsg = await channel.fetch_message(raid_dict['raidmessage'])
        except:
            async for message in channel.history(limit=500, reverse=True):
                if author and message.author.id == channel.guild.me.id:
                    c = 'Coordinate here'
                    if c in message.content:
                        raidmsg = message
                        break
        report_embed, raid_embed = await embed_utils.build_raid_embeds(self.bot, ctx, raid_dict, True)
        red_emoji = utils.parse_emoji(channel.guild, self.bot.config['team_dict']['valor'])
        yellow_emoji = utils.parse_emoji(channel.guild, self.bot.config['team_dict']['instinct'])
        blue_emoji = utils.parse_emoji(channel.guild, self.bot.config['team_dict']['mystic'])
        team_emojis = {'instinct': yellow_emoji, 'mystic': blue_emoji, 'valor': red_emoji, 'unknown': "❔"}
        if len(raid_embed.fields) % 2 == 1:
            raid_embed.add_field(name='\u200b', value='\u200b')
        for status in status_list:
            embed_value = None
            if status_dict[status]['total'] > 0:
                embed_value = u"\u200B"
                for trainer in status_dict[status]['trainers']:
                    member = channel.guild.get_member(trainer)
                    if member is not None:
                        embed_value += f"{member.display_name} "
                        for team in status_dict[status]['trainers'][trainer]:
                            embed_value += team_emojis[team] * status_dict[status]['trainers'][trainer][team]
                        embed_value += "\n"
            if embed_value is not None:
                raid_embed.add_field(name=f'**{status.capitalize()}**', value=embed_value, inline=True)
        try:
            await raidmsg.edit(embed=raid_embed)
        except:
            pass

    async def lobbylist(self, ctx, tag=False, team=False):
        guild_dict = self.bot.guild_dict
        ctx_lobbycount = 0
        now = datetime.datetime.utcnow() \
              + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
        raid_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id])
        trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
        lobby_exstr = ''
        lobby_list = []
        name_list = []
        for trainer in trainer_dict.keys():
            user = ctx.guild.get_member(trainer)
            if (trainer_dict[trainer]['status']['lobby']) and user and not team:
                ctx_lobbycount += trainer_dict[trainer]['status']['lobby']
                if trainer_dict[trainer]['status']['lobby'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    lobby_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['status']['lobby']))
                    lobby_list.append('{name} **({count})**'
                                      .format(name=user.mention, count=trainer_dict[trainer]['status']['lobby']))
            elif (trainer_dict[trainer]['status']['lobby']) and user and team and trainer_dict[trainer]['party'][team]:
                if trainer_dict[trainer]['status']['lobby'] == 1:
                    name_list.append('**{name}**'.format(name=user.display_name))
                    lobby_list.append(user.mention)
                else:
                    name_list.append('**{name} ({count})**'
                                     .format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                    lobby_list.append('{name} **({count})**'
                                      .format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
                if raid_dict.get('lobby', {"team": "all"})['team'] == team \
                        or raid_dict.get('lobby', {"team": "all"})['team'] == "all":
                    ctx_lobbycount += trainer_dict[trainer]['party'][team]

        if ctx_lobbycount > 0:
            if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and tag:
                lobby_exstr = ' including {trainer_list} and the people with them! ' \
                              'Use **!lobby** if you are joining them or **!backout** to request a backout' \
                    .format(trainer_list=', '.join(lobby_list))
            else:
                lobby_exstr = ' including {trainer_list} and the people with them! ' \
                              'Use **!lobby** if you are joining them or **!backout** to request a backout' \
                    .format(trainer_list=', '.join(name_list))
        listmsg = ' {trainer_count} in the lobby{including_string}!' \
            .format(trainer_count=str(ctx_lobbycount), including_string=lobby_exstr)
        return listmsg

    async def bosslist(self, ctx):
        guild_dict, raid_info = self.bot.guild_dict, self.bot.raid_info
        message = ctx.message
        channel = ctx.channel
        egglevel = guild_dict[message.guild.id]['raidchannel_dict'][channel.id]['egglevel']
        egg_level = str(egglevel)
        if egg_level in raid_info['raid_eggs'].keys():
            egg_info = raid_info['raid_eggs'][egg_level]
        else:
            return await ctx.message.delete()
        egg_img = egg_info['egg_img']
        boss_dict = {}
        boss_list = []
        boss_dict["unspecified"] = {"type": "❔", "total": 0, "maybe": 0, "coming": 0, "here": 0}
        for entry in egg_info['pokemon']:
            p = Pokemon.get_pokemon(self.bot, entry)
            name = str(p).lower()
            boss_list.append(name)
            boss_dict[name] = {"type": utils.types_to_str(message.guild, p.types, self.bot.config),
                               "total": 0, "maybe": 0, "coming": 0, "here": 0}
        boss_list.append('unspecified')
        trainer_dict = copy.deepcopy(guild_dict[message.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
        for trainer in trainer_dict:
            if not ctx.guild.get_member(trainer):
                continue
            interest = trainer_dict[trainer].get('interest', ['unspecified'])
            for item in interest:
                status = max(trainer_dict[trainer]['status'], key=lambda key: trainer_dict[trainer]['status'][key])
                count = trainer_dict[trainer]['count']
                boss_dict[item][status] += count
                boss_dict[item]['total'] += count
        bossliststr = ''
        for boss in boss_list:
            if boss_dict[boss]['total'] > 0:
                bossliststr += '{type}{name}: **{total} total,** {interested} interested, {coming} coming, ' \
                               '{here} waiting{type}\n' \
                    .format(type=boss_dict[boss]['type'], name=boss.capitalize(),
                            total=boss_dict[boss]['total'], interested=boss_dict[boss]['maybe'],
                            coming=boss_dict[boss]['coming'], here=boss_dict[boss]['here'])
        if bossliststr:
            listmsg = ' Boss numbers for the raid:\n{}'.format(bossliststr)
        else:
            listmsg = ' Nobody has told me what boss they want!'
        return listmsg

    async def teamlist(self, ctx):
        guild_dict = self.bot.guild_dict
        message = ctx.message
        team_dict = {"mystic": {"total": 0, "maybe": 0, "coming": 0, "here": 0},
                     "valor": {"total": 0, "maybe": 0, "coming": 0, "here": 0},
                     "instinct": {"total": 0, "maybe": 0, "coming": 0, "here": 0},
                     "unknown": {"total": 0, "maybe": 0, "coming": 0, "here": 0}}
        status_list = ["here", "coming", "maybe"]
        team_list = ["mystic", "valor", "instinct", "unknown"]
        teamliststr = ''
        trainer_dict = copy.deepcopy(
            guild_dict[message.guild.id]['raidchannel_dict'][message.channel.id]['trainer_dict'])
        for trainer in trainer_dict.keys():
            if not ctx.guild.get_member(trainer):
                continue
            for team in team_list:
                team_dict[team]["total"] += int(trainer_dict[trainer]['party'][team])
                for status in status_list:
                    if max(trainer_dict[trainer]['status'],
                           key=lambda key: trainer_dict[trainer]['status'][key]) == status:
                        team_dict[team][status] += int(trainer_dict[trainer]['party'][team])
        for team in team_list[:-1]:
            if team_dict[team]['total'] > 0:
                teamliststr += '{emoji} **{total} total,** {interested} interested, ' \
                               '{coming} coming, {here} waiting {emoji}\n' \
                    .format(emoji=utils.parse_emoji(ctx.guild, self.bot.config['team_dict'][team]),
                            total=team_dict[team]['total'], interested=team_dict[team]['maybe'],
                            coming=team_dict[team]['coming'], here=team_dict[team]['here'])
        if team_dict["unknown"]['total'] > 0:
            teamliststr += '❔ '
            teamliststr += '**{grey_number} total,** {greymaybe} interested, {greycoming} coming, {greyhere} waiting'
            teamliststr += ' ❔'
            teamliststr = teamliststr.format(grey_number=team_dict['unknown']['total'],
                                             greymaybe=team_dict['unknown']['maybe'],
                                             greycoming=team_dict['unknown']['coming'],
                                             greyhere=team_dict['unknown']['here'])
        if teamliststr:
            listmsg = ' Team numbers for the raid:\n{}'.format(teamliststr)
        else:
            listmsg = ' Nobody has updated their status!'
        return listmsg

    async def get_region_reporting_channels(self, guild, region):
        report_channels = []
        for c in self.bot.guild_dict[guild.id]['configure_dict']['raid']['report_channels']:
            if self.bot.guild_dict[guild.id]['configure_dict']['raid']['report_channels'][c] == region:
                report_channels.append(c)
        return report_channels

    async def update_listing_channels(self, guild, list_type, edit=False, regions=None):
        guild_dict = self.bot.guild_dict
        valid_types = ['raid', 'research', 'wild', 'nest', 'lure', 'hideout']
        if list_type not in valid_types:
            return
        listing_dict = guild_dict[guild.id]['configure_dict'].get(list_type, {}).get('listings', None)
        if not listing_dict or not listing_dict['enabled']:
            return
        if 'channel' in listing_dict:
            channel = self.bot.get_channel(listing_dict['channel']['id'])
            return await self._update_listing_channel(channel, list_type, edit)
        if 'channels' in listing_dict:
            if not regions:
                regions = [r for r in listing_dict['channels']]
            for region in regions:
                channel_list = listing_dict['channels'].get(region, [])
                if not isinstance(channel_list, list):
                    channel_list = [channel_list]
                for channel_info in channel_list:
                    channel = self.bot.get_channel(channel_info['id'])
                    await self._update_listing_channel(channel, list_type, edit, region=region)

    async def _update_listing_channel(self, channel, list_type, edit, region=None):
        guild_dict = self.bot.guild_dict
        lock = asyncio.Lock()
        async with lock:
            listing_dict = guild_dict[channel.guild.id]['configure_dict'].get(list_type, {}).get('listings', None)
            if not listing_dict or not listing_dict['enabled']:
                return
            if list_type == 'hideout':
                return await self._update_hideout_listings(channel, region, edit)
            new_messages = await self.get_listing_messages(list_type, channel, region)
            previous_messages = await self._get_previous_listing_messages(list_type, channel, region)
            new_messages = [] if new_messages is None else new_messages
            previous_messages = [] if previous_messages is None else previous_messages
            matches = itertools.zip_longest(new_messages, previous_messages)
            new_ids = []

            def should_delete(m):
                check = True
                if m.embeds and len(m.embeds) > 0:
                    check = (list_type in m.embeds[0].description.lower())
                else:
                    date1 = m.created_at
                    date2 = datetime.datetime.utcnow()
                    check = (abs(date2 - date1).seconds) > 180
                return m.author == self.bot.user and check

            if not edit:
                await channel.purge(check=should_delete)
            for pair in matches:
                new_message = pair[0]
                old_message = pair[1]
                if pair[1]:
                    try:
                        old_message = await channel.fetch_message(old_message)
                    except:
                        old_message = None
                if new_message:
                    new_embed = discord.Embed(description=new_message, colour=channel.guild.me.colour)
                    if old_message:
                        if edit:
                            await old_message.edit(embed=new_embed)
                            new_ids.append(old_message.id)
                            continue
                    new_message_obj = None
                    while new_message_obj is None:
                        try:
                            new_message_obj = await channel.send(embed=new_embed)
                        except ClientOSError:
                            pass
                    new_ids.append(new_message_obj.id)
            if 'channel' in listing_dict:
                listing_dict['channel']['messages'] = new_ids
            elif 'channels' in listing_dict:
                listing_dict['channels'][region]['messages'] = new_ids
            guild_dict[channel.guild.id]['configure_dict'][list_type]['listings'] = listing_dict

    async def _get_previous_listing_messages(self, list_type, channel, region=None):
        guild_dict = self.bot.guild_dict
        listing_dict = guild_dict[channel.guild.id]['configure_dict'].get(list_type, {}).get('listings', None)
        if not listing_dict or not listing_dict['enabled']:
            return
        previous_messages = []
        if 'channel' in listing_dict:
            previous_messages = listing_dict['channel'].get('messages', [])
        elif 'channels' in listing_dict:
            if region:
                previous_messages = listing_dict['channels'].get(region, {}).get('messages', [])
            else:
                for region, channel_info in listing_dict['channels'].items():
                    if channel_info['id'] == channel.id:
                        previous_messages = channel_info.get('messages', [])
                        break
        else:
            message_history = []
            message_history = await channel.history(reverse=True).flatten()
            if len(message_history) >= 1:
                search_text = f"active {list_type}"
                for message in message_history:
                    if search_text in message.embeds[0].description.lower():
                        previous_messages.append(message.id)
                        break
        return previous_messages


def setup(bot):
    bot.add_cog(ListManagement(bot))
