import copy
import re

import discord
from meowth import checks, utils, constants

async def _configure_team(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Team assignment allows users to assign their Pokemon Go team role using the **!team** command. If you have a bot that handles this already, you may want to disable this feature.\n\nIf you are to use this feature, ensure existing team roles are as follows: mystic, valor, instinct. These must be all lowercase letters. If they don't exist yet, I'll make some for you instead.\n\nRespond here with: **N** to disable, **Y** to enable:")).set_author(name=_('Team Assignments'), icon_url=Kyogre.user.avatar_url))
    while True:
        teamreply = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if teamreply.content.lower() == 'y':
            config_dict_temp['team']['enabled'] = True
            guild_roles = []
            for role in guild.roles:
                if role.name.lower() in config['team_dict'] and role.name not in guild_roles:
                    guild_roles.append(role.name)
            lowercase_roles = [element.lower() for element in guild_roles]
            for team in config['team_dict'].keys():
                temp_role = discord.utils.get(guild.roles, name=team)
                if temp_role == None:
                    try:
                        await guild.create_role(name=team, hoist=False, mentionable=True)
                    except discord.errors.HTTPException:
                        pass
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Team Assignments enabled!')))
            break
        elif teamreply.content.lower() == 'n':
            config_dict_temp['team']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Team Assignments disabled!')))
            break
        elif teamreply.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I'm sorry I don't understand. Please reply with either **N** to disable, or **Y** to enable.")))
            continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_welcome(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    welcomeconfig = _('I can welcome new members to the server with a short message. Here is an example, but it is customizable:\n\n')
    if config_dict_temp['team']['enabled']:
        welcomeconfig += _("Welcome to {server_name}, {owner_name.mention}! Set your team by typing '**!team mystic**' or '**!team valor**' or '**!team instinct**' without quotations. If you have any questions just ask an admin.").format(server_name=guild.name, owner_name=owner)
    else:
        welcomeconfig += _('Welcome to {server_name}, {owner_name.mention}! If you have any questions just ask an admin.').format(server_name=guild, owner_name=owner)
    welcomeconfig += _('\n\nThis welcome message can be in a specific channel or a direct message. If you have a bot that handles this already, you may want to disable this feature.\n\nRespond with: **N** to disable, **Y** to enable:')
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=welcomeconfig).set_author(name=_('Welcome Message'), icon_url=Kyogre.user.avatar_url))
    while True:
        welcomereply = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if welcomereply.content.lower() == 'y':
            config_dict_temp['welcome']['enabled'] = True
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Welcome Message enabled!')))
            await owner.send(embed=discord.Embed(
                colour=discord.Colour.lighter_grey(),
                description=(_("Would you like a custom welcome message? "
                             "You can reply with **N** to use the default message above or enter your own below.\n\n"
                             "I can read all [discord formatting](https://support.discordapp.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline-) "
                             "and I have the following template tags:\n\n"
                             "**{@member}** - Replace member with user name or ID\n"
                             "**{#channel}** - Replace channel with channel name or ID\n"
                             "**{&role}** - Replace role name or ID (shows as @deleted-role DM preview)\n"
                             "**{user}** - Will mention the new user\n"
                             "**{server}** - Will print your server's name\n"
                             "Surround your message with [] to send it as an embed. **Warning:** Mentions within embeds may be broken on mobile, this is a Discord bug."))).set_author(name=_("Welcome Message"), icon_url=Kyogre.user.avatar_url))
            if config_dict_temp['welcome']['welcomemsg'] != 'default':
                await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=config_dict_temp['welcome']['welcomemsg']).set_author(name=_("Current Welcome Message"), icon_url=Kyogre.user.avatar_url))
            while True:
                welcomemsgreply = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and (message.author == owner)))
                if welcomemsgreply.content.lower() == 'n':
                    config_dict_temp['welcome']['welcomemsg'] = 'default'
                    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_("Default welcome message set")))
                    break
                elif welcomemsgreply.content.lower() == "cancel":
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_("**CONFIG CANCELLED!**\n\nNo changes have been made.")))
                    return None
                elif len(welcomemsgreply.content) > 500:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("Please shorten your message to less than 500 characters. You entered {count}.").format(count=len(welcomemsgreply.content))))
                    continue
                else:
                    welcomemessage, errors = utils.do_template(welcomemsgreply.content, owner, guild)
                    if errors:
                        if welcomemessage.startswith("[") and welcomemessage.endswith("]"):
                            embed = discord.Embed(colour=guild.me.colour, description=welcomemessage[1:-1].format(user=owner.mention))
                            embed.add_field(name=_('Warning'), value=_('The following could not be found:\n{}').format('\n'.join(errors)))
                            await owner.send(embed=embed)
                        else:
                            await owner.send(_("{msg}\n\n**Warning:**\nThe following could not be found: {errors}").format(msg=welcomemessage, errors=', '.join(errors)))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("Please check the data given and retry a new welcome message, or reply with **N** to use the default.")))
                        continue
                    else:
                        if welcomemessage.startswith("[") and welcomemessage.endswith("]"):
                            embed = discord.Embed(colour=guild.me.colour, description=welcomemessage[1:-1].format(user=owner.mention))
                            question = await owner.send(content=_("Here's what you sent. Does it look ok?"),embed=embed)
                            try:
                                timeout = False
                                res, reactuser = await utils.ask(Kyogre, question, owner.id)
                            except TypeError:
                                timeout = True
                        else:
                            question = await owner.send(content=_("Here's what you sent. Does it look ok?\n\n{welcome}").format(welcome=welcomemessage.format(user=owner.mention)))
                            try:
                                timeout = False
                                res, reactuser = await utils.ask(Kyogre, question, owner.id)
                            except TypeError:
                                timeout = True
                    if timeout or res.emoji == '❎':
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("Please enter a new welcome message, or reply with **N** to use the default.")))
                        continue
                    else:
                        config_dict_temp['welcome']['welcomemsg'] = welcomemessage
                        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_("Welcome Message set to:\n\n{}").format(config_dict_temp['welcome']['welcomemsg'])))
                        break
                break
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Which channel in your server would you like me to post the Welcome Messages? You can also choose to have them sent to the new member via Direct Message (DM) instead.\n\nRespond with: **channel-name** or ID of a channel in your server or **DM** to Direct Message:")).set_author(name=_("Welcome Message Channel"), icon_url=Kyogre.user.avatar_url))
            while True:
                welcomechannelreply = await Kyogre.wait_for('message',check=lambda message: message.guild == None and message.author == owner)
                if welcomechannelreply.content.lower() == "dm":
                    config_dict_temp['welcome']['welcomechan'] = "dm"
                    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_("Welcome DM set")))
                    break
                elif " " in welcomechannelreply.content.lower():
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("Channel names can't contain spaces, sorry. Please double check the name and send your response again.")))
                    continue
                elif welcomechannelreply.content.lower() == "cancel":
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                else:
                    item = welcomechannelreply.content
                    channel = None
                    if item.isdigit():
                        channel = discord.utils.get(guild.text_channels, id=int(item))
                    if not channel:
                        item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                        item = item.replace(" ","-")
                        name = await utils.letter_case(guild.text_channels, item.lower())
                        channel = discord.utils.get(guild.text_channels, name=name)
                    if channel:
                        guild_channel_list = []
                        for textchannel in guild.text_channels:
                            guild_channel_list.append(textchannel.id)
                        diff = set([channel.id]) - set(guild_channel_list)
                    else:
                        diff = True
                    if (not diff):
                        config_dict_temp['welcome']['welcomechan'] = channel.id
                        ow = channel.overwrites_for(Kyogre.user)
                        ow.send_messages = True
                        ow.read_messages = True
                        ow.manage_roles = True
                        try:
                            await channel.set_permissions(Kyogre.user, overwrite = ow)
                        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Welcome Channel set to {channel}').format(channel=welcomechannelreply.content.lower())))
                        break
                    else:
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel you provided isn't in your server. Please double check your channel and resend your response.")))
                        continue
                break
            break
        elif welcomereply.content.lower() == 'n':
            config_dict_temp['welcome']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Welcome Message disabled!')))
            break
        elif welcomereply.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I'm sorry I don't understand. Please reply with either **N** to disable, or **Y** to enable.")))
            continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_regions(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    config_dict_temp.setdefault('regions', {})
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("I can keep track of multiple regions within your community. This can be useful for communities that span multiple cities or areas where users tend to only be interested in certain subsets of raids, research, etc. To start, I'll need the names of the regions you'd like to set up: `region-name, region-name, region-name`\n\nExample: `north-saffron, south-saffron, celadon`\n\nTo facilitate communication, I will be creating roles for each region name provided, so make sure the names are meaningful!\n\nIf you do not require regions, you may want to disable this functionality.\n\nRespond with: **N** to disable, or the **region-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Region Names'), icon_url=Kyogre.user.avatar_url))
    region_dict = {}
    while True:
        region_names = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        response = region_names.content.strip().lower()
        if response == 'n':
            config_dict_temp['regions']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Regions disabled')))
            break
        elif response == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['regions']['enabled'] = True
            region_names_list = re.split(r'\s*,\s*', response)
        break
    if config_dict_temp['regions']['enabled']:
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('Occasionally I will generate Google Maps links to give people directions to locations! To do this, I need to know what city/town/area each region represents to ensure I get the right location in the map. For each region name you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `saffron city kanto, saffron city kanto, celadon city kanto`\n\nEach location will have to be in the same order as you provided the names in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous region name list below.')).set_author(name=_('Region Locations'), icon_url=Kyogre.user.avatar_url))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_name_list}').format(region_name_list=response[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
        while True:
            locations = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            response = locations.content.strip().lower()
            if response == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            region_locations_list = re.split(r'\s*,\s*', response)
            if len(region_locations_list) == len(region_names_list):
                for i in range(len(region_names_list)):
                    region_dict[region_names_list[i]] = {'location': region_locations_list[i], 'role': utils.sanitize_name(region_names_list[i]), 'raidrole': utils.sanitize_name(region_names_list[i] + "-raids")}
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of locations doesn't match the number of regions you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{region_names_list}\n{region_locations_list}\n\nPlease double check that your locations match up with your provided region names and resend your response.").format(region_names_list=', '.join(region_names_list), region_locations_list=', '.join(region_locations_list))))
                continue
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Region locations are set')))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('Next, I need to know what channels should be flagged to allow users to modify their region assignments. Please enter the channels to be used for this as a comma-separated list. \n\nExample: `general, region-assignment`\n\nNote that this answer does *not* directly correspond to the previously entered channels/regions.\n\n')).set_author(name=_('Region Command Channels'), icon_url=Kyogre.user.avatar_url))
        while True:
            locations = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            response = locations.content.strip().lower()
            if response == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            channel_list = [c.strip() for c in response.split(',')]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            channel_objs = []
            channel_names = []
            channel_errors = []
            for item in channel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    channel_objs.append(channel)
                    channel_names.append(channel.name)
                else:
                    channel_errors.append(item)
            channel_list = [x.id for x in channel_objs]
            diff = set(channel_list) - set(guild_channel_list)
            if (not diff) and (not channel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Region Command Channels enabled')))
                for channel in channel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite=ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                config_dict_temp['regions']['command_channels'] = channel_list
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(channel_errors))))
                continue
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description='Region command channels are set'))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description='Lastly, I need to know what channel to send region join notification messages in').set_author(name='Region Notify Channel', icon_url=Kyogre.user.avatar_url))
        while True:
            locations = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            response = locations.content.strip().lower()
            if response == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description='**CONFIG CANCELLED!**\n\nNo changes have been made.'))
                return None
            channel_list = [c.strip() for c in response.split(',')]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            channel_objs = []
            channel_names = []
            channel_errors = []
            item = channel_list[0]
            channel = None
            if item.isdigit():
                channel = discord.utils.get(guild.text_channels, id=int(item))
            if not channel:
                item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                item = item.replace(" ","-")
                name = await utils.letter_case(guild.text_channels, item.lower())
                channel = discord.utils.get(guild.text_channels, name=name)
            if channel:
                channel_objs.append(channel)
                channel_names.append(channel.name)
            else:
                channel_errors.append(item)
            channel_list = [x.id for x in channel_objs]
            diff = set(channel_list) - set(guild_channel_list)
            if (not diff) and (not channel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description='Region Notify Channel enabled'))
                for channel in channel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite=ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description='I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.'.format(prefix=ctx.prefix, channel=channel.mention)))
                config_dict_temp['regions']['notify_channel'] = channel_list[0]
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description="The channel you provided was not found in your channel list.\n\nPlease double check your channel name or id and resend your reponse.".format(invalid_channels=', '.join(channel_errors))))
                continue
    # set up roles
    new_region_roles = set([r['role'] for r in region_dict.values()])
    new_region_raid_roles = set([r['raidrole'] for r in region_dict.values()])
    existing_region_dict = config_dict_temp['regions'].get('info', None)
    if existing_region_dict:
        existing_region_roles = set([r['role'] for r in existing_region_dict.values()])
        obsolete_roles = existing_region_roles - new_region_roles
        new_region_roles = new_region_roles - existing_region_roles
        # remove obsolete roles
        for role in obsolete_roles:
            temp_role = discord.utils.get(guild.roles, name=role)
            if temp_role:
                try:
                    await temp_role.delete(reason="Removed from region configuration")
                except discord.errors.HTTPException:
                    pass
        existing_region_roles = set([r.setdefault('raidrole', '') for r in existing_region_dict.values()])
        obsolete_roles = existing_region_roles - new_region_raid_roles
        new_region_raid_roles = new_region_raid_roles - existing_region_roles
        # remove obsolete roles
        for role in obsolete_roles:
            temp_role = discord.utils.get(guild.roles, name=role)
            if temp_role:
                try:
                    await temp_role.delete(reason="Removed from region configuration")
                except discord.errors.HTTPException:
                    pass
    for role in new_region_roles:
        temp_role = discord.utils.get(guild.roles, name=role)
        if not temp_role:
            try:
                await guild.create_role(name=role, hoist=False, mentionable=True)
            except discord.errors.HTTPException:
                pass
    for role in new_region_raid_roles:
        temp_role = discord.utils.get(guild.roles, name=role)
        if not temp_role:
            try:
                await guild.create_role(name=role, hoist=False, mentionable=True)
            except discord.errors.HTTPException:
                pass
    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Region roles updated')))
    config_dict_temp['regions']['info'] = region_dict
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_raid(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Raid Reporting allows users to report active raids with **!raid** or raid eggs with **!raidegg**. Pokemon raid reports are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-raids, hull-raids, sydney-raids`\n\nIf you do not require raid or raid egg reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Raid Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['raid']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Raid Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['raid']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Raid Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['raid']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to the raid or egg! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('Raid Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=(', '.join(region_names)).lower()[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to the raid or egg! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('Raid Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['raid']['report_channels'] = citychannel_dict
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Raid Reporting Locations are set')))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("How would you like me to categorize the raid channels I create? Your options are:\n\n**none** - If you don't want them categorized\n**same** - If you want them in the same category as the reporting channel\n**region** - If you want them categorized by region\n**level** - If you want them categorized by level.")).set_author(name=_('Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
        while True:
            guild = Kyogre.get_guild(guild.id)
            guild_catlist = []
            for cat in guild.categories:
                guild_catlist.append(cat.id)
            category_dict = {}
            categories = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
            if categories.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            elif categories.content.lower() == 'none':
                config_dict_temp['raid']['categories'] = None
                break
            elif categories.content.lower() == 'same':
                config_dict_temp['raid']['categories'] = 'same'
                break
            elif categories.content.lower() == 'region':
                while True:
                    guild = Kyogre.get_guild(guild.id)
                    guild_catlist = []
                    for cat in guild.categories:
                        guild_catlist.append(cat.id)
                    config_dict_temp['raid']['categories'] = 'region'
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(),description=_("In the same order as they appear below, please give the names of the categories you would like raids reported in each channel to appear in. You do not need to use different categories for each channel, but they do need to be pre-existing categories. Separate each category name with a comma. Response can be either category name or ID.\n\nExample: `kansas city, hull, 1231231241561337813`\n\nYou have configured the following channels as raid reporting channels.")).set_author(name=_('Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
                    regioncats = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
                    if regioncats.content.lower() == "cancel":
                        await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                        return None
                    regioncat_list = regioncats.content.split(',')
                    regioncat_list = [x.strip() for x in regioncat_list]
                    regioncat_ids = []
                    regioncat_names = []
                    regioncat_errors = []
                    for item in regioncat_list:
                        category = None
                        if item.isdigit():
                            category = discord.utils.get(guild.categories, id=int(item))
                        if not category:
                            name = await utils.letter_case(guild.categories, item.lower())
                            category = discord.utils.get(guild.categories, name=name)
                        if category:
                            regioncat_ids.append(category.id)
                            regioncat_names.append(category.name)
                        else:
                            regioncat_errors.append(item)
                    regioncat_list = regioncat_ids
                    if len(regioncat_list) == len(citychannel_list):
                        catdiff = set(regioncat_list) - set(guild_catlist)
                        if (not catdiff) and (not regioncat_errors):
                            for i in range(len(citychannel_list)):
                                category_dict[citychannel_list[i]] = regioncat_list[i]
                            break
                        else:
                            msg = _("The category list you provided doesn't match with your server's categories.")
                            if regioncat_errors:
                                msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                            msg += _("\n\nPlease double check your category list and resend your response. If you just made these categories, try again.")
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=msg))
                            continue
                    else:
                        msg = _("The number of categories I found in your server doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n**Matched Channels:** {channellist}\n**Matched Categories:** {catlist}\n\nPlease double check that your categories match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), catlist=', '.join(regioncat_names) if len(regioncat_list)>0 else "None")
                        if regioncat_errors:
                            msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=msg))
                        continue
                    break
            elif categories.content.lower() == 'level':
                config_dict_temp['raid']['categories'] = 'level'
                while True:
                    guild = Kyogre.get_guild(guild.id)
                    guild_catlist = []
                    for cat in guild.categories:
                        guild_catlist.append(cat.id)
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(),description=_("Pokemon Go currently has five levels of raids. Please provide the names of the categories you would like each level of raid to appear in. Use the following order: 1, 2, 3, 4, 5 \n\nYou do not need to use different categories for each level, but they do need to be pre-existing categories. Separate each category name with a comma. Response can be either category name or ID.\n\nExample: `level 1-3, level 1-3, level 1-3, level 4, 1231231241561337813`")).set_author(name=_('Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
                    levelcats = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
                    if levelcats.content.lower() == "cancel":
                        await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                        return None
                    levelcat_list = levelcats.content.split(',')
                    levelcat_list = [x.strip() for x in levelcat_list]
                    levelcat_ids = []
                    levelcat_names = []
                    levelcat_errors = []
                    for item in levelcat_list:
                        category = None
                        if item.isdigit():
                            category = discord.utils.get(guild.categories, id=int(item))
                        if not category:
                            name = await utils.letter_case(guild.categories, item.lower())
                            category = discord.utils.get(guild.categories, name=name)
                        if category:
                            levelcat_ids.append(category.id)
                            levelcat_names.append(category.name)
                        else:
                            levelcat_errors.append(item)
                    levelcat_list = levelcat_ids
                    if len(levelcat_list) == 5:
                        catdiff = set(levelcat_list) - set(guild_catlist)
                        if (not catdiff) and (not levelcat_errors):
                            level_list = ["1",'2','3','4','5']
                            for i in range(5):
                                category_dict[level_list[i]] = levelcat_list[i]
                            break
                        else:
                            msg = _("The category list you provided doesn't match with your server's categories.")
                            if levelcat_errors:
                                msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(levelcat_errors))
                            msg += _("\n\nPlease double check your category list and resend your response. If you just made these categories, try again.")
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=msg))
                            continue
                    else:
                        msg = _("The number of categories I found in your server doesn't match the number of raid levels! Make sure you give me exactly six categories, one for each level of raid. You can use the same category for multiple levels if you want, but I need to see six category names.\n\n**Matched Categories:** {catlist}\n\nPlease double check your categories.").format(catlist=', '.join(levelcat_names) if len(levelcat_list)>0 else "None")
                        if levelcat_errors:
                            msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(levelcat_errors))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=msg))
                        continue
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=_("Sorry, I didn't understand your answer! Try again.")))
                continue
            break
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Raid Categories are set')))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("For each of the regions with raid reporting enabled, please provide the region names\
                for each region you would like to have individual raid channels created. \nIf you would like this enabled for all regions, reply with **all**. \nIf you would like it disabled for\
                all regions reply with **none**.\n\nOtherwise, simply provide the region names like so:\n\
                `Johto, Kanto, Hoenn`")).set_author(name=_('Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
        config_dict_temp['raid']['raid_channels'] = {}
        region_names = [name for name in config_dict_temp['regions']['info'].keys()]
        while True:
            categories = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
            categories = categories.content.lower()
            if categories == "cancel":
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            if categories == "all":
                for region in region_names:
                    config_dict_temp['raid']['raid_channels'][region] = True
                break
            elif categories == "none":
                for region in region_names:
                    config_dict_temp['raid']['raid_channels'][region] = False
                break
            else:
                entered_regions = categories.split(',')
                entered_regions = [r.strip() for r in entered_regions]
                error_set = set(entered_regions) - set(region_names)
                if len(error_set) > 0:
                    msg = ("The following regions you provided are not in your server's region list: **{invalid}**").format(invalid=', '.join(error_set))
                    msg += "\n\nPlease enter the regions that will have raid channels enabled."
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=msg))
                    continue
                for region in entered_regions:
                    if region in region_names:
                        config_dict_temp['raid']['raid_channels'][region] = True
                disabled_region_set = set(region_names) - set(entered_regions)
                for region in disabled_region_set:
                    config_dict_temp['raid']['raid_channels'][region] = False
                break
        config_dict_temp['raid']['category_dict'] = category_dict
        config_dict_temp['raid']['listings'] = await _get_listings(Kyogre, guild, owner, config_dict_temp)
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_exraid(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("EX Raid Reporting allows users to report EX raids with **!exraid**. Pokemon EX raid reports are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-raids, hull-raids, sydney-raids`\n\nIf you do not require EX raid reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('EX Raid Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['exraid']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('EX Raid Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['exraid']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('EX Raid Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['exraid']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to the raid or egg! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('EX Raid Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=region_names[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to EX raids! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('EX Raid Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['exraid']['report_channels'] = citychannel_dict
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('EX Raid Reporting Locations are set')))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("How would you like me to categorize the EX raid channels I create? Your options are:\n\n**none** - If you don't want them categorized\n**same** - If you want them in the same category as the reporting channel\n**other** - If you want them categorized in a provided category name or ID")).set_author(name=_('EX Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
        while True:
            guild = Kyogre.get_guild(guild.id)
            guild_catlist = []
            for cat in guild.categories:
                guild_catlist.append(cat.id)
            category_dict = {}
            categories = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
            if categories.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            elif categories.content.lower() == 'none':
                config_dict_temp['exraid']['categories'] = None
                break
            elif categories.content.lower() == 'same':
                config_dict_temp['exraid']['categories'] = 'same'
                break
            elif categories.content.lower() == 'other':
                while True:
                    guild = Kyogre.get_guild(guild.id)
                    guild_catlist = []
                    for cat in guild.categories:
                        guild_catlist.append(cat.id)
                    config_dict_temp['exraid']['categories'] = 'region'
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(),description=_("In the same order as they appear below, please give the names of the categories you would like raids reported in each channel to appear in. You do not need to use different categories for each channel, but they do need to be pre-existing categories. Separate each category name with a comma. Response can be either category name or ID.\n\nExample: `kansas city, hull, 1231231241561337813`\n\nYou have configured the following channels as EX raid reporting channels.")).set_author(name=_('EX Raid Reporting Categories'), icon_url=Kyogre.user.avatar_url))
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
                    regioncats = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
                    if regioncats.content.lower() == "cancel":
                        await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                        return None
                    regioncat_list = regioncats.content.split(',')
                    regioncat_list = [x.strip() for x in regioncat_list]
                    regioncat_ids = []
                    regioncat_names = []
                    regioncat_errors = []
                    for item in regioncat_list:
                        category = None
                        if item.isdigit():
                            category = discord.utils.get(guild.categories, id=int(item))
                        if not category:
                            name = await utils.letter_case(guild.categories, item.lower())
                            category = discord.utils.get(guild.categories, name=name)
                        if category:
                            regioncat_ids.append(category.id)
                            regioncat_names.append(category.name)
                        else:
                            regioncat_errors.append(item)
                    regioncat_list = regioncat_ids
                    if len(regioncat_list) == len(citychannel_list):
                        catdiff = set(regioncat_list) - set(guild_catlist)
                        if (not catdiff) and (not regioncat_errors):
                            for i in range(len(citychannel_list)):
                                category_dict[citychannel_list[i]] = regioncat_list[i]
                            break
                        else:
                            msg = _("The category list you provided doesn't match with your server's categories.")
                            if regioncat_errors:
                                msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                            msg += _("\n\nPlease double check your category list and resend your response. If you just made these categories, try again.")
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=msg))
                            continue
                    else:
                        msg = _("The number of categories I found in your server doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n**Matched Channels:** {channellist}\n**Matched Categories:** {catlist}\n\nPlease double check that your categories match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), catlist=', '.join(regioncat_names) if len(regioncat_list)>0 else "None")
                        if regioncat_errors:
                            msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=msg))
                        continue
                    break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=_("Sorry, I didn't understand your answer! Try again.")))
                continue
            break
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('EX Raid Categories are set')))
        config_dict_temp['exraid']['category_dict'] = category_dict
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Who do you want to be able to **see** the EX Raid channels? Your options are:\n\n**everyone** - To have everyone be able to see all reported EX Raids\n**same** - To only allow those with access to the reporting channel.")).set_author(name=_('EX Raid Channel Read Permissions'), icon_url=Kyogre.user.avatar_url))
        while True:
            permsconfigset = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            if permsconfigset.content.lower() == 'everyone':
                config_dict_temp['exraid']['permissions'] = "everyone"
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Everyone permission enabled')))
                break
            elif permsconfigset.content.lower() == 'same':
                config_dict_temp['exraid']['permissions'] = "same"
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Same permission enabled')))
                break
            elif permsconfigset.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I'm sorry I don't understand. Please reply with either **N** to disable, or **Y** to enable.")))
                continue
    ctx.config_dict_temp = config_dict_temp
    return ctx


async def _configure_exinvite(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('Do you want access to EX raids controlled through members using the **!invite** command?\nIf enabled, members will have read-only permissions for all EX Raids until they use **!invite** to gain access. If disabled, EX Raids will inherit the permissions from their reporting channels.\n\nRespond with: **N** to disable, or **Y** to enable:')).set_author(name=_('Invite Configuration'), icon_url=Kyogre.user.avatar_url))
    while True:
        inviteconfigset = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if inviteconfigset.content.lower() == 'y':
            config_dict_temp['invite']['enabled'] = True
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Invite Command enabled')))
            break
        elif inviteconfigset.content.lower() == 'n':
            config_dict_temp['invite']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Invite Command disabled')))
            break
        elif inviteconfigset.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I'm sorry I don't understand. Please reply with either **N** to disable, or **Y** to enable.")))
            continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_counters(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('Do you want to generate an automatic counters list in newly created raid channels using PokeBattler?\nIf enabled, I will post a message containing the best counters for the raid boss in new raid channels. Users will still be able to use **!counters** to generate this list.\n\nRespond with: **N** to disable, or enable with a comma separated list of boss levels that you would like me to generate counters for. Example:`3,4,5,EX`')).set_author(name=_('Automatic Counters Configuration'), icon_url=Kyogre.user.avatar_url))
    while True:
        countersconfigset = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if countersconfigset.content.lower() == 'n':
            config_dict_temp['counters']['enabled'] = False
            config_dict_temp['counters']['auto_levels'] = []
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Automatic Counters disabled')))
            break
        elif countersconfigset.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            raidlevel_list = countersconfigset.content.lower().split(',')
            raidlevel_list = [x.strip() for x in raidlevel_list]
            counterlevels = []
            for level in raidlevel_list:
                if level.isdigit() and (int(level) <= 5):
                    counterlevels.append(str(level))
                elif level == "ex":
                    counterlevels.append("EX")
            if len(counterlevels) > 0:
                config_dict_temp['counters']['enabled'] = True
                config_dict_temp['counters']['auto_levels'] = counterlevels
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Automatic Counter Levels set to: {levels}').format(levels=', '.join((str(x) for x in config_dict_temp['counters']['auto_levels'])))))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("Please enter at least one level from 1 to EX separated by comma. Ex: `4,5,EX` or **N** to turn off automatic counters.")))
                continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_wild(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Wild Reporting allows users to report wild spawns with **!wild**. Pokemon **wild** reports are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-wilds, hull-wilds, sydney-wilds`\n\nIf you do not require **wild** reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Wild Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['wild']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Wild Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['wild']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Wild Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['wild']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to wild spawns! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('Wild Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=region_names[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to wild spawns! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('Wild Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['wild']['report_channels'] = citychannel_dict
        config_dict_temp['wild']['listings'] = await _get_listings(Kyogre, guild, owner, config_dict_temp)
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Wild Reporting Locations are set')))
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_research(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Research Reporting allows users to report field research with **!research**. Pokemon **research** reports are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-research, hull-research, sydney-research`\n\nIf you do not require **research** reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Research Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['research']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Research Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['research']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Research Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['research']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to the field research! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('Research Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=region_names[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to field research! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('Research Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['research']['report_channels'] = citychannel_dict
        config_dict_temp['research']['listings'] = await _get_listings(Kyogre, guild, owner, config_dict_temp)
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Research Reporting Locations are set')))
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_meetup(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    config_dict_temp['meetup'] = {}
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("Meetup Reporting allows users to report meetups with **!meetup** or **!event**. Meetup reports are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-meetups, hull-meetups, sydney-meetups`\n\nIf you do not require meetup reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Meetup Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['meetup']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Meetup Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['meetup']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Meetup Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['meetup']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to the meetup! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('Meetup Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=region_names[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to meetups! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('Meetup Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['meetup']['report_channels'] = citychannel_dict
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Meetup Reporting Locations are set')))
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("How would you like me to categorize the meetup channels I create? Your options are:\n\n**none** - If you don't want them categorized\n**same** - If you want them in the same category as the reporting channel\n**other** - If you want them categorized in a provided category name or ID")).set_author(name=_('Meetup Reporting Categories'), icon_url=Kyogre.user.avatar_url))
        while True:
            guild = Kyogre.get_guild(guild.id)
            guild_catlist = []
            for cat in guild.categories:
                guild_catlist.append(cat.id)
            category_dict = {}
            categories = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
            if categories.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            elif categories.content.lower() == 'none':
                config_dict_temp['meetup']['categories'] = None
                break
            elif categories.content.lower() == 'same':
                config_dict_temp['meetup']['categories'] = 'same'
                break
            elif categories.content.lower() == 'other':
                while True:
                    guild = Kyogre.get_guild(guild.id)
                    guild_catlist = []
                    for cat in guild.categories:
                        guild_catlist.append(cat.id)
                    config_dict_temp['meetup']['categories'] = 'region'
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(),description=_("In the same order as they appear below, please give the names of the categories you would like raids reported in each channel to appear in. You do not need to use different categories for each channel, but they do need to be pre-existing categories. Separate each category name with a comma. Response can be either category name or ID.\n\nExample: `kansas city, hull, 1231231241561337813`\n\nYou have configured the following channels as meetup reporting channels.")).set_author(name=_('Meetup Reporting Categories'), icon_url=Kyogre.user.avatar_url))
                    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
                    regioncats = await Kyogre.wait_for('message', check=lambda message: message.guild == None and message.author == owner)
                    if regioncats.content.lower() == "cancel":
                        await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                        return None
                    regioncat_list = regioncats.content.split(',')
                    regioncat_list = [x.strip() for x in regioncat_list]
                    regioncat_ids = []
                    regioncat_names = []
                    regioncat_errors = []
                    for item in regioncat_list:
                        category = None
                        if item.isdigit():
                            category = discord.utils.get(guild.categories, id=int(item))
                        if not category:
                            name = await utils.letter_case(guild.categories, item.lower())
                            category = discord.utils.get(guild.categories, name=name)
                        if category:
                            regioncat_ids.append(category.id)
                            regioncat_names.append(category.name)
                        else:
                            regioncat_errors.append(item)
                    regioncat_list = regioncat_ids
                    if len(regioncat_list) == len(citychannel_list):
                        catdiff = set(regioncat_list) - set(guild_catlist)
                        if (not catdiff) and (not regioncat_errors):
                            for i in range(len(citychannel_list)):
                                category_dict[citychannel_list[i]] = regioncat_list[i]
                            break
                        else:
                            msg = _("The category list you provided doesn't match with your server's categories.")
                            if regioncat_errors:
                                msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                            msg += _("\n\nPlease double check your category list and resend your response. If you just made these categories, try again.")
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=msg))
                            continue
                    else:
                        msg = _("The number of categories I found in your server doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n**Matched Channels:** {channellist}\n**Matched Categories:** {catlist}\n\nPlease double check that your categories match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), catlist=', '.join(regioncat_names) if len(regioncat_list)>0 else "None")
                        if regioncat_errors:
                            msg += _("\n\nThe following aren't in your server: **{invalid_categories}**").format(invalid_categories=', '.join(regioncat_errors))
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=msg))
                        continue
                    break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(),description=_("Sorry, I didn't understand your answer! Try again.")))
                continue
            break
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Meetup Categories are set')))
        config_dict_temp['meetup']['category_dict'] = category_dict
    ctx.config_dict_temp = config_dict_temp
    return ctx


async def _configure_subscriptions(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    if 'subscriptions' not in config_dict_temp:
        config_dict_temp['subscriptions'] = {}
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("The **!subscription** commmand lets users set up special triggers for me to send them a notification DM when an event they're interested in happens. I just need to know what channels you want to use to allow people to manage these notifications with the **!subscription** command.\n\nIf you don't want to allow the management of subscriptions, then you may want to disable this feature.\n\nRepond with: **N** to disable, or the **channel-name** list to enable, each seperated by a comma and space.")).set_author(name=_('Subscriptions'), icon_url=Kyogre.user.avatar_url))
    while True:
        subchs = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if subchs.content.lower() == 'n':
            config_dict_temp['subscriptions']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Subscriptions disabled')))
            break
        elif subchs.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            sub_list = subchs.content.lower().split(',')
            sub_list = [x.strip() for x in sub_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            sub_list_objs = []
            sub_list_names = []
            sub_list_errors = []
            for item in sub_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub(r'[^a-zA-Z0-9 _\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    sub_list_objs.append(channel)
                    sub_list_names.append(channel.name)
                else:
                    sub_list_errors.append(item)
            sub_list_set = [x.id for x in sub_list_objs]
            diff = set(sub_list_set) - set(guild_channel_list)
            if (not diff) and (not sub_list_errors):
                config_dict_temp['subscriptions']['enabled'] = True
                config_dict_temp['subscriptions']['report_channels'] = sub_list_set
                for channel in sub_list_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Subscriptions enabled')))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(sub_list_errors))))
                continue
    ctx.config_dict_temp = config_dict_temp
    return ctx
async def _configure_pvp(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    if 'pvp' not in config_dict_temp:
        config_dict_temp['pvp'] = {}
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("The **!pvp** command allows your users to announce to their friends when they're available for pvp. \
        Additionally it allows them to add and remove other users as friends. If User A has added User B as a friend, User A will receive a notification when User B announces they're available to battle. \
        This command requires at least one channel specifically for pvp.\n\nIf you would like to disable this feature, reply with **N**. \
        Otherwise, just send the names or IDs of the channels you want to allow the **!pvp** command in, separated by commas.")).set_author(name=_('PVP Configuration'), icon_url=Kyogre.user.avatar_url))
    while True:
        pvpmsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if pvpmsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        elif pvpmsg.content.lower() == 'n':
            config_dict_temp['pvp'] = {'enabled': False, 'report_channels': []}
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('PVP disabled.')))
            break
        else:
            pvp_list = pvpmsg.content.lower().split(',')
            pvp_list = [x.strip() for x in pvp_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            pvp_list_objs = []
            pvp_list_names = []
            pvp_list_errors = []
            for item in pvp_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    pvp_list_objs.append(channel)
                    pvp_list_names.append(channel.name)
                else:
                    pvp_list_errors.append(item)
            pvp_list_set = [x.id for x in pvp_list_objs]
            diff = set(pvp_list_set) - set(guild_channel_list)
            if (not diff) and (not pvp_list_errors):
                config_dict_temp['pvp']['enabled'] = True
                config_dict_temp['pvp']['report_channels'] = pvp_list_set
                for channel in pvp_list_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('PVP enabled')))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(pvp_list_errors))))
                continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_join(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    if 'join' not in config_dict_temp:
        config_dict_temp['join'] = {'enabled': False, 'link': ''}
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("The **!join** command allows your users to get an invite link to your server \
even if they are otherwise prevented from generating invite links.\n\nIf you would like to enable this, please provide a non-expiring invite link to your server.\
If you would like to disable this feature, reply with **N**. To cancel this configuration session, reply with **cancel**.\
")).set_author(name=_('Join Link Configuration'), icon_url=Kyogre.user.avatar_url))
    while True:
        joinmsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if joinmsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        elif joinmsg.content.lower() == 'n':
            config_dict_temp['join'] = {'enabled': False, 'link': ''}
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Invite link disabled.')))
            break
        else:
            if 'discord.gg/' in joinmsg.content.lower() or 'discordapp.com/invite/' in joinmsg.content.lower():
                config_dict_temp['join'] = {'enabled': True, 'link': joinmsg.content}
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('That does not appear to be a valid invite link. Please try again.')))
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_lure(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    if 'lure' not in config_dict_temp:
        config_dict_temp['lure'] = {'enabled':False, 'report_channels': {}}
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), 
        description=_("Lure Reporting allows users to report lures they've applied with **!lure**. **lure** are contained within one or more channels. Each channel will be able to represent different areas/communities. I'll need you to provide a list of channels in your server you will allow reports from in this format: `channel-name, channel-name, channel-name`\n\nExample: `kansas-city-lures, hull-lures, sydney-lures`\n\nIf you do not require **lure** reporting, you may want to disable this function.\n\nRespond with: **N** to disable, or the **channel-name** list to enable, each seperated with a comma and space:")).set_author(name=_('Lure Reporting Channels'), icon_url=Kyogre.user.avatar_url))
    citychannel_dict = {}
    while True:
        citychannels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if citychannels.content.lower() == 'n':
            config_dict_temp['lure']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Lure Reporting disabled')))
            break
        elif citychannels.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            config_dict_temp['lure']['enabled'] = True
            citychannel_list = citychannels.content.lower().split(',')
            citychannel_list = [x.strip() for x in citychannel_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            citychannel_objs = []
            citychannel_names = []
            citychannel_errors = []
            for item in citychannel_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    citychannel_objs.append(channel)
                    citychannel_names.append(channel.name)
                else:
                    citychannel_errors.append(item)
            citychannel_list = [x.id for x in citychannel_objs]
            diff = set(citychannel_list) - set(guild_channel_list)
            if (not diff) and (not citychannel_errors):
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Lure Reporting Channels enabled')))
                for channel in citychannel_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(citychannel_errors))))
                continue
    if config_dict_temp['lure']['enabled']:
        if config_dict_temp.get('regions', {}).get('enabled', None):
            region_names = [name for name in config_dict_temp['regions']['info'].keys()]
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to lures! To do this, I need to know which region each report channel represents using the region names as previously configured (see below), to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding region using only letters and spaces, with each region seperated by a comma and space.\n\nExample: `kanto, johto, sinnoh`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **region name, region name, region name** each matching the order of the previous channel list below.')).set_author(name=_('Lure Reporting Regions'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{region_names}').format(region_names=region_names[:2000])).set_author(name=_('Entered Regions'), icon_url=Kyogre.user.avatar_url))
            while True:
                regions = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                regions = regions.content.lower().strip()
                if regions == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                region_list = [x.strip() for x in regions.split(',')]
                if len(region_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = region_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of regions doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{regionlist}\n\nPlease double check that your regions match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), regionlist=', '.join(region_list))))
                    continue
        else:
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('For each report, I generate Google Maps links to give people directions to lures! To do this, I need to know which suburb/town/region each report channel represents, to ensure we get the right location in the map. For each report channel you provided, I will need its corresponding general location using only letters and spaces, with each location seperated by a comma and space.\n\nExample: `kansas city mo, hull uk, sydney nsw australia`\n\nEach location will have to be in the same order as you provided the channels in the previous question.\n\nRespond with: **location info, location info, location info** each matching the order of the previous channel list below.')).set_author(name=_('Lure Reporting Locations'), icon_url=Kyogre.user.avatar_url))
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('{citychannel_list}').format(citychannel_list=citychannels.content.lower()[:2000])).set_author(name=_('Entered Channels'), icon_url=Kyogre.user.avatar_url))
            while True:
                cities = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
                if cities.content.lower() == 'cancel':
                    await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                    return None
                city_list = cities.content.split(',')
                city_list = [x.strip() for x in city_list]
                if len(city_list) == len(citychannel_list):
                    for i in range(len(citychannel_list)):
                        citychannel_dict[citychannel_list[i]] = city_list[i]
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The number of cities doesn't match the number of channels you gave me earlier!\n\nI'll show you the two lists to compare:\n\n{channellist}\n{citylist}\n\nPlease double check that your locations match up with your provided channels and resend your response.").format(channellist=', '.join(citychannel_names), citylist=', '.join(city_list))))
                    continue
        config_dict_temp['lure']['report_channels'] = citychannel_dict
        config_dict_temp['lure']['listings'] = await _get_listings(Kyogre, guild, owner, config_dict_temp)
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Lure Reporting Locations are set')))
    ctx.config_dict_temp = config_dict_temp
    return ctx
async def _configure_archive(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("The **!archive** command marks temporary raid channels for archival rather than deletion. This can be useful for investigating potential violations of your server's rules in these channels.\n\nIf you would like to disable this feature, reply with **N**. Otherwise send the category you would like me to place archived channels in. You can say **same** to keep them in the same category, or type the name or ID of a category in your server.")).set_author(name=_('Archive Configuration'), icon_url=Kyogre.user.avatar_url))
    config_dict_temp['archive'] = {}
    while True:
        archivemsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if archivemsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        if archivemsg.content.lower() == 'same':
            config_dict_temp['archive']['category'] = 'same'
            config_dict_temp['archive']['enabled'] = True
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Archived channels will remain in the same category.')))
            break
        if archivemsg.content.lower() == 'n':
            config_dict_temp['archive']['enabled'] = False
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Archived Channels disabled.')))
            break
        else:
            item = archivemsg.content
            category = None
            if item.isdigit():
                category = discord.utils.get(guild.categories, id=int(item))
            if not category:
                name = await utils.letter_case(guild.categories, item.lower())
                category = discord.utils.get(guild.categories, name=name)
            if not category:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I couldn't find the category you replied with! Please reply with **same** to leave archived channels in the same category, or give the name or ID of an existing category.")))
                continue
            config_dict_temp['archive']['category'] = category.id
            config_dict_temp['archive']['enabled'] = True
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Archive category set.')))
            break
    if config_dict_temp['archive']['enabled']:
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("I can also listen in your raid channels for words or phrases that you want to trigger an automatic archival. For example, if discussion of spoofing is against your server rules, you might tell me to listen for the word 'spoofing'.\n\nReply with **none** to disable this feature, or reply with a comma separated list of phrases you want me to listen in raid channels for.")).set_author(name=_('Archive Configuration'), icon_url=Kyogre.user.avatar_url))
        phrasemsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if phrasemsg.content.lower() == 'none':
            config_dict_temp['archive']['list'] = None
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Phrase list disabled.')))
        elif phrasemsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        else:
            phrase_list = phrasemsg.content.lower().split(",")
            for i in range(len(phrase_list)):
                phrase_list[i] = phrase_list[i].strip()
            config_dict_temp['archive']['list'] = phrase_list
            await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Archive Phrase list set.')))
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_settings(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("There are a few settings available that are not within **!configure**. \
        To set these, use **!set <setting>** in any channel to set that setting.\n\nThese include:\n\
        **!set regional <name or number>** - To set a server's regional raid boss\n\
        **!set prefix <prefix>** - To set my command prefix\n\
        **!set timezone <offset>** - To set offset outside of **!configure**\n\
        **!set silph <trainer>** - To set a trainer's SilphRoad card (usable by members)\n\
        **!set pokebattler <ID>** - To set a trainer's pokebattler ID (usable by members)\n\n\
        However, we can set your timezone now to help coordinate reports or we can setup an admin command channel. \
        For others, use the **!set** command.\n\nThe current 24-hr time UTC is {utctime}. \
        Reply with 'skip' to setup your admin command channels.\
        How many hours off from that are you?\n\nRespond with: A number from **-12** to **12**:"\
        ).format(utctime=strftime('%H:%M', time.gmtime()))).set_author(name=_('Timezone Configuration and Other Settings'), icon_url=Kyogre.user.avatar_url))
    skipped = False
    while True:
        offsetmsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if offsetmsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        elif offsetmsg.content.lower() == 'skip':
            await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_('Timezone configuration skipped.')))
            skipped = True
            break
        else:
            try:
                offset = float(offsetmsg.content)
            except ValueError:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I couldn't convert your answer to an appropriate timezone!\n\n\
                    Please double check what you sent me and resend a number from **-12** to **12**.")))
                continue
            if (not ((- 12) <= offset <= 14)):
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("I couldn't convert your answer to an appropriate timezone!\n\n\
                    Please double check what you sent me and resend a number from **-12** to **12**.")))
                continue
            else:
                break
    if not skipped:
        config_dict_temp['settings']['offset'] = offset
        await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Timezone set')))
    else:
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description="It may be helpful to have an admin only command channel for\
            interacting with Kyogre.\n\nPlease provide a channel name or id for this purpose.\nYou can also provide a comma separate list but all list\
            items should be the same (all names or all ids)."))
        while True:
            channel_message = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            if offsetmsg.content.lower() == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            else:
                adminchannel_list = channel_message.content.lower().split(',')
                adminchannel_list = [x.strip() for x in adminchannel_list]
                guild_channel_list = []
                for channel in guild.text_channels:
                    guild_channel_list.append(channel.id)
                adminchannel_objs = []
                adminchannel_names = []
                adminchannel_errors = []
                for item in adminchannel_list:
                    channel = None
                    if item.isdigit():
                        channel = discord.utils.get(guild.text_channels, id=int(item))
                    if not channel:
                        item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                        item = item.replace(" ","-")
                        name = await utils.letter_case(guild.text_channels, item.lower())
                        channel = discord.utils.get(guild.text_channels, name=name)
                    if channel:
                        adminchannel_objs.append(channel)
                        adminchannel_names.append(channel.name)
                    else:
                        adminchannel_errors.append(item)
                adminchannel_list = [x.id for x in adminchannel_objs]
                diff = set(adminchannel_list) - set(guild_channel_list)
                if (not diff) and (not adminchannel_errors):
                    for channel in adminchannel_objs:
                        ow = channel.overwrites_for(Kyogre.user)
                        ow.send_messages = True
                        ow.read_messages = True
                        ow.manage_roles = True
                        try:
                            await channel.set_permissions(Kyogre.user, overwrite = ow)
                        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(adminchannel_errors))))
                    continue
        command_channels = []
        for channel in adminchannel_objs:
            command_channels.append(channel.id)
        admin_dict = config_dict_temp.setdefault('admin',{})
        admin_dict['command_channels'] = command_channels
    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Admin Command Channels enabled')))
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _configure_trade(ctx,Kyogre):
    guild_dict = Kyogre.guild_dict
    config = Kyogre.config
    guild = ctx.message.guild
    owner = ctx.message.author
    config_dict_temp = getattr(ctx, 'config_dict_temp',copy.deepcopy(guild_dict[guild.id]['configure_dict']))
    await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("The **!trade** command allows your users to organize and coordinate trades. This command requires at least one channel specifically for trades.\n\nIf you would like to disable this feature, reply with **N**. Otherwise, just send the names or IDs of the channels you want to allow the **!trade** command in, separated by commas.")).set_author(name=_('Trade Configuration'), icon_url=Kyogre.user.avatar_url))
    while True:
        trademsg = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
        if trademsg.content.lower() == 'cancel':
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
            return None
        elif trademsg.content.lower() == 'n':
            config_dict_temp['trade'] = {'enabled': False, 'report_channels': []}
            await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Trade disabled.')))
            break
        else:
            trade_list = trademsg.content.lower().split(',')
            trade_list = [x.strip() for x in trade_list]
            guild_channel_list = []
            for channel in guild.text_channels:
                guild_channel_list.append(channel.id)
            trade_list_objs = []
            trade_list_names = []
            trade_list_errors = []
            for item in trade_list:
                channel = None
                if item.isdigit():
                    channel = discord.utils.get(guild.text_channels, id=int(item))
                if not channel:
                    item = re.sub('[^a-zA-Z0-9 _\\-]+', '', item)
                    item = item.replace(" ","-")
                    name = await utils.letter_case(guild.text_channels, item.lower())
                    channel = discord.utils.get(guild.text_channels, name=name)
                if channel:
                    trade_list_objs.append(channel)
                    trade_list_names.append(channel.name)
                else:
                    trade_list_errors.append(item)
            trade_list_set = [x.id for x in trade_list_objs]
            diff = set(trade_list_set) - set(guild_channel_list)
            if (not diff) and (not trade_list_errors):
                config_dict_temp['trade']['enabled'] = True
                config_dict_temp['trade']['report_channels'] = trade_list_set
                for channel in trade_list_objs:
                    ow = channel.overwrites_for(Kyogre.user)
                    ow.send_messages = True
                    ow.read_messages = True
                    ow.manage_roles = True
                    try:
                        await channel.set_permissions(Kyogre.user, overwrite = ow)
                    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                        await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Pokemon Trades enabled')))
                break
            else:
                await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(trade_list_errors))))
                continue
    ctx.config_dict_temp = config_dict_temp
    return ctx

async def _get_listings(Kyogre, guild, owner, config_dict_temp):
    listing_dict = {}
    if config_dict_temp.get('regions', {}).get('enabled', None):
        region_names = list(config_dict_temp['regions']['info'].keys())
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("I can also provide listings per region that I will keep updated automatically as events are reported, updated, or expired. To get started, please provide a comma-separated list of channel names, one per region, matching the format of this list of regions:\n\n`{region_list}`\n\n**IMPORTANT** I recommend you set the permissions for each channel provided to allow only me to post to it. I will moderate each channel to remove other messages, but it will save me some work!").format(region_list=', '.join(region_names))).set_author(name=_('Listing Channels'), icon_url=Kyogre.user.avatar_url))
        while True:
            listing_channels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            listing_channels = listing_channels.content.lower()
            if listing_channels == 'n':
                listing_dict['enabled'] = False
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Listing disabled')))
                break
            elif listing_channels == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            else:
                listing_dict['enabled'] = True
                channel_dict = {}
                channel_list = [x.strip() for x in listing_channels.split(',')]
                guild_channel_list = [channel.id for channel in guild.text_channels]
                channel_objs = []
                channel_names = []
                channel_errors = []
                for item in channel_list:
                    channel = None
                    if item.isdigit():
                        channel = discord.utils.get(guild.text_channels, id=int(item))
                    if not channel:
                        name = utils.sanitize_name(item)
                        channel = discord.utils.get(guild.text_channels, name=name)
                    if channel:
                        channel_objs.append(channel)
                        channel_names.append(channel.name)
                    else:
                        channel_errors.append(item)
                if len(channel_objs) != len(region_names):
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your region list.\n\nPlease provide a channel for each region in your region list:\n\n{region_list}").format(region_list=', '.join(region_names))))
                    continue
                diff = set([x.id for x in channel_objs]) - set(guild_channel_list)
                if (not diff) and (not channel_errors):
                    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Listing Channels enabled')))
                    for i, channel in enumerate(channel_objs):
                        ow = channel.overwrites_for(Kyogre.user)
                        ow.send_messages = True
                        ow.read_messages = True
                        ow.manage_roles = True
                        try:
                            await channel.set_permissions(Kyogre.user, overwrite = ow)
                        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                        channel_dict[region_names[i]] = {'id': channel.id, 'messages': []}
                    listing_dict['channels'] = channel_dict
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel list you provided doesn't match with your servers channels.\n\nThe following aren't in your server: **{invalid_channels}**\n\nPlease double check your channel list and resend your reponse.").format(invalid_channels=', '.join(channel_errors))))
                    continue
    else:
        await owner.send(embed=discord.Embed(colour=discord.Colour.lighter_grey(), description=_("I can also provide a listing that I will keep updated automatically as events are reported, updated, or expired. To enable this, please provide a channel name where this listing should be shown.\n\n**IMPORTANT** I recommend you set the permissions for this channel to allow only me to post to it. I will moderate the channel to remove other messages, but it will save me some work!")).set_author(name=_('Listing Channels'), icon_url=Kyogre.user.avatar_url))
        while True:
            listing_channels = await Kyogre.wait_for('message', check=(lambda message: (message.guild == None) and message.author == owner))
            listing_channels = listing_channel.content.lower()
            if listing_channel == 'n':
                listing_dict['enabled'] = False
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('Listing disabled')))
                break
            elif listing_channel == 'cancel':
                await owner.send(embed=discord.Embed(colour=discord.Colour.red(), description=_('**CONFIG CANCELLED!**\n\nNo changes have been made.')))
                return None
            else:
                listing_dict['enabled'] = True
                channel_dict = {}
                channel_list = [(listing_channels.split(',')[0]).strip()]
                guild_channel_list = [channel.id for channel in guild.text_channels]
                channel_objs = []
                channel_names = []
                channel_errors = []
                for item in channel_list:
                    channel = None
                    if item.isdigit():
                        channel = discord.utils.get(guild.text_channels, id=int(item))
                    if not channel:
                        name = utils.sanitize_name(item)
                        channel = discord.utils.get(guild.text_channels, name=name)
                    if channel:
                        channel_objs.append(channel)
                        channel_names.append(channel.name)
                    else:
                        channel_errors.append(item)
                diff = set([x.id for x in channel_objs]) - set(guild_channel_list)
                if (not diff) and (not channel_errors):
                    await owner.send(embed=discord.Embed(colour=discord.Colour.green(), description=_('Listing Channel enabled')))
                    for i, channel in enumerate(channel_objs):
                        ow = channel.overwrites_for(Kyogre.user)
                        ow.send_messages = True
                        ow.read_messages = True
                        ow.manage_roles = True
                        try:
                            await channel.set_permissions(Kyogre.user, overwrite = ow)
                        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
                            await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_('I couldn\'t set my own permissions in this channel. Please ensure I have the correct permissions in {channel} using **{prefix}get perms**.').format(prefix=ctx.prefix, channel=channel.mention)))
                    listing_dict['channel'] = {'id': channel_objs[0].id, 'messages': []}
                    break
                else:
                    await owner.send(embed=discord.Embed(colour=discord.Colour.orange(), description=_("The channel you provided doesn't match with your servers channels.\n\nPlease double check your channel and resend your reponse.")))
                    continue
    return listing_dict
