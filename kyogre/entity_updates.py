import copy
import datetime

import discord

from kyogre import embed_utils, utils
from kyogre.exts.pokemon import Pokemon


async def update_raid_location(Kyogre, guild_dict, message, report_channel, raid_channel, gym):
    guild = message.guild
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
    oldraidmsg = await raid_channel.fetch_message(raid_dict['raidmessage'])
    oldreportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
    oldembed = oldraidmsg.embeds[0]
    newloc = gym.maps_url
    regions = [gym.region]
    new_embed = discord.Embed(title=oldembed.title, url=newloc, colour=guild.me.colour)
    for field in oldembed.fields:
        t = 'team'
        s = 'status'
        if (t not in field.name.lower()) and (s not in field.name.lower()):
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    weather = raid_dict.get('weather', None)
    utils_cog = Kyogre.cogs.get('Utilities')
    enabled = utils_cog.raid_channels_enabled(guild, raid_channel)
    embed_indices = await embed_utils.get_embed_field_indices(new_embed)
    gym_embed = new_embed.fields[embed_indices['gym']]
    gym_info = "**Name:** {0}\n**Notes:** {1}".format(gym.name, "_EX Eligible Gym_" if gym.ex_eligible else "N/A")
    if weather is not None:
        gym_info += "\n**Weather**: " + weather
    new_embed.set_field_at(embed_indices['gym'], name=gym_embed.name, value=gym_info, inline=True)
    new_embed.set_thumbnail(url=oldembed.thumbnail.url)
    if enabled:
        new_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
    otw_list = []
    trainer_dict = copy.deepcopy(raid_dict['trainer_dict'])
    for trainer in trainer_dict.keys():
        if trainer_dict[trainer]['status']['coming']:
            user = guild.get_member(trainer)
            otw_list.append(user.mention)
    await raid_channel.send(content='Someone has suggested a different location for the raid! Trainers {trainer_list}: make sure you are headed to the right place!'.format(trainer_list=', '.join(otw_list)))
    channel_name = raid_channel.name
    channel_prefix = channel_name.split("_")[0]
    new_channel_name = utils.sanitize_name(channel_prefix + "_" + gym.name)[:32]
    await raid_channel.edit(name=new_channel_name)
    try:
        message_content = get_raidtext(Kyogre, guild, raid_dict, raid_channel, False)
        await oldraidmsg.edit(new_content=message_content, embed=new_embed, content=message_content)
    except:
        pass
    try:
        content = build_raid_report_message(Kyogre, raid_channel, raid_dict)
        embed_indices = await embed_utils.get_embed_field_indices(new_embed)
        new_embed = await embed_utils.filter_fields_for_report_embed(new_embed, embed_indices, enabled)
        message_content = get_raidtext(Kyogre, guild, raid_dict, raid_channel, True)
        await oldreportmsg.edit(new_content=content, embed=new_embed, content=content)
        if raid_dict['raidcityreport'] is not None:
            report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
            report_city_msg = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
            await report_city_msg.edit(new_content=message_content, embed=new_embed, content=message_content)

    except:
        pass
    raid_dict['raidmessage'] = oldraidmsg.id
    raid_dict['raidreport'] = oldreportmsg.id
    raid_dict['gym'] = gym.id
    raid_dict['address'] = gym.name
    raid_dict['regions'] = regions
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict

    list_cog = Kyogre.cogs.get('ListManagement')
    await list_cog.update_listing_channels(guild, "raid", edit=True)
    return

def get_raidtext(Kyogre, guild, raid_dict, raid_channel, report):
    if 'type' in raid_dict:
        type = raid_dict['type']
    if 'pokemon' in raid_dict:
        pkmn = raid_dict['pokemon']
    if 'egglevel' in raid_dict:
        level = raid_dict['egglevel']
    if 'reporter' in raid_dict:
        member = raid_dict['reporter']
    member = guild.get_member(member)
    pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    if report:
        raidtext = build_raid_report_message(Kyogre, raid_channel, raid_dict)
    else:
        if type == "raid":
            raidtext = "{pkmn} raid reported by {member} in {channel}! Coordinate here!\n\nFor help, react to this message with the question mark and I will DM you a list of commands you can use!".format(pkmn=pkmn.name(), member=member.display_name, channel=raid_channel.mention)
        elif type == "egg":
            raidtext = "Level {level} raid egg reported by {member} in {channel}! Coordinate here!\n\nFor help, react to this message with the question mark and I will DM you a list of commands you can use!".format(level=level, member=member.display_name, channel=raid_channel.mention)
        elif type == "exraid":
            raidtext = "EX raid reported by {member} in {channel}! Coordinate here!\n\nFor help, react to this message with the question mark and I will DM you a list of commands you can use!".format(member=member.display_name, channel=raid_channel.mention)
    return raidtext

def build_raid_report_message(Kyogre, raid_channel, raid_dict):
    guild = raid_channel.guild
    gym_id = raid_dict['gym']
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    gym = location_matching_cog.get_gym_by_id(guild.id, gym_id)
    c_type = raid_dict['type']
    pokemon = raid_dict['pokemon']
    level = raid_dict['egglevel']
    raidexp = raid_dict['exp']
    utils_cog = Kyogre.cogs.get('Utilities')
    enabled = utils_cog.raid_channels_enabled(guild, raid_channel)
    if c_type == "raid":
        msg = '{boss} @ {location}{ex}'.format(ex=" (EX)" if gym.ex_eligible else "", boss=pokemon, location=gym.name)
        end_str = "Expires: "
    elif c_type == "egg":
        msg = 'T{level} egg @ {location}{ex}'.format(ex=" (EX)" if gym.ex_eligible else "", level=level, location=gym.name)
        end_str = "Hatches: "
    if raidexp is not False:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=Kyogre.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        end = now + datetime.timedelta(minutes=raidexp)
        msg += ' {type}{end}.'.format(end=end.strftime('%I:%M %p'), type=end_str)
    if enabled:
        msg += "\nCoordinate in the raid channel: {channel}".format(channel=raid_channel.mention)
    return msg
