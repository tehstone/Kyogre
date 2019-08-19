import discord
from discord.ext import commands

from kyogre import utils
from kyogre.exts.db.kyogredb import KyogreDB, RegionTable, GymTable, PokestopTable
from kyogre.exts.db.kyogredb import LocationTable, LocationRegionRelation


class LocationManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="loc")
    async def _loc(self, ctx):
        """Location data management command"""
        if ctx.invoked_subcommand is None:
            raise commands.BadArgument()

    @_loc.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def _loc_add(self, ctx, *, info):
        """**Usage**: `!loc add <type (gym/stop)>, <name>, <latitude>, <longitude>, <region>, [ex_eligible]`
        Adds a new location to the database. ex_eligible is optional, all other are required.
        *Order of information must be completely correct*."""
        channel = ctx.channel
        message = ctx.message
        ex_eligible = None
        error_msg = "Please provide the following when using this command: " \
                    "`location type, name, latitude, longitude, region, (optional) ex eligible`"
        try:
            if ',' in info:
                info_split = info.split(',')
                if len(info_split) == 5:
                    loc_type, name, latitude, longitude, region = [x.strip() for x in info.split(',')]
                    error_msg = None
                elif len(info_split) == 6:
                    loc_type, name, latitude, longitude, region, ex_eligible = [x.strip() for x in info.split(',')]
                    error_msg = None
        except:
            pass
        if error_msg is not None:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: Insufficient info: {info}.")
            await channel.send(error_msg, delete_after=12)
            return await message.add_reaction(self.bot.success_react)
        data = {"coordinates": f"{latitude},{longitude}"}
        if loc_type == "gym":
            if ex_eligible is not None:
                data["ex_eligible"] = bool(ex_eligible)
            else:
                data["ex_eligible"] = False
        data["region"] = region.lower()
        data["guild"] = str(ctx.guild.id)
        try:
            region = RegionTable.get(RegionTable.name == region.lower())
        except Exception as e:
            error_msg = f"No region found with name: **{region}**. \n"
        if not error_msg:
            error_msg = LocationTable.create_location(name, data)
        if error_msg is None:
            await channel.send(embed=discord.Embed(
                colour=discord.Colour.green(),
                description=f"Successfully added **{loc_type}** with name: **{name}**."),
                delete_after=12)
            return await message.add_reaction(self.bot.success_react)
        else:
            await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description=error_msg + f"Failed to add **{loc_type}** with name: **{name}**."),
                delete_after=12)
            return await message.add_reaction(self.bot.failed_react)

    @_loc.command(name="convert", aliases=["c"])
    @commands.has_permissions(manage_roles=True)
    async def _loc_convert(self, ctx, *, info):
        """**Usage**: `!loc convert <pokestop>`
        **Alias**: `c`
        Changes a pokestop into a gym."""
        channel = ctx.channel
        author = ctx.message.author
        stops = self._get_stops(ctx.guild.id, None)
        stop = await self._location_match_prompt(channel, author.id, info, stops)
        if not stop:
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"No pokestop found with name **{info}**"),
                               delete_after=12)
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: No Pokestop found with name: {info}.")
            return await ctx.message.add_reaction(self.bot.failed_react)
        result = await self.stop_to_gym(ctx, stop.name)
        if result[0] == 0:
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"Failed to convert stop to gym."),
                               delete_after=12)
            return await ctx.message.add_reaction(self.bot.failed_react)
        else:
            await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                   description=f"Converted {result[0]} stop(s) to gym(s)."),
                               delete_after=12)
            return await ctx.message.add_reaction(self.bot.success_react)

    @_loc.command(name="extoggle", aliases=["ext"])
    @commands.has_permissions(manage_roles=True)
    async def _loc_extoggle(self, ctx, *, info):
        """**Usage**: `!loc extoggle/ext <gym>`
        **Alias**: `ext`
        Toggles the ex status of the provided gym."""
        channel = ctx.channel
        author = ctx.message.author
        gyms = self._get_gyms(ctx.guild.id, None)
        gym = await self._location_match_prompt(channel, author.id, info, gyms)
        if not gym:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: No Gym found with name: {info}.")
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"No gym found with name {info}"),
                               delete_after=15)
            return await ctx.message.add_reaction(self.bot.failed_react)
        result = await self.toggle_ex(ctx, gym.name)
        if result == 0:
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"Failed to change gym's EX status."),
                               delete_after=15)
            await ctx.message.add_reaction(self.bot.failed_react)        
            return
        else:
            await channel.send(embed=discord.Embed(
                colour=discord.Colour.green(),
                description=f"Successfully changed EX status for {result} gym(s)."), delete_after=15)
            await ctx.message.add_reaction(self.bot.success_react)
            return

    @_loc.command(name="changeregion", aliases=["cr"])
    @commands.has_permissions(manage_nicknames=True)
    async def _loc_change_region(self, ctx, *, info):
        """**Usage**: `!loc changeregion/cr <type (stop/gym)>, <name>, <region>`
        **Alias**: 'cr'
        Changes the region of the provided location to the one provided."""
        channel = ctx.channel
        message = ctx.message
        author = message.author
        info = [x.strip() for x in info.split(',')]
        stop, gym = None, None
        if len(info) != 3:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: Insufficient info: {info}.")
            await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"Please provide (comma separated) the location type (stop or gym), "
                            f"name of the Pokestop or gym, and the new region it should be assigned to."),
                delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        if info[0].lower() == "stop":
            stops = self._get_stops(ctx.guild.id, None)
            stop = await self._location_match_prompt(channel, author.id, info[1], stops)
            if stop is not None:
                name = stop.name
        elif info[0].lower() == "gym":
            gyms = self._get_gyms(ctx.guild.id, None)
            gym = await self._location_match_prompt(channel, author.id, info[1], gyms)
            if gym is not None:
                name = gym.name
        if not stop and not gym:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: No {info[0]} found with name: {info[1]}.")
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"No {info[0]} found with name {info[1]}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        region = info[2]
        regions = self.bot.guild_dict[ctx.guild.id]['configure_dict'].get('regions', [])
        if region not in regions:
            if region.lower() in regions:
                region = region.lower()
            else:
                await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                       description=f"No {info[0]} found with name {info[1]}."),
                                   delete_after=12)
                return await message.add_reaction(self.bot.failed_react)
        result = await self.change_region(ctx, name, region)
        if result == 0:
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"Failed to change location for {name}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        else:
            await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                   description=f"Successfully changed location for {name}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.success_react)

    @_loc.command(name="deletelocation", aliases=["del"])
    @commands.has_permissions(manage_guild=True)
    async def _loc_deletelocation(self, ctx, *, info):
        """**Usage**: `!loc del <type (stop/gym), <name>`
        **Alias**: `del`
        Delete the location provided if found.
        Does not prompt for confirmation, will delete as soon as the correct stop or gym is identified."""
        channel = ctx.channel
        message = ctx.message
        author = message.author
        info = info.split(',')
        if len(info) != 2:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: Insufficient info: {info}.")
            await channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"Please provide (comma separated) the location type "
                            f"(stop or gym) and the name of the Pokestop or gym."),
                delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        loc_type = info[0].lower()
        stop = None
        gym = None
        if loc_type == "stop":
            stops = self._get_stops(ctx.guild.id, None)
            stop = await self._location_match_prompt(channel, author.id, info[1], stops)
            if stop is not None:
                name = stop.name
        elif loc_type == "gym":
            gyms = self._get_gyms(ctx.guild.id, None)
            gym = await self._location_match_prompt(channel, author.id, info[1], gyms)
            if gym is not None:
                name = gym.name
        if not stop and not gym:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, "
                                      f"error: No {info[0]} found with name: {info[1]}.")
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"No {info[0]} found with name {info[1]}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        result = await self.delete_location(ctx, loc_type, name)
        if result == 0:
            await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                   description=f"Failed to delete {loc_type}: {name}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.failed_react)
        else:
            await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                   description=f"Successfully deleted {loc_type}: {name}."),
                               delete_after=12)
            return await message.add_reaction(self.bot.success_react)

    @staticmethod
    async def delete_location(ctx, location_type, name):
        channel = ctx.channel
        guild = ctx.guild
        deleted = 0
        with KyogreDB._db.atomic() as txn:
            try:
                locationresult = (LocationTable
                    .get((LocationTable.guild == guild.id) &
                           (LocationTable.name == name)))
                location = LocationTable.get_by_id(locationresult)
                loc_reg = (LocationRegionRelation
                    .get(LocationRegionRelation.location_id == locationresult))
                if location_type == "stop":
                    deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
                elif location_type == "gym":
                    deleted = GymTable.delete().where(GymTable.location_id == locationresult).execute()
                deleted += LocationRegionRelation.delete().where(LocationRegionRelation.id == loc_reg).execute()
                deleted += location.delete_instance()
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return deleted

    @staticmethod
    async def stop_to_gym(ctx, name):
        channel = ctx.channel
        guild = ctx.guild
        deleted = 0
        created = 0
        with KyogreDB._db.atomic() as txn:
            try:
                locationresult = (LocationTable
                                  .get((LocationTable.guild == guild.id) & (LocationTable.name == name)))
                deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
                location = LocationTable.get_by_id(locationresult)
                created = GymTable.create(location=location, ex_eligible=False)
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return (deleted, created)

    @staticmethod
    async def toggle_ex(ctx, name):
        channel = ctx.channel
        guild = ctx.guild
        success = 0
        with KyogreDB._db.atomic() as txn:
            try:
                locationresult = (LocationTable
                    .get((LocationTable.guild == guild.id) &
                           (LocationTable.name == name)))
                location = LocationTable.get_by_id(locationresult)
                success = GymTable.update(ex_eligible=~GymTable.ex_eligible).where(GymTable.location_id == location.id).execute()
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return success

    @staticmethod
    async def change_region(ctx, name, region):
        success = 0
        with KyogreDB._db.atomic() as txn:
            try:
                current = (LocationTable
                           .select(LocationTable.id.alias('loc_id'))
                           .join(LocationRegionRelation)
                           .join(RegionTable)
                           .where((LocationTable.guild == ctx.guild.id) &
                                  (LocationTable.guild == RegionTable.guild) &
                                  (LocationTable.name == name)))
                loc_id = current[0].loc_id
                current = (RegionTable
                           .select(RegionTable.id.alias('reg_id'))
                           .join(LocationRegionRelation)
                           .join(LocationTable)
                           .where((LocationTable.guild == ctx.guild.id) &
                                  (LocationTable.guild == RegionTable.guild) &
                                  (LocationTable.id == loc_id)))
                reg_id = current[0].reg_id
                deleted = LocationRegionRelation.delete().where((LocationRegionRelation.location_id == loc_id) &
                                                                (LocationRegionRelation.region_id == reg_id)).execute()
                new = (RegionTable
                       .select(RegionTable.id)
                       .where((RegionTable.name == region) &
                              (RegionTable.guild_id == ctx.guild.id)))
                success = LocationRegionRelation.create(location=loc_id, region=new[0].id)
            except Exception as e: 
                await ctx.channel.send(e)
                txn.rollback()
        return success

    async def _location_match_prompt(self, channel, author_id, name, locations):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        return await location_matching_cog.match_prompt(channel, author_id, name, locations)

    def _get_stops(self, guild_id, regions=None):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        if not location_matching_cog:
            return None
        return location_matching_cog.get_stops(guild_id, regions)

    def _get_gyms(self, guild_id, regions=None):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        if not location_matching_cog:
            return None
        return location_matching_cog.get_gyms(guild_id, regions)


def setup(bot):
    bot.add_cog(LocationManagement(bot))
