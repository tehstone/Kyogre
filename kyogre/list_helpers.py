import asyncio
import copy
import datetime
import itertools
import time

from operator import itemgetter

import discord

from kyogre.exts.pokemon import Pokemon
from kyogre.exts.db.kyogredb import *
from kyogre import constants, embed_utils, raid_helpers, utils


async def _get_listing_messages(Kyogre, guild_dict, type, channel, region=None):
    if type == 'raid':
        return await _get_raid_listing_messages(Kyogre, channel, guild_dict, region)
    elif type == 'wild':
        return await _get_wild_listing_messages(Kyogre, channel, guild_dict, region)
    elif type == 'research':
        return await _get_research_listing_messages(Kyogre, channel, guild_dict, region)
    elif type == 'lure':
        return await _get_lure_listing_messages(Kyogre, channel, guild_dict, region)
    else:
        return None


async def _get_raid_listing_messages(Kyogre, channel, guild_dict, region=None):
    '''
    listings_enabled | region_set | result
    ======================================
            Y        |      Y     |   get for region only (regional listings configured)
            Y        |      N     |   get for all regions (listings configured -- one channel)
            N        |      Y     |   normal list for region only (list command enabled in regional channel)
            N        |      N     |   normal list (all regions -- list command enabled)
    '''
    guild = channel.guild
    listmsg_list = []
    listmsg = ""
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    listing_dict = guild_dict[guild.id]['configure_dict']['raid'].get('listings', {})
    listing_enabled = listing_dict.get('enabled', False)
    rc_d = guild_dict[guild.id]['raidchannel_dict']
    if region:
        cty = region
    else:
        cty = channel.name
    raid_dict = {}
    egg_dict = {}
    exraid_list = []
    event_list = []
    for r in rc_d:
        if region:
            reportlocation = rc_d[r].get('regions', [])
        elif listing_enabled and 'channel' in listing_dict:
            reportlocation = [Kyogre.get_channel(listing_dict['channel']).name]
        else: 
            reportlocation = [Kyogre.get_channel(rc_d[r]['reportcity']).name]
        if not reportlocation:
            continue
        if (cty in reportlocation) and rc_d[r]['active'] and discord.utils.get(guild.text_channels, id=r):
            exp = rc_d[r]['exp']
            type = rc_d[r]['type']
            level = rc_d[r]['egglevel']
            if (type == 'egg') and level.isdigit():
                egg_dict[r] = exp
            elif rc_d[r].get('meetup',{}):
                event_list.append(r)
            elif ((type == 'exraid') or (level == 'EX')):
                exraid_list.append(r)
            else:
                raid_dict[r] = exp

    def list_output(r):
        trainer_dict = rc_d[r]['trainer_dict']
        rchan = Kyogre.get_channel(r)
        end = now + datetime.timedelta(seconds=rc_d[r]['exp'] - time.time())
        output = ''
        start_str = ''
        t_emoji = ''
        ex_eligibility = ''
        trainer_count = {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
        for trainer in rc_d[r]['trainer_dict'].keys():
            if not guild.get_member(trainer):
                continue
            for stat in trainer_dict[trainer]['status']:
                if trainer_dict[trainer]['status'][stat] > 0 and stat != 'lobby':
                    for team in trainer_dict[trainer]['party']:
                        trainer_count[team] += trainer_dict[trainer]['party'][team]
        if rc_d[r]['manual_timer'] == False:
            assumed_str = ' (assumed)'
        else:
            assumed_str = ''
        starttime = rc_d[r].get('starttime',None)
        meetup = rc_d[r].get('meetup',{})
        if starttime and starttime > now and not meetup:
            start_str = '\n\t\t**Next Group**: {}'.format(starttime.strftime('%I:%M%p'))
        else:
            starttime = False
        egglevel = rc_d[r]['egglevel']
        if egglevel.isdigit() and (int(egglevel) > 0):
            t_emoji = str(egglevel) + '\u20e3'
            expirytext = '**Hatches**: {expiry}{is_assumed}'.format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
        elif ((rc_d[r]['egglevel'] == 'EX') or (rc_d[r]['type'] == 'exraid')) and not meetup:
            expirytext = '**Hatches**: {expiry}{is_assumed}'.format(expiry=end.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
        elif meetup:
            meetupstart = meetup['start']
            meetupend = meetup['end']
            expirytext = ""
            if meetupstart:
                expirytext += ' - Starts: {expiry}{is_assumed}'.format(expiry=meetupstart.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
            if meetupend:
                expirytext += " - Ends: {expiry}{is_assumed}".format(expiry=meetupend.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
            if not meetupstart and not meetupend:
                expirytext = ' - Starts: {expiry}{is_assumed}'.format(expiry=end.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
        else:
            expirytext = '**Expires**: {expiry}{is_assumed}'.format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
        boss = Pokemon.get_pokemon(Kyogre, rc_d[r].get('pokemon', ''))
        if not t_emoji and boss:
            t_emoji = str(boss.raid_level) + '\u20e3'
        gym = rc_d[r].get('gym', None)
        if gym:
            ex_eligibility = ' *EX-Eligible* ' if gym.ex_eligible else ''
        enabled = raid_helpers.raid_channels_enabled(guild, rchan, guild_dict)
        if enabled:
            blue_emoji = utils.parse_emoji(rchan.guild, Kyogre.config['team_dict']['mystic'])
            red_emoji = utils.parse_emoji(rchan.guild, Kyogre.config['team_dict']['valor'])
            yellow_emoji = utils.parse_emoji(rchan.guild, Kyogre.config['team_dict']['instinct'])
            team_emoji_dict = {'mystic': blue_emoji, 'valor': red_emoji, 'instinct': yellow_emoji, 'unknown': '❔'}
            total_count = ''
            for team in trainer_count:
                total_count += trainer_count[team] * team_emoji_dict[team]
            if len(total_count) < 1:
                total_count = '0'
            # sum([ctx_maybecount, ctx_comingcount, ctx_herecount, ctx_lobbycount])
            output += '\t{tier} {chan}{ex}\n\t\t{expiry_text}{starttime}\n\t\t**Trainer Count**: {total_count}\n'\
                .format(tier=t_emoji, chan=rchan.mention, ex=ex_eligibility, expiry_text=expirytext,
                        total_count=total_count, starttime=start_str)
        else:
            channel_name = rchan.name.replace('_', ': ').replace('-', ' ').title()
            map_url = ''
            map_url = rc_d[r]['gym'].maps_url
            try:
                map_url = rc_d[r]['gym'].maps_url
            except:
                pass
            output += '\t{tier} **{raidchannel}** {ex_eligibility}\n{expiry_text}\n[Click for directions]({map_url})\n'\
                .format(tier=t_emoji, raidchannel=channel_name, ex_eligibility=ex_eligibility,
                        expiry_text=expirytext, map_url=map_url)
        return output
    
    def process_category(listmsg_list, category_title, category_list):
        listmsg = f"**{category_title}:**\n"
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
        reporting_channels = await get_region_reporting_channels(guild, region, guild_dict)
        report_channel = guild.get_channel(reporting_channels[0])
        report_str = f"Report a new raid in {report_channel.mention}\n"
    if activeraidnum:
        listmsg += f"**Current eggs and raids reported in {cty.capitalize()}**\n"
        if region:
            listmsg += report_str
        listmsg += "\n"
        if raid_dict:
            listmsg += process_category(listmsg_list, "Active Raids", [r for (r, __) in sorted(raid_dict.items(), key=itemgetter(1))])
        if egg_dict:
            listmsg += process_category(listmsg_list, "Raid Eggs", [r for (r, __) in sorted(egg_dict.items(), key=itemgetter(1))])
        if exraid_list and not listing_enabled:
            listmsg += process_category(listmsg_list, "EX Raids", exraid_list)
        if event_list and not listing_enabled:
            listmsg += process_category(listmsg_list, "Meetups", event_list)
    else:
        listmsg = 'No active raids! Report one with **!raid <name> <location> [weather] [timer]**.'
        if region:
            listmsg += "\n" + report_str
    listmsg_list.append(listmsg)
    return listmsg_list


async def _get_wild_listing_messages(Kyogre, channel, guild_dict, region=None):
    guild = channel.guild
    if region:
        loc = region
    else:
        loc = channel.name
    wild_dict = copy.deepcopy(guild_dict[guild.id].get('wildreport_dict',{}))
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
        if not region or region in raid_helpers.get_channel_regions(report_channel, 'wild', guild_dict):
            try:
                await report_channel.fetch_message(wildid)
                newmsg += ('\n🔹')
                newmsg += "**Pokemon**: {pokemon}, **Location**: [{location}]({url})".format(pokemon=wild_dict[wildid]['pokemon'].title(),location=wild_dict[wildid]['location'].title(),url=wild_dict[wildid].get('url',None))
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


async def _get_research_listing_messages(Kyogre, channel, guild_dict, region=None):
    guild = channel.guild
    if region:
        loc = region
    else:
        loc = channel.name
    research_dict = copy.deepcopy(guild_dict[guild.id].setdefault('questreport_dict', {}))
    research_dict = dict(sorted(research_dict.items(), key=lambda i: (i[1]['quest'], i[1]['reward'], i[1]['location'])))
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
        if not region or region in raid_helpers.get_channel_regions(report_channel, 'research', guild_dict):
            try:
                await report_channel.fetch_message(questid) # verify quest message exists
                cat = research_dict[questid]['quest'].title()
                if current_category != cat:
                    current_category = cat
                    newmsg += f"\n\n**{current_category}**"
                newmsg += ('\n\t🔹')
                newmsg += "**Reward**: {reward}, **Pokestop**: [{location}]({url})".format(location=research_dict[questid]['location'].title(), reward=research_dict[questid]['reward'].title(), url=research_dict[questid].get('url',None))
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


async def _get_lure_listing_messages(Kyogre, channel, guild_dict, region=None):
    guild = channel.guild
    if region:
        loc = region
    else:
        loc = channel.name
    lurectr = 0
    listmsg_list = []
    listmsg = f"**Here are the active lures in {loc.capitalize()}**\n"
    current_category = ""
    current = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[channel.guild.id]['configure_dict']['settings']['offset'])
    result = (TrainerReportRelation.select(
                    TrainerReportRelation.created,
                    LocationTable.name.alias('location_name'),
                    LureTypeTable.name.alias('lure_type'),
                    LocationTable.latitude,
                    LocationTable.longitude)
            .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
            .join(LocationRegionRelation, on=(LocationTable.id==LocationRegionRelation.location_id))
            .join(RegionTable, on=(RegionTable.id==LocationRegionRelation.region_id))
            .join(LureTable, on=(TrainerReportRelation.id == LureTable.trainer_report_id))
            .join(LureTypeRelation, on=(LureTable.id == LureTypeRelation.lure_id))
            .join(LureTypeTable, on=(LureTypeTable.id == LureTypeRelation.type_id))
            .where((RegionTable.name == region) &
                   (TrainerReportRelation.created.day == current.day)))

    result = result.objects(LureInstance)
    results = [o for o in result]
    for lure in results:
        lure_create = datetime.datetime.strptime(lure.created, '%Y-%m-%d %H:%M:%S')
        exp = lure_create+datetime.timedelta(minutes=30)
        if exp < current:
            continue
        newmsg = ""
        try:
            type = lure.lure_type
            if current_category != type:
                current_category = type
                newmsg += f"\n\n**{current_category.capitalize()}**"
            newmsg += ('\n\t🔹')
            stop_url = utils.simple_gmaps_query(lure.latitude, lure.longitude)
            newmsg += f"**Pokestop**: [{lure.location_name}]({stop_url}) - Expires: {exp.strftime('%I:%M:%S')} (approx.)."
            if len(listmsg) + len(newmsg) < constants.MAX_MESSAGE_LENGTH:
                listmsg += newmsg
            else:
                listmsg_list.append(listmsg)
                if current_category not in newmsg:
                    newmsg = f"**({current_category} continued)**"
                listmsg = newmsg
            lurectr += 1
        except discord.errors.NotFound:
            continue    
    if lurectr == 0:
        listmsg = "There are no active lures. Report one with **!lure**"
    listmsg_list.append(listmsg)
    return listmsg_list


async def _interest(ctx, Kyogre, guild_dict, tag=False, team=False):
    ctx_maybecount = 0
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
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
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['status']['maybe']))
                maybe_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['status']['maybe']))
        elif (trainer_dict[trainer]['status']['maybe']) and user and team and trainer_dict[trainer]['party'][team]:
            if trainer_dict[trainer]['status']['maybe'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                maybe_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                maybe_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
            ctx_maybecount += trainer_dict[trainer]['party'][team]

    if ctx_maybecount > 0:
        if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and (tag == True):
            maybe_exstr = ' including {trainer_list} and the people with them! Let them know if there is a group forming'.format(trainer_list=', '.join(maybe_list))
        else:
            maybe_exstr = ' including {trainer_list} and the people with them! Let them know if there is a group forming'.format(trainer_list=', '.join(name_list))
    listmsg = ' {trainer_count} interested{including_string}!'.format(trainer_count=str(ctx_maybecount), including_string=maybe_exstr)
    return listmsg


async def _maybe(ctx, Kyogre, guild_dict, raid_info, count, party, entered_interest=None):
    channel = ctx.channel
    author = ctx.author
    trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    if (not party):
        party = determine_simple_party(author, count)
    message = f"**{author.display_name}** is interested!"   
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
    trainer_dict[author.id]['status'] = {'maybe':count, 'coming':0, 'here':0, 'lobby':0}
    trainer_dict[author.id]['count'] = count
    trainer_dict[author.id]['party'] = party
    await _edit_party(ctx, Kyogre, guild_dict, raid_info, channel, author)
    trainer_count = determine_trainer_count(trainer_dict)
    embed = build_status_embed(channel.guild, Kyogre, trainer_count)
    new_status = await channel.send(content=message, embed=embed)
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
    regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
    if regions:
        await update_listing_channels(Kyogre, guild_dict, channel.guild, 'raid', edit=True, regions=regions)


async def _otw(ctx, Kyogre, guild_dict, tag=False, team=False):
    ctx_comingcount = 0
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
    trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
    otw_exstr = ''
    otw_list = []
    name_list = []
    for trainer in trainer_dict.keys():
        user = ctx.guild.get_member(trainer)
        if (trainer_dict[trainer]['status']['coming']) and user and team == False:
            ctx_comingcount += trainer_dict[trainer]['status']['coming']
            if trainer_dict[trainer]['status']['coming'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                otw_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['status']['coming']))
                otw_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['status']['coming']))
        elif (trainer_dict[trainer]['status']['coming']) and user and team and trainer_dict[trainer]['party'][team]:
            if trainer_dict[trainer]['status']['coming'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                otw_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                otw_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
            ctx_comingcount += trainer_dict[trainer]['party'][team]

    if ctx_comingcount > 0:
        if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and (tag == True):
            otw_exstr = ' including {trainer_list} and the people with them! Be considerate and wait for them if possible'.format(trainer_list=', '.join(otw_list))
        else:
            otw_exstr = ' including {trainer_list} and the people with them! Be considerate and wait for them if possible'.format(trainer_list=', '.join(name_list))
    listmsg = ' {trainer_count} on the way{including_string}!'.format(trainer_count=str(ctx_comingcount), including_string=otw_exstr)
    return listmsg


async def _coming(ctx, Kyogre, guild_dict, raid_info, count, party, entered_interest=None):
    channel = ctx.channel
    author = ctx.author
    trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    if (not party):
        party = determine_simple_party(author, count)
    message = f"**{author.display_name}** is on their way!"
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
    await _edit_party(ctx, Kyogre, guild_dict, raid_info, channel, author)
    trainer_count = determine_trainer_count(trainer_dict)
    embed = build_status_embed(channel.guild, Kyogre, trainer_count)
    new_status = await channel.send(content=message, embed=embed)
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
    regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
    if regions:
        await update_listing_channels(Kyogre, guild_dict, channel.guild, 'raid', edit=True, regions=regions)


async def _waiting(ctx, Kyogre, guild_dict, tag=False, team=False):
    ctx_herecount = 0
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
    raid_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id])
    trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
    here_exstr = ''
    here_list = []
    name_list = []
    for trainer in trainer_dict.keys():
        user = ctx.guild.get_member(trainer)
        if (trainer_dict[trainer]['status']['here']) and user and team == False:
            ctx_herecount += trainer_dict[trainer]['status']['here']
            if trainer_dict[trainer]['status']['here'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                here_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['status']['here']))
                here_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['status']['here']))
        elif (trainer_dict[trainer]['status']['here']) and user and team and trainer_dict[trainer]['party'][team]:
            if trainer_dict[trainer]['status']['here'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                here_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                here_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
            ctx_herecount += trainer_dict[trainer]['party'][team]
            if raid_dict.get('lobby',{"team":"all"})['team'] == team or raid_dict.get('lobby',{"team":"all"})['team'] == "all":
                ctx_herecount -= trainer_dict[trainer]['status']['lobby']
    raidtype = "event" if guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id].get('meetup',False) else "raid"
    if ctx_herecount > 0:
        if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and (tag == True):
            here_exstr = " including {trainer_list} and the people with them! Be considerate and let them know if and when you'll be there".format(trainer_list=', '.join(here_list))
        else:
            here_exstr = " including {trainer_list} and the people with them! Be considerate and let them know if and when you'll be there".format(trainer_list=', '.join(name_list))
    listmsg = ' {trainer_count} waiting at the {raidtype}{including_string}!'.format(trainer_count=str(ctx_herecount), raidtype=raidtype, including_string=here_exstr)
    return listmsg

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
    return {'mystic':allblue, 'valor':allred, 'instinct':allyellow, 'unknown':allunknown}


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


def build_status_embed(guild, Kyogre, trainer_count):
    blue_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['mystic'])
    red_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['valor'])
    yellow_emoji = utils.parse_emoji(guild, Kyogre.config['team_dict']['instinct'])
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

async def _here(ctx, Kyogre, guild_dict, raid_info, count, party, entered_interest=None):
    channel = ctx.channel
    author = ctx.author
    lobbymsg = ''
    trainer_dict = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict']
    raidtype = "event" if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('meetup',False) else "raid"
    try:
        if guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['lobby']:
            lobbymsg += '\nThere is a group already in the lobby! Use **!lobby** to join them or **!backout** to request a backout! Otherwise, you may have to wait for the next group!'
    except KeyError:
        pass
    if (not party):
        party = determine_simple_party(author, count)
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
    trainer_dict[author.id]['status'] = {'maybe':0, 'coming':0, 'here':count, 'lobby':0}
    trainer_dict[author.id]['count'] = count
    trainer_dict[author.id]['party'] = party
    if entered_interest:
        trainer_dict[author.id]['interest'] = entered_interest
    await _edit_party(ctx, Kyogre, guild_dict, raid_info, channel, author)
    trainer_count = determine_trainer_count(trainer_dict)
    embed = build_status_embed(channel.guild, Kyogre, trainer_count)
    new_status = await channel.send(content=message, embed=embed)
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'] = trainer_dict
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
    regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
    if regions:
        await update_listing_channels(Kyogre, guild_dict, channel.guild, 'raid', edit=True, regions=regions)


async def _cancel(ctx, Kyogre, guild_dict, raid_info):
    channel = ctx.channel
    author = ctx.author
    guild = channel.guild
    raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',False) else "raid"
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
            message = '**{member}** and their total of {trainer_count} trainers are no longer interested!'.format(member=author.display_name, trainer_count=trainer_dict['count'])
    if trainer_dict['status']['here']:
        if trainer_dict['count'] == 1:
            message = '**{member}** has left the {raidtype}!'.format(member=author.display_name, raidtype=raidtype)
        else:
            message = '**{member}** and their total of {trainer_count} trainers have left the {raidtype}!'.format(member=author.display_name, trainer_count=trainer_dict['count'], raidtype=raidtype)
    if trainer_dict['status']['coming']:
        if trainer_dict['count'] == 1:
            message = '**{member}** is no longer on their way!'.format(member=author.display_name)
        else:
            message = '**{member}** and their total of {trainer_count} trainers are no longer on their way!'.format(member=author.display_name, trainer_count=trainer_dict['count'])
    if trainer_dict['status']['lobby']:
        if trainer_dict['count'] == 1:
            message = '**{member}** has backed out of the lobby!'.format(member=author.display_name)
        else:
            message = '**{member}** and their total of {trainer_count} trainers have backed out of the lobby!'.format(member=author.display_name, trainer_count=trainer_dict['count'])
    last_status = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('last_status', None)
    if last_status is not None:
        try:
            last = await channel.fetch_message(last_status)
            await last.delete()
        except:
            pass
    trainer_dict['status'] = {'maybe':0, 'coming':0, 'here':0, 'lobby':0}
    trainer_dict['party'] = {'mystic':0, 'valor':0, 'instinct':0, 'unknown':0}
    trainer_dict['interest'] = []
    trainer_dict['count'] = 1
    await _edit_party(ctx, Kyogre, guild_dict, raid_info, channel, author)
    trainer_count = determine_trainer_count(guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
    embed = build_status_embed(channel.guild, Kyogre, trainer_count)
    new_status = await channel.send(content=message, embed=embed)
    guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['last_status'] = new_status.id
    regions = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id].get('regions', None)
    if regions:
        await update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=True, regions=regions)


async def _edit_party(ctx, Kyogre, guild_dict, raid_info, channel, author=None):
    egglevel = guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['egglevel']
    if egglevel != "0":
        boss_dict = {}
        boss_list = []
        display_list = []
        for entry in raid_info['raid_eggs'][egglevel]['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, entry)
            boss_list.append(p)
            boss_dict[p.name] = {"type": utils.types_to_str(channel.guild, p.types, Kyogre.config), "total": 0}
    team_list = ["mystic", "valor", "instinct", "unknown"]
    status_list = ["maybe", "coming", "here"]
    trainer_dict = copy.deepcopy(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
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
    reportchannel = Kyogre.get_channel(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['reportchannel'])
    try:
        reportmsg = await reportchannel.fetch_message(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['raidreport'])
    except:
        pass
    try:
        raidmsg = await channel.fetch_message(guild_dict[channel.guild.id]['raidchannel_dict'][channel.id]['raidmessage'])
    except:
        async for message in channel.history(limit=500, reverse=True):
            if author and message.author.id == channel.guild.me.id:
                c = 'Coordinate here'
                if c in message.content:
                    reportchannel = message.raw_channel_mentions[0]
                    raidmsg = message
                    break
    reportembed = raidmsg.embeds[0]
    newembed = discord.Embed(title=reportembed.title, url=reportembed.url, colour=channel.guild.me.colour)
    index = 0
    m = 'maybe'
    c = 'coming'
    h = 'here'
    t = 'tips'
    embed_indices = await embed_utils.get_embed_field_indices(reportembed)
    for field in reportembed.fields:
        if (m not in field.name.lower()) and (c not in field.name.lower())\
                and (h not in field.name.lower()) and (t not in field.name.lower()):
            newembed.add_field(name=field.name, value=field.value, inline=field.inline)
    if egglevel != "0" and not guild_dict[channel.guild.id].get('raidchannel_dict',{}).get(channel.id,{}).get('meetup',{}):
        index = max(i for i in [embed_indices["possible"],embed_indices["interest"],embed_indices["details"]] if i is not None)
        name = "**Possible Bosses:**"
        if len(boss_list) > 1:
            newembed.set_field_at(index, name=name, value='{bosslist1}'.format(bosslist1='\n'.join(display_list[::2])), inline=True)
            newembed.set_field_at(index+1, name='\u200b', value='{bosslist2}'.format(bosslist2='\n'.join(display_list[1::2])), inline=True)
        else:
            newembed.set_field_at(index, name=name, value='{bosslist}'.format(bosslist=''.join(display_list)), inline=True)
            if newembed.fields[index+1].name == '\u200b':
                newembed.set_field_at(index+1, name='\u200b', value='\u200b', inline=True)
    red_emoji = utils.parse_emoji(channel.guild, Kyogre.config['team_dict']['valor'])
    yellow_emoji = utils.parse_emoji(channel.guild, Kyogre.config['team_dict']['instinct'])
    blue_emoji = utils.parse_emoji(channel.guild, Kyogre.config['team_dict']['mystic'])
    team_emojis = {'instinct': yellow_emoji, 'mystic': blue_emoji, 'valor': red_emoji, 'unknown': "❔"}
    tips = reportembed.fields[embed_indices["tips"]]
    if tips is not None:
        newembed.add_field(name=tips.name, value=tips.value)
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
            newembed.add_field(name=f'**{status.capitalize()}**', value=embed_value, inline=True)
    newembed.set_footer(text=reportembed.footer.text, icon_url=reportembed.footer.icon_url)
    newembed.set_thumbnail(url=reportembed.thumbnail.url)
    try:
        await raidmsg.edit(embed=newembed)
    except:
        pass
    try:
        embed_indices = await embed_utils.get_embed_field_indices(newembed)
        newembed = await embed_utils.filter_fields_for_report_embed(newembed, embed_indices)
        await reportmsg.edit(embed=newembed)
    except:
        pass


async def _lobbylist(ctx, Kyogre, guild_dict, tag=False, team=False):
    ctx_lobbycount = 0
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=guild_dict[ctx.channel.guild.id]['configure_dict']['settings']['offset'])
    raid_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id])
    trainer_dict = copy.deepcopy(guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'])
    lobby_exstr = ''
    lobby_list = []
    name_list = []
    for trainer in trainer_dict.keys():
        user = ctx.guild.get_member(trainer)
        if (trainer_dict[trainer]['status']['lobby']) and user and team == False:
            ctx_lobbycount += trainer_dict[trainer]['status']['lobby']
            if trainer_dict[trainer]['status']['lobby'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                lobby_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['status']['lobby']))
                lobby_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['status']['lobby']))
        elif (trainer_dict[trainer]['status']['lobby']) and user and team and trainer_dict[trainer]['party'][team]:
            if trainer_dict[trainer]['status']['lobby'] == 1:
                name_list.append('**{name}**'.format(name=user.display_name))
                lobby_list.append(user.mention)
            else:
                name_list.append('**{name} ({count})**'.format(name=user.display_name, count=trainer_dict[trainer]['party'][team]))
                lobby_list.append('{name} **({count})**'.format(name=user.mention, count=trainer_dict[trainer]['party'][team]))
            if raid_dict.get('lobby',{"team":"all"})['team'] == team or raid_dict.get('lobby',{"team":"all"})['team'] == "all":
                ctx_lobbycount += trainer_dict[trainer]['party'][team]

    if ctx_lobbycount > 0:
        if (now.time() >= datetime.time(5, 0)) and (now.time() <= datetime.time(21, 0)) and (tag == True):
            lobby_exstr = ' including {trainer_list} and the people with them! Use **!lobby** if you are joining them or **!backout** to request a backout'.format(trainer_list=', '.join(lobby_list))
        else:
            lobby_exstr = ' including {trainer_list} and the people with them! Use **!lobby** if you are joining them or **!backout** to request a backout'.format(trainer_list=', '.join(name_list))
    listmsg = ' {trainer_count} in the lobby{including_string}!'.format(trainer_count=str(ctx_lobbycount), including_string=lobby_exstr)
    return listmsg


async def _bosslist(ctx, Kyogre, guild_dict, raid_info):
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
        p = Pokemon.get_pokemon(Kyogre, entry)
        name = str(p).lower()
        boss_list.append(name)
        boss_dict[name] = {"type": utils.types_to_str(message.guild, p.types, Kyogre.config), "total": 0, "maybe": 0, "coming": 0, "here": 0}
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
            bossliststr += '{type}{name}: **{total} total,** {interested} interested, {coming} coming, {here} waiting{type}\n'.format(type=boss_dict[boss]['type'],name=boss.capitalize(), total=boss_dict[boss]['total'], interested=boss_dict[boss]['maybe'], coming=boss_dict[boss]['coming'], here=boss_dict[boss]['here'])
    if bossliststr:
        listmsg = ' Boss numbers for the raid:\n{}'.format(bossliststr)
    else:
        listmsg = ' Nobody has told me what boss they want!'
    return listmsg


async def teamlist(ctx, Kyogre, guild_dict):
    message = ctx.message
    team_dict = {}
    team_dict["mystic"] = {"total":0,"maybe":0,"coming":0,"here":0}
    team_dict["valor"] = {"total":0,"maybe":0,"coming":0,"here":0}
    team_dict["instinct"] = {"total":0,"maybe":0,"coming":0,"here":0}
    team_dict["unknown"] = {"total":0,"maybe":0,"coming":0,"here":0}
    status_list = ["here","coming","maybe"]
    team_list = ["mystic","valor","instinct","unknown"]
    teamliststr = ''
    trainer_dict = copy.deepcopy(guild_dict[message.guild.id]['raidchannel_dict'][message.channel.id]['trainer_dict'])
    for trainer in trainer_dict.keys():
        if not ctx.guild.get_member(trainer):
            continue
        for team in team_list:
            team_dict[team]["total"] += int(trainer_dict[trainer]['party'][team])
            for status in status_list:
                if max(trainer_dict[trainer]['status'], key=lambda key: trainer_dict[trainer]['status'][key]) == status:
                    team_dict[team][status] += int(trainer_dict[trainer]['party'][team])
    for team in team_list[:-1]:
        if team_dict[team]['total'] > 0:
            teamliststr += '{emoji} **{total} total,** {interested} interested, {coming} coming, {here} waiting {emoji}\n'.format(emoji=utils.parse_emoji(ctx.guild, Kyogre.config['team_dict'][team]), total=team_dict[team]['total'], interested=team_dict[team]['maybe'], coming=team_dict[team]['coming'], here=team_dict[team]['here'])
    if team_dict["unknown"]['total'] > 0:
        teamliststr += '❔ '
        teamliststr += '**{grey_number} total,** {greymaybe} interested, {greycoming} coming, {greyhere} waiting'
        teamliststr += ' ❔'
        teamliststr = teamliststr.format(grey_number=team_dict['unknown']['total'], greymaybe=team_dict['unknown']['maybe'], greycoming=team_dict['unknown']['coming'], greyhere=team_dict['unknown']['here'])
    if teamliststr:
        listmsg = ' Team numbers for the raid:\n{}'.format(teamliststr)
    else:
        listmsg = ' Nobody has updated their status!'
    return listmsg


async def get_region_reporting_channels(guild, region, guild_dict):
    report_channels = []
    for c in guild_dict[guild.id]['configure_dict']['raid']['report_channels']:
        if guild_dict[guild.id]['configure_dict']['raid']['report_channels'][c] == region:
            report_channels.append(c)
    return report_channels


async def update_listing_channels(Kyogre, guild_dict, guild, type, edit=False, regions=None):
    valid_types = ['raid', 'research', 'wild', 'nest', 'lure']
    if type not in valid_types:
        return
    # if type == 'lure':
    #     expiremax = datetime.datetime.utcnow() + datetime.timedelta(
    #         hours=guild_dict[guild.id]['configure_dict']['settings']['offset'],
    #         minutes=30)
    #     lures = (LureTable
    #     #created, location_name, lure_type, latitude, longitude
    #              .select(TrainerReportRelation.created,
    #                      LocationTable.name.alias("location_name"),
    #                      LureTypeTable.name.alias("lure_type"),
    #                      LocationTable.latitude,
    #                      LocationTable.longitude)
    #              .join(TrainerReportRelation)
    #              .join(TrainerTable, on=(TrainerReportRelation.trainer == TrainerTable.snowflake))
    #              .join(LureTypeRelation, on=(LureTypeRelation.lure_id == LureTable.id))
    #              .join(LureTypeTable, on=(LureTypeRelation.type_id == LureTypeTable.id))
    #              .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
    #              .where((TrainerTable.guild == guild.id) &
    #                     (TrainerReportRelation.created + 30 < expiremax)))
    #     lures = lures.objects(LureInstance)
    #     print([o for o in lures])

    # else:
    listing_dict = guild_dict[guild.id]['configure_dict'].get(type, {}).get('listings', None)
    if not listing_dict or not listing_dict['enabled']:
        return
    if 'channel' in listing_dict:
        channel = Kyogre.get_channel(listing_dict['channel']['id'])
        return await _update_listing_channel(Kyogre, guild_dict, channel, type, edit)
    if 'channels' in listing_dict:
        if not regions:
            regions = [r for r in listing_dict['channels']]
        for region in regions:
            channel_list = listing_dict['channels'].get(region, [])
            if not isinstance(channel_list, list):
                channel_list = [channel_list]
            for channel_info in channel_list:
                channel = Kyogre.get_channel(channel_info['id'])
                await _update_listing_channel(Kyogre, guild_dict, channel, type, edit, region=region)


async def _update_listing_channel(Kyogre, guild_dict, channel, type, edit, region=None):
    lock = asyncio.Lock()
    async with lock:
        listing_dict = guild_dict[channel.guild.id]['configure_dict'].get(type, {}).get('listings', None)
        if not listing_dict or not listing_dict['enabled']:
            return
        new_messages = await _get_listing_messages(Kyogre, guild_dict, type, channel, region)
        previous_messages = await _get_previous_listing_messages(Kyogre, guild_dict, type, channel, region)
        matches = itertools.zip_longest(new_messages, previous_messages)
        new_ids = []

        def should_delete(m):
            check = True
            if m.embeds is not None:
                check = (type in m.embeds[0].description.lower())
            return m.author == Kyogre.user and check
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
        guild_dict[channel.guild.id]['configure_dict'][type]['listings'] = listing_dict


async def _get_previous_listing_messages(Kyogre, guild_dict, type, channel, region=None):
    listing_dict = guild_dict[channel.guild.id]['configure_dict'].get(type, {}).get('listings', None)
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
            search_text = f"active {type}"
            for message in message_history:
                if search_text in message.embeds[0].description.lower():
                    previous_messages.append(message.id)
                    break
    return previous_messages
