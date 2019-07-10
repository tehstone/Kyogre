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
        if ctx.invoked_subcommand == None:
            raise commands.BadArgument()

    @_loc.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def _loc_add(self, ctx, *, info):
        """Adds a new location to the database

        Requires type (gym/stop), name, latitude, longitude, region name in that order.
        Optionally a true/false for ex eligibility can be provided as well."""
        channel = ctx.channel
        message = ctx.message
        ex_eligible = None
        error_msg = "Please provide the following when using this command: `location type, name, latitude, longitude, region, (optional) ex eligible`"
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
            return await channel.send(error_msg)
        data = {}
        data["coordinates"] = f"{latitude},{longitude}"
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
            success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully added **{loc_type}** with name: **{name}**."))
            await message.add_reaction('✅')
            return await utils.sleep_and_cleanup([success], 10)
        else:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=error_msg + f"Failed to add **{loc_type}** with name: **{name}**."))
            await message.add_reaction('❌')   
            return await utils.sleep_and_cleanup([failed], 10)


    @_loc.command(name="convert", aliases=["c"])
    @commands.has_permissions(manage_guild=True)
    async def _loc_convert(self, ctx, *, info):
        """Changes a pokestop into a gym

        Requires the name of a Pokestop."""
        channel = ctx.channel
        author = ctx.message.author
        stops = self._get_stops(ctx.guild.id, None)
        stop = await self._location_match_prompt(channel, author.id, info, stops)
        if not stop:
            no_stop_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No pokestop found with name **{info}**"))
            return await utils.sleep_and_cleanup([no_stop_msg], 10)
        result = await self.stopToGym(ctx, stop.name)
        if result[0] == 0:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to convert stop to gym."))
            await ctx.message.add_reaction('❌') 
            return await utils.sleep_and_cleanup([failed], 10)       
        else:
            success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Converted {result[0]} stop(s) to gym(s)."))
            await ctx.message.add_reaction('✅')
            return await utils.sleep_and_cleanup([success], 10)


    @_loc.command(name="extoggle", aliases=["ext"])
    @commands.has_permissions(manage_guild=True)
    async def _loc_extoggle(self, ctx, *, info):
        """Toggles gym ex status

        Requires the name of a gym. Ex status can't be set directly,
        only swapped from its current state."""
        channel = ctx.channel
        author = ctx.message.author
        gyms = self._get_gyms(ctx.guild.id, None)
        gym = await self._location_match_prompt(channel, author.id, info, gyms)
        if not gym:
            no_gym_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No gym found with name {info}"), delete_after=15)
            return
        result = await self.toggleEX(ctx, gym.name)
        if result == 0:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to change gym's EX status."), delete_after=15)
            await ctx.message.add_reaction('❌')        
            return
        else:
            success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully changed EX status for {result} gym(s)."), delete_after=15)
            await ctx.message.add_reaction('✅')
            return


    @_loc.command(name="changeregion", aliases=["cr"])
    @commands.has_permissions(manage_guild=True)
    async def _loc_change_region(self, ctx, *, info):
        """Changes the region associated with a Location.

        Requires type (stop/gym), the name of the location,
        and the name of the new region it should be assigned to."""
        channel = ctx.channel
        message = ctx.message
        author = message.author
        info = [x.strip() for x in info.split(',')]
        stop, gym = None, None
        if len(info) != 3:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Please provide (comma separated) the location type (stop or gym), name of the Pokestop or gym, and the new region it should be assigned to."))
            await message.add_reaction('❌')
            return await utils.sleep_and_cleanup([failed], 10)
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
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No {info[0]} found with name {info[1]}."))
            await message.add_reaction('❌')        
            return await utils.sleep_and_cleanup([failed], 10)
        result = await self.changeRegion(ctx, name, info[2])
        if result == 0:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to change location for {name}."))
            await message.add_reaction('❌')        
            return await utils.sleep_and_cleanup([failed], 10)
        else:
            success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully changed location for {name}."))
            await message.add_reaction('✅')
            return await utils.sleep_and_cleanup([success], 10)

    @_loc.command(name="deletelocation", aliases=["del"])
    @commands.has_permissions(manage_guild=True)
    async def _loc_deletelocation(self, ctx, *, info):
        """Removes a location from the database

        Requires type (stop/gym) and the name of the location.
        Requires no confirmation, will delete as soon as the
        correct stop or gym is identified."""
        channel = ctx.channel
        message = ctx.message
        author = message.author
        info = info.split(',')
        if len(info) != 2:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Please provide (comma separated) the location type (stop or gym) and the name of the Pokestop or gym."))
            await message.add_reaction('❌')
            return await utils.sleep_and_cleanup([failed], 10)
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
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"No {info[0]} found with name {info[1]}."))
            await message.add_reaction('❌')        
            return await utils.sleep_and_cleanup([failed], 10)
        result = await self.deleteLocation(ctx, loc_type, name)
        if result == 0:
            failed = await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=f"Failed to delete {loc_type}: {name}."))
            await message.add_reaction('❌')        
            return await utils.sleep_and_cleanup([failed], 10)
        else:
            success = await channel.send(embed=discord.Embed(colour=discord.Colour.green(), description=f"Successfully deleted {loc_type}: {name}."))
            await message.add_reaction('✅')
            return await utils.sleep_and_cleanup([success], 10)

    async def deleteLocation(self, ctx, type, name):
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
                if type == "stop":
                    deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
                elif type == "gym":
                    deleted = GymTable.delete().where(GymTable.location_id == locationresult).execute()
                deleted += LocationRegionRelation.delete().where(LocationRegionRelation.id == loc_reg).execute()
                deleted += location.delete_instance()
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return deleted


    async def stopToGym(self, ctx, name):
        channel = ctx.channel
        guild = ctx.guild
        deleted = 0
        created = 0
        with KyogreDB._db.atomic() as txn:
            try:
                locationresult = (LocationTable
                    .get((LocationTable.guild == guild.id) &
                           (LocationTable.name == name)))
                deleted = PokestopTable.delete().where(PokestopTable.location_id == locationresult).execute()
                location = LocationTable.get_by_id(locationresult)
                created = GymTable.create(location = location, ex_eligible = False)
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return (deleted, created)


    async def toggleEX(self, ctx, name):
        channel = ctx.channel
        guild = ctx.guild
        success = 0
        with KyogreDB._db.atomic() as txn:
            try:
                locationresult = (LocationTable
                    .get((LocationTable.guild == guild.id) &
                           (LocationTable.name == name)))
                location = LocationTable.get_by_id(locationresult)
                success = GymTable.update(ex_eligible = ~GymTable.ex_eligible).where(GymTable.location_id == location.id).execute()
                txn.commit()
            except Exception as e: 
                await channel.send(e)
                txn.rollback()
        return success


    async def changeRegion(self, ctx, name, region):
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
