import copy
import datetime
import time

from operator import itemgetter

import discord

from kyogre.exts.pokemon import Pokemon
from kyogre.exts.db.kyogredb import *
from kyogre import constants, raid_helpers, utils

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
        ctx_herecount = 0
        ctx_comingcount = 0
        ctx_maybecount = 0
        ctx_lobbycount = 0
        for trainer in rc_d[r]['trainer_dict'].keys():
            if not guild.get_member(trainer):
                continue
            if trainer_dict[trainer]['status']['here']:
                ctx_herecount += trainer_dict[trainer]['count']
            elif trainer_dict[trainer]['status']['coming']:
                ctx_comingcount += trainer_dict[trainer]['count']
            elif trainer_dict[trainer]['status']['maybe']:
                ctx_maybecount += trainer_dict[trainer]['count']
            elif trainer_dict[trainer]['status']['lobby']:
                ctx_lobbycount += trainer_dict[trainer]['count']
        if rc_d[r]['manual_timer'] == False:
            assumed_str = ' (assumed)'
        else:
            assumed_str = ''
        starttime = rc_d[r].get('starttime',None)
        meetup = rc_d[r].get('meetup',{})
        if starttime and starttime > now and not meetup:
            start_str = ' **Next Group**: {}'.format(starttime.strftime('%I:%M%p'))
        else:
            starttime = False
        egglevel = rc_d[r]['egglevel']
        if egglevel.isdigit() and (int(egglevel) > 0):
            t_emoji = str(egglevel) + '\u20e3'
            expirytext = ' - Hatches: {expiry}{is_assumed}'.format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
        elif ((rc_d[r]['egglevel'] == 'EX') or (rc_d[r]['type'] == 'exraid')) and not meetup:
            expirytext = ' - Hatches: {expiry}{is_assumed}'.format(expiry=end.strftime('%B %d at %I:%M%p'), is_assumed=assumed_str)
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
            expirytext = ' - **Expires**: {expiry}{is_assumed}'.format(expiry=end.strftime('%I:%M%p'), is_assumed=assumed_str)
        boss = Pokemon.get_pokemon(Kyogre, rc_d[r].get('pokemon', ''))
        if not t_emoji and boss:
            t_emoji = str(boss.raid_level) + '\u20e3'
        gym = rc_d[r].get('gym', None)
        if gym:
            ex_eligibility = ' *EX-Eligible*' if gym.ex_eligible else ''
        enabled = raid_helpers.raid_channels_enabled(guild, rchan, guild_dict)
        if enabled:
            output += '\t{tier} {raidchannel}{ex_eligibility}{expiry_text} ({total_count} players){starttime}\n'.format(tier=t_emoji, raidchannel=rchan.mention, ex_eligibility=ex_eligibility, expiry_text=expirytext, total_count=sum([ctx_maybecount, ctx_comingcount, ctx_herecount, ctx_lobbycount]), starttime=start_str)
        else:
            channel_name = rchan.name.replace('_',': ').replace('-', ' ').title()
            map_url = ''
            map_url = rc_d[r]['gym'].maps_url
            try:
                map_url = rc_d[r]['gym'].maps_url
            except:
                pass
            output += '\t{tier} **{raidchannel}**{ex_eligibility}{expiry_text} \n[Click for directions]({map_url})\n'.format(tier=t_emoji, raidchannel=channel_name, ex_eligibility=ex_eligibility, expiry_text=expirytext, total_count=sum([ctx_maybecount, ctx_comingcount, ctx_herecount, ctx_lobbycount]), starttime=start_str,map_url=map_url)
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
        if not region or region in raid_helpers._get_channel_regions(report_channel, 'wild', guild_dict):
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
        if not region or region in raid_helpers._get_channel_regions(report_channel, 'research', guild_dict):
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
                    listmsg = newmsg
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

async def _teamlist(ctx, Kyogre, guild_dict):
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
            teamliststr += '{emoji} **{total} total,** {interested} interested, {coming} coming, {here} waiting {emoji}\n'.format(emoji=utils.parse_emoji(ctx.guild, config['team_dict'][team]), total=team_dict[team]['total'], interested=team_dict[team]['maybe'], coming=team_dict[team]['coming'], here=team_dict[team]['here'])
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
