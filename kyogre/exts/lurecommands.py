import asyncio
import datetime

import discord
from discord.ext import commands

from kyogre import list_helpers, raid_helpers
from kyogre.exts.db.kyogredb import LureTable, LureTypeTable, LureTypeRelation, TrainerReportRelation


class WildSpawnCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='lure', aliases=['lu'])
    async def _lure(self, ctx, type, *, location):
        """Report that you're luring a pokestop.

        Usage: !lure <type> <location>
        Location should be the name of a Pokestop.
        Valid lure types are: normal, glacial, mossy, magnetic"""
        content = f"{type} {location}"
        message = ctx.message
        guild = message.guild
        channel = message.channel
        author = message.author
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        subscriptions_cog = self.bot.cogs.get('Subscriptions')
        if len(content.split()) <= 1:
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Give more details when reporting! Usage: **!lure <type> <location>**'))
        timestamp = (message.created_at +
                     datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])) \
            .strftime('%Y-%m-%d %H:%M:%S')
        luretype = content.split()[0].strip(',')
        pokestop = ' '.join(content.split()[1:])
        query = LureTypeTable.select()
        if id is not None:
            query = query.where(LureTypeTable.name == luretype)
        query = query.execute()
        result = [d for d in query]
        if len(result) != 1:
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Unable to find the lure type provided, please try again.'))
        luretype = result[0]
        lure_regions = raid_helpers.get_channel_regions(channel, 'lure', self.bot.guild_dict)
        stops = location_matching_cog.get_stops(guild.id, lure_regions)
        if stops:
            stop = await location_matching_cog.match_prompt(channel, author.id, pokestop, stops)
            if not stop:
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description="Unable to find that Pokestop. "
                                                    "Please check the name and try again!"))
        report = TrainerReportRelation.create(created=timestamp, trainer=author.id, location=stop.id)
        lure = LureTable.create(trainer_report=report)
        LureTypeRelation.create(lure=lure, type=luretype)
        lure_embed = discord.Embed(
            title=f'Click here for my directions to the {luretype.name.capitalize()} lure!',
            description=f"Ask {author.display_name} if my directions aren't perfect!",
            url=stop.maps_url, colour=discord.Colour.purple())
        lure_embed.set_footer(
            text='Reported by {author} - {timestamp}'
                .format(author=author.display_name, timestamp=timestamp),
            icon_url=author.avatar_url_as(format=None, static_format='jpg', size=32))
        lurereportmsg = await channel.send(f'**{luretype.name.capitalize()}** lure reported by '
                                           f'{author.display_name} at {stop.name}', embed=lure_embed)
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, guild,
                                                   'lure', edit=False, regions=lure_regions)
        details = {'regions': lure_regions, 'type': 'lure', 'lure_type': luretype.name, 'location': stop.name}
        await subscriptions_cog.send_notifications_async('lure', details, message.channel, [message.author.id])
        self.bot.event_loop.create_task(self.lure_expiry_check(lurereportmsg, report.id))

    async def lure_expiry_check(self, message, lure_id):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        message = await message.channel.fetch_message(message.id)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        expire_time = datetime.datetime.utcnow() + datetime.timedelta(hours=offset) + datetime.timedelta(minutes=1)
        if message not in self.bot.active_lures:
            self.bot.active_lures.append(message)
            self.bot.logger.info(
                'lure_expiry_check - Message added to watchlist - ' + message.channel.name
            )
            await asyncio.sleep(0.5)
            while True:
                if expire_time.timestamp() <= (
                        datetime.datetime.utcnow() + datetime.timedelta(hours=offset)).timestamp():
                    await self.expire_lure(message)
                await asyncio.sleep(30)
                continue

    async def expire_lure(self, message):
        channel = message.channel
        guild = channel.guild
        try:
            await message.edit(content="", embed=discord.Embed(description="This lure has expired"))
        except discord.errors.NotFound:
            pass
        await list_helpers.update_listing_channels(self.bot, self.bot.guild_dict, guild, 'lure', edit=True,
                                                   regions=raid_helpers.get_channel_regions(channel, 'lure',
                                                                                            self.bot.guild_dict))


def setup(bot):
    bot.add_cog(WildSpawnCommands(bot))
