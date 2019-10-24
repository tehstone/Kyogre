import asyncio
import copy
import datetime
import time

import discord
from discord.ext import commands

from kyogre import image_scan, utils, checks, image_utils
from kyogre.context import Context

month_map = {"jan": 1,
             "feb": 2,
             "mar": 3,
             "apr": 4,
             "may": 5,
             "jun": 6,
             "jul": 7,
             "aug": 8,
             "sep": 9,
             "oct": 10,
             "nov": 11,
             "dec": 12}


class EXRaids(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self.bot.get_context(message, cls=Context)
        if len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None)) \
                or message.author == self.bot.user:
            return
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'] \
            .setdefault('ex_scan_listen_channels', [])
        if message.channel.id in listen_channels:
            await message.add_reaction('🤔')
            file = await image_utils.image_pre_check(message.attachments[0])
            gym, date_key, start_time = await self.parse_ex_pass(ctx, file)
            ex_raid_dict = self.bot.guild_dict[ctx.guild.id].setdefault('exchannel_dict', {})
            ex_channel_ids = self.get_existing_raid(ctx.guild, gym, ex_raid_dict)
            if ex_channel_ids:
                ex_channel = self.bot.get_channel(ex_channel_ids[0])
                if ex_channel and self.bot.guild_dict[ctx.guild.id]['exchannel_dict'][ex_channel.category_id]\
                                      ['channels'][ex_channel.id]:
                    return await ctx.channel.send(
                        embed=discord.Embed(
                            colour=discord.Colour.red(),
                            description=f"An EX raid has already been reported for {gym.name}.\n{ex_channel.mention}"))
            if not gym or not date_key:
                return await ctx.channel.send(embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description=f"Could not determine gym name or pass date from EX Pass screenshot."))
            return await self._process_ex_request(ctx, gym, start_time, date_key)

    async def parse_ex_pass(self, ctx, file):
        ex_info = await image_scan.check_gym_ex(file)
        if not ex_info['gym']:
            return None, None, None
        region, gym, date_key, start_time = None, None, None, None
        if ex_info['location']:
            location = ex_info['location'].split(',')
            all_regions = list(self.bot.guild_dict[ctx.guild.id]['configure_dict']['regions']['info'].keys())
            p_region = location[0].strip().lower()
            if p_region in all_regions:
                region = [p_region]
            else:
                region = all_regions
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gyms = location_matching_cog.get_gyms(ctx.guild.id, region)
            gym = await location_matching_cog.match_prompt(ctx.channel, ctx.author.id, ex_info['gym'], gyms)
        if ex_info['date']:
            date_split = ex_info['date'].split()
            month, day = date_split[0], date_split[1]
            month = month[:3].lower()
            date_key = f"{str(month)}_{str(day)}"
            start_time = date_split[2]
        return gym, date_key, start_time

    async def _process_ex_request(self, ctx, gym, start_time, date_key):
        category_id = await self._get_or_create_category(ctx, date_key)
        category = ctx.guild.get_channel(category_id)
        ex_channel = await self._create_ex_channel(ctx, gym, start_time, category)
        date_str = date_key.replace('_', ' ')
        report_message_text = f"EX Raid at {gym.name} on {date_str} starting at {start_time}.\n" \
                              f"If you have an invite to this raid, RSVP in: {ex_channel.mention}"
        report_message = await ctx.channel.send(embed=discord.Embed(colour=discord.Colour.gold(),
                                                                    description=report_message_text))
        hatch, expire = self._calculate_ex_start_time(date_key, start_time)
        ex_dict = self.bot.guild_dict[ctx.guild.id]['exchannel_dict'][category_id]['channels']
        ex_raid_dict = {
            "hatch": hatch,
            "expire": expire,
            "type": "exraid",
            "level": "exraid",
            "pokemon": None,
            "gym": gym.id,
            "report_channel": ctx.channel.id,
            "report_message": report_message.id,
            "channel_message": None,
            "trainer_dict": {},
            "stage": "pre"
        }
        ex_embed = await self._build_ex_embed(ctx, ex_raid_dict)
        channel_message = await ex_channel.send(embed=ex_embed)
        ex_raid_dict['channel_message'] = channel_message.id
        ex_dict[ex_channel.id] = ex_raid_dict
        self.bot.event_loop.create_task(self.expiry_check(ex_channel))

    async def _get_or_create_category(self, ctx, date_key):
        ex_dict = self.bot.guild_dict[ctx.guild.id].setdefault('exchannel_dict', {})
        categories = ex_dict.keys()
        for cat in categories:
            if date_key == ex_dict[cat]['date_key']:
                return cat
        name = date_key.replace('_', ' ')
        category = await ctx.guild.create_category(f"{name} EX Raids")
        ex_dict[category.id] = {'date_key': date_key, 'channels': {}}
        return category.id

    async def _create_ex_channel(self, ctx, gym, start_time, cat):
        channel_overwrite_dict = ctx.channel.overwrites
        kyogre_overwrite = {
            self.bot.user: discord.PermissionOverwrite(send_messages=True, read_messages=True, manage_roles=True,
                                                       manage_channels=True, manage_messages=True, add_reactions=True,
                                                       external_emojis=True, read_message_history=True,
                                                       embed_links=True, mention_everyone=True, attach_files=True)}
        channel_overwrite_dict.update(kyogre_overwrite)
        name = start_time.lower().replace(':', '').replace('am', '').replace('pm', '')
        name = utils.sanitize_name(f"{name} {gym.name}")[:36]
        return await ctx.guild.create_text_channel(name, overwrites=channel_overwrite_dict, category=cat)

    async def _build_ex_embed(self, ctx, ex_raid_dict):
        gym_id = ex_raid_dict['gym']
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gym = location_matching_cog.get_gym_by_id(ctx.guild.id, gym_id)
        utils_cog = self.bot.cogs.get('Utilities')
        raid_gmaps_link = gym.maps_url
        waze_link = utils_cog.create_waze_query(gym.latitude, gym.longitude)
        apple_link = utils_cog.create_applemaps_query(gym.latitude, gym.longitude)
        ex_embed = discord.Embed(colour=ctx.guild.me.colour)
        ex_embed.add_field(name='**Gym:**', value=gym.name, inline=False)
        ex_embed.add_field(name='Directions',
                           value=f'[Google]({raid_gmaps_link}) | [Waze]({waze_link}) | [Apple]({apple_link})',
                           inline=False)
        hatch = datetime.datetime.fromtimestamp(ex_raid_dict['hatch'])
        expire = datetime.datetime.fromtimestamp(ex_raid_dict['expire'])
        ex_embed.add_field(name='**Hatches:**', value=f"{hatch.strftime('%a %b %d %I:%M %p')}")
        ex_embed.add_field(name='**Expires:**', value=f"{expire.strftime('%a %b %d %I:%M %p')}")
        attendance_str = self._get_team_count_str(ctx, ex_raid_dict)
        ex_embed.add_field(name='**Attending:**', value=attendance_str)
        tip_str = "Use `!invite` or `!in` if you plan to attend\n"
        tip_str += "If you will be attending with additional accounts or friends, you can specify a number"
        ex_embed.add_field(name='**Tips:**', value=tip_str)
        egg_img = self.bot.raid_info['raid_eggs']['EX']['egg_img']
        raid_img_url = "https://github.com/tehstone/Kyogre/blob/master/images/eggs/{}?raw=true"\
            .format(str(egg_img))
        ex_embed.set_thumbnail(url=raid_img_url)
        return ex_embed

    def _calculate_ex_start_time(self, date_key, start_time):
        months, days = date_key.split('_')
        days = int(days)
        months = month_map[months]
        hours, minutes = start_time.lower().replace('am', '').replace('pm', '').split(':')
        hours, minutes = int(hours), int(minutes)
        if hours < 9:
            hours += 12
        hatch = datetime.datetime.utcnow().replace(month=months, day=days, hour=hours, minute=minutes, second=0)
        raid_length = self.bot.raid_info['raid_eggs']['EX']['raidtime']
        raid_length = 1
        expire = hatch + datetime.timedelta(minutes=raid_length)
        return hatch.timestamp(), expire.timestamp()

    @commands.command(name='invite', aliases=['in'])
    @checks.exraidchannel()
    async def _invite(self, ctx, *, teamcounts: str = None):
        trainer_dict = self.bot.guild_dict[ctx.guild.id]['exchannel_dict'][ctx.channel.category_id]\
            ['channels'][ctx.channel.id].setdefault('trainer_dict', {})
        raidparty_cog = self.bot.cogs.get('RaidParty')
        result, __, __ = await raidparty_cog.process_status_command(ctx, teamcounts, trainer_dict, 'EX')
        if isinstance(result, list):
            count = result[0]
            partylist = result[1]
            if not partylist:
                listmanagement_cog = self.bot.cogs.get('ListManagement')
                partylist = listmanagement_cog.determine_simple_party(ctx.author, count)
            spec_t_dict = trainer_dict.setdefault(ctx.author.id, {})
            spec_t_dict['count'] = count
            spec_t_dict['party'] = partylist
        else:
            return
        ex_raid_dict = self.bot.guild_dict[ctx.guild.id]['exchannel_dict'][ctx.channel.category_id] \
            ['channels'][ctx.channel.id]
        embed = await self._build_ex_embed(ctx, ex_raid_dict)
        channel_message_id = ex_raid_dict['channel_message']
        channel_message = await ctx.channel.fetch_message(channel_message_id)
        await channel_message.edit(embed=embed)
        await ctx.channel.send(f"{ctx.author.display_name} will be attending with {count}")
        await ctx.message.delete()

    def _get_team_count_str(self, ctx, ex_raid_dict):
        team_counts = {"instinct": 0,
                       "mystic": 0,
                       "valor": 0,
                       "unknown": 0}
        trainer_dict = ex_raid_dict.setdefault('trainer_dict', {})
        for trainer in trainer_dict:
            party = trainer_dict[trainer].get('party', {})
            for team in ["mystic", "valor", "instinct", "unknown"]:
                team_counts[team] += party.get(team, 0)
        red_emoji = utils.parse_emoji(ctx.channel.guild, self.bot.config['team_dict']['valor'])
        yellow_emoji = utils.parse_emoji(ctx.channel.guild, self.bot.config['team_dict']['instinct'])
        blue_emoji = utils.parse_emoji(ctx.channel.guild, self.bot.config['team_dict']['mystic'])
        grey_emoji = '❔'
        return f"{yellow_emoji} : {team_counts['instinct']} - {blue_emoji} : {team_counts['mystic']} " \
               f"- {red_emoji} : {team_counts['valor']} - {grey_emoji} : {team_counts['unknown']} "

    def get_existing_raid(self, guild, location, ex_raid_dict):
        """returns a list of channel ids for ex raids reported at the location provided"""
        report_dict = {}
        for cat in ex_raid_dict:
            cat_dict = ex_raid_dict[cat]
            report_dict = {**report_dict, **cat_dict['channels']}

        def matches_existing(report):
            gym_id = report['gym']
            location_matching_cog = self.bot.cogs.get('LocationMatching')
            gym = location_matching_cog.get_gym_by_id(guild.id, gym_id)
            if gym is None:
                return False
            name_matches = gym.name.lower() == location.name.lower()
            return report.get('gym', None) and name_matches
        return [channel_id for channel_id, report in report_dict.items() if matches_existing(report)]

    @staticmethod
    async def _send_ex_channel_reminder(this_ex_dict, channel, action):
        trainers = []
        for t in this_ex_dict['trainer_dict'].keys():
            user = channel.guild.get_member(t)
            trainers.append(user.mention)
        if action == "before":
            this_ex_dict['stage'] = 'egg'
            return await channel.send(f"This EX Raid will be hatching soon!\n{' '.join(trainers)}")
        elif action == "hatch":
            this_ex_dict['stage'] = 'active'
            return await channel.send("This EX raid has hatched!")
        elif action == "expire":
            this_ex_dict['stage'] = 'expired'
            return await channel.send("This EX raid has expired. This channel will be deleted in about 2 hours.")

    async def _delete_ex_channel(self, channel):
        try:
            del self.bot.guild_dict[channel.guild.id]['exchannel_dict'][channel.category_id]['channels'][channel.id]
        except KeyError:
            pass
        try:
            await channel.delete()
        except (discord.errors.NotFound, discord.errors.Forbidden, discord.errors.HTTPException):
            pass

    async def channel_cleanup(self):
        while not self.bot.is_closed():
            active_ex = self.bot.active_ex
            guilddict_chtemp = copy.deepcopy(self.bot.guild_dict)
            self.bot.logger.info('EX Channel_Cleanup ------ BEGIN ------')
            # for every server in save data
            for guildid in guilddict_chtemp.keys():
                guild = self.bot.get_guild(guildid)
                log_str = 'EX Channel_Cleanup - Server: ' + str(guildid)
                log_str = log_str + ' - CHECKING FOR SERVER'
                if guild is None:
                    self.bot.logger.info(log_str + ': NOT FOUND')
                    continue
                self.bot.logger.info(((log_str + ' (') + guild.name) + ')  - BEGIN CHECKING SERVER')
                # clear channel lists
                dict_channel_delete = []
                discord_channel_delete = []
                # check every ex channel data for each server
                for cat in guilddict_chtemp[guildid].get('exchannel_dict', {}):
                    cat_dict = guilddict_chtemp[guildid]['exchannel_dict'][cat]
                    for channelid in cat_dict['channels'].keys():
                        channel = self.bot.get_channel(channelid)
                        log_str = 'EX Channel_Cleanup - Server: ' + guild.name
                        log_str = (log_str + ': Channel:') + str(channelid)
                        self.bot.logger.info(log_str + ' - CHECKING')
                        channelmatch = self.bot.get_channel(channelid)
                        if channelmatch is None:
                            # list channel for deletion from save data
                            dict_channel_delete.append((cat, channelid))
                            self.bot.logger.info(log_str + " - NOT IN DISCORD")
                        # otherwise, if kyogre can still see the channel in discord
                        else:
                            self.bot.logger.info(
                                ((log_str + ' (') + channel.name) + ') - EXISTS IN DISCORD')
                            # If it's been more than 2 hours since the raid ended
                            if cat_dict['channels'][channel.id]['expire'] < (time.time() - (120 * 60)):
                                # list the channel to be removed from save data
                                dict_channel_delete.append((cat, channelid))
                                # and list the channel to be deleted in discord
                                discord_channel_delete.append(channel)
                                self.bot.logger.info(
                                    log_str + ' - Expired EX Raid')
                                continue
                            else:
                                if channel not in active_ex:
                                    # if channel is still active, make sure it's expiry is being monitored
                                    self.bot.event_loop.create_task(self.expiry_check(channel))
                                    self.bot.logger.info(
                                        log_str + ' - MISSING FROM EXPIRY CHECK')
                                    continue
                # for every channel listed to have save data deleted
                for p in dict_channel_delete:
                    try:
                        # attempt to delete the channel from save data
                        del self.bot.guild_dict[guildid]['exchannel_dict'][p[0]]['channels'][p[1]]
                        self.bot.logger.info(
                            'EX Channel_Cleanup - Channel Savedata Cleared - ' + str(p[1]))
                    except KeyError:
                        pass
                # for every channel listed to have the discord channel deleted
                for c in discord_channel_delete:
                    try:
                        # delete channel from discord
                        await c.delete()
                        self.bot.logger.info(
                            'EX Channel_Cleanup - Channel Deleted - ' + c.name)
                    except:
                        self.bot.logger.info(
                            'EX Channel_Cleanup - Channel Deletion Failure - ' + c.name)
                        pass
                # save server_dict changes after cleanup
                self.bot.logger.info('EX Channel_Cleanup - SAVING CHANGES')
                try:
                    admin_commands_cog = self.bot.cogs.get('AdminCommands')
                    if not admin_commands_cog:
                        return None
                    await admin_commands_cog.save(guildid)
                except Exception as err:
                    self.bot.logger.info('EX Channel_Cleanup - SAVING FAILED' + str(err))
            self.bot.logger.info('EX Channel_Cleanup ------ END ------')
            await asyncio.sleep(600)
            continue

    async def expiry_check(self, channel):
        self.bot.logger.info('Expiry_Check - ' + channel.name)
        guild = channel.guild
        channel = self.bot.get_channel(channel.id)
        cat_id = channel.category_id
        offset = self.bot.guild_dict[channel.guild.id]['configure_dict']['settings']['offset']
        if channel not in self.bot.active_ex:
            self.bot.active_ex.append(channel)
            self.bot.logger.info(
                'Expire_Channel - Channel Added To Watchlist - ' + channel.name)
            await asyncio.sleep(0.5)
            while True:
                this_ex_dict = self.bot.guild_dict[guild.id]['exchannel_dict'][cat_id]['channels'][channel.id]
                sleep_time = 30
                try:
                    if this_ex_dict['stage'] == 'pre':
                        if this_ex_dict['hatch'] - (30 * 60) < time.time():
                            await self._send_ex_channel_reminder(this_ex_dict, channel, "before")
                        time_diff = this_ex_dict['hatch'] - (
                                    datetime.datetime.utcnow() + datetime.timedelta(hours=offset)).timestamp()
                        sleep_time = round(time_diff/2)
                    if this_ex_dict['stage'] == 'egg':
                        if this_ex_dict['hatch'] - (1 * 60) < time.time():
                            await self._send_ex_channel_reminder(this_ex_dict, channel, "hatch")
                    if this_ex_dict['stage'] == 'active':
                        if this_ex_dict['expire'] < time.time():
                            await self._send_ex_channel_reminder(this_ex_dict, channel, "expire")
                        sleep_time = 60
                    if this_ex_dict['stage'] == 'expired':
                        if this_ex_dict['expire'] + (120 * 60) < time.time():
                            await self._delete_ex_channel(channel)
                            try:
                                self.bot.active_ex.remove(channel)
                            except ValueError:
                                self.bot.logger.info(
                                    'Expire_Channel - Channel Removal From Active EX Failed - '
                                    'Not in List - ' + channel.name)
                            self.bot.logger.info(
                                'Expire_Channel - Channel Expired And Removed From Watchlist - ' + channel.name)
                            break
                        time_diff = (this_ex_dict['expire'] + (120 * 60)) - (
                                datetime.datetime.utcnow() + datetime.timedelta(hours=offset)).timestamp()
                        sleep_time = round(time_diff / 2)
                except:
                    pass
                print(f"st: {sleep_time}")
                await asyncio.sleep(sleep_time)
                continue


def setup(bot):
    bot.add_cog(EXRaids(bot))
