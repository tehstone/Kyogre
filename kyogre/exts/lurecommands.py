import asyncio
import datetime

import discord
from discord.ext import commands

from kyogre.exts.db.kyogredb import LureTable, LureTypeTable, LureTypeRelation, TrainerReportRelation


class LureCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='lure', aliases=['lu'], brief="Report that you're luring a Pokestop.")
    async def _lure(self, ctx, type, *, location):
        """**Usage**: `!lure <type> <location>`
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
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Insufficient info.")
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Give more details when reporting! Usage: **!lure <type> <location>**'))
        report_time = message.created_at + datetime.timedelta(hours=self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset'])
        report_time_int = round(report_time.timestamp())
        timestamp = report_time.strftime('%Y-%m-%d %H:%M:%S')
        luretype = content.split()[0].strip(',')
        pokestop = ' '.join(content.split()[1:])
        query = LureTypeTable.select()
        if id is not None:
            query = query.where(LureTypeTable.name == luretype)
        query = query.execute()
        result = [d for d in query]
        if len(result) != 1:
            self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Lure type: {luretype} not found.")
            return await channel.send(
                embed=discord.Embed(colour=discord.Colour.red(),
                                    description='Unable to find the lure type provided, please try again.'))
        luretype = result[0]
        utils_cog = self.bot.cogs.get('Utilities')
        lure_regions = utils_cog.get_channel_regions(channel, 'lure')
        stops = location_matching_cog.get_stops(guild.id, lure_regions)
        if stops:
            stop = await location_matching_cog.match_prompt(channel, author.id, pokestop, stops)
            if not stop:
                self.bot.help_logger.info(f"User: {ctx.author.name}, channel: {ctx.channel}, error: Pokestop not found with name: {pokestop}.")
                return await channel.send(
                    embed=discord.Embed(colour=discord.Colour.red(),
                                        description="Unable to find that Pokestop. "
                                                    "Please check the name and try again!"))
        report = TrainerReportRelation.create(guild=ctx.guild.id,
                                              created=report_time_int, trainer=author.id, location=stop.id)
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
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        await listmgmt_cog.update_listing_channels(guild, 'lure', edit=False, regions=lure_regions)
        details = {'regions': lure_regions, 'type': 'lure', 'lure_type': luretype.name, 'location': stop}
        send_channel = subscriptions_cog.get_region_list_channel(guild, stop.region, 'lure')
        if send_channel is None:
            send_channel = message.channel
        await subscriptions_cog.send_notifications_async('lure', details, send_channel, [message.author.id])
        self.bot.event_loop.create_task(self.lure_expiry_check(lurereportmsg, report.id))

    async def lure_expiry_check(self, message, lure_id):
        self.bot.logger.info('Expiry_Check - ' + message.channel.name)
        channel = message.channel
        message = await message.channel.fetch_message(message.id)
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        expiration_minutes = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings'].setdefault('lure_minutes',30)
        expire_time = datetime.datetime.utcnow() + datetime.timedelta(hours=offset) + datetime.timedelta(minutes=expiration_minutes)
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
        listmgmt_cog = self.bot.cogs.get('ListManagement')
        utils_cog = self.bot.cogs.get('Utilities')
        await listmgmt_cog.update_listing_channels(guild, 'lure', edit=True,
                                                   regions=utils_cog.get_channel_regions(channel, 'lure'))


def setup(bot):
    bot.add_cog(LureCommands(bot))
