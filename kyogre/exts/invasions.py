import asyncio
import datetime
import random
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import HideoutInstance, HideoutTable, LocationTable
from kyogre.exts.db.kyogredb import LocationRegionRelation, RegionTable, TrainerReportRelation

from kyogre.exts.pokemon import Pokemon


class Invasions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.leader_strings = ['arlo', 'red', 'valor', 'cliff', 'blue', 'mystic', 'sierra', 'yellow', 'instinct']
        self.leader_map = {'arlo': 123, 'red': 123, 'valor': 123,
                           'cliff': 52, 'blue': 52, 'mystic': 52,
                           'sierra': 215, 'yellow': 215, 'instinct': 215}

    @commands.command(name='invasion', aliases=['takeover', 'rocket', 'rock', 'roc',
                                                'hideout', 'hide', 'leader', 'lead'],
                      brief="Report a Team Rocket Hideout!")
    @checks.allowinvasionreport()
    async def _invasion(self, ctx, *, info=None):
        """**Usage**: `!rocket <pokestop name> [,pokemon]`
        Pokemon name is optional and can be updated later."""
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = message.guild
        info = re.split(r',+\s+', info)
        stopname = info[0]
        report_time = message.created_at + \
                      datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        epoch = datetime.datetime(1970, 1, 1)
        report_time_int = (report_time - epoch).total_seconds()
        utilities_cog = self.bot.cogs.get('Utilities')
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'hideout')
        stops = location_matching_cog.get_stops(guild.id, regions)
        stop = await location_matching_cog.match_prompt(channel, author.id, stopname, stops)
        if not stop:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokestop found {stopname}.")
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description=f"No pokestop found with name '**{stopname}**' "
                                    f"either. Try reporting again using the exact pokestop name!"),
                delete_after=15)
        existing = await self._check_existing(stop)
        if existing:
            if existing.leader and existing.second_pokemon and existing.third_pokemon:
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description=f"Hideout for **{stop.name}** has been completely reported already."),
                    delete_after=15)
        if not existing:
            existing = HideoutInstance(None, report_time_int, stop.id, stop.name, None, None,
                                       None, None, stop.latitude, stop.longitude, message.id, message.author.id)
        regions = [stop.region]
        leader = None
        pokemon_names = [None]
        pokemon_ids = [None]
        # Check through all the info sent in, pull out any leader names and pokemon names we find
        if len(info) > 1:
            for i in info[1:]:
                # if we find a leader name then we can also set the first pokemon
                # this assumption may change in the future
                if i.lower() in self.leader_strings:
                    leader = i
                    p_id = self.leader_map[leader.lower()]
                    pkmn = Pokemon.get_pokemon(self.bot, p_id)
                    pokemon_names[0] = pkmn.name
                    pokemon_ids[0] = pkmn.id
                else:
                    pkmn = Pokemon.get_pokemon(self.bot, i)
                    if pkmn is not None:
                        # if the name found is the one already known to be in the first slot then ignore
                        if pkmn.id not in self.leader_map.values():
                            pokemon_names.append(pkmn.name)
                            pokemon_ids.append(pkmn.id)
        # pad the id and names lists
        if len(pokemon_names) < 3:
            pokemon_names = (pokemon_names + 3 * [None])[:3]
        if len(pokemon_ids) < 3:
            pokemon_ids = (pokemon_ids + 3 * [None])[:3]
        # if there was a pre-existing report, make sure not to override leader set before
        if existing.leader:
            if leader and leader != existing.leader:
                await channel.send(f"**{existing.leader.capitalize()}** has already been reported for **{stop.name}**.",
                                   delete_after=30)
            leader = existing.leader
            pkmn = Pokemon.get_pokemon(self.bot, self.leader_map[leader.lower()])
            pokemon_names[0] = pkmn.name
            pokemon_ids[0] = pkmn.id
        # don't override 2nd slot if already set
        if existing.second_pokemon:
            if pokemon_ids[1]:
                if pokemon_ids[1] != existing.second_pokemon:
                    if pokemon_ids[2]:
                        await channel.send(f"The second lineup slot has already been reported for **{stop.name}**.",
                                           delete_after=30)
                    else:
                        # but if the third slot was previously not set, we can fill that in now
                        if not existing.third_pokemon:
                            existing.third_pokemon = pokemon_ids[1]
            pkmn = Pokemon.get_pokemon(self.bot, existing.second_pokemon)
            pokemon_names[1] = pkmn.name
            pokemon_ids[1] = pkmn.id
        # don't override 3rd slot if already set. this may be unreachable
        if existing.third_pokemon:
            if pokemon_ids[2]:
                if pokemon_ids[2] != existing.second_pokemon:
                    await channel.send(f"The third lineup slot has already been reported for **{stop.name}**",
                                       delete_after=30)
            pkmn = Pokemon.get_pokemon(self.bot, existing.third_pokemon)
            pokemon_names[2] = pkmn.name
            pokemon_ids[2] = pkmn.id
        if existing.id:
            report = TrainerReportRelation.get_by_id(existing.id)
            HideoutTable.update(rocket_leader=leader, first_pokemon=pokemon_ids[0],
                                second_pokemon=pokemon_ids[1], third_pokemon=pokemon_ids[2])\
                .where(HideoutTable.trainer_report == report.id).execute()
            updated = True
        else:
            report = TrainerReportRelation.create(guild=ctx.guild.id, created=report_time_int, trainer=author.id,
                                                  location=stop.id, cancelled=False)
            HideoutTable.create(trainer_report=report, rocket_leader=leader, first_pokemon=pokemon_ids[0],
                                second_pokemon=pokemon_ids[1], third_pokemon=pokemon_ids[2])
            updated = False
        hideout = self.get_single_hideout(report.id)
        inv_embed = await self._build_hideout_embed(ctx, hideout)
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        if updated:
            hideout = self.get_single_hideout(report.id)
            message = await channel.fetch_message(hideout.message)
            try:
                await message.delete()
            except:
                pass
            invasionreportmsg = await channel.send(
                f'**Team Rocket Hideout** report at *{hideout.location_name}* updated!',
                embed=inv_embed)
            await utilities_cog.reaction_delay(invasionreportmsg, ['\u270f', '🚫'])
            TrainerReportRelation.update(message=invasionreportmsg.id) \
                .where(TrainerReportRelation.id == report.id).execute()
            await listmgmt_cog.update_listing_channels(guild, 'hideout', edit=True, regions=regions)
        else:
            invasionreportmsg = await channel.send(f'**Team Rocket Hideout** reported at *{stop.name}*', embed=inv_embed)
            await utilities_cog.reaction_delay(invasionreportmsg, ['\u270f', '🚫'])
            details = {'regions': regions, 'type': 'hideout', 'location': stop}
            TrainerReportRelation.update(message=invasionreportmsg.id).where(TrainerReportRelation.id == report.id).execute()
            send_channel = subscriptions_cog.get_region_list_channel(guild, stop.region, 'invasion')
            if send_channel is None:
                send_channel = message.channel
            await subscriptions_cog.send_notifications_async('hideout', details, send_channel, [message.author.id])
            await asyncio.sleep(1)
            await listmgmt_cog.update_listing_channels(guild, 'hideout', edit=False, regions=regions)
        clean_list = self.bot.guild_dict[ctx.guild.id]['configure_dict'].setdefault('channel_auto_clean', [])
        if ctx.channel.id in clean_list:
            await ctx.message.delete()

    async def invasion_expiry_check(self, message, invasion_id, author):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        message = await message.channel.fetch_message(message.id)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        timestamp = (message.created_at + datetime.timedelta(hours=offset))
        to_day_end = 22 * 60 * 60 - (timestamp - timestamp.replace(hour=0, minute=0, second=0, microsecond=0)).seconds
        expire_time = time.time() + to_day_end
        epoch = datetime.datetime(1970, 1, 1)
        if message not in self.bot.active_invasions:
            self.bot.active_invasions[invasion_id] = {"author": author.id, "message": message}
            self.bot.logger.info(
                'invasion_expiry_check - Message added to watchlist - ' + message.channel.name
            )
            await asyncio.sleep(0.5)
            while True:
                current = datetime.datetime.utcnow()# + datetime.timedelta(hours=offset)
                current_seconds = (current - epoch).total_seconds()
                time_diff = expire_time - current_seconds
                if time_diff < 1:
                    await self.expire_invasion(invasion_id)
                    break
                await asyncio.sleep(round(time_diff/2))
                continue

    async def expire_invasion(self, invasion_id):
        try:
            message = self.bot.active_invasions[invasion_id]["message"]
        except KeyError:
            return
        channel = message.channel
        guild = channel.guild
        try:
            await message.edit(content="", embed=discord.Embed(description="Team Rocket has blasted off again!"))
            await message.clear_reactions()
        except discord.errors.NotFound:
            pass
        try:
            del self.bot.active_invasions[invasion_id]
        except ValueError:
            pass
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'hideout')
        await listmgmt_cog.update_listing_channels(guild, 'hideout', edit=True, regions=regions)

    @staticmethod
    async def _check_existing(stop):
        epoch = datetime.datetime(1970, 1, 1)
        day_start = datetime.datetime.utcnow().replace(hour=6, minute=0, second=0, microsecond=0)
        day_end = datetime.datetime.utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
        day_start = (day_start - epoch).total_seconds()
        day_end = (day_end - epoch).total_seconds()
        result = (TrainerReportRelation.select(
            TrainerReportRelation.id,
            TrainerReportRelation.created,
            LocationTable.id.alias('location_id'),
            LocationTable.name.alias('location_name'),
            HideoutTable.rocket_leader.alias('leader'),
            HideoutTable.first_pokemon,
            HideoutTable.second_pokemon,
            HideoutTable.third_pokemon,
            LocationTable.latitude,
            LocationTable.longitude,
            TrainerReportRelation.message,
            TrainerReportRelation.trainer)
                  .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
                  .join(LocationRegionRelation, on=(LocationTable.id == LocationRegionRelation.location_id))
                  .join(RegionTable, on=(RegionTable.id == LocationRegionRelation.region_id))
                  .join(HideoutTable, on=(TrainerReportRelation.id == HideoutTable.trainer_report_id))
                  .where((LocationTable.name == stop.name) &
                         (TrainerReportRelation.created > day_start) &
                         (TrainerReportRelation.created < day_end) &
                         (TrainerReportRelation.cancelled == False))
                  .order_by(TrainerReportRelation.created))
        results = result.objects(HideoutInstance)
        if len(results) > 0:
            return result.objects(HideoutInstance)[0]
        return None

    async def modify_report(self, ctx, payload, report_id):
        channel = self.bot.get_channel(ctx.channel.id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.errors.NotFound, AttributeError):
            return
        guild = message.guild
        try:
            user = guild.get_member(payload.user_id)
        except AttributeError:
            return
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'hideout')
        prompt = f'Modifying details for **Team Rocket Hideout** at '    #**{stop}**\n' \
                 #f'Which item would you like to modify ***{user.display_name}***?'
        choices_list = ['Pokestop', 'Leader', 'Lineup']
        match = await utils.ask_list(self.bot, prompt, channel, choices_list, user_list=user.id)
        if match in choices_list:
            updated = False
            report = TrainerReportRelation.get_by_id(report_id)
            # Changing pokestop
            if match == choices_list[0]:
                location_matching_cog = self.bot.cogs.get('LocationMatching')
                utils_cog = self.bot.cogs.get('Utilities')
                regions = utils_cog.get_channel_regions(channel, 'hideout')
                stops = location_matching_cog.get_stops(guild.id, regions)
                query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                   description="What is the correct Location?"))
                try:
                    stopmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    await query_msg.delete()
                    stopmsg = None
                stop = None
                if not stopmsg:
                    error = "took too long to respond"
                elif stopmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await stopmsg.delete()
                elif stopmsg:
                    stop = await location_matching_cog.match_prompt(channel, user.id, stopmsg.clean_content, stops)
                    if not stop:
                        return await channel.send(
                            embed=discord.Embed(colour=discord.Colour.red(),
                                                description=f"No pokestop found with name '**{stopmsg.clean_content}**' "
                                                            f"either. Try reporting again using the exact pokestop name!"),
                            delete_after=15)
                    if await self._check_existing(stop):
                        return await channel.send(
                            embed=discord.Embed(colour=discord.Colour.red(),
                                                description=f"A Team Rocket Hideout has already been reported for '**{stop.name}**'!"))
                if stop:
                    updated = True
                    report.location_id = stop.id
                    report.save()
            # Changing leader
            elif match == choices_list[1]:
                query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                   description="What is the correct Leader?"))
                try:
                    leadmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    await query_msg.delete()
                    leadmsg = None
                if not leadmsg:
                    error = "took too long to respond"
                elif leadmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await leadmsg.delete()
                else:
                    if leadmsg.clean_content.lower() in self.leader_strings:
                        updated = True
                        report = TrainerReportRelation.get_by_id(report_id)
                        HideoutTable.update(rocket_leader=leadmsg.clean_content.lower())\
                            .where(HideoutTable.trainer_report == report.id).execute()
                    else:
                        return await channel.send(
                            embed=discord.Embed(colour=discord.Colour.red(),
                                                description=f"No Team Rocket Leader found with name "
                                                            f"{leadmsg.clean_content}. Please start again."),
                            delete_after=15)
            # Changing lineup
            elif match == choices_list[2]:
                query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                   description="What is the correct Lineup?"))
                try:
                    lineupmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
                except asyncio.TimeoutError:
                    await query_msg.delete()
                    lineupmsg = None
                if not lineupmsg:
                    error = "took too long to respond"
                elif lineupmsg.clean_content.lower() == "cancel":
                    error = "cancelled the report"
                    await lineupmsg.delete()
                else:
                    info = re.split(r',+\s+', lineupmsg.clean_content)
                    pokemon_ids = [None]
                    for i in info:
                        pkmn = Pokemon.get_pokemon(self.bot, i)
                        if pkmn is not None:
                            if pkmn.id not in self.leader_map.values():
                                pokemon_ids.append(pkmn.id)
                    if not pokemon_ids[0]:
                        hideout = self.get_single_hideout(report.id)
                        if hideout.leader and hideout.leader in self.leader_map:
                            pokemon_ids[0] = self.leader_map[hideout.leader]
                    if len(pokemon_ids) < 3:
                        pokemon_ids = (pokemon_ids + 3 * [None])[:3]
                    updated = True
                    report = TrainerReportRelation.get_by_id(report_id)
                    HideoutTable.update(first_pokemon=pokemon_ids[0], second_pokemon=pokemon_ids[1],
                                        third_pokemon=pokemon_ids[2]) \
                        .where(HideoutTable.trainer_report == report.id).execute()
            if updated:
                hideout = self.get_single_hideout(report.id)
                message = await channel.fetch_message(hideout.message)
                try:
                    await message.delete()
                except:
                    pass
                inv_embed = await self._build_hideout_embed(ctx, hideout)
                invasionreportmsg = await channel.send(f'**Team Rocket Hideout** report at *{hideout.location_name}* updated!',
                                                       embed=inv_embed)
                utilities_cog = self.bot.cogs.get('Utilities')
                await utilities_cog.reaction_delay(invasionreportmsg, ['\u270f', '🚫'])
                TrainerReportRelation.update(message=invasionreportmsg.id) \
                    .where(TrainerReportRelation.id == report.id).execute()
                listmgmt_cog = self.bot.cogs.get('ListManagement')
                await listmgmt_cog.update_listing_channels(guild, 'hideout', edit=True, regions=regions)
        try:
            await message.remove_reaction(payload.emoji, user)
        except (discord.errors.NotFound):
            pass

    async def _build_hideout_embed(self, ctx, hideout):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        stop = location_matching_cog.get_stop_by_id(ctx.guild.id, hideout.location_id)
        inv_embed = discord.Embed(
            title=f'**Pokestop**: {stop.name}', url=stop.maps_url, colour=discord.Colour.red())
        desc = ""
        if hideout.leader:
            desc += f"\nRocket Leader {hideout.leader.capitalize()}\n"
            inv_embed.set_thumbnail(
                url=f"https://github.com/tehstone/Kyogre/blob/master/images/misc/{hideout.leader.lower()}.png?raw=true")
        else:
            if random.randint(0, 1):
                inv_embed.set_thumbnail(
                    url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_F.png?raw=true")
            else:
                inv_embed.set_thumbnail(
                    url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_M.png?raw=true")
            desc += "\n Unknown Rocket Leader\n"
        names, img_url = '', ''
        pokemon_list = [hideout.first_pokemon, hideout.second_pokemon, hideout.third_pokemon]
        for pk_id in pokemon_list:
            if pk_id:
                pokemon = Pokemon.get_pokemon(self.bot, pk_id)
                if pokemon:
                    names += f"{pokemon.name.capitalize()} "
        if pokemon_list[0]:
            pokemon = Pokemon.get_pokemon(self.bot, pokemon_list[0])
            img_url = pokemon.img_url
            img_url = img_url.replace('007_', '007normal_')
            img_url = img_url.replace('025_', '025normal_')
        if len(names) > 0:
            names = "\n**Lineup**:\n" + names
        else:
            names = "\n**Unknown Lineup**"
        desc += names
        inv_embed.description = desc
        created_time = datetime.datetime.utcfromtimestamp(hideout.created) + datetime.timedelta(
            hours=self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset'])
        timestamp = created_time.strftime('%Y-%m-%d %H:%M:%S')
        trainer = ctx.guild.get_member(hideout.trainer)
        inv_embed.set_footer(
            text=f'Reported by {trainer.display_name} - {timestamp}', icon_url=img_url)
        return inv_embed

    @staticmethod
    async def _update_report(channel, message_id, pokemon):
        report_message = await channel.fetch_message(message_id)
        if report_message is None:
            return
        embed = report_message.embeds[0]
        embed.description = re.sub(r'\*\*Pokemon\*\*: [A-Za-z]+', f'**Pokemon**: {pokemon.name}', embed.description)
        try:
            img_url = pokemon.img_url
            img_url = img_url.replace('007_', '007normal_')
            img_url = img_url.replace('025_', '025normal_')
            footer = embed.footer
            embed.set_footer(text=footer.text, icon_url=img_url)

        except:
            pass
        await report_message.edit(embed=embed)

    @staticmethod
    async def cancel_and_delete(ctx, i):
        report = TrainerReportRelation.get_by_id(i)
        report.cancelled = True
        report.save()
        message_id = report.message
        message = await ctx.channel.fetch_message(message_id)
        try:
            await message.delete()
        except (discord.errors.Forbidden, discord.errors.HTTPException):
            pass

    @commands.Cog.listener()
    @checks.good_standing()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
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
        ctx = await self.bot.get_context(message)
        update = False
        active_hideouts = self.active_hideouts()
        for h in active_hideouts:
            if h.message == message.id:
                if h.trainer == payload.user_id or utils.can_manage(user, self.bot.config):
                    if str(payload.emoji) == '\u270f':
                        await self.modify_report(ctx, payload, h.id)
                        update = True
                        break
                    elif str(payload.emoji) == '🚫':
                        await self.cancel_and_delete(ctx, h.id)
                        update = True
                        break
        if update:
            utils_cog = self.bot.cogs.get('Utilities')
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            regions = utils_cog.get_channel_regions(channel, 'research')
            await listmgmt_cog.update_listing_channels(guild, 'hideout', edit=True, regions=regions)

    @staticmethod
    def active_hideouts():
        epoch = datetime.datetime(1970, 1, 1)
        day_start = datetime.datetime.utcnow().replace(hour=6, minute=0, second=0, microsecond=0)
        day_end = datetime.datetime.utcnow().replace(hour=22, minute=0, second=0, microsecond=0)
        day_start = (day_start - epoch).total_seconds()
        day_end = (day_end - epoch).total_seconds()
        result = (TrainerReportRelation.select(
            TrainerReportRelation.id,
            TrainerReportRelation.created,
            LocationTable.id.alias('location_id'),
            LocationTable.name.alias('location_name'),
            HideoutTable.rocket_leader.alias('leader'),
            HideoutTable.first_pokemon,
            HideoutTable.second_pokemon,
            HideoutTable.third_pokemon,
            LocationTable.latitude,
            LocationTable.longitude,
            TrainerReportRelation.message,
            TrainerReportRelation.trainer)
                  .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
                  .join(LocationRegionRelation, on=(LocationTable.id == LocationRegionRelation.location_id))
                  .join(RegionTable, on=(RegionTable.id == LocationRegionRelation.region_id))
                  .join(HideoutTable, on=(TrainerReportRelation.id == HideoutTable.trainer_report_id))
                  .where((TrainerReportRelation.created > day_start) &
                         (TrainerReportRelation.created < day_end) &
                         (TrainerReportRelation.cancelled == False))
                  .order_by(TrainerReportRelation.created))
        results = result.objects(HideoutInstance)
        return [r for r in results]

    @staticmethod
    def get_single_hideout(report_id):
        result = (TrainerReportRelation.select(
            TrainerReportRelation.id,
            TrainerReportRelation.created,
            LocationTable.id.alias('location_id'),
            LocationTable.name.alias('location_name'),
            HideoutTable.rocket_leader.alias('leader'),
            HideoutTable.first_pokemon,
            HideoutTable.second_pokemon,
            HideoutTable.third_pokemon,
            LocationTable.latitude,
            LocationTable.longitude,
            TrainerReportRelation.message,
            TrainerReportRelation.trainer)
                  .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
                  .join(LocationRegionRelation, on=(LocationTable.id == LocationRegionRelation.location_id))
                  .join(RegionTable, on=(RegionTable.id == LocationRegionRelation.region_id))
                  .join(HideoutTable, on=(TrainerReportRelation.id == HideoutTable.trainer_report_id))
                  .where(TrainerReportRelation.id == report_id))
        return result.objects(HideoutInstance)[0]

def setup(bot):
    bot.add_cog(Invasions(bot))
