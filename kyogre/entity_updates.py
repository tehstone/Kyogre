import copy
import datetime

from kyogre import embed_utils, utils


async def update_raid_location(Kyogre, ctx, guild_dict, message, report_channel, raid_channel, gym):
    guild = message.guild
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
    oldraidmsg = await raid_channel.fetch_message(raid_dict['raidmessage'])
    oldreportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
    report_embed, raid_embed = await embed_utils.build_raid_embeds(Kyogre, ctx, raid_dict, True)
    regions = [gym.region]
    otw_list = []
    trainer_dict = copy.deepcopy(raid_dict['trainer_dict'])
    for trainer in trainer_dict.keys():
        if trainer_dict[trainer]['status']['coming']:
            user = guild.get_member(trainer)
            otw_list.append(user.mention)
    await raid_channel.send(content=f"Someone has suggested a different location for the raid! "
                                    f"Trainers {', '.join(otw_list)}: make sure you are headed to the right place!")
    channel_name = raid_channel.name
    channel_prefix = channel_name.split("_")[0]
    new_channel_name = utils.sanitize_name(channel_prefix + "_" + gym.name)[:32]
    await raid_channel.edit(name=new_channel_name)
    try:
        content = build_raid_report_message(Kyogre, raid_channel, raid_dict)
        message_content = get_raidtext(raid_channel)
        await oldreportmsg.edit(new_content=content, embed=report_embed, content=content)
        if raid_dict['raidcityreport'] is not None:
            report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
            report_city_msg = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
            await report_city_msg.edit(new_content=message_content, embed=report_embed, content=message_content)
    except:
        Kyogre.logger.info(f"Failed to update report channel embed for raid at {gym.name}")
    raid_dict['raidmessage'] = oldraidmsg.id
    raid_dict['raidreport'] = oldreportmsg.id
    raid_dict['gym'] = gym.id
    raid_dict['address'] = gym.name
    raid_dict['regions'] = regions
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict

    list_cog = Kyogre.cogs.get('ListManagement')
    await list_cog.update_listing_channels(guild, "raid", edit=True)
    return


def get_raidtext(report_channel):
    return (f"Click {report_channel.mention} to return to this region's reporting channel. \n"
            "For help, react to this message with the question mark to receive a DM with a "
            "list of commands you can use in this channel!")


def build_raid_report_message(Kyogre, raid_channel, raid_dict):
    guild = raid_channel.guild
    gym_id = raid_dict['gym']
    location_matching_cog = Kyogre.cogs.get('LocationMatching')
    gym = location_matching_cog.get_gym_by_id(guild.id, gym_id)
    c_type = raid_dict['type']
    pokemon = raid_dict['pokemon'].capitalize()
    level = raid_dict['egglevel']
    raidexp = False
    raid_hatch = raid_dict['hatch_time']
    raid_expire = raid_dict['expire_time']
    utils_cog = Kyogre.cogs.get('Utilities')
    enabled = utils_cog.raid_channels_enabled(guild, raid_channel)
    ex = " (EX)" if gym.ex_eligible else ""
    end_str, msg = '', ''
    if c_type == "raid":
        msg = f'{pokemon} @ {gym.name}{ex}'
        end_str = "Expires: "
        if raid_expire:
            raidexp = raid_expire
    elif c_type == "egg":
        msg = f'T{level} egg @ {gym.name}{ex}'
        end_str = "Hatches: "
        if raid_hatch:
            raidexp = raid_hatch
    if raidexp is not False:
        end = datetime.datetime.utcfromtimestamp(raidexp) + \
              datetime.timedelta(hours=Kyogre.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        msg += f" {end_str}{end.strftime('%I:%M %p')}."
    if enabled:
        msg += f"\nCoordinate in the raid channel: {raid_channel.mention}"
    return msg
