import asyncio
import copy
import datetime
import re
import time

import discord
from discord.ext import commands

from kyogre import checks, list_helpers, raid_helpers, utils
from kyogre.exts.pokemon import Pokemon


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
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Give more details when reporting! '
                                                'Usage: **!wild <pokemon name> <location>**'))
        channel_regions = raid_helpers.get_channel_regions(channel, 'wild', self.bot.guild_dict)
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
        if locations and not ('http' in wild_details or '/maps' in wild_details):
            location = await location_matching_cog.match_prompt(channel, author.id, location, locations)
            if location:
                wild_gmaps_link = location.maps_url
                wild_details = location.name
        if wild_gmaps_link is None:
            if 'http' in wild_details or '/maps' in wild_details:
                wild_gmaps_link = utilities_cog.create_gmaps_query(wild_details, channel, type="wild")
                wild_details = 'Custom Map Pin'
            else:
                return await channel.send(
                    embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description="Please use the name of an existing pokestop or gym, "
                                    "or include a valid Google Maps link."))

        wild_embed = discord.Embed(title='Click here for my directions to the wild {pokemon}!'
                                   .format(pokemon=pkmn.full_name),
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
        wildreportmsg = await channel.send(content='Wild {pokemon} reported by {member}! Details: {location_details}'
                                           .format(pokemon=pkmn.full_name, member=author.display_name,
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
            'url': wild_gmaps_link,
            'pokemon': pkmn.full_name,
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
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, message.guild, 'wild',
                                                   edit=False, regions=channel_regions)
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        await subscriptions_cog.send_notifications_async('wild', wild_details, message.channel, [message.author.id])

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
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, guild, 'wild', edit=True,
                                                   regions=raid_helpers.get_channel_regions(channel, 'wild',
                                                                                            self.bot.guild_dict))


def setup(bot):
    bot.add_cog(WildSpawnCommands(bot))
