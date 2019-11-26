import os
import tempfile

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import *


class Location:
    def __init__(self, id, name, latitude, longitude, region, note):
        self.id = id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.region = region
        self.note = None
        if note is not None:
            self.note = note
    
    @property
    def coordinates(self):
        if self.latitude and self.longitude:
            return f"{self.latitude},{self.longitude}"
        return None
    
    @property
    def maps_url(self):
        if self.coordinates:
            query = self.coordinates
        else:
            query = self.name
            if self.region:
                query += f"+{'+'.join(self.region)}"
        return f"https://www.google.com/maps/search/?api=1&query={query}"


class Gym(Location):
    __name__ = "Gym"

    def __init__(self, id, name, latitude, longitude, region, ex_eligible, note):
        super().__init__(id, name, latitude, longitude, region, note)
        self.ex_eligible = ex_eligible


class Pokestop(Location):
    __name__ = "Pokestop"

    def __init__(self, id, name, latitude, longitude, region, note):
        super().__init__(id, name, latitude, longitude, region, note)


class LocationMatching(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_all(self, guild_id, regions=None):
        return self.get_gyms(guild_id, regions=regions) + self.get_stops(guild_id, regions=regions)

    @staticmethod
    def get_stop_by_id(guild_id, stop_id):
        try:
            result = (PokestopTable
                      .select(LocationTable.id,
                              LocationTable.name,
                              LocationTable.latitude,
                              LocationTable.longitude,
                              RegionTable.name.alias('region'),
                              LocationNoteTable.note)
                      .join(LocationTable)
                      .join(LocationRegionRelation)
                      .join(RegionTable)
                      .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                      .where((LocationTable.guild == guild_id) &
                             (LocationTable.guild == RegionTable.guild) &
                             (LocationTable.id == stop_id)))
            result = result.objects(Pokestop)
            return [o for o in result][0]
        except:
            return None

    @staticmethod
    def get_gym_by_id(guild_id, gym_id):
        try:
            result = (GymTable
                      .select(LocationTable.id,
                              LocationTable.name,
                              LocationTable.latitude,
                              LocationTable.longitude,
                              RegionTable.name.alias('region'),
                              GymTable.ex_eligible,
                              LocationNoteTable.note)
                      .join(LocationTable)
                      .join(LocationRegionRelation)
                      .join(RegionTable)
                      .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                      .where((LocationTable.guild == guild_id) &
                             (LocationTable.guild == RegionTable.guild) &
                             (LocationTable.id == gym_id)))
            result = result.objects(Gym)
            return [o for o in result][0]
        except:
            return None

    @staticmethod
    def get_gyms(guild_id, regions=None, ex=None):
        result = (GymTable
                  .select(LocationTable.id,
                          LocationTable.name,
                          LocationTable.latitude,
                          LocationTable.longitude,
                          RegionTable.name.alias('region'),
                          GymTable.ex_eligible,
                          LocationNoteTable.note)
                  .join(LocationTable)
                  .join(LocationRegionRelation)
                  .join(RegionTable)
                  .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                  .where((LocationTable.guild == guild_id) &
                         (LocationTable.guild == RegionTable.guild)))
        if regions:
            if not isinstance(regions, list):
                regions = [regions]
            result = result.where(RegionTable.name << regions)
        if ex:
            result = result.where(GymTable.ex_eligible == '1')
        result = result.objects(Gym)
        return [o for o in result]

    @staticmethod
    def get_stops(guild_id, regions=None):
        result = (PokestopTable
                  .select(LocationTable.id,
                          LocationTable.name,
                          LocationTable.latitude,
                          LocationTable.longitude,
                          RegionTable.name.alias('region'),
                          LocationNoteTable.note)
                  .join(LocationTable)
                  .join(LocationRegionRelation)
                  .join(RegionTable)
                  .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                  .where((LocationTable.guild == guild_id) &
                         (LocationTable.guild == RegionTable.guild)))
        if regions:
            if not isinstance(regions, list):
                regions = [regions]
            result = result.where(RegionTable.name << regions)
        result = result.objects(Pokestop)
        return [o for o in result]

    @staticmethod
    def location_match(name, locations, threshold=75, is_partial=True, limit=None):
        match = utils.get_match([l.name for l in locations], name, threshold, is_partial, limit)
        if not isinstance(match, list):
            match = [match]
        return [(l, score) for l in locations for match_name, score in match if l.name == match_name]
    
    @commands.command(hidden=True, aliases=["lmt"])
    @checks.is_dev_or_owner_or_perms(manage_nicknames=True)
    async def location_match_test(self, ctx, *, content=None):
        """**Usage**: `!lmt <type (stop/gym)>, <name>, [region]`
        **Alias**: `lmt`
        Looks up all locations with a name matching the one provided of the type provided.
        Can optionally be filtered to a particular region.
        """
        add_prefix = False
        if ',' not in content:
            return await ctx.send('Comma-separated type and name are required')
        loc_type, name, *regions = [c.strip() for c in content.split(',')]
        if not name or not loc_type:
            return await ctx.send('Type and name are required')
        loc_type = loc_type.lower()
        if 'stop' in loc_type:
            locations = self.get_stops(ctx.guild.id, regions)
        elif loc_type.startswith('gym'):
            locations = self.get_gyms(ctx.guild.id, regions)
        else:
            add_prefix = True
            locations = self.get_all(ctx.guild.id, regions)
        if not locations:
            await ctx.send('Location matching has not been set up for this server.')
            return        
        result = self.location_match(name, locations)
        if not result:
            result_str = 'No matches found!'
        else:
            result_str = f'{len(result)} result(s) found for **{loc_type}** matching query "**{name}**"'
            if len(regions) > 0:
                result_str += f' within region(s) **{", ".join(regions)}**:\n\n'
            else:
                result_str += ':\n\n'
            result_str += '\n'.join([f"{f'[{l.__name__}] ' if add_prefix else ''}{l.name} {score} "
                                    f"({l.latitude}, {l.longitude}) {l.region}" for l, score in result])
        for i in range(len(result_str) // 1999 + 1):
            await ctx.send(result_str[1999*i:1999*(i+1)])

    @commands.command(name="lmts", aliases=['smt'])
    @checks.is_dev_or_owner_or_perms(manage_nicknames=True)
    async def stop_match_test(self, ctx, *, content=None):
        if content is None:
            return
        return await ctx.invoke(self.bot.get_command('lmt'), content=f"stop, {content}")

    @commands.command(name="lmtg", aliases=['gmt'])
    @checks.is_dev_or_owner_or_perms(manage_nicknames=True)
    async def gym_match_test(self, ctx, *, content=None):
        if content is None:
            return
        return await ctx.invoke(self.bot.get_command('lmt'), content=f"gym, {content}")

    @staticmethod
    def _get_location_info_output(result, locations):
        match, score = result
        location_info = locations[match]
        coords = location_info['coordinates']
        notes = location_info.get('notes', 'No notes for this location.')
        location_info_str = f"**Coordinates:** {coords}\n**Notes:** {notes}"
        return (f"Successful match with `{match}` "
                f"with a score of `{score}`\n{location_info_str}")

    @staticmethod
    def __process(location_type, locations):
        result = []
        for name, data in locations.items():
            coords = data['coordinates'].split(',')
            if location_type == "gym":
                result.append(Gym(name, coords[0], coords[1], None, data['ex_eligible']))
            elif location_type == "stop":
                result.append(Pokestop(name, coords[0], coords[1], None))
        return result

    @staticmethod
    def save_stops_to_json(guild_id):
        try:
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(os.path.join('data', 'pokestop_data_backup1')),
                                             delete=False) as f:
                stops = (PokestopTable
                         .select(LocationTable.id,
                                 LocationTable.name,
                                 LocationTable.latitude,
                                 LocationTable.longitude,
                                 RegionTable.name.alias('region'),
                                 LocationNoteTable.note)
                         .join(LocationTable)
                         .join(LocationRegionRelation)
                         .join(RegionTable)
                         .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                         .where((LocationTable.guild == guild_id) &
                                (LocationTable.guild == RegionTable.guild)))
                stops = stops.objects(Location)
                s = {}
                for stop in stops:
                    if stop.name in s:
                        try:
                            s[stop.name]["notes"].append(stop.note)
                        except:
                            pass
                        try:
                            s[stop.name]["notes"] = [stop.note]
                        except:
                            pass
                    else:
                        s[stop.name] = {}
                        s[stop.name]["coordinates"] = f"{stop.latitude},{stop.longitude}"
                        s[stop.name]["region"] = stop.region
                        s[stop.name]["guild"] = str(guild_id)
                        try:
                            s[stop.name]["notes"] = [stop.note]
                        except:
                            pass
                f.write(json.dumps(s, indent=4))
                tempname = f.name
            try:
                os.remove(os.path.join('data', 'pokestop_data_backup1'))
            except OSError as e:
                pass
            try:
                os.rename(os.path.join('data', 'pokestop_data_backup1'), os.path.join('data', 'pokestop_data_backup2'))
            except OSError as e:
                pass
            os.rename(tempname, os.path.join('data', 'pokestop_data_backup1'))
            return None
        except Exception as err:
            return err

    @staticmethod
    def save_gyms_to_json(guild_id):
        try:
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(os.path.join('data', 'gym_data_backup1')), delete=False) as f:
                gyms = (GymTable
                        .select(LocationTable.id,
                                LocationTable.name,
                                LocationTable.latitude,
                                LocationTable.longitude,
                                RegionTable.name.alias('region'),
                                GymTable.ex_eligible,
                                LocationNoteTable.note)
                        .join(LocationTable)
                        .join(LocationRegionRelation)
                        .join(RegionTable)
                        .join(LocationNoteTable, JOIN.LEFT_OUTER, on=(LocationNoteTable.location_id == LocationTable.id))
                        .where((LocationTable.guild == guild_id) &
                                (LocationTable.guild == RegionTable.guild)))
                gyms = gyms.objects(Gym)
                g = {}
                for gym in gyms:
                    if gym.name in g:
                        try:
                            g[gym.name]["notes"].append(gym.note)
                        except:
                            pass
                        try:
                            g[gym.name]["notes"] = [gym.note]
                        except:
                            pass
                    else:
                        g[gym.name] = {}
                        g[gym.name]["coordinates"] = f"{gym.latitude},{gym.longitude}"
                        g[gym.name]["ex_eligible"] = gym.ex_eligible
                        g[gym.name]["region"] = gym.region
                        g[gym.name]["guild"] = str(guild_id)
                        try:
                            g[gym.name]["notes"] = [gym.note]
                        except:
                            pass
                f.write(json.dumps(g, indent=4))
                tempname = f.name
            try:
                os.remove(os.path.join('data', 'gym_data_backup1'))
            except OSError as e:
                pass
            try:
                os.rename(os.path.join('data', 'gym_data_backup1'), os.path.join('data', 'gym_data_backup2'))
            except OSError as e:
                pass
            os.rename(tempname, os.path.join('data', 'gym_data_backup1'))
            return None
        except Exception as err:
            return err

    @commands.command(name='gyminfo', aliases=['gym', 'gi'])
    async def _gym(self, ctx, *, info):
        """**Usage**: `!gyminfo <gym name>`
        **Aliases**: `gym`, `gi`
        Look up directions to a gym by providing its name.
        Gym name provided should be as close as possible to the name displayed in game."""
        message = ctx.message
        channel = ctx.channel
        guild = ctx.guild
        info = info.split(',')
        info = [i.strip() for i in info]
        name, region = None, None
        if len(info) > 1:
            region = info[-1:]
            name = ','.join(info[:-1])
        else:
            name = info[0]
        gyms = self.get_gyms(guild.id, region)
        gym = await self.match_prompt(channel, message.author.id, name, gyms)
        if not gym:
            region_desc = '. '
            if region is not None:
                region_desc = f" in the '{region[0]}' region. "
            desc = f"No gym found with name '{name}'{region_desc}Try again using the exact gym name!"
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description=desc))
        else:
            gym_embed = discord.Embed(colour=guild.me.colour)
            utils_cog = self.bot.cogs.get('Utilities')
            waze_link = utils_cog.create_waze_query(gym.latitude, gym.longitude)
            apple_link = utils_cog.create_applemaps_query(gym.latitude, gym.longitude)
            location_str = f'[Google]({gym.maps_url}) | [Waze]({waze_link}) | [Apple]({apple_link})'
            ex_eligible = ''
            if gym.ex_eligible:
                ex_eligible = '\n*This is an EX Eligible gym.*'
            gym_notes = ''
            if gym.note is not None:
                gym_notes = f"\n**Notes:** {gym.note}"
            gym_info = f"**Name:** {gym.name}{ex_eligible}\n**Region:** {gym.region.title()}" \
                       f"\n**Directions:** {location_str}{gym_notes}"
            gym_embed.add_field(name='**Gym Information**', value=gym_info, inline=False)
            return await channel.send(content="", embed=gym_embed)

    @commands.command(name='pokestopinfo', aliases=['pokestop', 'pi'])
    async def _pokestop(self, ctx, *, info):
        """**Usage**: `!pokestopinfo <pokestop name>`
        **Aliases**: `pokestop`, `pi`
        Look up directions to a pokestop by providing its name.
        Pokestop name provided should be as close as possible to the name displayed in game."""
        message = ctx.message
        channel = ctx.channel
        guild = ctx.guild
        info = info.split(',')
        info = [i.strip() for i in info]
        name, region = None, None
        if len(info) > 1:
            region = info[-1:]
            name = ','.join(info[:-1])
        else:
            name = info[0]
        stops = self.get_stops(guild.id, region)
        stop = await self.match_prompt(channel, message.author.id, name, stops)
        if not stop:
            region_desc = '. '
            if region is not None:
                region_desc = f" in the '{region[0]}' region. "
            desc = f"No Pokestop found with name '{name}'{region_desc}Try again using the exact gym name!"
            return await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                          description=desc))
        else:
            gym_embed = discord.Embed(colour=guild.me.colour)
            utils_cog = self.bot.cogs.get('Utilities')
            waze_link = utils_cog.create_waze_query(stop.latitude, stop.longitude)
            apple_link = utils_cog.create_applemaps_query(stop.latitude, stop.longitude)
            location_str = f'[Google]({stop.maps_url}) | [Waze]({waze_link}) | [Apple]({apple_link})'
            gym_notes = ''
            if stop.note is not None:
                gym_notes = f"\n**Notes:** {stop.note}"
            gym_info = f"**Name:** {stop.name}\n**Region:** {stop.region.title()}" \
                       f"\n**Directions:** {location_str}{gym_notes}"
            gym_embed.add_field(name='**Pokestop Information**', value=gym_info, inline=False)
            return await channel.send(content="", embed=gym_embed)

    @commands.command(name='ex_gyms', aliases=['exgym', 'exgyms', 'exg'])
    async def _ex_gym_lookup(self, ctx, region: str = None):
        """**Usage**: `!ex_gyms [region]`
        **Aliases**: `exgym`, `exgyms`, `exg`
        Look up all EX Eligible gyms.
        Region is optional *but recommended*.
        If a region is provided the resulting list will contain only gyms in that region."""
        gyms = self.get_gyms(ctx.guild.id, region.lower(), True)
        if len(gyms) < 1:
            return await ctx.send("No EX gyms found.")
        region_str = ' (you may want to specify a region when running this command)'
        if region:
            region_str = f' in {region.capitalize()}'
        embeds = []
        embed = discord.Embed(colour=discord.Colour.gold(), title=f"EX Gyms{region_str}")
        utils_cog = self.bot.cogs.get('Utilities')
        length_count = 0
        for gym in gyms:
            if len(embed.fields) == 25 or length_count >= 5500:
                embeds.append(embed)
                embed = discord.Embed(colour=discord.Colour.gold())
                length_count = 0
            waze_link = utils_cog.create_waze_query(gym.latitude, gym.longitude)
            apple_link = utils_cog.create_applemaps_query(gym.latitude, gym.longitude)
            location_str = f'[Google]({gym.maps_url}) | [Waze]({waze_link}) | [Apple]({apple_link})'
            name_text = f"{gym.name}"
            if not region:
                name_text += f" ({gym.region.capitalize()})"
            length_count += len(name_text) + len(location_str)
            embed.add_field(name=name_text, value=f"{location_str}", inline=False)
        embeds.append(embed)
        for e in embeds:
            await ctx.send(embed=e)

    async def match_prompt(self, channel, author_id, name, locations):
        # note: the following logic assumes json constraints -- no duplicates in source data
        result = self.location_match(name, locations)
        results = [(match.name, score) for match, score in result]
        match = await utils.prompt_match_result(self.bot, channel, author_id, name, results)
        return next((l for l in locations if l.name == match), None)


def setup(bot):
    bot.add_cog(LocationMatching(bot))
