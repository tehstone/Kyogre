import asyncio
import datetime
import random
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.db.kyogredb import *

from kyogre.exts.pokemon import Pokemon
from kyogre.exts.locationmatching import Pokestop

class Invasions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='invasion', aliases=['takeover', 'rocket', 'rock', 'roc'], brief="Report a Team Rocket Takeover!")
    @checks.allowinvasionreport()
    async def _invasion(self, ctx, *, info=None):
        """**Usage**: `!rocket <pokestop name> [,pokemon]`
        Pokemon name is optional and can be updated later."""
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = message.guild
        img_url = author.avatar_url_as(format=None, static_format='jpg', size=32)
        info = re.split(r',+\s+', info)
        leader_strings = ['arlo', 'red', 'valor', 'cliff', 'blue', 'mystic', 'sierra', 'yellow', 'instinct']
        leader_map = {'arlo': 123, 'red': 123, 'valor': 123,
                      'cliff': 52, 'blue': 52, 'mystic': 52,
                      'sierra': 215, 'yellow': 215, 'instinct': 215}
        stopname = info[0]
        report_time = message.created_at + \
                      datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        report_time_int = round(report_time.timestamp())
        timestamp = report_time.strftime('%Y-%m-%d %H:%M:%S')
        utilities_cog = self.bot.cogs.get('Utilities')
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'takeover')
        stops = location_matching_cog.get_stops(guild.id, regions)
        if stops:
            stop = await location_matching_cog.match_prompt(channel, author.id, stopname, stops)
            if not stop:
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: No Pokestop found {stopname}.")
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description=f"No pokestop found with name '**{stopname}**' "
                                        f"either. Try reporting again using the exact pokestop name!"),
                    delete_after=15)
            if await self._check_existing(ctx, stop):
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description=f"A Team Rocket Hideout has already been reported for '**{stop.name}**'!"))
            regions = [stop.region]
        leader = None
        pokemon_names = [None]
        pokemon_ids = [None]
        if len(info) > 1:
            for i in info[1:]:
                if i.lower() in leader_strings:
                    leader = i
                    p_id = leader_map[leader]
                    pkmn = Pokemon.get_pokemon(self.bot, p_id)
                    pokemon_names[0] = pkmn.name
                    pokemon_ids[0] = pkmn.id
                else:
                    pkmn = Pokemon.get_pokemon(self.bot, i)
                    if pkmn is not None:
                        if pkmn.id not in leader_map.values():
                            pokemon_names.append(pkmn.name)
                            pokemon_ids.append(pkmn.id)
                img_url = pkmn.img_url
                img_url = img_url.replace('007_', '007normal_')
                img_url = img_url.replace('025_', '025normal_')
        report = TrainerReportRelation.create(guild=ctx.guild.id,
                                              created=report_time_int, trainer=author.id, location=stop.id)
        if len(pokemon_names) < 3:
            pokemon_names = (pokemon_names + 3 * [None])[:3]
        if len(pokemon_ids) < 3:
            pokemon_ids = (pokemon_ids + 3 * [None])[:3]
        hideout = HideoutTable.create(trainer_report=report, rocket_leader=leader, first_pokemon=pokemon_ids[0],
                                      second_pokemon=pokemon_ids[1], third_pokemon=pokemon_ids[2])
        desc = f"**Pokestop**: {stop.name}"
        if leader:
            desc += f"\n Rocket Leader {leader.capitalize()}\n"
        names = ''
        for name in pokemon_names:
            if name:
                names += f"{name.capitalize()} "
        if len(names) > 0:
            names = "**Lineup**:\n" + names
        else:
            names = "**Unknown Lineup**"
        desc += names
        inv_embed = discord.Embed(
            title=f'Click for directions!', description=desc, 
            url=stop.maps_url, colour=discord.Colour.red())

        inv_embed.set_footer(
            text='Reported by {author} - {timestamp}'
                .format(author=author.display_name, timestamp=timestamp),
            icon_url=img_url)
        if random.randint(0, 1):
            inv_embed.set_thumbnail(url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_F.png?raw=true")
        else:
            inv_embed.set_thumbnail(url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_M.png?raw=true")            
        invasionreportmsg = await channel.send(f'**Team Rocket Hideout** reported at *{stop.name}*', embed=inv_embed)
        await utilities_cog.reaction_delay(invasionreportmsg, ['🇵', '💨'])#, '\u270f'])
        details = {'regions': regions, 'type': 'takeover', 'location': stop}
        TrainerReportRelation.update(message=invasionreportmsg.id).where(TrainerReportRelation.id == report.id).execute()
        send_channel = subscriptions_cog.get_region_list_channel(guild, stop.region, 'invasion')
        if send_channel is None:
            send_channel = message.channel
        await subscriptions_cog.send_notifications_async('takeover', details, send_channel, [message.author.id])
        self.bot.event_loop.create_task(self.invasion_expiry_check(invasionreportmsg, report.id, author))
        await asyncio.sleep(1) # without this the listing update will miss the most recent report
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.update_listing_channels(guild, 'takeover', edit=False, regions=regions)
        clean_list = self.bot.guild_dict[ctx.guild.id]['configure_dict'].setdefault('channel_auto_clean', [])
        if ctx.channel.id in clean_list:
            await ctx.message.delete()

    async def invasion_expiry_check(self, message, invasion_id, author):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        message = await message.channel.fetch_message(message.id)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        timestamp = (message.created_at + datetime.timedelta(
            hours=self.bot.guild_dict[message.channel.guild.id]['configure_dict']['settings']['offset']))
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
                current = datetime.datetime.utcnow() + datetime.timedelta(hours=offset)
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
        regions = utils_cog.get_channel_regions(channel, 'takeover')
        await listmgmt_cog.update_listing_channels(guild, 'takeover', edit=True, regions=regions)
                                                    
    async def _check_existing(self, ctx, stop):
        current = datetime.datetime.utcnow() \
                + datetime.timedelta(hours=self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['offset'])
        current = round(current.timestamp())
        expiration_seconds = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']['invasion_minutes'] * 60
        result = (TrainerReportRelation.select(
                    TrainerReportRelation.created)
            .join(LocationTable, on=(TrainerReportRelation.location_id == LocationTable.id))
            .join(LocationRegionRelation, on=(LocationTable.id==LocationRegionRelation.location_id))
            .join(RegionTable, on=(RegionTable.id==LocationRegionRelation.region_id))
            .join(InvasionTable, on=(TrainerReportRelation.id == InvasionTable.trainer_report_id))
            .join(PokemonTable, JOIN.LEFT_OUTER, on=(InvasionTable.pokemon_number_id == PokemonTable.id))
            .where((RegionTable.name == stop.region) &
                   (TrainerReportRelation.created + expiration_seconds > current) & 
                   (LocationTable.id == stop.id)))
        return len(result) > 0

    async def modify_report(self, payload):
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
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'takeover')
        if str(payload.emoji) == '🇵':
            query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                               description="What is the Pokemon awarded from this encounter?"))
            try:
                pkmnmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                await query_msg.delete()
                pkmnmsg = None
            if not pkmnmsg:
                error = "took too long to respond"
            elif pkmnmsg.clean_content.lower() == "cancel":
                error = "cancelled the report"
                await pkmnmsg.delete()
            elif pkmnmsg:
                pkmn = Pokemon.get_pokemon(self.bot, pkmnmsg.clean_content)
                if not pkmn:
                    await query_msg.delete()
                    await pkmnmsg.delete()
                    await channel.send(embed=discord.Embed(colour=discord.Colour.red(),
                                                           description="Could not find a Pokemon by that name, please try again."),
                                       delete_after=15)
                result = (TrainerReportRelation.select(TrainerReportRelation.id)
                             .where(TrainerReportRelation.message == message.id))
                if result is not None:
                    InvasionTable.update(pokemon_number_id=pkmn.id).where(InvasionTable.trainer_report_id == result[0].id).execute()
                await self._update_report(channel, message.id, pkmn)
                listmgmt_cog = self.bot.cogs.get('ListManagement')
                await listmgmt_cog.update_listing_channels(guild, 'takeover', edit=False, regions=regions)
                await query_msg.delete()
                await pkmnmsg.delete()
                await channel.send(embed=discord.Embed(colour=discord.Colour.green(),
                                                       description="Team Rocket Takeover listing updated."),
                                   delete_after=15)
        elif str(payload.emoji) == '\u270f':
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            utils_cog = self.bot.cogs.get('Utilities')
            regions = utils_cog.get_channel_regions(channel, 'takeover')
            stops = location_matching_cog.get_stops(guild.id, regions)
            query_msg = await channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                               description="What is the correct Location?"))
            try:
                stopmsg = await self.bot.wait_for('message', timeout=30, check=(lambda reply: reply.author == user))
            except asyncio.TimeoutError:
                await query_msg.delete()
                stopmsg = None
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
                if await self._check_existing(ctx, stop):
                    return await channel.send(
                        embed=discord.Embed(colour=discord.Colour.red(),
                                            description=f"A Team Rocket Takeover has already been reported for '**{stop.name}**'!"))
                location = stop.name
                loc_url = stop.maps_url
                regions = [stop.region]
        await message.remove_reaction(payload.emoji, user)

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
        for i, d in self.bot.active_invasions.items():
            if d["message"].id == message.id:
                if d["author"] == payload.user_id or utils.can_manage(user, self.bot.config):
                    if str(payload.emoji) == '💨':
                        await self.expire_invasion(i)
                        break
                    elif str(payload.emoji) in ['🇵', '\u270f']:
                        await self.modify_report(payload)

def setup(bot):
    bot.add_cog(Invasions(bot))
