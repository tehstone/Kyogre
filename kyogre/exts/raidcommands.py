import asyncio
import copy
import datetime
import re
import textwrap
import time

import discord
from discord.ext import commands

from kyogre import checks, list_helpers, raid_helpers, utils
from kyogre.exts.pokemon import Pokemon


class RaidCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

@commands.command(name="raid", aliases=['r', 're', 'egg', 'regg', 'raidegg', '1', '2', '3', '4', '5'],
    brief="Report an ongoing raid or a raid egg.")
@checks.allowraidreport()
async def _raid(self, ctx, pokemon, *, location:commands.clean_content(fix_channel_mentions=True) = "",
                weather = None, timer = None):
    """**Usage**: `!raid <raid tier/pokemon> <gym name> [time]`
    Kyogre will attempt to find a gym with the name you provide and create a separate channel for the raid report, for the purposes of organizing the raid."""
    if ctx.invoked_with.isdigit():
        content = f"{ctx.invoked_with} {pokemon} {location} {weather if weather is not None else ''} " \
            f"{timer if timer is not None else ''}"
        new_channel = await _raidegg(ctx, content)
    else:
        content = f"{pokemon} {location}".lower()
        if pokemon.isdigit():
            new_channel = await _raidegg(ctx, content)
        elif len(pokemon) == 2 and pokemon[0] == "t":
            new_channel = await _raidegg(ctx, content[1:])
        else:
            new_channel = await _raid_internal(ctx, content)
    ctx.raid_channel = new_channel

async def _raid_internal(self, ctx, content):
    message = ctx.message
    channel = message.channel
    guild = channel.guild
    author = message.author
    fromegg = False
    eggtoraid = False
    if guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('type') == "egg":
        fromegg = True
    raid_split = content.split()
    if len(raid_split) == 0:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                      description='Give more details when reporting! '
                                                                  'Usage: **!raid <pokemon name> <location>**'))
    if raid_split[0] == 'egg':
        await _raidegg(ctx, content)
        return
    if fromegg:
        eggdetails = guild_dict[guild.id]['raidchannel_dict'][channel.id]
        egglevel = eggdetails['egglevel']
        if raid_split[0].lower() == 'assume':
            if config['allow_assume'][egglevel] == 'False':
                return await channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description='**!raid assume** is not allowed for this level egg.'))
            if not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                await _eggtoraid(ctx, raid_split[1].lower(), channel, author)
                return
            else:
                await _eggassume(" ".join(raid_split), channel, author)
                return
        elif (raid_split[0] == "alolan" and len(raid_split) > 2) or (raid_split[0] != "alolan" and len(raid_split) > 1):
            if (raid_split[0] not in Pokemon.get_forms_list() and len(raid_split) > 1):
                Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Raid report made in raid channel.")
                return await channel.send(
                    embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description='Please report new raids in a reporting channel.'))
        elif not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
            eggtoraid = True
        ## This is a hack but it allows users to report the just hatched boss
        ## before Kyogre catches up with hatching the egg.
        elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 < datetime.datetime.now().timestamp():
            eggtoraid = True
        else:
            Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Hatch announced too soon.")            
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Please wait until the egg has hatched before changing it to an open raid!'))
    raid_pokemon = Pokemon.get_pokemon(Kyogre, content)
    pkmn_error = None
    pkmn_error_dict = {'not_pokemon': "I couldn't determine the Pokemon in your report.\n"
                                      "What raid boss or raid tier are you reporting?",
                       'not_boss': 'That Pokemon does not appear in raids!\nWhat is the correct Pokemon?',
                       'ex': ("The Pokemon {pokemon} only appears in EX Raids!\nWhat is the correct Pokemon?")
                           .format(pokemon=str(raid_pokemon).capitalize()),
                       'level': "That is not a valid raid tier. Please provide the raid boss or tier for your report."}
    if not raid_pokemon:
        pkmn_error = 'not_pokemon'
        try:
            new_content = content.split()
            pkmn_index = new_content.index('alolan')
            del new_content[pkmn_index + 1]
            del new_content[pkmn_index]
            new_content = ' '.join(new_content)
        except ValueError:
            new_content = ' '.join(content.split())
    elif not raid_pokemon.is_raid:
        pkmn_error = 'not_boss'
        try:
            new_content = content.split()
            pkmn_index = new_content.index('alolan')
            del new_content[pkmn_index + 1]
            del new_content[pkmn_index]
            new_content = ' '.join(new_content)
        except ValueError:
            new_content = ' '.join(content.split())
    elif raid_pokemon.is_exraid:
        pkmn_error = 'ex'
        new_content = ' '.join(content.split()[1:])
    if pkmn_error is not None:
        while True:
            pkmn_embed=discord.Embed(colour=discord.Colour.red(), description=pkmn_error_dict[pkmn_error])
            pkmn_embed.set_footer(text="Reply with 'cancel' to cancel your raid report.")
            pkmnquery_msg = await channel.send(embed=pkmn_embed)
            try:
                pokemon_msg = await Kyogre.wait_for('message', timeout=30, check=(lambda reply: reply.author == author))
            except asyncio.TimeoutError:
                await channel.send(embed=discord.Embed(
                    colour=discord.Colour.light_grey(),
                    description="You took too long to reply. Raid report cancelled."))
                await pkmnquery_msg.delete()
                return
            if pokemon_msg.clean_content.lower() == "cancel":
                await pkmnquery_msg.delete()
                await pokemon_msg.delete()
                await channel.send(embed=discord.Embed(colour=discord.Colour.light_grey(),
                                                       description="Raid report cancelled."))
                return
            if pokemon_msg.clean_content.isdigit():
                if 0 < int(pokemon_msg.clean_content) <= 5:
                    return await _raidegg(ctx, ' '.join([str(pokemon_msg.clean_content), new_content]))
                else:
                    pkmn_error = 'level'
                    continue
            raid_pokemon = Pokemon.get_pokemon(Kyogre, pokemon_msg.clean_content)
            if not raid_pokemon:
                pkmn_error = 'not_pokemon'
            elif not raid_pokemon.is_raid:
                pkmn_error = 'not_boss'
            elif raid_pokemon.is_exraid:
                pkmn_error = 'ex'
            else:
                await pkmnquery_msg.delete()
                await pokemon_msg.delete()
                break
            await pkmnquery_msg.delete()
            await pokemon_msg.delete()
            await asyncio.sleep(.5)
    else:
        new_content = ' '.join(content.split()[len(raid_pokemon.full_name.split()):])
    if fromegg:
        return await _eggtoraid(ctx, raid_pokemon.full_name.lower(), channel, author)
    if eggtoraid:
        return await _eggtoraid(ctx, new_content.lower(), channel, author)
    raid_split = new_content.strip().split()
    if len(raid_split) == 0:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    raidexp = await utils.time_to_minute_count(guild_dict, channel, raid_split[-1], False)
    if raidexp:
        del raid_split[-1]
        if _timercheck(raidexp, raid_info['raid_eggs'][raid_pokemon.raid_level]['raidtime']):
            Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Raid expiration time too long.")
            time_embed = discord.Embed(description="That's too long. Level {raidlevel} Raids currently last no "
                                                   "more than {hatchtime} minutes...\nExpire time will not be set."
                                       .format(raidlevel=raid_pokemon.raid_level,
                                               hatchtime=raid_info['raid_eggs'][raid_pokemon.raid_level]['hatchtime']),
                                       colour=discord.Colour.red())
            await channel.send(embed=time_embed)
            raidexp = False
            Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: raid expiration time too long")
    else:
        await channel.send(
            embed=discord.Embed(colour=discord.Colour.orange(),
                                description='Could not determine expiration time. Using default of 45 minutes'))
    raid_details = ' '.join(raid_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    rgx = '[^a-zA-Z0-9]'
    weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
    if not weather:
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    raid_pokemon.weather = weather
    raid_details = raid_details.replace(str(weather), '', 1)
    if raid_details == '':
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    return await finish_raid_report(ctx, raid_details, raid_pokemon, raid_pokemon.raid_level, weather, raidexp)

@staticmethod
async def retry_gym_match(channel, author_id, raid_details, gyms):
    attempt = raid_details.split(' ')
    if len(attempt) > 1:
        if attempt[-2] == "alolan" and len(attempt) > 2:
            del attempt[-2]
        del attempt[-1]
    attempt = ' '.join(attempt)
    gym = await location_match_prompt(channel, author_id, attempt, gyms)
    if gym:
        return gym
    else:
        attempt = raid_details.split(' ')
        if len(attempt) > 1:
            if attempt[0] == "alolan" and len(attempt) > 2:
                del attempt[0]
            del attempt[0]
        attempt = ' '.join(attempt)
        gym = await location_match_prompt(channel, author_id, attempt, gyms)
        if gym:
            return gym
        else:
            return None

async def _raidegg(self, ctx, content):
    message = ctx.message
    channel = message.channel

    if checks.check_eggchannel(ctx) or checks.check_raidchannel(ctx):
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Raid reported in raid channel.")
        return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                      description='Please report new raids in a reporting channel.'))
    
    guild = message.guild
    author = message.author
    raidexp = False
    hourminute = False
    raidegg_split = content.split()
    if raidegg_split[0].lower() == 'egg':
        del raidegg_split[0]
    if len(raidegg_split) <= 1:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Usage: **!raidegg <level> <location>**'))
    if raidegg_split[0].isdigit():
        egg_level = int(raidegg_split[0])
        del raidegg_split[0]
    else:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. '
                        'Type **!help** raidegg for more info.'))
    raidexp = await utils.time_to_minute_count(guild_dict, channel, raidegg_split[-1], False)
    if raidexp:
        del raidegg_split[-1]
        if _timercheck(raidexp, raid_info['raid_eggs'][str(egg_level)]['hatchtime']):
            await channel.send("That's too long. Level {raidlevel} Raid Eggs "
                               "currently last no more than {hatchtime} minutes..."
                               .format(raidlevel=egg_level,
                                       hatchtime=raid_info['raid_eggs'][str(egg_level)]['hatchtime']))
            Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: raid expiration time too long")
            return
    else:
        await channel.send(
            embed=discord.Embed(colour=discord.Colour.orange(),
                                description='Could not determine hatch time. Using default of 60 minutes'))
    raid_details = ' '.join(raidegg_split)
    raid_details = raid_details.strip()
    if raid_details == '':
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), 
            description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. '
                        'Type **!help** raidegg for more info.'))
    rgx = '[^a-zA-Z0-9]'
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
    raid_details = raid_details.replace(str(weather), '', 1)
    if not weather:
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    if raid_details == '':
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient raid details provided.")
        return await channel.send(embed=discord.Embed(
            colour=discord.Colour.red(), 
            description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
    return await finish_raid_report(ctx, raid_details, None, egg_level, weather, raidexp)

async def finish_raid_report(self, ctx, raid_details, raid_pokemon, level, weather, raidexp):
    message = ctx.message
    channel = message.channel
    guild = channel.guild
    author = message.author
    timestamp = (message.created_at + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
    if raid_pokemon is None:
        raid_report = False
    else:
        raid_report = True
    report_regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
    gym = None
    gyms = get_gyms(guild.id, report_regions)
    other_region = False
    if gyms:
        gym = await location_match_prompt(channel, author.id, raid_details, gyms)
        if not gym:
            all_regions = list(guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
            gyms = get_gyms(guild.id, all_regions)
            gym = await location_match_prompt(channel, author.id, raid_details, gyms)
            if not gym:
                gym = await retry_gym_match(channel, author.id, raid_details, gyms)
                if not gym:
                    Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No gym found with name: {raid_details}.")
                    return await channel.send(embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description=f"I couldn't find a gym named '{raid_details}'. "
                        f"Try again using the exact gym name!"))
            if report_regions[0] != gym.region:
                other_region = True
        raid_channel_ids = get_existing_raid(guild, gym)
        if raid_channel_ids:
            raid_channel = Kyogre.get_channel(raid_channel_ids[0])
            try:
                raid_dict_entry = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
            except:
                return await message.add_reaction('\u274c')
            enabled =raid_helpers.raid_channels_enabled(guild, channel, guild_dict)
            if raid_dict_entry and not (raid_dict_entry['exp'] - 60 < datetime.datetime.now().timestamp()):
                msg = f"A raid has already been reported for {gym.name}."
                if enabled:
                    msg += f"\nCoordinate in the raid channel: {raid_channel.mention}"
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=msg))
            else:
                await message.add_reaction('✅')
                location = raid_dict_entry.get('address', 'unknown gym')
                if not enabled:
                    await channel.send(f"The egg at {location} has hatched into a {raid_pokemon.name} raid!")
                return await _eggtoraid(ctx, raid_pokemon.name.lower(), raid_channel)

        raid_details = gym.name
        raid_gmaps_link = gym.maps_url
        gym_regions = [gym.region]
    else:
        utilities_cog = Kyogre.cogs.get('Utilities')
        raid_gmaps_link = utilities_cog.create_gmaps_query(raid_details, channel, type="raid")
    if other_region:
        report_channels = await list_helpers.get_region_reporting_channels(guild, gym_regions[0], guild_dict)
        report_channel = Kyogre.get_channel(report_channels[0])
    else:
        report_channel = channel
    if raid_report:
        raid_channel = await create_raid_channel("raid", raid_pokemon, None, gym, channel)
    else:
        egg_info = raid_info['raid_eggs'][str(level)]
        egg_img = egg_info['egg_img']
        boss_list = []
        for entry in egg_info['pokemon']:
            p = Pokemon.get_pokemon(Kyogre, entry)
            boss_list.append(str(p) + ' (' + str(p.id) + ') ' + utils.types_to_str(guild, p.types, Kyogre.config))
        raid_channel = await create_raid_channel("egg", None, level, gym, channel)
    ow = raid_channel.overwrites_for(guild.default_role)
    ow.send_messages = True
    try:
        await raid_channel.set_permissions(guild.default_role, overwrite = ow)
    except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
        pass
    raid_dict = {
        'regions': gym_regions,
        'reportcity': report_channel.id,
        'trainer_dict': {},
        'exp': time.time() + (60 * raid_info['raid_eggs'][str(level)]['raidtime']),
        'manual_timer': False,
        'active': True,
        'reportchannel': channel.id,
        'address': raid_details,
        'type': 'raid' if raid_report else 'egg',
        'pokemon': raid_pokemon.name.lower() if raid_report else '',
        'egglevel': str(level) if not raid_report else '0',
        'moveset': 0,
        'weather': weather,
        'gym': gym,
        'reporter': author.id,
        'hatching': False,
        'short': None
    }
    raid_embed = discord.Embed(title='Click here for directions to the raid!',
                               url=raid_gmaps_link,
                               colour=guild.me.colour)
    enabled = raid_helpers.raid_channels_enabled(guild, channel, guild_dict)
    if gym:
        gym_info = f"**{raid_details}**\n{'_EX Eligible Gym_' if gym.ex_eligible else ''}"
        raid_embed.add_field(name='**Gym:**', value=gym_info, inline=False)
    cp_range = ''
    if raid_report:
        if enabled:
            if str(raid_pokemon).lower() in boss_cp_chart:
                cp_range = boss_cp_chart[str(raid_pokemon).lower()]
            weak_str = utils.types_to_str(guild, raid_pokemon.weak_against.keys(), Kyogre.config)
            raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                .format(pokemon=str(raid_pokemon), 
                        pokemonnumber=str(raid_pokemon.id), 
                        type=utils.types_to_str(guild, raid_pokemon.types, Kyogre.config), 
                        cprange='\n'+cp_range, 
                        inline=True))
            raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=weak_str))
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**')
            raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**')
        raid_img_url = raid_pokemon.img_url
        msg = entity_updates.build_raid_report_message(gym, 'raid', raid_pokemon.name, '0',
                                                       raidexp, raid_channel, guild_dict)
    else:
        if enabled:
            if len(egg_info['pokemon']) > 1:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist1}'
                                     .format(bosslist1='\n'.join(boss_list[::2])), inline=True)
                raid_embed.add_field(name='\u200b', value='{bosslist2}'
                                     .format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
            else:
                raid_embed.add_field(name='**Possible Bosses:**', value='{bosslist}'
                                     .format(bosslist=''.join(boss_list)), inline=True)
                raid_embed.add_field(name='\u200b', value='\u200b', inline=True)
            raid_embed.add_field(name='**Hatches:**', value='Set with **!timerset**', inline=True)
            raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**', inline=True)
        raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'\
            .format(str(egg_img))
        msg = entity_updates.build_raid_report_message(gym, 'egg', '', level, raidexp, raid_channel, guild_dict)
    if enabled:
        raid_embed.set_footer(text='Reported by {author} - {timestamp}'
                              .format(author=author.display_name, timestamp=timestamp),
                              icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
    raid_embed.set_thumbnail(url=raid_img_url)
    report_embed = raid_embed
    embed_indices = await embed_utils.get_embed_field_indices(report_embed)
    report_embed = await embed_utils.filter_fields_for_report_embed(report_embed, embed_indices)
    raidreport = await channel.send(content=msg, embed=report_embed)
    short_output_channel_id = guild_dict[guild.id]['configure_dict']['raid'].setdefault('short_output', {}).get(gym.region, None)
    if short_output_channel_id:
        send_level = 0
        if raid_pokemon:
            if raid_pokemon.raid_level:
                send_level = int(raid_pokemon.raid_level)
        else:
            if level:
                send_level = int(level)
        if send_level >= 4:
            short_output_channel = Kyogre.get_channel(short_output_channel_id)
            short_message = await short_output_channel.send(f"Raid Reported: {raid_channel.mention}")
            raid_dict['short'] = short_message.id
    await asyncio.sleep(1)
    raid_embed.add_field(name='**Tips:**', value='`!i` if interested\n`!c` if on the way\n`!h` '
                                                 'when you arrive\n`!x` to cancel your status\n'
                                                 "`!s` to signal lobby start\n`!shout` to ping raid party", inline=True)
    ctrsmessage_id = None
    if raid_report:
        raidmsg = "{pokemon} raid reported at {location_details} gym by {member} in {citychannel}. " \
                  "Coordinate here!\n\nClick the question mark reaction" \
                  " to get help on the commands that work in this channel."\
            .format(pokemon=str(raid_pokemon), member=author.display_name,
                    citychannel=channel.mention, location_details=raid_details)
        if str(level) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
            try:
                ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
                ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                          "Update weather with **!weather**. If you know the moveset of the boss, " \
                          "you can react to this message with the matching emoji and I will update the counters."
                ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
                ctrsmessage_id = ctrsmessage.id
                await ctrsmessage.pin()
                for moveset in ctrs_dict:
                    await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
                    await asyncio.sleep(0.25)
            except:
                ctrs_dict = {}
                ctrsmessage_id = None
        else:
            ctrs_dict = {}
            ctrsmessage_id = None
        raid_reports = guild_dict[guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                           .setdefault(author.id, {}).setdefault('raid_reports', 0) + 1
        guild_dict[guild.id]['trainers'][gym.region][author.id]['raid_reports'] = raid_reports
        raid_details = {'pokemon': raid_pokemon,
                        'tier': raid_pokemon.raid_level,
                        'ex-eligible': gym.ex_eligible if gym else False,
                        'location': raid_details,
                        'regions': gym_regions}
    else:
        raidmsg = "Level {level} raid egg reported at {location_details} gym by {member} in {citychannel}. " \
                  "Coordinate here!\n\nClick the question mark reaction to get help " \
                  "on the commands that work in this channel."\
            .format(level=level, member=author.display_name, citychannel=channel.mention, location_details=raid_details)
        egg_reports = guild_dict[guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                          .setdefault(author.id, {}).setdefault('egg_reports', 0) + 1
        guild_dict[guild.id]['trainers'][gym.region][author.id]['egg_reports'] = egg_reports
        raid_details = {'tier': level,
                        'ex-eligible': gym.ex_eligible if gym else False,
                        'location': raid_details,
                        'regions': gym_regions}
    raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
    await raidmessage.add_reaction('\u2754')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await raidmessage.add_reaction('🚫')
    await asyncio.sleep(0.25)
    await raidmessage.pin()
    raid_dict['raidmessage'] = raidmessage.id
    raid_dict['raidreport'] = raidreport.id
    raid_dict['raidcityreport'] = None
    if ctrsmessage_id is not None:
        raid_dict['ctrsmessage'] = ctrsmessage_id
        raid_dict['ctrs_dict'] = ctrs_dict
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict
    if raidexp is not False:
        await _timerset(raid_channel, raidexp, False)
    else:
        await raid_channel.send(content='Hey {member}, if you can, set the time left on the raid using '
                                        '**!timerset <minutes>** so others can check it with **!timer**.'
                                .format(member=author.mention))
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild, 'raid', edit=False, regions=gym_regions)
    subscriptions_cog = Kyogre.cogs.get('Subscriptions')
    if enabled:
        send_channel = raid_channel
    else:
        send_channel = subscriptions_cog.get_region_list_channel(guild, gym.region, 'raid')
        if send_channel is None:
            send_channel = channel
    await subscriptions_cog.send_notifications_async('raid', raid_details, send_channel, [author.id])
    await raidreport.add_reaction('\u270f')
    await asyncio.sleep(0.25)
    await raidreport.add_reaction('🚫')
    await asyncio.sleep(0.25)
    if other_region:
        region_command_channels = guild_dict[guild.id]['configure_dict']['regions'].setdefault('command_channels', [])
        channel_text = ''
        if len(region_command_channels) > 0:
            channel_text = ' in '
            for c in region_command_channels:
                channel_text += Kyogre.get_channel(c).mention
        region_msg = f'Hey {author.mention}, **{gym.name}** is in the **{gym_regions[0].capitalize()}** ' \
            f'region. Your report was successful, but please consider joining that region{channel_text} ' \
            f'to report raids at this gym in the future'
        embed = discord.Embed(colour=discord.Colour.gold(), description=region_msg)
        embed.set_footer(text=f"If you believe this region assignment is incorrect, "
        f"please contact {guild.owner.display_name}")
        await channel.send(embed=embed)
        raidcityreport = await report_channel.send(content=msg, embed=report_embed)
        raid_dict['raidcityreport'] = raidcityreport.id
        await raidcityreport.add_reaction('\u270f')
        await asyncio.sleep(0.25)
        await raidcityreport.add_reaction('🚫')
        await asyncio.sleep(0.25)
    if not raid_report:
        if len(raid_info['raid_eggs'][str(level)]['pokemon']) == 1:
            await _eggassume('assume ' + raid_info['raid_eggs'][str(level)]['pokemon'][0], raid_channel)
        elif level == "5" and guild_dict[guild.id]['configure_dict']['settings']\
                .get('regional', None) in raid_info['raid_eggs']["5"]['pokemon']:
            await _eggassume('assume ' + guild_dict[guild.id]['configure_dict']['settings']['regional'],
                             raid_channel)
    event_loop.create_task(expiry_check(raid_channel))
    return raid_channel

async def _eggassume(self, args, raid_channel):
    guild = raid_channel.guild
    eggdetails = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
    report_channel = Kyogre.get_channel(eggdetails['reportchannel'])
    egglevel = eggdetails['egglevel']
    manual_timer = eggdetails['manual_timer']
    weather = eggdetails.get('weather', None)
    egg_report = await report_channel.fetch_message(eggdetails['raidreport'])
    raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
    entered_raid = re.sub('[\\@]', '', args.lower().lstrip('assume').lstrip(' '))
    raid_pokemon = Pokemon.get_pokemon(Kyogre, entered_raid)
    if not raid_pokemon:
        return
    if not raid_pokemon.is_raid:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: {raid_pokemon.name} reported, but not in raid data.")
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {raid_pokemon.name} does not appear in raids!'))
    elif raid_pokemon.name.lower() not in raid_info['raid_eggs'][egglevel]['pokemon']:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: {raid_pokemon.name} reported, but not in raid data for this raid level.")
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {raid_pokemon.name} does not hatch from level {egglevel} raid eggs!'))
    eggdetails['pokemon'] = raid_pokemon.name
    oldembed = raid_message.embeds[0]
    raid_gmaps_link = oldembed.url
    enabled = raid_helpers.raid_channels_enabled(guild, raid_channel, guild_dict)
    if enabled:
        embed_indices = await embed_utils.get_embed_field_indices(oldembed)
        raid_embed = discord.Embed(title='Click here for directions to the raid!',
                                   url=raid_gmaps_link,
                                   colour=guild.me.colour)
        raid_embed.add_field(name=(oldembed.fields[embed_indices["gym"]].name),
                             value=oldembed.fields[embed_indices["gym"]].value, inline=True)
        cp_range = ''
        if raid_pokemon.name.lower() in boss_cp_chart:
            cp_range = boss_cp_chart[raid_pokemon.name.lower()]
        raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                             .format(pokemon=raid_pokemon.name, pokemonnumber=str(raid_pokemon.id),
                                     type=utils.types_to_str(guild, raid_pokemon.types, Kyogre.config),
                                     cprange='\n'+cp_range, inline=True))
        raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                             .format(weakness_list=utils.types_to_str(guild,
                                                                      raid_pokemon.weak_against, Kyogre.config)))
        if embed_indices["next"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["next"]].name),
                                 value=oldembed.fields[embed_indices["next"]].value, inline=True)
        if embed_indices["hatch"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["hatch"]].name),
                                 value=oldembed.fields[embed_indices["hatch"]].value, inline=True)
        if embed_indices["tips"] is not None:
            raid_embed.add_field(name=(oldembed.fields[embed_indices["tips"]].name),
                                 value=oldembed.fields[embed_indices["tips"]].value, inline=True)

        raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
        raid_embed.set_thumbnail(url=raid_pokemon.img_url)
        try:
            await raid_message.edit(new_content=raid_message.content, embed=raid_embed, content=raid_message.content)
            raid_message = raid_message.id
        except discord.errors.NotFound:
            raid_message = None
        try:
            embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
            raid_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices)
            await egg_report.edit(new_content=egg_report.content, embed=raid_embed, content=egg_report.content)
            egg_report = egg_report.id
        except discord.errors.NotFound:
            egg_report = None
        if eggdetails.get('raidcityreport', None) is not None:
            report_city_channel = Kyogre.get_channel(eggdetails['reportcity'])
            city_report = await report_city_channel.fetch_message(eggdetails['raidcityreport'])
            try:
                await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
                city_report = city_report.id
            except discord.errors.NotFound:
                city_report = None
    if str(egglevel) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, raid_pokemon, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                  "Update weather with **!weather**. If you know the moveset of the boss, " \
                  "you can react to this message with the matching emoji and I will update the counters."
        ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
        ctrsmessage_id = ctrsmessage.id
        await ctrsmessage.pin()
        for moveset in ctrs_dict:
            await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
            await asyncio.sleep(0.25)
    else:
        ctrs_dict = {}
        ctrsmessage_id = eggdetails.get('ctrsmessage', None)
    eggdetails['ctrs_dict'] = ctrs_dict
    eggdetails['ctrsmessage'] = ctrsmessage_id
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = eggdetails
    return

async def _eggtoraid(self, ctx, entered_raid, raid_channel, author=None):
    guild = raid_channel.guild
    pkmn = Pokemon.get_pokemon(Kyogre, entered_raid)
    if not pkmn:
        return
    eggdetails = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
    egglevel = eggdetails['egglevel']
    if egglevel == "0":
        egglevel = pkmn.raid_level
    try:
        reportcitychannel = Kyogre.get_channel(eggdetails['reportcity'])
        reportcity = reportcitychannel.name
    except (discord.errors.NotFound, AttributeError):
        reportcity = None
    manual_timer = eggdetails['manual_timer']
    trainer_dict = eggdetails['trainer_dict']
    egg_address = eggdetails['address']
    weather = eggdetails.get('weather', None)
    try:
        gym = eggdetails['gym']
    except:
        gym = None
    try:
        reporter = eggdetails['reporter']
    except:
        reporter = None
    try:
        reportchannel = eggdetails['reportchannel']
    except:
        reportchannel = None
    if reportchannel is not None:
        reportchannel = Kyogre.get_channel(reportchannel)
    raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
    if not reportcitychannel:
        async for message in raid_channel.history(limit=500, reverse=True):
            if message.author.id == guild.me.id:
                c = 'Coordinate here'
                if c in message.content:
                    reportcitychannel = message.raw_channel_mentions[0]
                    break
    if reportchannel:
        try:
            egg_report = await reportchannel.fetch_message(eggdetails['raidreport'])
        except (discord.errors.NotFound, discord.errors.HTTPException):
            egg_report = None
    if reportcitychannel:
        try:
            city_report = await reportcitychannel.fetch_message(eggdetails.get('raidcityreport', 0))
        except (discord.errors.NotFound, discord.errors.HTTPException):
            city_report = None
    starttime = eggdetails.get('starttime',None)
    duplicate = eggdetails.get('duplicate',0)
    archive = eggdetails.get('archive',False)
    meetup = eggdetails.get('meetup',{})
    raid_match = pkmn.is_raid
    if not raid_match:
        Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: {raid_pokemon.name} reported, but not in raid data.")
        return await raid_channel.send(embed=discord.Embed(
            colour=discord.Colour.red(),
            description=f'The Pokemon {pkmn.full_name} does not appear in raids!'))
    if (egglevel.isdigit() and int(egglevel) > 0) or egglevel == 'EX':
        raidexp = eggdetails['exp'] + 60 * raid_info['raid_eggs'][str(egglevel)]['raidtime']
    else:
        raidexp = eggdetails['exp']
    end = datetime.datetime.utcfromtimestamp(raidexp) + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    oldembed = raid_message.embeds[0]
    raid_gmaps_link = oldembed.url
    enabled = True
    if guild_dict[guild.id].get('raidchannel_dict', {}).get(raid_channel.id, {}).get('meetup', {}):
        guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['type'] = 'exraid'
        guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['egglevel'] = '0'
        await raid_channel.send("The event has started!", embed=oldembed)
        await raid_channel.edit(topic="")
        event_loop.create_task(expiry_check(raid_channel))
        return
    if egglevel.isdigit():
        hatchtype = 'raid'
        raidreportcontent = 'The egg has hatched into a {pokemon} raid at {location_details} gym.'\
            .format(pokemon=entered_raid.capitalize(), location_details=egg_address)
        enabled = raid_helpers.raid_channels_enabled(guild, raid_channel, guild_dict)
        if enabled:
            raidreportcontent += 'Coordinate in the raid channel: {raid_channel}'\
                .format(raid_channel=raid_channel.mention)
        raidmsg = "The egg reported in {citychannel} hatched into a {pokemon} raid! Details: {location_details}. " \
                  "Coordinate here!\n\nClick the question mark react to get help on the commands that work in here." \
                  "\n\nThis channel will be deleted five minutes after the timer expires."\
            .format(citychannel=reportcitychannel.mention,
                    pokemon=entered_raid.capitalize(),
                    location_details=egg_address)
    elif egglevel == 'EX':
        hatchtype = 'exraid'
        if guild_dict[guild.id]['configure_dict']['invite']['enabled']:
            invitemsgstr = "Use the **!invite** command to gain access and coordinate"
            invitemsgstr2 = " after using **!invite** to gain access"
        else:
            invitemsgstr = "Coordinate"
            invitemsgstr2 = ""
        raidreportcontent = 'The EX egg has hatched into a {pokemon} raid! Details: {location_details}. ' \
                            '{invitemsgstr} coordinate in {raid_channel}'\
            .format(pokemon=entered_raid.capitalize(),
                    location_details=egg_address,
                    invitemsgstr=invitemsgstr,
                    raid_channel=raid_channel.mention)
        raidmsg = "{pokemon} EX raid reported in {citychannel}! Details: {location_details}. Coordinate here" \
                  "{invitemsgstr2}!\n\nClick the question mark reaction to get help on the commands " \
                  "that work in here.\n\nThis channel will be deleted five minutes after the timer expires."\
            .format(pokemon=entered_raid.capitalize(),
                    citychannel=reportcitychannel.mention,
                    location_details=egg_address,
                    invitemsgstr2=invitemsgstr2)
    raid_channel_name = utils.sanitize_name(pkmn.name.lower() + '_' + egg_address)[:32]
    embed_indices = await embed_utils.get_embed_field_indices(oldembed)
    raid_embed = discord.Embed(title='Click here for directions to the raid!',
                               url=raid_gmaps_link,
                               colour=guild.me.colour)
    cp_range = ''
    if pkmn.name.lower() in boss_cp_chart:
        cp_range = boss_cp_chart[pkmn.name.lower()]
    raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                         .format(pokemon=pkmn.name, pokemonnumber=str(pkmn.id),
                                 type=utils.types_to_str(guild, pkmn.types, Kyogre.config),
                                 cprange='\n'+cp_range, inline=True))
    raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                         .format(weakness_list=utils.types_to_str(guild, pkmn.weak_against, Kyogre.config))
                         , inline=True)
    raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
    raid_embed.set_thumbnail(url=pkmn.img_url)
    await raid_channel.edit(name=raid_channel_name, topic=end.strftime('Ends at %I:%M %p (%H:%M)'))
    trainer_list = []
    trainer_dict = copy.deepcopy(guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'])
    for trainer in trainer_dict.keys():
        try:
            user = guild.get_member(trainer)
        except (discord.errors.NotFound, AttributeError):
            continue
        if (trainer_dict[trainer].get('interest', None)) \
                and (entered_raid.lower() not in trainer_dict[trainer]['interest']):
            guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['status'] =\
                {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0}
            guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['party'] =\
                {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
            guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['count'] = 1
        else:
            guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['interest'] = []
    await asyncio.sleep(1)
    trainer_count = list_helpers.determine_trainer_count(trainer_dict)
    status_embed = list_helpers.build_status_embed(guild, Kyogre, trainer_count)
    for trainer in trainer_dict.keys():
        if (trainer_dict[trainer]['status']['maybe']) \
                or (trainer_dict[trainer]['status']['coming']) \
                or (trainer_dict[trainer]['status']['here']):
            try:
                user = guild.get_member(trainer)
                trainer_list.append(user.mention)
            except (discord.errors.NotFound, AttributeError):
                continue
    trainers = ' ' + ', '.join(trainer_list) if trainer_list else ''
    await raid_channel.send(content="Trainers{trainer}: The raid egg has just hatched into a {pokemon} raid!"
                            .format(trainer=trainers, pokemon=entered_raid.title()), embed=raid_embed)
    raid_details = {'pokemon': pkmn, 'tier': pkmn.raid_level,
                    'ex-eligible': False if eggdetails['gym'] is None else eggdetails['gym'].ex_eligible,
                    'location': eggdetails['address'], 'regions': eggdetails['regions'],
                    'hatching': True}
    new_status = None
    subscriptions_cog = Kyogre.cogs.get('Subscriptions')
    if enabled:
        last_status = guild_dict[guild.id]['raidchannel_dict'][raid_channel.id].get('last_status', None)
        if last_status is not None:
            try:
                last = await raid_channel.fetch_message(last_status)
                await last.delete()
            except:
                pass
        if status_embed is not None:
            new_status = await raid_channel.send(embed=status_embed)
            guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['last_status'] = new_status.id
    if enabled:
        send_channel = raid_channel
    else:
        send_channel = subscriptions_cog.get_region_list_channel(guild, gym.region, 'raid')
        if send_channel is None:
            send_channel = reportchannel
    await subscriptions_cog.send_notifications_async('raid', raid_details, send_channel,
                                                     [author] if author else [])
    if embed_indices["gym"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["gym"]].name,
                             value=oldembed.fields[embed_indices["gym"]].value, inline=True)
    if embed_indices["next"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["next"]].name,
                             value=oldembed.fields[embed_indices["next"]].value, inline=True)
    if meetup:
        raid_embed.add_field(name=oldembed.fields[3].name, value=end.strftime('%I:%M %p (%H:%M)'), inline=True)
    else:
        raid_embed.add_field(name='**Expires:**', value=end.strftime(' %I:%M %p (%H:%M)'), inline=True)
    if embed_indices["tips"] is not None:
        raid_embed.add_field(name=oldembed.fields[embed_indices["tips"]].name,
                             value=oldembed.fields[embed_indices["tips"]].value, inline=True)
    for field in oldembed.fields:
        m = 'maybe'
        c = 'coming'
        h = 'here'
        if (m in field.name.lower()) or (c in field.name.lower()) or (h in field.name.lower()):
            raid_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    try:
        await raid_message.edit(new_content=raidmsg, embed=raid_embed, content=raidmsg)
        raid_message = raid_message.id
    except (discord.errors.NotFound, AttributeError):
        raid_message = None
    try:
        embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
        report_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices)
        await egg_report.edit(new_content=raidreportcontent, embed=report_embed, content=raidreportcontent)
        egg_report = egg_report.id
    except (discord.errors.NotFound, AttributeError):
        egg_report = None
    if eggdetails.get('raidcityreport', None) is not None:
        try:
            await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
        except (discord.errors.NotFound, AttributeError):
            city_report = None
    if str(egglevel) in guild_dict[guild.id]['configure_dict']['counters']['auto_levels'] \
            and not eggdetails.get('pokemon', None):
        ctrs_dict = await counters_helpers._get_generic_counters(Kyogre, guild, pkmn, weather)
        ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                  "Update weather with **!weather**. If you know the moveset of the boss, you can react " \
                  "to this message with the matching emoji and I will update the counters."
        ctrsmessage = await raid_channel.send(content=ctrsmsg,embed=ctrs_dict[0]['embed'])
        ctrsmessage_id = ctrsmessage.id
        await ctrsmessage.pin()
        for moveset in ctrs_dict:
            await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
            await asyncio.sleep(0.25)
    else:
        ctrs_dict = eggdetails.get('ctrs_dict', {})
        ctrsmessage_id = eggdetails.get('ctrsmessage', None)
    regions = eggdetails.get('regions', None)
    short_id = eggdetails.get('short', None)
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = {
        'regions': regions,
        'reportcity': reportcitychannel.id,
        'trainer_dict': trainer_dict,
        'exp': raidexp,
        'manual_timer': manual_timer,
        'active': True,
        'raidmessage': raid_message,
        'raidreport': egg_report,
        'reportchannel': reportchannel.id,
        'address': egg_address,
        'type': hatchtype,
        'pokemon': pkmn.name.lower(),
        'egglevel': '0',
        'ctrs_dict': ctrs_dict,
        'ctrsmessage': ctrsmessage_id,
        'weather': weather,
        'moveset': 0,
        'gym': gym,
        'reporter': reporter,
        'last_status': new_status.id if new_status is not None else None,
        'short': short_id
    }
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['starttime'] = starttime
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['duplicate'] = duplicate
    guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['archive'] = archive
    if author:
        raid_reports = guild_dict[guild.id].setdefault('trainers',{}).setdefault(regions[0], {})\
                           .setdefault(author.id,{}).setdefault('raid_reports',0) + 1
        guild_dict[guild.id]['trainers'][regions[0]][author.id]['raid_reports'] = raid_reports
        await list_helpers._edit_party(ctx, Kyogre, guild_dict, raid_info, raid_channel, author)
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild,
                                               'raid', edit=False, regions=regions)
    await asyncio.sleep(1)
    event_loop.create_task(expiry_check(raid_channel))


@commands.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def clearstatus(self, ctx):
    """Clears raid channel status lists.

    Usage: !clearstatus
    Only usable by admins."""
    msg = "Are you sure you want to clear all status for this raid? " \
          "Everybody will have to RSVP again. If you are wanting to " \
          "clear one user's status, use `!setstatus <user> cancel`"
    question = await ctx.channel.send(msg)
    try:
        timeout = False
        res, reactuser = await utils.simple_ask(Kyogre, question, ctx.message.channel, ctx.message.author.id)
    except TypeError:
        timeout = True
    await question.delete()
    if timeout or res.emoji == '❎':
        return
    elif res.emoji == '✅':
        pass
    else:
        return
    try:
        guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'] = {}
        await ctx.channel.send('Raid status lists have been cleared!')
    except KeyError:
        pass

@commands.command()
@commands.has_permissions(manage_channels=True)
@checks.raidchannel()
async def setstatus(self, ctx, member: discord.Member, status,*, status_counts: str = ''):
    """Changes raid channel status lists.

    Usage: !setstatus <user> <status> [count]
    User can be a mention or ID number. Status can be maybeinterested/i, coming/c, here/h, or cancel/x
    Only usable by admins."""
    valid_status_list = ['interested', 'i', 'maybe', 'coming', 'c', 'here', 'h', 'cancel', 'x']
    if status not in valid_status_list:
        await ctx.message.channel.send("{status} is not a valid status!".format(status=status))
        return
    ctx.message.author = member
    ctx.message.content = "{}{} {}".format(ctx.prefix, status, status_counts)
    await ctx.bot.process_commands(ctx.message)

@staticmethod
def get_existing_raid(guild, location, only_ex = False):
    """returns a list of channel ids for raids reported at the location provided"""
    report_dict = {k: v for k, v in guild_dict[guild.id]['raidchannel_dict'].items()
                   if ((v.get('egglevel', '').lower() != 'ex')
                   if not only_ex else (v.get('egglevel', '').lower() == 'ex'))}
    def matches_existing(report):
        # ignore meetups
        if report.get('meetup', {}):
            return False
        return report.get('gym', None) and report['gym'].name.lower() == location.name.lower()
    return [channel_id for channel_id, report in report_dict.items() if matches_existing(report)]

async def print_raid_timer(self, channel):
    guild = channel.guild
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(
        seconds=guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - time.time())
    timerstr = ' '
    if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup',{}):
        end = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']['end']
        start = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']['start']
        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
            if start:
                timerstr += "This event will start at {expiry_time}"\
                    .format(expiry_time=start.strftime('%I:%M %p (%H:%M)'))
            else:
                timerstr += "Nobody has told me a start time! Set it with **!starttime**"
            if end:
                timerstr += " | This event will end at {expiry_time}"\
                    .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid':
            if end:
                timerstr += "This event will end at {expiry_time}"\
                    .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
            else:
                timerstr += "Nobody has told me a end time! Set it with **!timerset**"
        return timerstr
    if guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
        raidtype = 'egg'
        raidaction = 'hatch'
    else:
        raidtype = 'raid'
        raidaction = 'end'
    if not guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
        timerstr += "This {raidtype}'s timer has already expired as of {expiry_time}!"\
            .format(raidtype=raidtype, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    elif (guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel'] == 'EX') \
            or (guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid'):
        if guild_dict[guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
            timerstr += 'This {raidtype} will {raidaction} on {expiry}!'\
                .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
        else:
            timerstr += "No one told me when the {raidtype} will {raidaction}, " \
                        "so I'm assuming it will {raidaction} on {expiry}!"\
                .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
    elif guild_dict[guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
        timerstr += 'This {raidtype} will {raidaction} at {expiry_time}!'\
            .format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    else:
        timerstr += "No one told me when the {raidtype} will {raidaction}, " \
                    "so I'm assuming it will {raidaction} at {expiry_time}!"\
            .format(raidtype=raidtype, raidaction=raidaction, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
    return timerstr

@commands.command(aliases=['ts'])
@checks.raidchannel()
async def timerset(self, ctx, *, timer):
    """Set the remaining duration on a raid.
    
    **Usage**: `!timerset/ts [HH:MM] or [minutes]`
    If using the HH:MM format, provide the time the egg hatches or raid expires
    Otherwise, provide the number of minutes until the egg hatches or raid expires.
    **Examples**: `!timerset 10:32`  `!ts 20`"""
    message = ctx.message
    channel = message.channel
    guild = message.guild
    author = message.author
    hourminute = False
    type = guild_dict[guild.id]['raidchannel_dict'][channel.id]['type']
    if (not checks.check_exraidchannel(ctx)) and not (checks.check_meetupchannel(ctx)):
        if type == 'egg':
            raidlevel = guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel']
            raidtype = 'Raid Egg'
            maxtime = raid_info['raid_eggs'][raidlevel]['hatchtime']
        else:
            raidlevel = utils.get_level(Kyogre, guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon'])
            raidtype = 'Raid'
            maxtime = raid_info['raid_eggs'][raidlevel]['raidtime']
        raidexp = await utils.time_to_minute_count(guild_dict, channel, timer)
        if raidexp is False:
            return
        if _timercheck(raidexp, maxtime):
            Kyogre.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: raid expiration time too long")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"That's too long. Level {raidlevel} {raidtype.capitalize()}s "
                f"currently last no more than {maxtime} minutes."))
        await _timerset(channel, raidexp)
    if checks.check_exraidchannel(ctx):
        if checks.check_eggchannel(ctx) or checks.check_meetupchannel(ctx):
            now = datetime.datetime.utcnow() + datetime.timedelta(
                hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
            timer_split = timer.lower().split()
            try:
                start = dateparser.parse(' '.join(timer_split).lower(), settings={'DATE_ORDER': 'MDY'})
            except:
                if ('am' in ' '.join(timer_split).lower()) or ('pm' in ' '.join(timer_split).lower()):
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year),
                                                           '%m/%d %I:%M %p %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset**"
                                           " to match this format: **MM/DD HH:MM AM/PM** "
                                           "(You can also omit AM/PM and use 24-hour time!)")
                        return
                else:
                    try:
                        start = datetime.datetime.strptime((' '.join(timer_split) + ' ') + str(now.year),
                                                           '%m/%d %H:%M %Y')
                        if start.month < now.month:
                            start = start.replace(year=now.year + 1)
                    except ValueError:
                        await channel.send("Your timer wasn't formatted correctly. Change your **!timerset** to "
                                           "match this format: **MM/DD HH:MM AM/PM** "
                                           "(You can also omit AM/PM and use 24-hour time!)")
                        return
            if checks.check_meetupchannel(ctx):
                starttime = guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('start', False)
                if starttime and start < starttime:
                    await channel.send('Please enter a time after your start time.')
                    return
            diff = start - now
            total = diff.total_seconds() / 60
            if now <= start:
                await _timerset(channel, total)
            elif now > start:
                await channel.send('Please enter a time in the future.')
        else:
            await channel.send("Timerset isn't supported for EX Raids after they have hatched.")

@staticmethod
def _timercheck(time, maxtime):
    return time > maxtime

async def _timerset(self, raidchannel, exptime, print=True):
    guild = raidchannel.guild
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    end = now + datetime.timedelta(minutes=exptime)
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][raidchannel.id]
    raid_dict['exp'] = time.time() + (exptime * 60)
    if not raid_dict['active']:
        await raidchannel.send('The channel has been reactivated.')
    raid_dict['active'] = True
    raid_dict['manual_timer'] = True
    topicstr = ''
    if raid_dict.get('meetup',{}):
        raid_dict['meetup']['end'] = end
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = end.strftime('%I:%M %p (%H:%M)')
    elif raid_dict['type'] == 'egg':
        egglevel = raid_dict['egglevel']
        hatch = end
        end = hatch + datetime.timedelta(minutes=raid_info['raid_eggs'][egglevel]['raidtime'])
        topicstr += 'Hatches at {expiry}'.format(expiry=hatch.strftime('%I:%M %p (%H:%M) | '))
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = hatch.strftime('%I:%M %p (%H:%M)')
    else:
        topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
        endtime = end.strftime('%I:%M %p (%H:%M)')
    if print:
        timerstr = await print_raid_timer(raidchannel)
        await raidchannel.send(timerstr)
    await raidchannel.edit(topic=topicstr)
    report_channel = Kyogre.get_channel(raid_dict['reportchannel'])
    raidmsg = await raidchannel.fetch_message(raid_dict['raidmessage'])
    reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
    for message in [raidmsg, reportmsg]:
        embed = message.embeds[0]
        embed_indices = await embed_utils.get_embed_field_indices(embed)
        if raid_dict['type'] == "raid":
            type = "expires"
        else:
            type = "hatch"
        if embed_indices[type] is not None:
            embed.set_field_at(embed_indices[type], name=embed.fields[embed_indices[type]].name, value=endtime)
        else:
            embed.add_field(name='**Expires:**' if type == 'expires' else '**Hatches:**', value=endtime)
        if message == raidmsg:
            try:
                await message.edit(content=message.content,embed=embed)
            except discord.errors.NotFound:
                pass
        else:
            embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices)
            try:
                await message.edit(content=message.content,embed=embed)
            except discord.errors.NotFound:
                pass
            if raid_dict.get('raidcityreport', None) is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=embed, content=city_report.content)
                    city_report = city_report.id
                except:
                    pass
    await list_helpers.update_listing_channels(Kyogre, guild_dict, guild,
                                               'raid', edit=True, regions=raid_dict.get('regions', None))
    Kyogre.get_channel(raidchannel.id)

@commands.command()
@checks.raidchannel()
async def timer(self, ctx):
    """Have Kyogre resend the expire time message for a raid.

    **Usage**: `!timer`
    The expiry time should have been previously set with `!timerset`."""
    timerstr = await print_raid_timer(ctx.channel)
    await ctx.channel.send(timerstr)

@commands.command(aliases=['st'])
async def starttime(self, ctx, *, start_time=""):
    """Set a time for a group to start a raid

    **Usage**: `!starttime/st [HH:MM] or [minutes]`
    If using the HH:MM format, provide the time the group will start
    Otherwise, provide the number of minutes until the group will start
    **Examples**: `!starttime 10:32`  `!st 20`

    Only one start time is allowed at a time and is visible in `!list` output. 
    Cleared with `!starting.`"""
    message = ctx.message
    guild = message.guild
    channel = message.channel
    author = message.author
    raid_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    now = datetime.datetime.utcnow() + datetime.timedelta(
        hours=guild_dict[guild.id]['configure_dict']['settings']['offset'])
    if start_time:
        exp_minutes = await utils.time_to_minute_count(guild_dict, channel, start_time)
        if not exp_minutes:
            return
        if raid_dict['type'] == 'egg':
            egglevel = raid_dict['egglevel']
            mintime = (raid_dict['exp'] - time.time()) / 60
            maxtime = mintime + raid_info['raid_eggs'][egglevel]['raidtime']
        elif (raid_dict['type'] == 'raid') or (raid_dict['type'] == 'exraid'):
            mintime = 0
            maxtime = (raid_dict['exp'] - time.time()) / 60
        alreadyset = raid_dict.get('starttime', False)
        if exp_minutes > maxtime:
            return await channel.send('The raid will be over before that....')
        if exp_minutes < 0:
            return await channel.send('Please enter a time in the future.')
        if exp_minutes < mintime:
            return await channel.send('The egg will not hatch by then!')
        if alreadyset:
            query_change = await channel.send('There is already a start time of **{start}**! Do you want to change it?'
                                              .format(start=alreadyset.strftime('%I:%M %p (%H:%M)')))
            try:
                timeout = False
                res, reactuser = await utils.simple_ask(Kyogre, query_change, channel, author.id)
            except TypeError:
                timeout = True
            if timeout or res.emoji == '❎':
                await query_change.delete()
                confirmation = await channel.send('Start time change cancelled.')
                await asyncio.sleep(10)
                await confirmation.delete()
                return
            elif res.emoji == '✅':
                await query_change.delete()
                if exp_minutes > 0:
                    timeset = True
            else:
                return
        start = datetime.datetime.utcnow() + datetime.timedelta(
            hours=guild_dict[guild.id]['configure_dict']['settings']['offset'],
            minutes=exp_minutes)
        if (exp_minutes and start > now) or timeset:
            raid_dict['starttime'] = start
            nextgroup = start.strftime('%I:%M %p (%H:%M)')
            if raid_dict.get('meetup',{}):
                nextgroup = start.strftime('%I:%M %p (%H:%M)')
            await channel.send('The current start time has been set to: **{starttime}**'.format(starttime=nextgroup))
            report_channel = Kyogre.get_channel(raid_dict['reportchannel'])
            raidmsg = await channel.fetch_message(raid_dict['raidmessage'])
            reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
            embed = raidmsg.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(embed)
            embed.set_field_at(embed_indices['next'],
                               name=embed.fields[embed_indices['next']].name, value=nextgroup, inline=True)
            try:
                await raidmsg.edit(content=raidmsg.content,embed=embed)
            except discord.errors.NotFound:
                pass
            try:
                embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices)
                await reportmsg.edit(content=reportmsg.content,embed=embed)
            except discord.errors.NotFound:
                pass
            if raid_dict.get('raidcityreport', None) is not None:
                report_city_channel = Kyogre.get_channel(raid_dict['reportcity'])
                city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=embed, content=city_report.content)
                except discord.errors.NotFound:
                    pass
            return
    else:
        starttime = raid_dict.get('starttime', None)
        if starttime and starttime < now:
            raid_dict['starttime'] = None
            starttime = None
        if starttime:
            await channel.send('The current start time is: **{starttime}**'
                               .format(starttime=starttime.strftime('%I:%M %p (%H:%M)')))
        elif not starttime:
            await channel.send('No start time has been set, set one with **!starttime HH:MM AM/PM**! '
                               '(You can also omit AM/PM and use 24-hour time!)')

@commands.group(case_insensitive=True)
@checks.activechannel()
async def location(self, ctx):
    """Get raid location.

    Usage: !location
    Works only in raid channels. Gives the raid location link."""
    if ctx.invoked_subcommand == None:
        message = ctx.message
        guild = message.guild
        channel = message.channel
        rc_d = guild_dict[guild.id]['raidchannel_dict']
        raidmsg = await channel.fetch_message(rc_d[channel.id]['raidmessage'])
        location = rc_d[channel.id]['address']
        report_channel = Kyogre.get_channel(rc_d[channel.id]['reportcity'])
        oldembed = raidmsg.embeds[0]
        locurl = oldembed.url
        newembed = discord.Embed(title=oldembed.title, url=locurl, colour=guild.me.colour)
        for field in oldembed.fields:
            newembed.add_field(name=field.name, value=field.value, inline=field.inline)
        newembed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
        newembed.set_thumbnail(url=oldembed.thumbnail.url)
        locationmsg = await channel.send(content="Here's the current location for the raid!\nDetails: {location}"
                                         .format(location=location), embed=newembed)
        await asyncio.sleep(60)
        await locationmsg.delete()

@location.command()
@checks.activechannel()
async def new(self, ctx, *, content):
    """Change raid location.

    Usage: !location new <gym name>
    Works only in raid channels. Updates the gym at which the raid is located."""
    message = ctx.message
    channel = message.channel
    location_split = content.lower().split()
    if len(location_split) < 1:
        await channel.send("We're missing the new location details! Usage: **!location new <new address>**")
        return
    else:
        report_channel = Kyogre.get_channel(guild_dict[message.guild.id]['raidchannel_dict'][channel.id]['reportcity'])
        if not report_channel:
            async for m in channel.history(limit=500, reverse=True):
                if m.author.id == message.guild.me.id:
                    c = 'Coordinate here'
                    if c in m.content:
                        report_channel = m.raw_channel_mentions[0]
                        break
        details = ' '.join(location_split)
        config_dict = guild_dict[message.guild.id]['configure_dict']
        regions = raid_helpers.get_channel_regions(channel, 'raid', guild_dict)
        gym = None
        gyms = get_gyms(message.guild.id, regions)
        if gyms:
            gym = await location_match_prompt(channel, message.author.id, details, gyms)
            if not gym:
                return await channel.send("I couldn't find a gym named '{0}'. Try again using the exact gym name!"
                                          .format(details))
            details = gym.name
            newloc = gym.maps_url
            regions = [gym.region]
        else:
            utilities_cog = Kyogre.cogs.get('Utilities')
            newloc = utilities_cog.create_gmaps_query(details, report_channel, type="raid")
        await entity_updates.update_raid_location(Kyogre, guild_dict, message, report_channel, channel, gym)
        return

@commands.command()
@checks.activechannel()
async def duplicate(self, ctx):
    """A command to report a raid channel as a duplicate.

    **Usage**: `!duplicate`
    When three users report a channel as a duplicate,
    Kyogre deactivates the channel and marks it for deletion."""
    channel = ctx.channel
    author = ctx.author
    guild = ctx.guild
    rc_d = guild_dict[guild.id]['raidchannel_dict'][channel.id]
    t_dict = rc_d['trainer_dict']
    can_manage = channel.permissions_for(author).manage_channels
    raidtype = "event" if guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', False) else "raid"
    regions = rc_d['regions']
    if can_manage:
        dupecount = 2
        rc_d['duplicate'] = dupecount
    else:
        if author.id in t_dict:
            try:
                if t_dict[author.id]['dupereporter']:
                    dupeauthmsg = await channel.send("You've already made a duplicate report for this {raidtype}!"
                                                     .format(raidtype=raidtype))
                    await asyncio.sleep(10)
                    await dupeauthmsg.delete()
                    return
                else:
                    t_dict[author.id]['dupereporter'] = True
            except KeyError:
                t_dict[author.id]['dupereporter'] = True
        else:
            t_dict[author.id] = {
                'status': {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0},
                'dupereporter': True,
            }
        try:
            dupecount = rc_d['duplicate']
        except KeyError:
            dupecount = 0
            rc_d['duplicate'] = dupecount
    dupecount += 1
    rc_d['duplicate'] = dupecount
    if dupecount >= 3:
        rusure = await channel.send('Are you sure you wish to remove this {raidtype}?'.format(raidtype=raidtype))
        try:
            timeout = False
            res, reactuser = await utils.simple_ask(Kyogre, rusure, channel, author.id)
        except TypeError:
            timeout = True
        if not timeout:
            if res.emoji == '❎':
                await rusure.delete()
                confirmation = await channel.send('Duplicate Report cancelled.')
                logger.info((('Duplicate Report - Cancelled - ' + channel.name) + ' - Report by ') + author.name)
                dupecount = 2
                guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
                await asyncio.sleep(10)
                await confirmation.delete()
                return
            elif res.emoji == '✅':
                await rusure.delete()
                await channel.send('Duplicate Confirmed')
                logger.info((('Duplicate Report - Channel Expired - ' + channel.name) + ' - Last Report by ') + author.name)
                raidmsg = await channel.fetch_message(rc_d['raidmessage'])
                reporter = raidmsg.mentions[0]
                if 'egg' in raidmsg.content:
                    egg_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports'] = egg_reports - 1
                elif 'EX' in raidmsg.content:
                    ex_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports'] = ex_reports - 1
                else:
                    raid_reports = guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports']
                    guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports'] = raid_reports - 1
                await expire_channel(channel)
                return
        else:
            await rusure.delete()
            confirmation = await channel.send('Duplicate Report Timed Out.')
            logger.info((('Duplicate Report - Timeout - ' + channel.name) + ' - Report by ') + author.name)
            dupecount = 2
            guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
            await asyncio.sleep(10)
            await confirmation.delete()
    else:
        rc_d['duplicate'] = dupecount
        confirmation = await channel.send('Duplicate report #{duplicate_report_count} received.'
                                          .format(duplicate_report_count=str(dupecount)))
        logger.info((((('Duplicate Report - ' + channel.name) + ' - Report #')
                      + str(dupecount)) + '- Report by ') + author.name)
        return

@commands.command()
async def counters(self, ctx, *, args=''):
    """Simulate a Raid battle with Pokebattler.

    **Usage**: `!counters [pokemon] [weather] [user]`
    See `!help` weather for acceptable values for weather.
    If [user] is a valid Pokebattler user id, Kyogre will simulate the Raid with that user's Pokebox.
    Uses current boss and weather by default if available.
    """
    rgx = '[^a-zA-Z0-9 ]'
    channel = ctx.channel
    guild = channel.guild
    user = guild_dict[guild.id].get('trainers',{}).setdefault('info', {})\
                                   .get(ctx.author.id,{}).get('pokebattlerid', None)
    if checks.check_raidchannel(ctx) and not checks.check_meetupchannel(ctx):
        if args:
            args_split = args.split()
            for arg in args_split:
                if arg.isdigit():
                    user = arg
                    break
        try:
            ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]
                                                      .get('ctrsmessage',None))
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        pkmn = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
        if pkmn:
            if not user:
                try:
                    ctrsmessage = await channel.fetch_message(guild_dict[guild.id]['raidchannel_dict'][channel.id]
                                                              .get('ctrsmessage',None))
                    ctrsembed = ctrsmessage.embeds[0]
                    ctrsembed.remove_field(6)
                    ctrsembed.remove_field(6)
                    await channel.send(content=ctrsmessage.content,embed=ctrsembed)
                    return
                except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                    pass
            moveset = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('moveset', 0)
            movesetstr = guild_dict[guild.id]['raidchannel_dict'][channel.id]\
            .get('ctrs_dict', {'enabled': False, 'auto_levels': []})\
            .get(moveset, {}).get('moveset', "Unknown Moveset")
            weather = guild_dict[guild.id]['raidchannel_dict'][channel.id].get('weather', None)
        else:
            pkmn = next((str(p) for p in Pokemon.get_raidlist() if not str(p).isdigit()
                         and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
            if not pkmn:
                await ctx.channel.send("You're missing some details! Be sure to enter a pokemon"
                                       " that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
                return
        if not weather:
            if args:
                weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
                weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', args.lower())), None)
        pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
        return await counters_helpers._counters(ctx, Kyogre, pkmn, user, weather, movesetstr)
    if args:
        args_split = args.split()
        for arg in args_split:
            if arg.isdigit():
                user = arg
                break
        rgx = '[^a-zA-Z0-9]'
        pkmn = next((str(p) for p in Pokemon.get_raidlist() if not str(p).isdigit()
                     and re.sub(rgx, '', str(p)) in re.sub(rgx, '', args.lower())), None)
        if not pkmn:
            pkmn = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('pokemon', None)
        weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
        weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', args.lower())), None)
        if not weather:
            weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    else:
        pkmn = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('pokemon', None)
        weather = guild_dict[guild.id]['raidchannel_dict'].get(channel.id,{}).get('weather', None)
    if not pkmn:
        await ctx.channel.send("You're missing some details! Be sure to enter a "
                               "pokemon that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
        return
    pkmn = Pokemon.get_pokemon(Kyogre, pkmn)
    await counters_helpers._counters(ctx, Kyogre, pkmn, user, weather, "Unknown Moveset")

@commands.command()
@checks.activechannel()
async def weather(self, ctx, *, weather):
    """Sets the weather for the raid.

    **Usage**: !weather <weather>
    
    Acceptable options: none, extreme, clear, rainy, partlycloudy, cloudy, windy, snow, fog"""
    weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                    'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
    if weather.lower() not in weather_list:
        return await ctx.channel.send("Enter one of the following weather conditions: {}".format(", ".join(weather_list)))
    else:
        await raid_lobby_helpers._weather(ctx, Kyogre, guild_dict, weather)


def setup(bot):
    bot.add_cog(RaidCommands(bot))
