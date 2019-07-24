import asyncio
import datetime
import random
import re

import discord
from discord.ext import commands

from kyogre import constants, checks, list_helpers, raid_helpers, utils
from kyogre.exts.db.kyogredb import *

from kyogre.exts.pokemon import Pokemon
from kyogre.exts.locationmatching import Pokestop

class Invasions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='invasion', aliases=['takeover', 'rocket', 'rock', 'roc'], brief="Report a Team Rocket Takeover!")
    @checks.allowinvasionreport()
    async def _invasion(self, ctx, *, info=None):
        message = ctx.message
        channel = message.channel
        author = message.author
        guild = message.guild
        img_url = author.avatar_url_as(format=None, static_format='jpg', size=32)
        info = re.split(r',*', info)
        stopname = info[0]
        report_time = message.created_at + datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        report_time_int = round(report_time.timestamp())
        timestamp = report_time.strftime('%Y-%m-%d %H:%M:%S')
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        regions = raid_helpers.get_channel_regions(channel, 'invasion', self.bot.guild_dict)
        stops = location_matching_cog.get_stops(guild.id, regions)
        if stops:
            stop = await location_matching_cog.match_prompt(channel, author.id, stopname, stops)
            if not stop:
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description=f"No pokestop found with name '**{stopname}**' "
                                        f"either. Try reporting again using the exact pokestop name!"),
                    delete_after = 15)
            location = stop.name
            loc_url = stop.maps_url
            regions = [stop.region]
        pokemon_name = None
        pkmnid = None
        if len(info) > 1:
            pkmn = Pokemon.get_pokemon(self.bot, info[1])
            if pkmn is not None:
                pkmnid = pkmn.id
                pokemon_name = pkmn.name
                img_url = pkmn.img_url
                img_url = img_url.replace('007_', '007normal_')
                img_url = img_url.replace('025_', '025normal_')
        report = TrainerReportRelation.create(created=report_time_int, trainer=author.id, location=stop.id)
        invasion = InvasionTable.create(trainer_report=report, pokemon_number=pkmnid)
        desc = f"**Pokestop**: {stop.name}"
        if pokemon_name is None:
            desc += "\n**Pokemon**: Unknown"
        else:
            desc += f"\n**Pokemon**: {pokemon_name.capitalize()}"
        inv_embed = discord.Embed(
            title=f'Click for directions!', description=desc, 
            url=stop.maps_url, colour=discord.Colour.red())

        inv_embed.set_footer(
            text='Reported by {author} - {timestamp}'
                .format(author=author.display_name, timestamp=timestamp),
            icon_url=img_url)
        if random.randint(0,1):
            inv_embed.set_thumbnail(url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_F.png?raw=true")
        else:
            inv_embed.set_thumbnail(url="https://github.com/tehstone/Kyogre/blob/master/images/misc/Team_Rocket_Grunt_M.png?raw=true")            
        invasionreportmsg = await channel.send(f'**Team Rocket Takeover** reported at *{stop.name}*', embed=inv_embed)
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, guild,
                                                   'takeover', edit=False, regions=regions)
        details = {'regions': regions, 'type': 'takeover', 'location': stop}
        await subscriptions_cog.send_notifications_async('takeover', details, message.channel, [message.author.id])
        self.bot.event_loop.create_task(self.invasion_expiry_check(invasionreportmsg, report.id))

    async def invasion_expiry_check(self, message, invasion_id):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        message = await message.channel.fetch_message(message.id)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        expiration_minutes = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['invasion_minutes']
        expire_time = datetime.datetime.utcnow() + datetime.timedelta(hours=offset) + datetime.timedelta(minutes=expiration_minutes)
        if message not in self.bot.active_invasions:
            self.bot.active_invasions.append(message)
            self.bot.logger.info(
                'invasion_expiry_check - Message added to watchlist - ' + message.channel.name
            )
            await asyncio.sleep(0.5)
            while True:
                if expire_time.timestamp() <= (
                        datetime.datetime.utcnow() + datetime.timedelta(hours=offset)).timestamp():
                    await self.expire_invasion(message)
                await asyncio.sleep(30)
                continue

    async def expire_invasion(self, message):
        channel = message.channel
        guild = channel.guild
        try:
            await message.edit(content="", embed=discord.Embed(description="Team Rocket has blasted off again!"))
        except discord.errors.NotFound:
            pass
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, guild, 'takeover', edit=True,
                                                   regions=raid_helpers.get_channel_regions(channel, 'takeover',                                                    
                                                                                            self.bot.guild_dict))
                                                    

def setup(bot):
    bot.add_cog(Invasions(bot))
