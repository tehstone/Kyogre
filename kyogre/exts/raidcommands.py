import asyncio
import copy
import dateparser
import datetime
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, counters_helpers, embed_utils, entity_updates, utils
from kyogre.exts.pokemon import Pokemon
from kyogre.exts.bosscp import boss_cp_chart

from kyogre.exts.db.kyogredb import KyogreDB, RaidActionTable, RaidTable, TrainerReportRelation


class RaidCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="raid", aliases=['r', 're', 'egg', 'regg', 'raidegg', '1', '2', '3', '4', '5'],
                      brief="Report an ongoing raid or a raid egg.")
    @checks.allowraidreport()
    async def _raid(self, ctx, pokemon, *, location:commands.clean_content(fix_channel_mentions=True) = "",
                    weather=None, timer=None):
        """**Usage**: `!raid <raid tier/pokemon> <gym name> [time]`
        Kyogre will attempt to find a gym with the name you provide and create a separate channel for the raid report,
        for the purposes of organizing the raid."""
        if ctx.invoked_with.isdigit():
            content = f"{ctx.invoked_with} {pokemon} {location} {weather if weather is not None else ''} " \
                f"{timer if timer is not None else ''}"
            new_channel = await self._raidegg(ctx, content)
        else:
            content = f"{pokemon} {location}".lower()
            if pokemon.isdigit():
                new_channel = await self._raidegg(ctx, content)
            elif len(pokemon) == 2 and pokemon[0] == "t":
                new_channel = await self._raidegg(ctx, content[1:])
            else:
                new_channel = await self._raid_internal(ctx, content)
        ctx.raid_channel = new_channel

    async def _raid_internal(self, ctx, content):
        message = ctx.message
        channel = message.channel
        guild = channel.guild
        author = message.author
        fromegg = False
        eggtoraid = False
        if self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('type') == "egg":
            fromegg = True
        raid_split = content.split()
        if len(raid_split) == 0:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description='Give more details when reporting! '
                                                                      'Usage: **!raid <pokemon name> <location>**'))
        if raid_split[0] == 'egg':
            await self._raidegg(ctx, content)
            return
        if fromegg:
            eggdetails = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
            egglevel = eggdetails['egglevel']
            if raid_split[0].lower() == 'assume':
                if self.bot.config['allow_assume'][egglevel] == 'False':
                    return await channel.send(embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description='**!raid assume** is not allowed for this level egg.'))
                if not self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                    await self._eggtoraid(ctx, raid_split[1].lower(), channel, author)
                    return
                else:
                    await self._eggassume(" ".join(raid_split), channel, author)
                    return
            elif (raid_split[0] == "alolan" and len(raid_split) > 2) \
                    or (raid_split[0] != "alolan" and len(raid_split) > 1):
                if raid_split[0] not in Pokemon.get_forms_list() and len(raid_split) > 1:
                    self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                              f" error: Raid report made in raid channel.")
                    return await channel.send(
                        embed=discord.Embed(
                            colour=discord.Colour.red(),
                            description='Please report new raids in a reporting channel.'))
            elif not self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                eggtoraid = True
            # This is a hack but it allows users to report the just hatched boss
            # before Kyogre catches up with hatching the egg.
            elif self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - 60 \
                    < datetime.datetime.now().timestamp():
                eggtoraid = True
            else:
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                          f" error: Hatch announced too soon.")
                return await channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description='Please wait until the egg has hatched before changing it to an open raid!'))
        raid_pokemon = Pokemon.get_pokemon(self.bot, content)
        pkmn_error = None
        pkmn_error_dict = {'not_pokemon': "I couldn't determine the Pokemon in your report.\n"
                                          "What raid boss or raid tier are you reporting?",
                           'not_boss': 'That Pokemon does not appear in raids!\nWhat is the correct Pokemon?',
                           'ex': f"The Pokemon {str(raid_pokemon).capitalize()} only appears in EX Raids!"
                                 "\nWhat is the correct Pokemon?",
                           'level': "That is not a valid raid tier. "
                                    "Please provide the raid boss or tier for your report."}
        new_content = ''
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
                pkmn_embed = discord.Embed(colour=discord.Colour.red(), description=pkmn_error_dict[pkmn_error])
                pkmn_embed.set_footer(text="Reply with 'cancel' to cancel your raid report.")
                pkmnquery_msg = await channel.send(embed=pkmn_embed)
                try:
                    pokemon_msg = await self.bot.wait_for('message', timeout=20,
                                                          check=(lambda reply: reply.author == author))
                except asyncio.TimeoutError:
                    await channel.send(embed=discord.Embed(
                        colour=discord.Colour.light_grey(),
                        description="You took too long to reply. Raid report cancelled."), delete_after=12)
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
                        return await self._raidegg(ctx, ' '.join([str(pokemon_msg.clean_content), new_content]))
                    else:
                        pkmn_error = 'level'
                        continue
                raid_pokemon = Pokemon.get_pokemon(self.bot, pokemon_msg.clean_content)
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
            return await self._eggtoraid(ctx, raid_pokemon.full_name.lower(), channel, author)
        if eggtoraid:
            return await self._eggtoraid(ctx, new_content.lower(), channel, author)
        raid_split = new_content.strip().split()
        if len(raid_split) == 0:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
        raidexp = await utils.time_to_minute_count(self.bot.guild_dict, channel, raid_split[-1], False)
        if raidexp:
            del raid_split[-1]
            if self._timercheck(raidexp, self.bot.raid_info['raid_eggs'][raid_pokemon.raid_level]['raidtime']):
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                          f" error: Raid expiration time too long.")
                time_embed = discord.Embed(description="That's too long. Level {raidlevel} Raids currently last no "
                                                       "more than {hatchtime} minutes...\nExpire time will not be set."
                                           .format(raidlevel=raid_pokemon.raid_level,
                                                   hatchtime=self.bot.raid_info['raid_eggs']
                                                   [raid_pokemon.raid_level]['hatchtime']),
                                           colour=discord.Colour.red())
                await channel.send(embed=time_embed)
                raidexp = False
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                          f" error: raid expiration time too long")
        else:
            await channel.send(
                embed=discord.Embed(colour=discord.Colour.orange(),
                                    description='Could not determine expiration time. Using default of 45 minutes'))
        raid_details = ' '.join(raid_split)
        raid_details = raid_details.strip()
        if raid_details == '':
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
        weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                        'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
        rgx = '[^a-zA-Z0-9]'
        weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', raid_details.lower())), None)
        if not weather:
            weather = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('weather', None)
        raid_pokemon.weather = weather
        raid_details = raid_details.replace(str(weather), '', 1)
        if raid_details == '':
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
        return await self.finish_raid_report(ctx, raid_details, raid_pokemon, raid_pokemon.raid_level, weather, raidexp)

    async def retry_gym_match(self, channel, author_id, raid_details, gyms):
        attempt = raid_details.split(' ')
        if len(attempt) > 1:
            if attempt[-2] == "alolan" and len(attempt) > 2:
                del attempt[-2]
            del attempt[-1]
        attempt = ' '.join(attempt)
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gym = await location_matching_cog.match_prompt(channel, author_id, attempt, gyms)
        if gym:
            return gym
        else:
            attempt = raid_details.split(' ')
            if len(attempt) > 1:
                if attempt[0] == "alolan" and len(attempt) > 2:
                    del attempt[0]
                del attempt[0]
            attempt = ' '.join(attempt)
            gym = await location_matching_cog.match_prompt(channel, author_id, attempt, gyms)
            if gym:
                return gym
            else:
                return None

    async def _raidegg(self, ctx, content):
        message = ctx.message
        channel = message.channel
        guild = message.guild
        author = message.author

        if checks.check_eggchannel(ctx) or checks.check_raidchannel(ctx):
            self.bot.help_logger.info(f"User: {author.name}, channel: {channel},"
                                      f" error: Raid reported in raid channel.")
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description='Please report new raids in a reporting channel.'))

        raidegg_split = content.split()
        if raidegg_split[0].lower() == 'egg':
            del raidegg_split[0]
        if len(raidegg_split) <= 1:
            self.bot.help_logger.info(f"User: {author.name}, channel: {channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Usage: **!raidegg <level> <location>**'))
        if raidegg_split[0].isdigit():
            egg_level = int(raidegg_split[0])
            del raidegg_split[0]
        else:
            self.bot.help_logger.info(f"User: {author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Use at least: **!raidegg <level> <location>**. '
                            'Type **!help** raidegg for more info.'))
        raidexp = await utils.time_to_minute_count(self.bot.guild_dict, channel, raidegg_split[-1], False)
        if raidexp:
            del raidegg_split[-1]
            if self._timercheck(raidexp, self.bot.raid_info['raid_eggs'][str(egg_level)]['hatchtime']):
                await channel.send("That's too long. Level {raidlevel} Raid Eggs "
                                   "currently last no more than {hatchtime} minutes..."
                                   .format(raidlevel=egg_level,
                                           hatchtime=self.bot.raid_info['raid_eggs'][str(egg_level)]['hatchtime']))
                self.bot.help_logger.info(f"User: {author.name}, channel: {ctx.channel},"
                                          f" error: raid expiration time too long")
                return
        else:
            await channel.send(
                embed=discord.Embed(colour=discord.Colour.orange(),
                                    description='Could not determine hatch time. Using default of 60 minutes'))
        raid_details = ' '.join(raidegg_split)
        raid_details = raid_details.strip()
        if raid_details == '':
            self.bot.help_logger.info(f"User: {author.name}, channel: {ctx.channel},"
                                      f" error: Insufficient raid details provided.")
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
            weather = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('weather', None)
        if raid_details == '':
            self.bot.help_logger.info(f"User: {author.name}, channel: {channel},"
                                      f" error: Insufficient raid details provided.")
            return await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description='Give more details when reporting! Usage: **!raid <pokemon name> <location>**'))
        return await self.finish_raid_report(ctx, raid_details, None, egg_level, weather, raidexp)

    async def finish_raid_report(self, ctx, raid_details, raid_pokemon, level, weather, raidexp):
        message = ctx.message
        channel = message.channel
        guild = channel.guild
        author = message.author
        timestamp = (message.created_at + datetime.timedelta(
            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])).strftime('%I:%M %p (%H:%M)')
        if raid_pokemon is None:
            raid_report = False
        else:
            raid_report = True
        utils_cog = self.bot.cogs.get('Utilities')
        report_regions = utils_cog.get_channel_regions(channel, 'raid')
        gym = None
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(guild.id, report_regions)
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        utils_cog = self.bot.cogs.get('Utilities')
        other_region = False
        gym_regions = []
        egg_info = None
        boss_list = []
        egg_img = None
        if gyms:
            gym = await location_matching_cog.match_prompt(channel, author.id, raid_details, gyms)
            if not gym:
                all_regions = list(self.bot.guild_dict[guild.id]['configure_dict']['regions']['info'].keys())
                gyms = location_matching_cog.get_gyms(guild.id, all_regions)
                gym = await location_matching_cog.match_prompt(channel, author.id, raid_details, gyms)
                if not gym:
                    gym = await self.retry_gym_match(channel, author.id, raid_details, gyms)
                    if not gym:
                        self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                                  f"error: No gym found with name: {raid_details}.")
                        return await channel.send(embed=discord.Embed(
                            colour=discord.Colour.red(),
                            description=f"I couldn't find a gym named '{raid_details}'. "
                            f"Try again using the exact gym name!"))
                if report_regions[0] != gym.region:
                    other_region = True
            raid_channel_ids = self.get_existing_raid(guild, gym)
            if raid_channel_ids:
                raid_channel = self.bot.get_channel(raid_channel_ids[0])
                try:
                    raid_dict_entry = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
                except:
                    return await message.add_reaction('\u274c')
                utils_cog = self.bot.cogs.get('Utilities')
                enabled = utils_cog.raid_channels_enabled(guild, channel)
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
                    return await self._eggtoraid(ctx, raid_pokemon.name.lower(), raid_channel)

            raid_details = gym.name
            raid_gmaps_link = gym.maps_url
            waze_link = utils_cog.create_waze_query(gym.latitude, gym.longitude)
            apple_link = utils_cog.create_applemaps_query(gym.latitude, gym.longitude)
            gym_regions = [gym.region]
        else:
            raid_gmaps_link = utils_cog.create_gmaps_query(raid_details, channel, type="raid")
        if other_region:
            report_channels = await listmgmt_cog.get_region_reporting_channels(guild, gym.region)
            report_channel = self.bot.get_channel(report_channels[0])
        else:
            report_channel = channel
        if raid_report:
            raid_channel = await self.create_raid_channel("raid", raid_pokemon, None, gym, channel)
        else:
            egg_info = self.bot.raid_info['raid_eggs'][str(level)]
            egg_img = egg_info['egg_img']
            for entry in egg_info['pokemon']:
                p = Pokemon.get_pokemon(self.bot, entry)
                boss_list.append(str(p) + ' (' + str(p.id) + ') ' + utils.types_to_str(guild, p.types, self.bot.config))
            raid_channel = await self.create_raid_channel("egg", None, level, gym, channel)
        ow = raid_channel.overwrites_for(guild.default_role)
        ow.send_messages = True
        try:
            await raid_channel.set_permissions(guild.default_role, overwrite=ow)
        except (discord.errors.Forbidden, discord.errors.HTTPException, discord.errors.InvalidArgument):
            pass
        exp = raidexp
        if not raidexp:
            exp = time.time() + (60 * self.bot.raid_info['raid_eggs'][str(level)]['raidtime'])
        raid_dict = {
            'regions': gym_regions,
            'reportcity': report_channel.id,
            'trainer_dict': {},
            'exp': exp,
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
        raid_embed = discord.Embed(colour=guild.me.colour)
        enabled = utils_cog.raid_channels_enabled(guild, channel)
        if gym:
            gym_info = f"**{raid_details}**\n{'_EX Eligible Gym_' if gym.ex_eligible else ''}"
            if gym.note is not None:
                gym_info += f"\n**Note**: {gym.note}"
            raid_embed.add_field(name='**Gym:**', value=gym_info, inline=False)
        raid_embed.add_field(name='Directions',
                             value=f'[Google]({raid_gmaps_link}) | [Waze]({waze_link}) | [Apple]({apple_link})',
                             inline=False)
        cp_range = ''
        if raid_report:
            if enabled:
                if str(raid_pokemon).lower() in boss_cp_chart:
                    cp_range = boss_cp_chart[str(raid_pokemon).lower()]
                weak_str = utils.types_to_str(guild, raid_pokemon.weak_against.keys(), self.bot.config)
                raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                                     .format(pokemon=str(raid_pokemon),
                                             pokemonnumber=str(raid_pokemon.id),
                                             type=utils.types_to_str(guild, raid_pokemon.types, self.bot.config),
                                             cprange='\n'+cp_range,
                                             inline=True))
                raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'.format(weakness_list=weak_str))
                raid_embed.add_field(name='**Next Group:**', value='Set with **!starttime**')
                raid_embed.add_field(name='**Expires:**', value='Set with **!timerset**')
            raid_img_url = raid_pokemon.img_url
            msg = entity_updates.build_raid_report_message(self.bot, gym, 'raid', raid_pokemon.name, '0',
                                                           raidexp, raid_channel, self.bot.guild_dict)
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
            msg = entity_updates.build_raid_report_message(self.bot, gym, 'egg', '', level, raidexp,
                                                           raid_channel, self.bot.guild_dict)
        if enabled:
            raid_embed.set_footer(text='Reported by {author} - {timestamp}'
                                  .format(author=author.display_name, timestamp=timestamp),
                                  icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
        raid_embed.set_thumbnail(url=raid_img_url)
        report_embed = raid_embed
        embed_indices = await embed_utils.get_embed_field_indices(report_embed)
        report_embed = await embed_utils.filter_fields_for_report_embed(report_embed, embed_indices, enabled)
        raidreport = await channel.send(content=msg, embed=report_embed)
        short_output_channel_id = self.bot.guild_dict[guild.id]['configure_dict']['raid']\
            .setdefault('short_output', {}).get(gym.region, None)
        if short_output_channel_id:
            send_level = 0
            if raid_pokemon:
                if raid_pokemon.raid_level:
                    send_level = int(raid_pokemon.raid_level)
            else:
                if level:
                    send_level = int(level)
            if send_level >= 4:
                short_output_channel = self.bot.get_channel(short_output_channel_id)
                short_message = await short_output_channel.send(f"Raid Reported: {raid_channel.mention}")
                raid_dict['short'] = short_message.id
        await asyncio.sleep(1)
        raid_embed.add_field(name='**Tips:**',
                             value='`!i` if interested\n`!c` if on the way\n`!h` '
                                   'when you arrive\n`!x` to cancel your status\n'
                                   "`!s` to signal lobby start\n`!shout` to ping raid party",
                             inline=True)
        ctrsmessage_id = None
        ctrs_dict = {}
        if raid_report:
            raidmsg = "{pokemon} raid reported at {location_details} gym by {member} in {citychannel}. " \
                      "Coordinate here!\n\nClick the question mark reaction" \
                      " to get help on the commands that work in this channel."\
                .format(pokemon=str(raid_pokemon), member=author.display_name,
                        citychannel=channel.mention, location_details=raid_details)
            if str(level) in self.bot.guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
                try:
                    ctrs_dict = await counters_helpers._get_generic_counters(self.bot, guild, raid_pokemon, weather)
                    ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                              "Update weather with **!weather**. If you know the moveset of the boss, " \
                              "you can react to this message with the matching emoji and I will update the counters."
                    ctrsmessage = await raid_channel.send(content=ctrsmsg, embed=ctrs_dict[0]['embed'])
                    ctrsmessage_id = ctrsmessage.id
                    await ctrsmessage.pin()
                    for moveset in ctrs_dict:
                        await ctrsmessage.add_reaction(ctrs_dict[moveset]['emoji'])
                        await asyncio.sleep(0.25)
                except:
                    pass
            else:
                pass
            raid_reports = self.bot.guild_dict[guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                               .setdefault(author.id, {}).setdefault('raid_reports', 0) + 1
            self.bot.guild_dict[guild.id]['trainers'][gym.region][author.id]['raid_reports'] = raid_reports
            raid_details = {'pokemon': raid_pokemon,
                            'tier': raid_pokemon.raid_level,
                            'ex-eligible': gym.ex_eligible if gym else False,
                            'location': raid_details,
                            'regions': gym_regions}
        else:
            raidmsg = "Level {level} raid egg reported at {location_details} gym by {member} in {citychannel}. " \
                      "Coordinate here!\n\nClick the question mark reaction to get help " \
                      "on the commands that work in this channel."\
                .format(level=level, member=author.display_name,
                        citychannel=channel.mention, location_details=raid_details)
            egg_reports = self.bot.guild_dict[guild.id].setdefault('trainers', {}).setdefault(gym.region, {})\
                              .setdefault(author.id, {}).setdefault('egg_reports', 0) + 1
            self.bot.guild_dict[guild.id]['trainers'][gym.region][author.id]['egg_reports'] = egg_reports
            raid_details = {'tier': level,
                            'ex-eligible': gym.ex_eligible if gym else False,
                            'location': raid_details,
                            'regions': gym_regions}
        raidmessage = await raid_channel.send(content=raidmsg, embed=raid_embed)
        await utils.reaction_delay(raidmessage, ['\u2754', '\u270f', '🚫'])
        await raidmessage.pin()
        raid_dict['raidmessage'] = raidmessage.id
        raid_dict['raidreport'] = raidreport.id
        raid_dict['raidcityreport'] = None
        if ctrsmessage_id is not None:
            raid_dict['ctrsmessage'] = ctrsmessage_id
            raid_dict['ctrs_dict'] = ctrs_dict
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = raid_dict
        if raidexp is not False:
            await self._timerset(raid_channel, raidexp, to_print=False)
        else:
            await raid_channel.send(content='Hey {member}, if you can, set the time left on the raid using '
                                            '**!timerset <minutes>** so others can check it with **!timer**.'
                                    .format(member=author.mention))
        await listmgmt_cog.update_listing_channels(guild, 'raid', edit=False, regions=gym_regions)
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        if enabled:
            send_channel = raid_channel
        else:
            send_channel = subscriptions_cog.get_region_list_channel(guild, gym.region, 'raid')
            if send_channel is None:
                send_channel = channel
        await subscriptions_cog.send_notifications_async('raid', raid_details, send_channel, [author.id])
        await utils.reaction_delay(raidreport, ['\u270f', '🚫'])
        if other_region:
            region_command_channels = self.bot.guild_dict[guild.id]['configure_dict']['regions']\
                .setdefault('command_channels', [])
            channel_text = ''
            if len(region_command_channels) > 0:
                channel_text = ' in '
                for c in region_command_channels:
                    channel_text += self.bot.get_channel(c).mention
            region_msg = f'Hey {author.mention}, **{gym.name}** is in the **{gym_regions[0].capitalize()}** ' \
                f'region. Your report was successful, but please consider joining that region{channel_text} ' \
                f'to report raids at this gym in the future'
            embed = discord.Embed(colour=discord.Colour.gold(), description=region_msg)
            embed.set_footer(text=f"If you believe this region assignment is incorrect, "
                                  f"please contact {guild.owner.display_name}")
            await channel.send(embed=embed)
            raidcityreport = await report_channel.send(content=msg, embed=report_embed)
            raid_dict['raidcityreport'] = raidcityreport.id
            await utils.reaction_delay(raidcityreport, ['\u270f', '🚫'])
        if not raid_report:
            if len(self.bot.raid_info['raid_eggs'][str(level)]['pokemon']) == 1:
                await self._eggassume('assume ' + self.bot.raid_info['raid_eggs'][str(level)]['pokemon'][0],
                                      raid_channel, author)
            elif level == "5" and self.bot.guild_dict[guild.id]['configure_dict']['settings']\
                    .get('regional', None) in self.bot.raid_info['raid_eggs']["5"]['pokemon']:
                await self._eggassume('assume ' +
                                      self.bot.guild_dict[guild.id]['configure_dict']['settings']['regional'],
                                      raid_channel, author)
        self.bot.event_loop.create_task(self.expiry_check(raid_channel))
        await self._add_db_raid_report(ctx, raid_channel)
        return raid_channel

    async def create_raid_channel(self, raid_type, pkmn, level, gym, report_channel):
        guild = report_channel.guild
        cat = None
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        if raid_type == "exraid":
            name = "ex-raid-egg-"
            raid_channel_overwrite_dict = report_channel.overwrites
            # If and when ex reporting is revisited this will need a complete rewrite.
            # Overwrites went from Tuple -> Dict
            # if guild_dict[guild.id]['configure_dict']['invite']['enabled']:
            #     if guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone":
            #         everyone_overwrite = (guild.default_role, discord.PermissionOverwrite(send_messages=False))
            #         raid_channel_overwrite_list.append(everyone_overwrite)
            #     for overwrite in raid_channel_overwrite_dict:
            #         if isinstance(overwrite[0], discord.Role):
            #             if overwrite[0].permissions.manage_guild or
            #             #overwrite[0].permissions.manage_channels or overwrite[0].permissions.manage_messages:
            #                 continue
            #             overwrite[1].send_messages = False
            #         elif isinstance(overwrite[0], discord.Member):
            #             if report_channel.permissions_for(overwrite[0]).manage_guild or
            #             report_channel.permissions_for(overwrite[0]).manage_channels or
            #             report_channel.permissions_for(overwrite[0]).manage_messages:
            #                 continue
            #             overwrite[1].send_messages = False
            #         if (overwrite[0].name not in guild.me.top_role.name) and (overwrite[0].name not in guild.me.name):
            #             overwrite[1].send_messages = False
            #     for role in guild.role_hierarchy:
            #         if role.permissions.manage_guild or role.permissions.manage_channels
            #         or role.permissions.manage_messages:
            #             raid_channel_overwrite_dict.update({role: discord.PermissionOverwrite(send_messages=True)})
            # else:
            if self.bot.guild_dict[guild.id]['configure_dict']['exraid']['permissions'] == "everyone":
                everyone_overwrite = {guild.default_role: discord.PermissionOverwrite(send_messages=True)}
                raid_channel_overwrite_dict.update(everyone_overwrite)
            cat = utils.get_category(report_channel, "EX", self.bot.guild_dict, category_type=raid_type)
        else:
            reporting_channels = await listmgmt_cog.get_region_reporting_channels(guild, gym.region)
            report_channel = guild.get_channel(reporting_channels[0])
            raid_channel_overwrite_dict = report_channel.overwrites
            name = ""
            if raid_type == "raid":
                name = pkmn.name.lower() + "_"
                cat = utils.get_category(report_channel, str(pkmn.raid_level), self.bot.guild_dict,
                                         category_type=raid_type)
            elif raid_type == "egg":
                name = "{level}-egg_".format(level=str(level))
                cat = utils.get_category(report_channel, str(level), self.bot.guild_dict, category_type=raid_type)
        kyogre_overwrite = {
            self.bot.user: discord.PermissionOverwrite(send_messages=True, read_messages=True, manage_roles=True,
                                                       manage_channels=True, manage_messages=True, add_reactions=True,
                                                       external_emojis=True, read_message_history=True,
                                                       embed_links=True, mention_everyone=True, attach_files=True)}
        raid_channel_overwrite_dict.update(kyogre_overwrite)
        utils_cog = self.bot.cogs.get('Utilities')
        enabled = utils_cog.raid_channels_enabled(guild, report_channel)
        if not enabled:
            user_overwrite = {guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=False,
                                                                              read_message_history=False)}
            raid_channel_overwrite_dict.update(user_overwrite)
            role = discord.utils.get(guild.roles, name=gym.region)
            if role is not None:
                role_overwrite = {role: discord.PermissionOverwrite(send_messages=False, read_messages=False,
                                                                    read_message_history=False)}
                raid_channel_overwrite_dict.update(role_overwrite)
        name = utils.sanitize_name(name + gym.name)[:32]
        return await guild.create_text_channel(name, overwrites=raid_channel_overwrite_dict, category=cat)

    async def _eggassume(self, args, raid_channel, author):
        guild = raid_channel.guild
        eggdetails = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
        report_channel = self.bot.get_channel(eggdetails['reportchannel'])
        egglevel = eggdetails['egglevel']
        weather = eggdetails.get('weather', None)
        egg_report = await report_channel.fetch_message(eggdetails['raidreport'])
        raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
        entered_raid = re.sub('[\\@]', '', args.lower().lstrip('assume').lstrip(' '))
        raid_pokemon = Pokemon.get_pokemon(self.bot, entered_raid)
        if not raid_pokemon:
            return
        if not raid_pokemon.is_raid:
            self.bot.help_logger.info(f"User: {author.name}, channel: {raid_channel},"
                                      f" error: {raid_pokemon.name} reported, but not in raid data.")
            return await raid_channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f'The Pokemon {raid_pokemon.name} does not appear in raids!'))
        elif raid_pokemon.name.lower() not in self.bot.raid_info['raid_eggs'][egglevel]['pokemon']:
            self.bot.help_logger.info(f"User: {author.name}, channel: {raid_channel},"
                                      f" error: {raid_pokemon.name} reported, but not in raiddata for this raid level.")
            return await raid_channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f'The Pokemon {raid_pokemon.name} does not hatch from level {egglevel} raid eggs!'))
        eggdetails['pokemon'] = raid_pokemon.name
        oldembed = raid_message.embeds[0]
        raid_gmaps_link = oldembed.url
        utils_cog = self.bot.cogs.get('Utilities')
        enabled = utils_cog.raid_channels_enabled(guild, raid_channel)
        if enabled:
            embed_indices = await embed_utils.get_embed_field_indices(oldembed)
            raid_embed = discord.Embed(colour=guild.me.colour)
            raid_embed.add_field(name=oldembed.fields[embed_indices["directions"]].name,
                                 value=oldembed.fields[embed_indices["directions"]].value, inline=True)
            raid_embed.add_field(name=oldembed.fields[embed_indices["gym"]].name,
                                 value=oldembed.fields[embed_indices["gym"]].value, inline=True)
            cp_range = ''
            if raid_pokemon.name.lower() in boss_cp_chart:
                cp_range = boss_cp_chart[raid_pokemon.name.lower()]
            raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                                 .format(pokemon=raid_pokemon.name, pokemonnumber=str(raid_pokemon.id),
                                         type=utils.types_to_str(guild, raid_pokemon.types, self.bot.config),
                                         cprange='\n'+cp_range, inline=True))
            raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                                 .format(weakness_list=utils.types_to_str(guild,
                                                                          raid_pokemon.weak_against, self.bot.config)))
            if embed_indices["next"] is not None:
                raid_embed.add_field(name=oldembed.fields[embed_indices["next"]].name,
                                     value=oldembed.fields[embed_indices["next"]].value, inline=True)
            if embed_indices["hatch"] is not None:
                raid_embed.add_field(name=oldembed.fields[embed_indices["hatch"]].name,
                                     value=oldembed.fields[embed_indices["hatch"]].value, inline=True)
            if embed_indices["tips"] is not None:
                raid_embed.add_field(name=oldembed.fields[embed_indices["tips"]].name,
                                     value=oldembed.fields[embed_indices["tips"]].value, inline=True)

            raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
            raid_embed.set_thumbnail(url=raid_pokemon.img_url)
            try:
                await raid_message.edit(new_content=raid_message.content, embed=raid_embed,
                                        content=raid_message.content)
            except discord.errors.NotFound:
                pass
            try:
                embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
                raid_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices, enabled)
                await egg_report.edit(new_content=egg_report.content, embed=raid_embed, content=egg_report.content)
            except discord.errors.NotFound:
                pass
            if eggdetails.get('raidcityreport', None) is not None:
                report_city_channel = self.bot.get_channel(eggdetails['reportcity'])
                city_report = await report_city_channel.fetch_message(eggdetails['raidcityreport'])
                try:
                    await city_report.edit(new_content=city_report.content, embed=raid_embed,
                                           content=city_report.content)
                except discord.errors.NotFound:
                    pass
        if str(egglevel) in self.bot.guild_dict[guild.id]['configure_dict']['counters']['auto_levels']:
            ctrs_dict = await counters_helpers._get_generic_counters(self.bot, guild, raid_pokemon, weather)
            ctrsmsg = "Here are the best counters for the raid boss in currently known weather conditions! " \
                      "Update weather with **!weather**. If you know the moveset of the boss, " \
                      "you can react to this message with the matching emoji and I will update the counters."
            ctrsmessage = await raid_channel.send(content=ctrsmsg, embed=ctrs_dict[0]['embed'])
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
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = eggdetails
        return

    async def _eggtoraid(self, ctx, entered_raid, raid_channel, author=None):
        guild = raid_channel.guild
        pkmn = Pokemon.get_pokemon(self.bot, entered_raid)
        if not pkmn:
            return
        action_time = round(time.time())
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        eggdetails = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
        egglevel = eggdetails['egglevel']
        if egglevel == "0":
            egglevel = pkmn.raid_level
        reportcitychannel = None
        try:
            reportcitychannel = self.bot.get_channel(eggdetails['reportcity'])
        except (discord.errors.NotFound, AttributeError):
            pass
        manual_timer = eggdetails['manual_timer']
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
            reportchannel = self.bot.get_channel(reportchannel)
        raid_message = await raid_channel.fetch_message(eggdetails['raidmessage'])
        egg_report = None
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
                pass
        city_report = None
        if reportcitychannel:
            try:
                city_report = await reportcitychannel.fetch_message(eggdetails.get('raidcityreport', 0))
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass
        starttime = eggdetails.get('starttime', None)
        duplicate = eggdetails.get('duplicate', 0)
        archive = eggdetails.get('archive', False)
        meetup = eggdetails.get('meetup', {})
        raid_match = pkmn.is_raid
        if not raid_match:
            await raid_channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f'The Pokemon {pkmn.full_name} does not appear in raids!'))
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel},"
                                      f" error: {pkmn.name} reported, but not in raid data.")
            return
        if (egglevel.isdigit() and int(egglevel) > 0) or egglevel == 'EX':
            raidexp = eggdetails['exp'] + 60 * self.bot.raid_info['raid_eggs'][str(egglevel)]['raidtime']
        else:
            raidexp = eggdetails['exp']
        end = datetime.datetime.utcfromtimestamp(raidexp) + datetime.timedelta(
            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        oldembed = raid_message.embeds[0]
        raid_gmaps_link = oldembed.url
        enabled = True
        raidmsg = ''
        raidreportcontent = ''
        hatchtype = ''
        if self.bot.guild_dict[guild.id].get('raidchannel_dict', {}).get(raid_channel.id, {}).get('meetup', {}):
            self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['type'] = 'exraid'
            self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['egglevel'] = '0'
            await raid_channel.send("The event has started!", embed=oldembed)
            await raid_channel.edit(topic="")
            self.bot.event_loop.create_task(self.expiry_check(raid_channel))
            return
        if egglevel.isdigit():
            hatchtype = 'raid'
            raidreportcontent = 'The egg has hatched into a {pokemon} raid at {location_details} gym.'\
                .format(pokemon=entered_raid.capitalize(), location_details=egg_address)
            utils_cog = self.bot.cogs.get('Utilities')
            enabled = utils_cog.raid_channels_enabled(guild, raid_channel)
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
            if self.bot.guild_dict[guild.id]['configure_dict']['invite']['enabled']:
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
        raid_embed = discord.Embed(colour=guild.me.colour)
        cp_range = ''
        if pkmn.name.lower() in boss_cp_chart:
            cp_range = boss_cp_chart[pkmn.name.lower()]
        raid_embed.add_field(name='**Details:**', value='**{pokemon}** ({pokemonnumber}) {type}{cprange}'
                             .format(pokemon=pkmn.name, pokemonnumber=str(pkmn.id),
                                     type=utils.types_to_str(guild, pkmn.types, self.bot.config),
                                     cprange='\n'+cp_range, inline=True))
        raid_embed.add_field(name='**Weaknesses:**', value='{weakness_list}'
                             .format(weakness_list=utils.types_to_str(guild, pkmn.weak_against, self.bot.config))
                             , inline=True)
        raid_embed.set_footer(text=oldembed.footer.text, icon_url=oldembed.footer.icon_url)
        raid_embed.set_thumbnail(url=pkmn.img_url)
        await raid_channel.edit(name=raid_channel_name, topic=end.strftime('Ends at %I:%M %p (%H:%M)'))
        trainer_list = []
        trainer_dict = copy.deepcopy(self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'])
        for trainer in trainer_dict.keys():
            if (trainer_dict[trainer].get('interest', None)) \
                    and (entered_raid.lower() not in trainer_dict[trainer]['interest']):
                self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['status'] =\
                    {'maybe': 0, 'coming': 0, 'here': 0, 'lobby': 0}
                self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['party'] =\
                    {'mystic': 0, 'valor': 0, 'instinct': 0, 'unknown': 0}
                self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['count'] = 1
            else:
                self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['trainer_dict'][trainer]['interest'] = []
        await asyncio.sleep(1)

        trainer_count = listmgmt_cog.determine_trainer_count(trainer_dict)
        status_embed = listmgmt_cog.build_status_embed(guild, trainer_count)
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
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        if enabled:
            last_status = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id].get('last_status', None)
            if last_status is not None:
                try:
                    last = await raid_channel.fetch_message(last_status)
                    await last.delete()
                except:
                    pass
            if status_embed is not None:
                new_status = await raid_channel.send(embed=status_embed)
                self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['last_status'] = new_status.id
        if enabled:
            send_channel = raid_channel
        else:
            send_channel = subscriptions_cog.get_region_list_channel(guild, gym.region, 'raid')
            if send_channel is None:
                send_channel = reportchannel
        await subscriptions_cog.send_notifications_async('raid', raid_details, send_channel,
                                                         [author] if author else [])
        if embed_indices["directions"] is not None:
            raid_embed.add_field(name=oldembed.fields[embed_indices["directions"]].name,
                                 value=oldembed.fields[embed_indices["directions"]].value, inline=True)
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
            report_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices, enabled)
            await egg_report.edit(new_content=raidreportcontent, embed=report_embed, content=raidreportcontent)
            egg_report = egg_report.id
        except (discord.errors.NotFound, AttributeError):
            egg_report = None
        if eggdetails.get('raidcityreport', None) is not None:
            try:
                await city_report.edit(new_content=city_report.content, embed=raid_embed, content=city_report.content)
            except (discord.errors.NotFound, AttributeError):
                pass
        if str(egglevel) in self.bot.guild_dict[guild.id]['configure_dict']['counters']['auto_levels'] \
                and not eggdetails.get('pokemon', None):
            ctrs_dict = await counters_helpers._get_generic_counters(self.bot, guild, pkmn, weather)
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
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id] = {
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
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['starttime'] = starttime
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['duplicate'] = duplicate
        self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]['archive'] = archive
        if author:
            raid_reports = self.bot.guild_dict[guild.id].setdefault('trainers', {}).setdefault(regions[0], {})\
                               .setdefault(author.id, {}).setdefault('raid_reports', 0) + 1
            self.bot.guild_dict[guild.id]['trainers'][regions[0]][author.id]['raid_reports'] = raid_reports

            await listmgmt_cog.edit_party(ctx, raid_channel, author)
        await listmgmt_cog.update_listing_channels(guild, 'raid', edit=False, regions=regions)
        await asyncio.sleep(1)
        self.bot.event_loop.create_task(self.expiry_check(raid_channel))
        updated_time = round(time.time())
        await self._update_db_raid_report(guild, raid_channel, updated_time)
        await self.add_db_raid_action(raid_channel, "hatch", action_time)

    async def _add_db_raid_report(self, ctx, raid_channel):
        message = ctx.message
        channel = message.channel
        guild = channel.guild
        author = message.author
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]
        gym = raid_dict['gym']
        created = round(message.created_at.timestamp())
        level, pokemon, hatch_time, expire_time, weather = None, None, None, None, None
        if 'egglevel' in raid_dict and raid_dict['egglevel'] != '0':
            try:
                level = int(raid_dict['egglevel'])
            except TypeError:
                pass
        if 'pokemon' in raid_dict and raid_dict['pokemon'] != '':
            pokemon = raid_dict['pokemon']
            raid_pokemon = Pokemon.get_pokemon(self.bot, pokemon)
            level = raid_pokemon.raid_level
        if 'weather' in raid_dict:
            weather = raid_dict['weather']
        if 'type' in raid_dict:
            if 'exp' in raid_dict:
                if raid_dict['type'] == 'egg':
                    hatch_time = round(raid_dict['exp'])
                    expire_time = round(raid_dict['exp']) + 2700
                elif raid_dict['type'] == 'raid':
                    expire_time = round(raid_dict['exp'])
                    hatch_time = round(raid_dict['exp']) - 2700
        report = TrainerReportRelation.create(created=created, trainer=author.id, location=gym.id)
        try:
            RaidTable.create(trainer_report=report, level=level, pokemon=pokemon, hatch_time=hatch_time,
                             expire_time=expire_time, channel=raid_channel.id, weather=weather)
        except Exception as e:
            self.bot.logger.info(f"Failed to create raid table entry with error: {e}")

    async def _update_db_raid_report(self, guild, raid_channel, updated):
        report = None
        try:
            report = RaidTable.get(RaidTable.channel == raid_channel.id)
        except Exception as e:
            self.bot.logger.info(f"Failed to update raid table entry with error: {e}")
        if report is None:
            return self.bot.logger.info(f"No Raid report found in db to update. Channel id: {raid_channel.id}")
        report_relation = TrainerReportRelation.get(TrainerReportRelation.id == report.trainer_report_id)
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(raid_channel.id, None)
        if raid_dict is None:
            return self.bot.logger.info(f"No raid_dict found in guild_dict. "
                                        f"Cannot update raid report. Channel id: {raid_channel.id}")
        if 'egglevel' in raid_dict and raid_dict['egglevel'] != '0':
            try:
                report.level = int(raid_dict['egglevel'])
            except TypeError:
                pass
        if 'pokemon' in raid_dict and raid_dict['pokemon'] != '':
            report.pokemon = raid_dict['pokemon']
            raid_pokemon = Pokemon.get_pokemon(self.bot, report.pokemon)
            report.level = raid_pokemon.raid_level
        if 'weather' in raid_dict:
            report.weather = raid_dict['weather']
        if 'type' in raid_dict:
            if 'exp' in raid_dict:
                if raid_dict['type'] == 'egg':
                    report.hatch_time = round(raid_dict['exp'])
                    report.expire_time = round(raid_dict['exp']) + 2700
                elif raid_dict['type'] == 'raid':
                    report.expire_time = round(raid_dict['exp'])
                    report.hatch_time = round(raid_dict['exp']) - 2700
        report.save()
        if report_relation is not None:
            gym = raid_dict['gym']
            if gym is None:
                return
            report_relation.location_id = gym.id
            report_relation.updated = updated
            report_relation.save()

    async def _cancel_db_raid_report(self, raid_channel_id):
        report = None
        try:
            report = RaidTable.get(RaidTable.channel == raid_channel_id)
        except Exception as e:
            self.bot.logger.info(f"Failed to cancel raid table entry with error: {e}")
        if report is None:
            return self.bot.logger.info(f"No Raid report found in db to cancel. Channel id: {raid_channel_id}")
        report_relation = TrainerReportRelation.get(TrainerReportRelation.id == report.trainer_report_id)
        report_relation.cancelled = 'True'
        report_relation.save()

    async def add_db_raid_action(self, raid_channel, action, action_time):
        guild = raid_channel.guild
        report = None
        try:
            report = RaidTable.get(RaidTable.channel == raid_channel.id)
        except Exception as e:
            self.bot.logger.info(f"Failed to create raid table entry with error: {e}")
        if report is None:
            return self.bot.logger.info(f"No Raid report found in db to add raid action. Channel id: {raid_channel.id}")
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(raid_channel.id, None)
        if raid_dict is None:
            return self.bot.logger.info(f"No raid_dict found in guild_dict. "
                                        f"Cannot add raid action. Channel id: {raid_channel.id}")
        trainer_dict = raid_dict.get('trainer_dict', {})
        RaidActionTable.create(raid=report, action=action, action_time=action_time, trainer_dict=trainer_dict)

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
            res, reactuser = await utils.simple_ask(self.bot, question, ctx.message.channel, ctx.message.author.id)
        except TypeError:
            timeout = True
            res = None
        await question.delete()
        if timeout or res.emoji == '❎':
            return
        elif res.emoji == '✅':
            pass
        else:
            return
        try:
            self.bot.guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['trainer_dict'] = {}
            await ctx.channel.send('Raid status lists have been cleared!')
        except KeyError:
            pass

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @checks.raidchannel()
    async def setstatus(self, ctx, member: discord.Member, status, *, status_counts: str = ''):
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

    def get_existing_raid(self, guild, location, only_ex=False):
        """returns a list of channel ids for raids reported at the location provided"""
        report_dict = {k: v for k, v in self.bot.guild_dict[guild.id]['raidchannel_dict'].items()
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
            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        end = now + datetime.timedelta(
            seconds=self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] - time.time())
        timerstr = ' '
        if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', {}):
            end = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']['end']
            start = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']['start']
            if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
                if start:
                    timerstr += "This event will start at {expiry_time}"\
                        .format(expiry_time=start.strftime('%I:%M %p (%H:%M)'))
                else:
                    timerstr += "Nobody has told me a start time! Set it with **!starttime**"
                if end:
                    timerstr += " | This event will end at {expiry_time}"\
                        .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
            if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid':
                if end:
                    timerstr += "This event will end at {expiry_time}"\
                        .format(expiry_time=end.strftime('%I:%M %p (%H:%M)'))
                else:
                    timerstr += "Nobody has told me a end time! Set it with **!timerset**"
            return timerstr
        if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
            raidtype = 'egg'
            raidaction = 'hatch'
        else:
            raidtype = 'raid'
            raidaction = 'end'
        if not self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
            timerstr += "This {raidtype}'s timer has already expired as of {expiry_time}!"\
                .format(raidtype=raidtype, expiry_time=end.strftime('%I:%M %p (%H:%M)'))
        elif (self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel'] == 'EX') \
                or (self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'exraid'):
            if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
                timerstr += 'This {raidtype} will {raidaction} on {expiry}!'\
                    .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
            else:
                timerstr += "No one told me when the {raidtype} will {raidaction}, " \
                            "so I'm assuming it will {raidaction} on {expiry}!"\
                    .format(raidtype=raidtype, raidaction=raidaction, expiry=end.strftime('%I:%M %p (%H:%M)'))
        elif self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['manual_timer']:
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
        raid_type = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type']
        if (not checks.check_exraidchannel(ctx)) and not (checks.check_meetupchannel(ctx)):
            if raid_type == 'egg':
                raidlevel = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel']
                raidtype = 'Raid Egg'
                maxtime = self.bot.raid_info['raid_eggs'][raidlevel]['hatchtime']
            else:
                raidlevel = utils.get_level(self.bot,
                                            self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon'])
                raidtype = 'Raid'
                maxtime = self.bot.raid_info['raid_eggs'][raidlevel]['raidtime']
            raidexp = await utils.time_to_minute_count(self.bot.guild_dict, channel, timer)
            if raidexp is False:
                return
            if self._timercheck(raidexp, maxtime):
                self.bot.help_logger.info(f"User: {author.name}, channel: {channel},"
                                          f" error: raid expiration time too long")
                return await channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description=f"That's too long. Level {raidlevel} {raidtype.capitalize()}s "
                    f"currently last no more than {maxtime} minutes."))
            await self._timerset(channel, raidexp, update=True)
        if checks.check_exraidchannel(ctx):
            if checks.check_eggchannel(ctx) or checks.check_meetupchannel(ctx):
                now = datetime.datetime.utcnow() + datetime.timedelta(
                    hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
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
                    starttime = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup'].get('start', False)
                    if starttime and start < starttime:
                        await channel.send('Please enter a time after your start time.')
                        return
                diff = start - now
                total = diff.total_seconds() / 60
                if now <= start:
                    await self._timerset(channel, total)
                elif now > start:
                    await channel.send('Please enter a time in the future.')
            else:
                await channel.send("Timerset isn't supported for EX Raids after they have hatched.")

    @staticmethod
    def _timercheck(exp_time, maxtime):
        return exp_time > maxtime

    async def _timerset(self, raidchannel, exptime, to_print=True, update=False):
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        guild = raidchannel.guild
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        end = now + datetime.timedelta(minutes=exptime)
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][raidchannel.id]
        raid_dict['exp'] = time.time() + (exptime * 60)
        if not raid_dict['active']:
            await raidchannel.send('The channel has been reactivated.')
        raid_dict['active'] = True
        raid_dict['manual_timer'] = True
        topicstr = ''
        if raid_dict.get('meetup', {}):
            raid_dict['meetup']['end'] = end
            topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
            endtime = end.strftime('%I:%M %p (%H:%M)')
        elif raid_dict['type'] == 'egg':
            egglevel = raid_dict['egglevel']
            hatch = end
            end = hatch + datetime.timedelta(minutes=self.bot.raid_info['raid_eggs'][egglevel]['raidtime'])
            topicstr += 'Hatches at {expiry}'.format(expiry=hatch.strftime('%I:%M %p (%H:%M) | '))
            topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
            endtime = hatch.strftime('%I:%M %p (%H:%M)')
        else:
            topicstr += 'Ends at {end}'.format(end=end.strftime('%I:%M %p (%H:%M)'))
            egglevel = Pokemon.get_pokemon(self.bot, raid_dict['pokemon']).raid_level
            hatch = end - datetime.timedelta(minutes=self.bot.raid_info['raid_eggs'][egglevel]['raidtime'])
            endtime = end.strftime('%I:%M %p (%H:%M)')
        if to_print:
            timerstr = await self.print_raid_timer(raidchannel)
            await raidchannel.send(timerstr)
        await raidchannel.edit(topic=topicstr)
        report_channel = self.bot.get_channel(raid_dict['reportchannel'])
        raidmsg = await raidchannel.fetch_message(raid_dict['raidmessage'])
        reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
        for message in [raidmsg, reportmsg]:
            embed = message.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(embed)
            if raid_dict['type'] == "raid":
                exp_type = "expires"
            else:
                exp_type = "hatch"
            if embed_indices[exp_type] is not None:
                embed.set_field_at(embed_indices[exp_type],
                                   name=embed.fields[embed_indices[exp_type]].name, value=endtime)
            else:
                embed.add_field(name='**Expires:**' if exp_type == 'expires' else '**Hatches:**', value=endtime)
            if message == raidmsg:
                try:
                    await message.edit(content=message.content, embed=embed)
                except discord.errors.NotFound:
                    pass
            else:
                utils_cog = self.bot.cogs.get('Utilities')
                enabled = utils_cog.raid_channels_enabled(guild, raidchannel)
                embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices, enabled)
                try:
                    await message.edit(content=message.content, embed=embed)
                except discord.errors.NotFound:
                    pass
                if raid_dict.get('raidcityreport', None) is not None:
                    report_city_channel = self.bot.get_channel(raid_dict['reportcity'])
                    city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                    try:
                        await city_report.edit(new_content=city_report.content,
                                               embed=embed, content=city_report.content)
                    except:
                        pass
        await listmgmt_cog.update_listing_channels(guild, 'raid', edit=True, regions=raid_dict.get('regions', None))
        if update:
            with KyogreDB._db.atomic() as txn:
                try:
                    RaidTable.update(hatch_time=round(hatch.timestamp()), expire_time=round(end.timestamp()))\
                        .where(RaidTable.channel == raidchannel.id).execute()
                    txn.commit()
                except Exception as e:
                    self.bot.logger.info("Failed to update hatch and expire time for raid.")
                    txn.rollback()

    @commands.command()
    @checks.raidchannel()
    async def timer(self, ctx):
        """Have Kyogre resend the expire time message for a raid.

        **Usage**: `!timer`
        The expiry time should have been previously set with `!timerset`."""
        timerstr = await self.print_raid_timer(ctx.channel)
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
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
        now = datetime.datetime.utcnow() + datetime.timedelta(
            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        if start_time:
            maxtime, mintime, timeset = 0, 0, False
            exp_minutes = await utils.time_to_minute_count(self.bot.guild_dict, channel, start_time)
            if not exp_minutes:
                return
            if raid_dict['type'] == 'egg':
                egglevel = raid_dict['egglevel']
                mintime = (raid_dict['exp'] - time.time()) / 60
                maxtime = mintime + self.bot.raid_info['raid_eggs'][egglevel]['raidtime']
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
                query_change = await channel.send('There is already a start time of **{start}**! '
                                                  'Do you want to change it?'
                                                  .format(start=alreadyset.strftime('%I:%M %p (%H:%M)')))
                try:
                    timeout = False
                    res, reactuser = await utils.simple_ask(self.bot, query_change, channel, author.id)
                except TypeError:
                    timeout = True
                    res = None
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
                hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'],
                minutes=exp_minutes)
            if (exp_minutes and start > now) or timeset:
                raid_dict['starttime'] = start
                nextgroup = start.strftime('%I:%M %p (%H:%M)')
                if raid_dict.get('meetup', {}):
                    nextgroup = start.strftime('%I:%M %p (%H:%M)')
                await channel.send('The current start time has been set to: **{starttime}**'
                                   .format(starttime=nextgroup))
                report_channel = self.bot.get_channel(raid_dict['reportchannel'])
                raidmsg = await channel.fetch_message(raid_dict['raidmessage'])
                reportmsg = await report_channel.fetch_message(raid_dict['raidreport'])
                embed = raidmsg.embeds[0]
                embed_indices = await embed_utils.get_embed_field_indices(embed)
                embed.set_field_at(embed_indices['next'],
                                   name=embed.fields[embed_indices['next']].name, value=nextgroup, inline=True)
                try:
                    await raidmsg.edit(content=raidmsg.content, embed=embed)
                except discord.errors.NotFound:
                    pass
                try:
                    utils_cog = self.bot.cogs.get('Utilities')
                    enabled = utils_cog.raid_channels_enabled(ctx.guild, ctx.channel)
                    embed = await embed_utils.filter_fields_for_report_embed(embed, embed_indices, enabled)
                    await reportmsg.edit(content=reportmsg.content, embed=embed)
                except discord.errors.NotFound:
                    pass
                if raid_dict.get('raidcityreport', None) is not None:
                    report_city_channel = self.bot.get_channel(raid_dict['reportcity'])
                    city_report = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                    try:
                        await city_report.edit(new_content=city_report.content, embed=embed,
                                               content=city_report.content)
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
        if ctx.invoked_subcommand is None:
            message = ctx.message
            guild = message.guild
            channel = message.channel
            rc_d = self.bot.guild_dict[guild.id]['raidchannel_dict']
            raidmsg = await channel.fetch_message(rc_d[channel.id]['raidmessage'])
            location = rc_d[channel.id]['address']
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
            report_channel = self.bot.get_channel(self.bot.guild_dict[message.guild.id]['raidchannel_dict']
                                                  [channel.id]['reportcity'])
            if not report_channel:
                async for m in channel.history(limit=500, reverse=True):
                    if m.author.id == message.guild.me.id:
                        c = 'Coordinate here'
                        if c in m.content:
                            report_channel = m.raw_channel_mentions[0]
                            break
            details = ' '.join(location_split)
            utils_cog = self.bot.cogs.get('Utilities')
            regions = utils_cog.get_channel_regions(channel, 'raid')
            gym = None
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gyms = location_matching_cog.get_gyms(message.guild.id, regions)
            if gyms:
                gym = await location_matching_cog.match_prompt(channel, message.author.id, details, gyms)
                if not gym:
                    return await channel.send("I couldn't find a gym named '{0}'. Try again using the exact gym name!"
                                              .format(details))
            else:
                pass
            await entity_updates.update_raid_location(self.bot, self.bot.guild_dict, message,
                                                      report_channel, channel, gym)
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
        rc_d = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
        t_dict = rc_d['trainer_dict']
        can_manage = channel.permissions_for(author).manage_channels
        raidtype = "event" if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', False) \
            else "raid"
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
                res, reactuser = await utils.simple_ask(self.bot, rusure, channel, author.id)
            except TypeError:
                timeout = True
                res = None
            if not timeout:
                if res.emoji == '❎':
                    await rusure.delete()
                    confirmation = await channel.send('Duplicate Report cancelled.')
                    self.bot.logger.info((('Duplicate Report - Cancelled - ' + channel.name) + ' - Report by ')
                                         + author.name)
                    dupecount = 2
                    self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
                    await asyncio.sleep(10)
                    await confirmation.delete()
                    return
                elif res.emoji == '✅':
                    await rusure.delete()
                    await channel.send('Duplicate Confirmed')
                    self.bot.logger.info((('Duplicate Report - Channel Expired - ' + channel.name) +
                                          ' - Last Report by ') + author.name)
                    raidmsg = await channel.fetch_message(rc_d['raidmessage'])
                    reporter = raidmsg.mentions[0]
                    if 'egg' in raidmsg.content:
                        egg_reports = self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports']
                        self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['egg_reports'] \
                            = egg_reports - 1
                    elif 'EX' in raidmsg.content:
                        ex_reports = self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports']
                        self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['ex_reports'] \
                            = ex_reports - 1
                    else:
                        raid_reports = self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports']
                        self.bot.guild_dict[guild.id]['trainers'][regions[0]][reporter.id]['raid_reports'] \
                            = raid_reports - 1
                    await self.expire_channel(channel)
                    return
            else:
                await rusure.delete()
                confirmation = await channel.send('Duplicate Report Timed Out.')
                self.bot.logger.info((('Duplicate Report - Timeout - ' + channel.name) + ' - Report by ') + author.name)
                dupecount = 2
                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = dupecount
                await asyncio.sleep(10)
                await confirmation.delete()
        else:
            rc_d['duplicate'] = dupecount
            await channel.send('Duplicate report #{duplicate_report_count} received.'
                               .format(duplicate_report_count=str(dupecount)))
            self.bot.logger.info((((('Duplicate Report - ' + channel.name) + ' - Report #')
                                   + str(dupecount)) + '- Report by ') + author.name)
            return

    async def expire_channel(self, channel):
        guild = channel.guild
        alreadyexpired = False
        self.bot.logger.info('Expire_Channel - ' + channel.name)
        # If the channel exists, get ready to delete it.
        # Otherwise, just clean up the dict since someone
        # else deleted the actual channel at some point.
        channel_exists = self.bot.get_channel(channel.id)
        channel = channel_exists
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        if channel_exists is None and not self.bot.is_closed():
            try:
                del self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
            except KeyError:
                pass
            return
        elif channel_exists:
            dupechannel = False
            if not self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                alreadyexpired = True
            else:
                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active'] = False
            self.bot.logger.info('Expire_Channel - Channel Expired - ' + channel.name)
            dupecount = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('duplicate', 0)
            if dupecount >= 3:
                dupechannel = True
                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['duplicate'] = 0
                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] = time.time()
                if not alreadyexpired:
                    await channel.send(
                        'This channel has been successfully reported as a duplicate and will be deleted in 1 minute. '
                        'Check the channel list for the other raid channel to coordinate in!\n'
                        'If this was in error, reset the raid with **!timerset**')
                delete_time = (self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp']
                               + (1 * 60)) - time.time()
            elif self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg' and not \
                    self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', {}):
                if not alreadyexpired:
                    pkmn = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
                    if pkmn:
                        await self._eggtoraid(None, pkmn.lower(), channel)
                        return
                    maybe_list = []
                    trainer_dict = copy.deepcopy(
                        self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['trainer_dict'])
                    for trainer in trainer_dict.keys():
                        user = guild.get_member(trainer)
                        maybe_list.append(user.mention)
                    h = 'hatched-'
                    new_name = h if h not in channel.name else ''
                    new_name += channel.name
                    await channel.edit(name=new_name)
                    await channel.send("**This egg has hatched!**\n\nTrainers {trainer_list}: \
                    \nUse **!raid <pokemon>** to set the Raid Boss\
                    \nor **!timerset** to reset the hatch timer. \
                    \nThis channel will be deactivated until I get an update.".format(
                        trainer_list=', '.join(maybe_list)))
                delete_time = (self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp']
                               + (45 * 60)) - time.time()
                expiremsg = '**This level {level} raid egg has expired!**'.format(
                    level=self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel'])
            else:
                if not alreadyexpired:
                    e = 'expired-'
                    new_name = e if e not in channel.name else ''
                    new_name += channel.name
                    await channel.edit(name=new_name)
                    await channel.send(
                        'This channel timer has expired! The channel has been deactivated'
                        ' and will be deleted in 1 minute.\nTo reactivate the channel, '
                        'use **!timerset** to set the timer again.')
                delete_time = (self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] + (1 * 60)) \
                              - time.time()
                raidtype = "event" if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]\
                    .get('meetup', False) else " raid"
                expiremsg = '**This {pokemon}{raidtype} has expired!**'.format(
                    pokemon=self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon'].capitalize(),
                    raidtype=raidtype)
            await asyncio.sleep(delete_time)
            # If the channel has already been deleted from the dict, someone
            # else got to it before us, so don't do anything.
            # Also, if the channel got reactivated, don't do anything either.
            try:
                if (not self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']) \
                        and (not self.bot.is_closed()):
                    try:
                        short_id = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['short']
                        if short_id is not None:
                            region = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id] \
                                         .get('regions', [None])[0]
                            if region is not None:
                                so_channel_id = self.bot.guild_dict[guild.id]['configure_dict']['raid'].setdefault(
                                    'short_output', {}).get(region, None)
                                if so_channel_id is not None:
                                    so_channel = self.bot.get_channel(so_channel_id)
                                    if so_channel is not None:
                                        so_message = await so_channel.fetch_message(short_id)
                                        await so_message.delete()
                    except Exception as err:
                        self.bot.logger.info("Short message delete failed" + str(err))
                    if dupechannel:
                        try:
                            report_channel = self.bot.get_channel(
                                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                            reportmsg = await report_channel.fetch_message(
                                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                            await reportmsg.delete()
                        except:
                            pass
                    else:
                        try:
                            report_channel = self.bot.get_channel(
                                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['reportcity'])
                            reportmsg = await report_channel.fetch_message(
                                self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['raidreport'])
                            await reportmsg.edit(
                                embed=discord.Embed(description=expiremsg, colour=channel.guild.me.colour))
                            await reportmsg.clear_reactions()
                            regions = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('regions', None)
                            await listmgmt_cog.update_listing_channels(guild, 'raid', edit=True, regions=regions)
                        except:
                            pass
                        # channel doesn't exist anymore in serverdict
                    archive = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('archive', False)
                    logs = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('logs', {})
                    channel_exists = self.bot.get_channel(channel.id)
                    if channel_exists is None:
                        return
                    elif not archive and not logs:
                        try:
                            del self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
                        except KeyError:
                            pass
                        await channel_exists.delete()
                        self.bot.logger.info(
                            'Expire_Channel - Channel Deleted - ' + channel.name)
                    elif archive or logs:
                        # Todo: Fix this
                        """
                        # Overwrites were changed from Tuple -> Dict
                        # try:
                        #     for overwrite in channel.overwrites:
                        #         if isinstance(overwrite[0], discord.Role):
                        #             if overwrite[0].permissions.manage_guild 
                        or overwrite[0].permissions.manage_channels:
                        #                 await channel.set_permissions(overwrite[0], read_messages=True)
                        #                 continue
                        #         elif isinstance(overwrite[0], discord.Member):
                        #             if channel.permissions_for(overwrite[0]).manage_guild or 
                        channel.permissions_for(overwrite[0]).manage_channels:
                        #                 await channel.set_permissions(overwrite[0], read_messages=True)
                        #                 continue
                        #         if (overwrite[0].name not in guild.me.top_role.name) 
                        and (overwrite[0].name not in guild.me.name):
                        #             await channel.set_permissions(overwrite[0], read_messages=False)
                        #     for role in guild.role_hierarchy:
                        #         if role.permissions.manage_guild or role.permissions.manage_channels:
                        #             await channel.set_permissions(role, read_messages=True)
                        #         continue
                        #     await channel.set_permissions(guild.default_role, read_messages=False)
                        # except (discord.errors.Forbidden, discord.errors.HTTPException, 
                        discord.errors.InvalidArgument):
                        #     pass
                        """
                        new_name = 'archived-'
                        if new_name not in channel.name:
                            new_name += channel.name
                            category = self.bot.guild_dict[guild.id]['configure_dict'].get('archive', {})\
                                .get('category', 'same')
                            if category == 'same':
                                newcat = channel.category
                            else:
                                newcat = guild.get_channel(category)
                            await channel.edit(name=new_name, category=newcat)
                            await channel.send(
                                '-----------------------------------------------\n'
                                '**The channel has been archived and removed from view for everybody but Kyogre and '
                                'those with Manage Channel permissions. Any messages that were deleted after the '
                                'channel was marked for archival will be posted below. '
                                'You will need to delete this channel manually.**'
                                '\n-----------------------------------------------')
                            while logs:
                                earliest = min(logs)
                                embed = discord.Embed(colour=logs[earliest]['color_int'],
                                                      description=logs[earliest]['content'],
                                                      timestamp=logs[earliest]['created_at'])
                                if logs[earliest]['author_nick']:
                                    embed.set_author(name="{name} [{nick}]".format(name=logs[earliest]['author_str'],
                                                                                   nick=logs[earliest]['author_nick']),
                                                     icon_url=logs[earliest]['author_avy'])
                                else:
                                    embed.set_author(name=logs[earliest]['author_str'],
                                                     icon_url=logs[earliest]['author_avy'])
                                await channel.send(embed=embed)
                                del logs[earliest]
                                await asyncio.sleep(.25)
                            del self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
            except:
                pass

    async def channel_cleanup(self):
        while not self.bot.is_closed():
            active_raids = self.bot.active_raids
            guilddict_chtemp = copy.deepcopy(self.bot.guild_dict)
            self.bot.logger.info('Channel_Cleanup ------ BEGIN ------')
            # for every server in save data
            for guildid in guilddict_chtemp.keys():
                guild = self.bot.get_guild(guildid)
                log_str = 'Channel_Cleanup - Server: ' + str(guildid)
                log_str = log_str + ' - CHECKING FOR SERVER'
                if guild is None:
                    self.bot.logger.info(log_str + ': NOT FOUND')
                    continue
                self.bot.logger.info(((log_str + ' (') + guild.name) + ')  - BEGIN CHECKING SERVER')
                # clear channel lists
                dict_channel_delete = []
                discord_channel_delete = []
                # check every raid channel data for each server
                for channelid in guilddict_chtemp[guildid]['raidchannel_dict']:
                    channel = self.bot.get_channel(channelid)
                    log_str = 'Channel_Cleanup - Server: ' + guild.name
                    log_str = (log_str + ': Channel:') + str(channelid)
                    self.bot.logger.info(log_str + ' - CHECKING')
                    channelmatch = self.bot.get_channel(channelid)
                    if channelmatch is None:
                        # list channel for deletion from save data
                        dict_channel_delete.append(channelid)
                        self.bot.logger.info(log_str + " - NOT IN DISCORD")
                    # otherwise, if kyogre can still see the channel in discord
                    else:
                        self.bot.logger.info(
                            ((log_str + ' (') + channel.name) + ') - EXISTS IN DISCORD')
                        # if the channel save data shows it's not an active raid
                        if not guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['active']:
                            if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['type'] == 'egg':
                                # and if it has been expired for longer than 45 minutes already
                                if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] < (
                                        time.time() - (45 * 60)):
                                    # list the channel to be removed from save data
                                    dict_channel_delete.append(channelid)
                                    # and list the channel to be deleted in discord
                                    discord_channel_delete.append(channel)
                                    self.bot.logger.info(
                                        log_str + ' - 15+ MIN EXPIRY NONACTIVE EGG')
                                    continue
                                # and if it has been expired for longer than 1 minute already
                            elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] < (
                                    time.time() - (1 * 60)):
                                # list the channel to be removed from save data
                                dict_channel_delete.append(channelid)
                                # and list the channel to be deleted in discord
                                discord_channel_delete.append(channel)
                                self.bot.logger.info(
                                    log_str + ' - 5+ MIN EXPIRY NONACTIVE RAID')
                                continue
                            self.bot.event_loop.create_task(self.expire_channel(channel))
                            self.bot.logger.info(
                                log_str + ' - = RECENTLY EXPIRED NONACTIVE RAID')
                            continue
                        # if the channel save data shows it as an active raid still
                        elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['active']:
                            # if it's an exraid
                            if guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['type'] == 'exraid':
                                self.bot.logger.info(log_str + ' - EXRAID')

                                continue
                            # or if the expiry time for the channel has already passed within 5 minutes
                            elif guilddict_chtemp[guildid]['raidchannel_dict'][channelid]['exp'] <= time.time():
                                # list the channel to be sent to the channel expiry function
                                self.bot.event_loop.create_task(self.expire_channel(channel))
                                self.bot.logger.info(log_str + ' - RECENTLY EXPIRED')

                                continue

                            if channel not in active_raids:
                                # if channel is still active, make sure it's expiry is being monitored
                                self.bot.event_loop.create_task(self.expiry_check(channel))
                                self.bot.logger.info(
                                    log_str + ' - MISSING FROM EXPIRY CHECK')
                                continue
                # for every channel listed to have save data deleted
                for c in dict_channel_delete:
                    try:
                        # attempt to delete the channel from save data
                        del self.bot.guild_dict[guildid]['raidchannel_dict'][c]
                        self.bot.logger.info(
                            'Channel_Cleanup - Channel Savedata Cleared - ' + str(c))
                    except KeyError:
                        pass
                # for every channel listed to have the discord channel deleted
                for c in discord_channel_delete:
                    try:
                        # delete channel from discord
                        await c.delete()
                        self.bot.logger.info(
                            'Channel_Cleanup - Channel Deleted - ' + c.name)
                    except:
                        self.bot.logger.info(
                            'Channel_Cleanup - Channel Deletion Failure - ' + c.name)
                        pass
            # save server_dict changes after cleanup
            self.bot.logger.info('Channel_Cleanup - SAVING CHANGES')
            try:
                admin_commands_cog = self.bot.cogs.get('AdminCommands')
                if not admin_commands_cog:
                    return None
                await admin_commands_cog.save(guildid)
            except Exception as err:
                self.bot.logger.info('Channel_Cleanup - SAVING FAILED' + str(err))
            self.bot.logger.info('Channel_Cleanup ------ END ------')
            await asyncio.sleep(600)
            continue

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
        user = self.bot.guild_dict[guild.id].get('trainers', {}).setdefault('info', {})\
            .get(ctx.author.id, {}).get('pokebattlerid', None)
        if checks.check_raidchannel(ctx) and not checks.check_meetupchannel(ctx):
            if args:
                args_split = args.split()
                for arg in args_split:
                    if arg.isdigit():
                        user = arg
                        break
            try:
                await channel.fetch_message(self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
                                            .get('ctrsmessage', None))
            except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                pass
            pkmn = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('pokemon', None)
            weather = None
            movesetstr = ''
            if pkmn:
                if not user:
                    try:
                        ctrsmessage = await channel.fetch_message(self.bot.guild_dict[guild.id]
                                                                  ['raidchannel_dict'][channel.id]
                                                                  .get('ctrsmessage',None))
                        ctrsembed = ctrsmessage.embeds[0]
                        ctrsembed.remove_field(6)
                        ctrsembed.remove_field(6)
                        await channel.send(content=ctrsmessage.content, embed=ctrsembed)
                        return
                    except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                        pass
                moveset = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('moveset', 0)
                movesetstr = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]\
                    .get('ctrs_dict', {'enabled': False, 'auto_levels': []})\
                    .get(moveset, {}).get('moveset', "Unknown Moveset")
                weather = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('weather', None)
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
                    weather = next((w for w in weather_list if re.sub(rgx, '', w)
                                    in re.sub(rgx, '', args.lower())), None)
            pkmn = Pokemon.get_pokemon(self.bot, pkmn)
            return await counters_helpers._counters(ctx, self.bot, pkmn, user, weather, movesetstr)
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
                pkmn = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('pokemon', None)
            weather_list = ['none', 'extreme', 'clear', 'sunny', 'rainy',
                            'partlycloudy', 'cloudy', 'windy', 'snow', 'fog']
            weather = next((w for w in weather_list if re.sub(rgx, '', w) in re.sub(rgx, '', args.lower())), None)
            if not weather:
                weather = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('weather', None)
        else:
            pkmn = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('pokemon', None)
            weather = self.bot.guild_dict[guild.id]['raidchannel_dict'].get(channel.id, {}).get('weather', None)
        if not pkmn:
            await ctx.channel.send("You're missing some details! Be sure to enter a "
                                   "pokemon that appears in raids! Usage: **!counters <pkmn> [weather] [user ID]**")
            return
        pkmn = Pokemon.get_pokemon(self.bot, pkmn)
        await counters_helpers._counters(ctx, self.bot, pkmn, user, weather, "Unknown Moveset")

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
            guild_dict = self.bot.guild_dict
            guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['weather'] = weather.lower()
            pkmn = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id].get('pokemon', None)
            pkmn = Pokemon.get_pokemon(self.bot, pkmn)
            if pkmn:
                if str(pkmn.raid_level) in guild_dict[ctx.guild.id]['configure_dict']['counters']['auto_levels']:
                    ctrs_dict = await counters_helpers._get_generic_counters(self.bot, ctx.guild, pkmn, weather.lower())
                    try:
                        ctrsmessage = await ctx.channel.fetch_message(
                            guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['ctrsmessage'])
                        moveset = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['moveset']
                        newembed = ctrs_dict[moveset]['embed']
                        await ctrsmessage.edit(embed=newembed)
                    except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
                        pass
                    guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['ctrs_dict'] = ctrs_dict
            raid_message = guild_dict[ctx.guild.id]['raidchannel_dict'][ctx.channel.id]['raidmessage']
            raid_message = await ctx.channel.fetch_message(raid_message)
            embed = raid_message.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(embed)
            new_embed = embed
            gym_embed = embed.fields[embed_indices['gym']]
            gym_embed_value = '\n'.join(gym_embed.value.split('\n')[:2])
            gym_embed_value += "\n**Weather**: " + weather
            new_embed.set_field_at(embed_indices['gym'], name=gym_embed.name, value=gym_embed_value, inline=True)
            await raid_message.edit(embed=new_embed)
            await ctx.channel.send("Weather set to {}!".format(weather.lower()))
            updated_time = round(time.time())
            return await self._update_db_raid_report(ctx, ctx.channel, updated_time)

    async def expiry_check(self, channel):
        self.bot.logger.info('Expiry_Check - ' + channel.name)
        guild = channel.guild
        channel = self.bot.get_channel(channel.id)
        if channel not in self.bot.active_raids:
            self.bot.active_raids.append(channel)
            self.bot.logger.info(
                'Expire_Channel - Channel Added To Watchlist - ' + channel.name)
            await asyncio.sleep(0.5)
            while True:
                try:
                    if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id].get('meetup', {}):
                        now = datetime.datetime.utcnow() + datetime.timedelta(
                            hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
                        start = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']\
                            .get('start', False)
                        end = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['meetup']\
                            .get('end', False)
                        if start and self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
                            if start < now:
                                pokemon = self.bot.raid_info['raid_eggs']['EX']['pokemon'][0]
                                await self._eggtoraid(None, pokemon.lower(), channel, author=None)
                        if end and end < now:
                            self.bot.event_loop.create_task(self.bot.expire_channel(channel))
                            try:
                                self.bot.active_raids.remove(channel)
                            except ValueError:
                                self.bot.logger.info(
                                    'Expire_Channel - Channel Removal From Active Raid Failed - Not in List - '
                                    + channel.name)
                            self.bot.logger.info(
                                'Expire_Channel - Channel Expired And Removed From Watchlist - ' + channel.name)
                            break
                    elif self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['active']:
                        if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp']:
                            if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['exp'] <= time.time():
                                if self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['type'] == 'egg':
                                    pokemon = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['pokemon']
                                    egglevel = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]['egglevel']
                                    if not pokemon and len(self.bot.raid_info['raid_eggs'][egglevel]['pokemon']) == 1:
                                        pokemon = self.bot.raid_info['raid_eggs'][egglevel]['pokemon'][0]
                                    elif not pokemon and egglevel == "5" \
                                            and self.bot.guild_dict[guild.id]['configure_dict']['settings']\
                                            .get('regional', '').lower() \
                                            in self.bot.raid_info['raid_eggs']["5"]['pokemon']:
                                        pokemon = str(Pokemon.get_pokemon(self.bot, self.bot.guild_dict[guild.id]
                                            ['configure_dict']['settings']['regional']))
                                    if pokemon:
                                        self.bot.logger.info(
                                            'Expire_Channel - Egg Auto Hatched - ' + channel.name)
                                        try:
                                            self.bot.active_raids.remove(channel)
                                        except ValueError:
                                            self.bot.logger.info(
                                                'Expire_Channel - Channel Removal From Active Raid Failed - '
                                                'Not in List - ' + channel.name)
                                        await self._eggtoraid(None, pokemon.lower(), channel, author=None)
                                        break
                                self.bot.event_loop.create_task(self.expire_channel(channel))
                                try:
                                    self.bot.active_raids.remove(channel)
                                except ValueError:
                                    self.bot.logger.info(
                                        'Expire_Channel - Channel Removal From Active Raid Failed - '
                                        'Not in List - ' + channel.name)
                                self.bot.logger.info(
                                    'Expire_Channel - Channel Expired And Removed From Watchlist - ' + channel.name)
                                break
                except:
                    pass
                await asyncio.sleep(30)
                continue

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @checks.raidchannel()
    async def changeraid(self, ctx, newraid):
        """Changes raid boss.

        Usage: !changeraid <new pokemon or level>
        Only usable by admins."""
        message = ctx.message
        guild = message.guild
        channel = message.channel
        return await self.changeraid_internal(ctx, guild, channel, newraid)

    async def changeraid_internal(self, ctx, guild, channel, newraid):
        if (not channel) or (channel.id not in self.bot.guild_dict[guild.id]['raidchannel_dict']):
            await channel.send('The channel you entered is not a raid channel.')
            return
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict'][channel.id]
        if newraid.isdigit():
            raid_channel_name = '{egg_level}-egg_'.format(egg_level=newraid)
            raid_channel_name += utils.sanitize_name(raid_dict['address'])[:32]
            raid_dict['egglevel'] = newraid
            raid_dict['pokemon'] = ''
            changefrom = raid_dict['type']
            raid_dict['type'] = 'egg'
            egg_img = self.bot.raid_info['raid_eggs'][newraid]['egg_img']
            boss_list = []
            for entry in self.bot.raid_info['raid_eggs'][newraid]['pokemon']:
                p = Pokemon.get_pokemon(self.bot, entry)
                boss_list.append(
                    (((str(p) + ' (') + str(p.id)) + ') ') +
                    ''.join(utils.types_to_str(guild, p.types, self.bot.config)))
            raid_img_url = 'https://raw.githubusercontent.com/klords/Kyogre/master/images/eggs/{}?cache=0'.format(
                str(egg_img))
            raid_message = await channel.fetch_message(raid_dict['raidmessage'])
            report_channel = self.bot.get_channel(raid_dict['reportchannel'])
            report_message = await report_channel.fetch_message(raid_dict['raidreport'])
            raid_embed = raid_message.embeds[0]
            embed_indices = await embed_utils.get_embed_field_indices(raid_embed)
            if embed_indices["possible"] is not None:
                index = embed_indices["possible"]
                raid_embed.set_field_at(index, name="**Possible Bosses:**",
                                        value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
                if len(boss_list) > 2:
                    raid_embed.set_field_at(index + 1, name='\u200b',
                                            value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])),
                                            inline=True)
            else:
                raid_embed.add_field(name='**Possible Bosses:**',
                                     value='{bosslist1}'.format(bosslist1='\n'.join(boss_list[::2])), inline=True)
                if len(boss_list) > 2:
                    raid_embed.add_field(name='\u200b',
                                         value='{bosslist2}'.format(bosslist2='\n'.join(boss_list[1::2])), inline=True)
            raid_embed.set_thumbnail(url=raid_img_url)
            if changefrom == "egg":
                raid_message.content = re.sub(r'level\s\d', 'Level {}'.format(newraid), raid_message.content,
                                              flags=re.IGNORECASE)
                report_message.content = re.sub(r'level\s\d', 'Level {}'.format(newraid), report_message.content,
                                                flags=re.IGNORECASE)
            else:
                raid_message.content = re.sub(r'.*\sraid\sreported', 'Level {} reported'.format(newraid),
                                              raid_message.content, flags=re.IGNORECASE)
                report_message.content = re.sub(r'.*\sraid\sreported', 'Level {}'.format(newraid),
                                                report_message.content, flags=re.IGNORECASE)
            await raid_message.edit(new_content=raid_message.content, embed=raid_embed, content=raid_message.content)
            try:
                utils_cog = self.bot.cogs.get('Utilities')
                enabled = utils_cog.raid_channels_enabled(guild, channel)
                raid_embed = await embed_utils.filter_fields_for_report_embed(raid_embed, embed_indices, enabled)
                await report_message.edit(new_content=report_message.content, embed=raid_embed,
                                          content=report_message.content)
                if raid_dict.get('raidcityreport', None) is not None:
                    report_city_channel = self.bot.get_channel(raid_dict['reportcity'])
                    report_city_msg = await report_city_channel.fetch_message(raid_dict['raidcityreport'])
                    await report_city_msg.edit(new_content=report_city_msg.content, embed=raid_embed,
                                               content=report_city_msg.content)
            except (discord.errors.NotFound, AttributeError):
                pass
            await channel.edit(name=raid_channel_name, topic=channel.topic)
        elif newraid and not newraid.isdigit():
            # What a hack, subtract raidtime from exp time because _eggtoraid will add it back
            egglevel = raid_dict['egglevel']
            if egglevel == "0":
                egglevel = Pokemon.get_pokemon(self.bot, newraid).raid_level
            raid_dict['exp'] -= 60 * self.bot.raid_info['raid_eggs'][egglevel]['raidtime']
            author = None
            author_id = raid_dict.get('reporter', None)
            if author_id is not None:
                author = guild.get_member(author_id)
            await self._eggtoraid(ctx, newraid.lower(), channel, author=author)

    @commands.Cog.listener()
    @checks.good_standing()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        guild_dict = self.bot.guild_dict
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        try:
            user = guild.get_member(payload.user_id)
        except AttributeError:
            return
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        raid_dict = guild_dict[guild.id].setdefault('raidchannel_dict', {})
        if channel.id in guild_dict[guild.id]['raidchannel_dict']:
            if message.id == guild_dict[guild.id]['raidchannel_dict'][channel.id].get('ctrsmessage', None):
                ctrs_dict = guild_dict[guild.id]['raidchannel_dict'][channel.id]['ctrs_dict']
                for i in ctrs_dict:
                    if ctrs_dict[i]['emoji'] == str(payload.emoji):
                        newembed = ctrs_dict[i]['embed']
                        moveset = i
                        break
                else:
                    return
                await message.edit(embed=newembed)
                guild_dict[guild.id]['raidchannel_dict'][channel.id]['moveset'] = moveset
                await message.remove_reaction(payload.emoji, user)
            elif message.id == guild_dict[guild.id]['raidchannel_dict'][channel.id].get('raidmessage', None):
                if str(payload.emoji) == '\u2754':
                    prefix = guild_dict[guild.id]['configure_dict']['settings']['prefix']
                    prefix = prefix or self.bot.config['default_prefix']
                    avatar = self.bot.user.avatar_url
                    await utils.get_raid_help(prefix, avatar, user)
        if channel.id in raid_dict:
            raid_report = channel.id
        else:
            raid_report = self.get_raid_report(guild, message.id)
        if raid_report is not None:
            if raid_dict[raid_report].get('reporter', 0) == payload.user_id or utils.can_manage(user, self.bot.config):
                try:
                    await message.remove_reaction(payload.emoji, user)
                except:
                    pass
                if str(payload.emoji) == '\u270f':
                    await self.modify_raid_report(payload, raid_report)
                elif str(payload.emoji) == '🚫':
                    try:
                        await message.edit(embed=discord.Embed(description="Raid report cancelled",
                                                               colour=message.embeds[0].colour.value))
                        await message.clear_reactions()
                        await self._cancel_db_raid_report(raid_report)
                    except discord.errors.NotFound:
                        pass
                    report_channel = self.bot.get_channel(raid_report)
                    await report_channel.delete()
                    try:
                        del raid_dict[raid_report]
                    except:
                        pass
                    utils_cog = self.bot.cogs.get('Utilities')
                    regions = utils_cog.get_channel_regions(channel, 'raid')
                    await listmgmt_cog.update_listing_channels(guild, "raid", edit=True, regions=regions)

    def get_raid_report(self, guild, message_id):
        raid_dict = self.bot.guild_dict[guild.id]['raidchannel_dict']
        for raid in raid_dict:
            if raid_dict[raid]['raidreport'] == message_id:
                return raid
            if 'raidcityreport' in raid_dict[raid]:
                if raid_dict[raid]['raidcityreport'] == message_id:
                    return raid
        return None

    async def modify_raid_report(self, payload, raid_report):
        guild_dict = self.bot.guild_dict
        channel = self.bot.get_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        try:
            user = guild.get_member(payload.user_id)
        except AttributeError:
            return
        updated_time = round(time.time())
        raids_cog = self.bot.cogs.get('RaidCommands')
        raid_dict = guild_dict[guild.id].setdefault('raidchannel_dict', {})
        config_dict = guild_dict[guild.id]['configure_dict']
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'raid')
        raid_channel = channel.id
        if channel.id not in guild_dict[guild.id]['raidchannel_dict']:
            for rchannel in guild_dict[guild.id]['raidchannel_dict']:
                if raid_dict[rchannel]['raidreport'] == message.id:
                    raid_channel = rchannel
                    break
        raid_channel = self.bot.get_channel(raid_report)
        raid_report = raid_dict[raid_channel.id]
        report_channel_id = raid_report['reportchannel']
        report_channel = self.bot.get_channel(report_channel_id)
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        locationmatching_cog = self.bot.cogs.get('LocationMatching')
        gyms = locationmatching_cog.get_gyms(guild.id, regions)
        choices_list = ['Location', 'Hatch / Expire Time', 'Boss / Tier']
        gym = raid_report["address"]
        prompt = f'Modifying details for **raid** at **{gym}**\n' \
                 f'Which item would you like to modify ***{user.display_name}***?'
        match = await utils.ask_list(self.bot, prompt, channel, choices_list, user_list=user.id)
        err_msg = None
        success_msg = None
        if match in choices_list:
            # Updating location
            if match == choices_list[0]:
                query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                   description="What is the correct Location?"))
                try:
                    gymmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    await query_msg.delete()
                    gymmsg = None
                if not gymmsg:
                    error = "took too long to respond"
                elif gymmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await gymmsg.delete()
                elif gymmsg:
                    if gyms:
                        gym = await locationmatching_cog.match_prompt(channel, user.id, gymmsg.clean_content, gyms)
                        if not gym:
                            await channel.send(
                                embed=discord.Embed(
                                    colour=discord.Colour.red(),
                                    description=f"I couldn't find a gym named '{gymmsg.clean_content}'. "
                                                f"Try again using the exact gym name!"))
                            self.bot.help_logger.info(
                                f"User: {user.name}, channel: {channel}, error: Couldn't find gym with name: {gymmsg.clean_content}")
                        else:
                            location = gym.name
                            raid_channel_ids = raids_cog.get_existing_raid(guild, gym)
                            if raid_channel_ids:
                                raid_channel = self.bot.get_channel(raid_channel_ids[0])
                                if guild_dict[guild.id]['raidchannel_dict'][raid_channel.id]:
                                    await channel.send(
                                        embed=discord.Embed(
                                            colour=discord.Colour.red(),
                                            description=f"A raid has already been reported for {gym.name}"))
                                    self.bot.help_logger.info(
                                        f"User: {user.name}, channel: {channel}, error: Raid already reported.")
                            else:
                                await entity_updates.update_raid_location(self.bot, guild_dict, message,
                                                                          report_channel, raid_channel, gym)
                                await listmgmt_cog.update_listing_channels(guild, "raid", edit=True, regions=regions)
                                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                                       description="Raid location updated"))
                                await gymmsg.delete()
                                await query_msg.delete()

            # Updating time
            elif match == choices_list[1]:
                timewait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                  description="What is the Hatch / Expire time?"))
                try:
                    timemsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    timemsg = None
                    await timewait.delete()
                if not timemsg:
                    error = "took too long to respond"
                elif timemsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await timemsg.delete()
                raidexp = await utils.time_to_minute_count(guild_dict, raid_channel, timemsg.clean_content)
                if raidexp is not False:
                    await raids_cog._timerset(raid_channel, raidexp)
                await listmgmt_cog.update_listing_channels(guild, "raid", edit=True, regions=regions)
                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                       description="Raid hatch / expire time updated"))
                await timewait.delete()
                await timemsg.delete()
            # Updating boss
            elif match == choices_list[2]:
                bosswait = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                  description="What is the Raid Tier / Boss?"))
                try:
                    bossmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    bossmsg = None
                    await bosswait.delete()
                if not bossmsg:
                    error = "took too long to respond"
                elif bossmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await bossmsg.delete()
                await raids_cog.changeraid_internal(None, guild, raid_channel, bossmsg.clean_content)
                if not bossmsg.clean_content.isdigit():
                    await raids_cog._timerset(raid_channel, 45)
                await listmgmt_cog.update_listing_channels(guild, "raid", edit=True, regions=regions)
                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                       description="Raid Tier / Boss updated"))
                await bosswait.delete()
                await bossmsg.delete()
            await self._update_db_raid_report(guild, raid_channel, updated_time)
        else:
            return


def setup(bot):
    bot.add_cog(RaidCommands(bot))
