import asyncio
import copy
import datetime
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, utils
from kyogre.exts.pokemon import Pokemon

from kyogre.exts.db.kyogredb import GuildTable, SightingTable, TrainerTable, TrainerReportRelation


class WildSpawnCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="wild", aliases=['w'], brief="Report a wild Pokemon spawn location.")
    @checks.allowwildreport()
    async def _wild(self, ctx, pokemon, *, location):
        """**Usage**: `!wild <pokemon> <location>`
        Location can be a pokestop name, gym name, Google or Apple Maps link."""
        content = f"{pokemon} {location}"
        message = ctx.message
        guild = message.guild
        channel = message.channel
        author = message.author
        utilities_cog = self.bot.cogs.get('Utilities')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        timestamp = (message.created_at +
                     datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset']))\
                    .strftime('%I:%M %p (%H:%M)')
        if len(content.split()) <= 1:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient wild report info provided.")
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Give more details when reporting! '
                                                'Usage: **!wild <pokemon name> <location>**'))
        utils_cog = self.bot.cogs.get('Utilities')
        channel_regions = utils_cog.get_channel_regions(channel, 'wild')
        rgx = r'\s*((100(\s*%)?|perfect)(\s*ivs?\b)?)\s*'
        content, count = re.subn(rgx, '', content.strip(), flags=re.I)
        is_perfect = count > 0
        entered_wild, wild_details = content.split(' ', 1)
        if Pokemon.has_forms(entered_wild):
            prompt = 'Which form of this Pokemon are you reporting?'
            choices_list = [f.capitalize() for f in Pokemon.get_forms_for_pokemon(entered_wild)]
            match = await utils.ask_list(self.bot, prompt, channel, choices_list, user_list=author.id)
            content = ' '.join([match, content])
        pkmn = Pokemon.get_pokemon(self.bot, entered_wild if entered_wild.isdigit() else content)
        if not pkmn:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Pokemon not found with name: {content}.")
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description="Unable to find that pokemon. Please check the name and try again!"))
        wild_number = pkmn.id
        wild_img_url = pkmn.img_url
        expiremsg = '**This {pokemon} has despawned!**'.format(pokemon=pkmn.full_name)
        if len(pkmn.name.split(' ')) > 1:
            entered_wild, entered_wild, wild_details = content.split(' ', 2)
        else:
            wild_details = re.sub(pkmn.name.lower(), '', content, flags=re.I)
        wild_gmaps_link = None
        locations = location_matching_cog.get_all(guild.id, channel_regions)
        location_id = None
        if locations and not ('http' in wild_details or '/maps' in wild_details):
            location = await location_matching_cog.match_prompt(channel, author.id, location, locations)
            if location:
                wild_gmaps_link = location.maps_url
                wild_details = location.name
                location_id = location.id
        if wild_gmaps_link is None:
            if 'http' in wild_details or '/maps' in wild_details:
                wild_gmaps_link = utilities_cog.create_gmaps_query(wild_details, channel, type="wild")
                wild_details = 'Custom Map Pin'
            else:
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Invalid location provided.")
                return await channel.send(
                    embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description="Please use the name of an existing pokestop or gym, "
                                    "or include a valid Google Maps link."))

        wild_embed = discord.Embed(title='Click here for my directions to the wild {perfect}{pokemon}!'
                                   .format(pokemon=pkmn.full_name,
                                           perfect="💯 " if is_perfect else ""),
                                   description="Ask {author} if my directions aren't perfect!"
                                   .format(author=author.name),
                                   url=wild_gmaps_link, colour=guild.me.colour)
        wild_embed.add_field(name='**Details:**', value='{emoji}{pokemon} ({pokemonnumber}) {type}'
                             .format(emoji='💯' if is_perfect else '', pokemon=pkmn.full_name,
                                     pokemonnumber=str(wild_number),
                                     type=''.join(utils.types_to_str(guild, pkmn.types, self.bot.config))),
                             inline=False)
        wild_embed.set_thumbnail(url=wild_img_url)
        wild_embed.add_field(name='**Reactions:**', value="{emoji}: I'm on my way!".format(emoji="🏎"))
        wild_embed.add_field(name='\u200b', value="{emoji}: The Pokemon despawned!".format(emoji="💨"))
        wild_embed.set_footer(text='Reported by {author} - {timestamp}'
                              .format(author=author.display_name, timestamp=timestamp),
                              icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
        wildreportmsg = await channel.send(content='Wild {perfect}{pokemon} reported by {member} at: {location_details}'
                                           .format(perfect="💯 " if is_perfect else "",
                                                   pokemon=pkmn.full_name, member=author.display_name,
                                                   location_details=wild_details), embed=wild_embed)
        await utilities_cog.reaction_delay(wildreportmsg, ['🏎', '💨'])
        wild_dict = copy.deepcopy(self.bot.guild_dict[guild.id].get('wildreport_dict', {}))
        wild_dict[wildreportmsg.id] = {
            'exp': time.time() + 3600,
            'expedit': {"content": wildreportmsg.content, "embedcontent": expiremsg},
            'reportmessage': message.id,
            'reportchannel': channel.id,
            'reportauthor': author.id,
            'location': wild_details,
            'location_id': location_id,
            'url': wild_gmaps_link,
            'pokemon': pkmn.full_name,
            'pokemon_id': pkmn.id,
            'perfect': is_perfect,
            'omw': []
        }
        self.bot.guild_dict[guild.id]['wildreport_dict'] = wild_dict
        wild_reports = self.bot.guild_dict[guild.id]\
                           .setdefault('trainers', {})\
                           .setdefault(channel_regions[0], {})\
                           .setdefault(author.id, {})\
                           .setdefault('wild_reports', 0) + 1
        self.bot.guild_dict[guild.id]['trainers'][channel_regions[0]][author.id]['wild_reports'] = wild_reports
        wild_details = {'pokemon': pkmn, 'perfect': is_perfect, 'location': wild_details, 'regions': channel_regions}
        self.bot.event_loop.create_task(self.wild_expiry_check(wildreportmsg))
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.update_listing_channels(message.guild, 'wild', edit=False, regions=channel_regions)
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        send_channel = subscriptions_cog.get_region_list_channel(guild, channel_regions[0], 'wild')
        if send_channel is None:
            send_channel = message.channel
        await subscriptions_cog.send_notifications_async('wild', wild_details, send_channel, [message.author.id])
        await self._add_db_sighting_report(ctx, wildreportmsg)

    async def wild_expiry_check(self, message):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        guild = message.channel.guild
        message = await message.channel.fetch_message(message.id)
        if message not in self.bot.active_wilds:
            self.bot.active_wilds.append(message)
            self.bot.logger.info(
                'wild_expiry_check - Message added to watchlist - ' + message.channel.name
            )
            await asyncio.sleep(0.5)
            while True:
                try:
                    if self.bot.guild_dict[guild.id]['wildreport_dict'][message.id]['exp'] <= time.time():
                        await self.expire_wild(message)
                        break
                except KeyError:
                    break
                await asyncio.sleep(30)
                continue

    async def expire_wild(self, message):
        channel = message.channel
        guild = channel.guild
        wild_dict = self.bot.guild_dict[guild.id]['wildreport_dict']
        try:
            self.bot.active_wilds.remove(message)
        except ValueError:
            pass
        try:
            await message.edit(embed=discord.Embed(description=wild_dict[message.id]['expedit']['embedcontent'],
                                                   colour=message.embeds[0].colour.value))
            await message.clear_reactions()
        except discord.errors.NotFound:
            pass
        try:
            user_message = await channel.fetch_message(wild_dict[message.id]['reportmessage'])
            await user_message.delete()
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass
        del self.bot.guild_dict[guild.id]['wildreport_dict'][message.id]
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        utils_cog = self.bot.cogs.get('Utilities')
        await listmgmt_cog.update_listing_channels(guild, 'wild', edit=True,
                                                   regions=utils_cog.get_channel_regions(channel, 'wild'))

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
        wildreport_dict = guild_dict[guild.id].setdefault('wildreport_dict', {})
        if message.id in wildreport_dict:
            wild_dict = wildreport_dict.get(message.id, None)
            if str(payload.emoji) == '🏎':
                wild_dict['omw'].append(user.mention)
                wildreport_dict[message.id] = wild_dict
            elif str(payload.emoji) == '💨':
                for reaction in message.reactions:
                    if reaction.emoji == '💨' and reaction.count >= 2:
                        if wild_dict['omw']:
                            despawn = "has despawned"
                            await channel.send(
                                f"{', '.join(wild_dict['omw'])}: {wild_dict['pokemon'].title()} {despawn}!")
                        wilds_cog = self.bot.cogs.get('WildSpawnCommands')
                        await wilds_cog.expire_wild(message)

    async def _add_db_sighting_report(self, ctx, message):
        channel = ctx.channel
        guild = channel.guild
        author = ctx.author
        wild_dict = self.bot.guild_dict[guild.id]['wildreport_dict'][message.id]
        created = round(message.created_at.timestamp())
        __, __ = GuildTable.get_or_create(snowflake=guild.id)
        __, __ = TrainerTable.get_or_create(snowflake=author.id, guild=guild.id)
        report = TrainerReportRelation.create(created=created, trainer=author.id,
                                              location=wild_dict['location_id'], message=message.id)
        try:
            SightingTable.create(trainer_report=report, pokemon=wild_dict['pokemon_id'])
        except Exception as e:
            self.bot.logger.info(f"Failed to create sighting table entry with error: {e}")


def setup(bot):
    bot.add_cog(WildSpawnCommands(bot))
