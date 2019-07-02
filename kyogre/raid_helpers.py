
def raid_channels_enabled(guild, channel, guild_dict):
    enabled = True
    regions = get_channel_regions(channel, 'raid', guild_dict)
    # TODO: modify this to accomodate multiple regions once necessary
    if regions and len(regions) > 0:
        enabled_dict = guild_dict[guild.id]['configure_dict']['raid'].setdefault('raid_channels', {})
        enabled = enabled_dict.setdefault(regions[0], True)
    return enabled


def get_channel_regions(channel, type, guild_dict):
    regions = None
    config_dict = guild_dict[channel.guild.id]['configure_dict']
    if config_dict.get(type, {}).get('enabled', None):
        regions = config_dict.get(type, {}).get('report_channels', {}).get(channel.id, None)
        if regions and not isinstance(regions, list):
            regions = [regions]
    if type == "raid":
        cat_dict = config_dict.get(type, {}).get('category_dict', {})
        for r in cat_dict:
            if cat_dict[r] == channel.category.id:
                regions = [config_dict.get(type, {}).get('report_channels', {}).get(r, None)]
    if regions is None:
        return []
    if len(regions) < 1:
        return []
    else:
        return list(set(regions))
