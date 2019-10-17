import datetime
import os
from operator import itemgetter

import shutil
import time
from PIL import Image

import discord
from discord.ext import commands

from kyogre import image_scan, testident, utils, checks
from kyogre.context import Context
from kyogre.exts.db.kyogredb import APIUsageTable, GuildTable, TrainerTable, fn
from kyogre.exts.pokemon import Pokemon


async def _save_image(attachment):
    __, file_extension = os.path.splitext(attachment.filename)
    filename = f"{attachment.id}{file_extension}"
    filepath = os.path.join('screenshots', filename)
    with open(filepath, 'wb') as out_file:
        await attachment.save(out_file)
    return filepath


class RaidAuto(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hashes = {}

    async def create_raid(self, ctx, raid_info):
        guild = ctx.guild
        channel = ctx.channel
        author = ctx.author
        raidexp, start = 0, None
        # Determine current time based on raid_info["phone"] or just use current time
        if raid_info["phone_time"]:
            offset = self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset']
            start = utils.parse_time_str(offset, raid_info["phone_time"])
        # Determine hatch time based on raid_info["egg"] or use default
        if raid_info['exp']:
            raidexp = await utils.time_to_minute_count(self.bot.guild_dict, channel, raid_info["exp"],
                                                       current=start)
        if raidexp < 0 and raid_info['type'] == 'raid':
            self.bot.gcv_logger.info(f"{ctx.author} posted an expired raid.")
            return await ctx.channel.send(embed=discord.Embed(
                colour=discord.Colour.red(),
                description=f"This raid has already expired. Please do not post expired raids."))
        # Determine region
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(channel, 'raid')
        # Get gyms
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(guild.id, regions)
        # check existing
        raid_cog = self.bot.cogs.get('RaidCommands')
        gym = await location_matching_cog.match_prompt(channel, author.id, raid_info["gym"], gyms)
        raid_channel_ids = raid_cog.get_existing_raid(guild, gym)
        if raid_channel_ids:
            try:
                raid_dict_entry = self.bot.guild_dict[guild.id]['raidchannel_dict'][raid_channel_ids[0]]
                # if existing, if screenshot is boss and existing is egg then update
                if raid_dict_entry['type'] == 'raid' or raid_info['type'] == 'egg':
                    # already reported
                    return await channel.send(
                                        embed=discord.Embed(
                                            colour=discord.Colour.red(),
                                            description=f"A raid has already been reported for {gym.name}"))
                return await raid_cog.egg_to_raid(ctx, raid_info['boss'], self.bot.get_channel(raid_channel_ids[0]))
            except KeyError:
                pass
        if raid_info['type'] == 'egg':
            await raid_cog.finish_raid_report(ctx, raid_info["gym"], None, raid_info["tier"],
                                              None, raidexp, auto=True)
        else:
            report_channel = None
            listmgmt_cog = self.bot.cogs.get('ListManagement')
            reporting_channels = await listmgmt_cog.get_region_reporting_channels(guild, regions[0])
            if len(reporting_channels) > 0:
                report_channel = guild.get_channel(reporting_channels[0])
            pokemon_name = raid_info['boss']
            if pokemon_name in Pokemon.get_alolans_list():
                raid_pokemon = Pokemon.get_pokemon(self.bot, pokemon_name)
                if not raid_pokemon.is_raid:
                    raid_pokemon = Pokemon.get_pokemon(self.bot, "alolan" + pokemon_name)
            else:
                raid_pokemon = Pokemon.get_pokemon(self.bot, pokemon_name)
            if not raid_pokemon.is_raid:
                error_desc = f'The Pokemon {raid_pokemon.name} does not currently appear in raids.'
                return await channel.send(embed=discord.Embed(colour=discord.Colour.red(), description=error_desc))
            await raid_cog.finish_raid_report(ctx, raid_info["gym"], raid_pokemon, raid_pokemon.raid_level,
                                              None, raidexp, auto=True, report_channel=report_channel)

    @commands.command(name='add_scan_listen_channel', aliases=['aslc'])
    async def _add_scan_listen_channel(self, ctx, channel):
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'] \
            .setdefault('scan_listen_channels', [])
        utilities_cog = self.bot.cogs.get('Utilities')
        aslc_channel = await utilities_cog.get_channel_by_name_or_id(ctx, channel)
        if aslc_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        if aslc_channel.id in listen_channels:
            await ctx.channel.send('Channel already listed as a listen channel.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        listen_channels.append(aslc_channel.id)
        await ctx.channel.send(f'Added channel {aslc_channel.mention} to listen channel list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.command(name='remove_scan_listen_channel', aliases=['rslc'])
    async def _remove_scan_listen_channel(self, ctx, channel):
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings'] \
            .setdefault('scan_listen_channels', [])
        utilities_cog = self.bot.cogs.get('Utilities')
        aslc_channel = await utilities_cog.get_channel_by_name_or_id(ctx, channel)
        if aslc_channel is None:
            await ctx.channel.send('No channel found by that name or id, please try again.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        if aslc_channel.id not in listen_channels:
            await ctx.channel.send('Channel not listed as a listen channel.', delete_after=10)
            return await ctx.message.add_reaction(self.bot.failed_react)
        listen_channels.remove(aslc_channel.id)
        await ctx.channel.send(f'Removed channel {aslc_channel.mention} from listen channel list.', delete_after=10)
        return await ctx.message.add_reaction(self.bot.success_react)

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self.bot.get_context(message, cls=Context)
        if len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None))\
                or message.author == self.bot.user:
            return
        listen_channels = self.bot.guild_dict[ctx.guild.id]['configure_dict']['settings']\
            .setdefault('scan_listen_channels', [])
        if message.channel.id in listen_channels:
            await message.add_reaction('🤔')
            for attachment in message.attachments:
                file = await self._image_pre_check(attachment)
                start = time.time()
                await self.scan_test(ctx, file)
                self.bot.gcv_logger.info(f"test scan: {time.time()-start}")
            return
        if not checks.check_raidreport(ctx) and not checks.check_raidchannel(ctx):
            return
        await message.add_reaction('🤔')
        await self._process_message_attachments(ctx, message)

    async def _process_message_attachments(self, ctx, message):
        # TODO Determine if it's worth handling multiple attachments and refactor to accommodate
        start = time.time()
        file = await self._image_pre_check(message.attachments[0])
        if self.already_scanned(file):
            os.remove(file)
            return await ctx.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="This image has already been scanned. If a raid was not created previously from this "
                                "image, please report using the command instead:\n `!r <boss/tier> <gym name> <time>`"))
        self.bot.gcv_logger.info(file)
        utils_cog = self.bot.cogs.get('Utilities')
        regions = utils_cog.get_channel_regions(ctx.channel, 'raid')
        raid_info = await self._scan_wrapper(ctx, file, regions)
        if raid_info["gym"] is None:
            return await message.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="Could not determine gym name from screenshot, unable to create raid channel. "
                                "Please report using the command instead: `!r <boss/tier> <gym name> <time>`"))
        c_file = None
        if raid_info['egg_time'] and not raid_info['boss']:
            c_file = self._crop_tier(file)
            tiers = testident.determine_tier(c_file)
            self.bot.gcv_logger.info(tiers)
            tier = self._determine_tier(tiers)
            raid_info['type'] = 'egg'
            raid_info['tier'] = tier
            if tier == "0":
                return await message.channel.send(
                    embed=discord.Embed(
                        colour=discord.Colour.red(),
                        description=("Could not determine raid boss or egg level from screenshot, unable to create "
                                     "raid channel. If you're trying to report a raid, please use the command instead: "
                                     "`!r <boss/tier> <gym name> <time>`")))
        if raid_info['expire_time'] or raid_info['boss']:
            raid_info['type'] = 'raid'
        timev = None
        if raid_info['egg_time']:
            timev = raid_info['egg_time']
        elif raid_info['expire_time']:
            timev = raid_info['expire_time']
        if timev:
            time_split = timev.split(':')
            timev = str(60*int(time_split[0]) + int(time_split[1]))
            raid_info['exp'] = timev
        self.bot.gcv_logger.info(raid_info)
        self.bot.gcv_logger.info(f"real scan: {time.time() - start}")
        await self.create_raid(ctx, raid_info)
        if c_file:
            os.remove(c_file)

    async def _image_pre_check(self, attachment):
        file = await _save_image(attachment)
        img = Image.open(file)
        img = self.exif_transpose(img)
        filesize = os.stat(file).st_size
        img = self._check_resize(img, filesize)
        img.save(file)
        return file

    async def _build_raid_info(self, tier, file):
        raid_info = {}
        if tier == "0":
            self._cleanup_file(file, "screenshots/not_raid")
            return None, None
        elif tier.isdigit():
            file = self._cleanup_file(file, f"screenshots/{tier}")
            raid_info["type"] = "egg"
            raid_info["level"] = f"{tier}"
        else:
            out_path = os.path.join("screenshots", tier)
            if not os.path.exists(out_path):
                os.makedirs(out_path)
            file = self._cleanup_file(file, out_path)
            raid_info["type"] = "raid"
            raid_info["boss"] = tier
        return raid_info, file

    @staticmethod
    def _check_resize(image, filesize):
        if filesize > 2500000:
            factor = 1.05
            if filesize > 5000000:
                factor = 1.2
            width, height = image.size
            width = int(width/factor)
            height = int(height/factor)
            image = image.resize((width, height))
        return image

    @staticmethod
    def exif_transpose(img):
        if not img:
            return img
        exif_orientation_tag = 274
        # Check for EXIF data (only present on some files)
        if hasattr(img, "_getexif") and isinstance(img._getexif(), dict) and exif_orientation_tag in img._getexif():
            exif_data = img._getexif()
            orientation = exif_data[exif_orientation_tag]
            # Handle EXIF Orientation
            if orientation == 1:
                # Normal image - nothing to do!
                pass
            elif orientation == 2:
                # Mirrored left to right
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 3:
                # Rotated 180 degrees
                img = img.rotate(180)
            elif orientation == 4:
                # Mirrored top to bottom
                img = img.rotate(180).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 5:
                # Mirrored along top-left diagonal
                img = img.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 6:
                # Rotated 90 degrees
                img = img.rotate(-90, expand=True)
            elif orientation == 7:
                # Mirrored along top-right diagonal
                img = img.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 8:
                # Rotated 270 degrees
                img = img.rotate(90, expand=True)
        return img

    @staticmethod
    def dhash(image, hash_size=32):
        image = image.convert('L').resize(
            (hash_size + 1, hash_size),
            Image.ANTIALIAS,
        )
        difference = []
        for row in range(0, hash_size):
            for col in range(0, hash_size):
                pixel_left = image.getpixel((col, row))
                pixel_right = image.getpixel((col + 1, row))
                difference.append(pixel_left > pixel_right)
        decimal_value = 0
        hex_string = []
        for index, value in enumerate(difference):
            if value:
                decimal_value += 2 ** (index % 8)
            if (index % 8) == 7:
                hex_string.append(hex(decimal_value)[2:].rjust(2, '0'))
                decimal_value = 0
        return ''.join(hex_string)

    def already_scanned(self, file):
        image = Image.open(file)
        im_hash = self.dhash(image)
        if im_hash in self.hashes:
            return True
        else:
            self.hashes[im_hash] = 1
            return False

    @staticmethod
    def _determine_tier(tiers):
        tier_str = "0"
        for tier in tiers:
            if tier[0].startswith("tier"):
                tier_str = tier[0][4]
                break
        return tier_str

    @staticmethod
    def _count_usage(ctx):
        __, __ = GuildTable.get_or_create(snowflake=ctx.guild.id)
        trainer, __ = TrainerTable.get_or_create(snowflake=ctx.author.id, guild=ctx.guild.id)
        now = round(time.time())
        APIUsageTable.create(trainer=trainer, date=now)

    @staticmethod
    async def _get_usage(ctx):
        month_start = round(datetime.datetime.today().replace(day=1, hour=0, minute=0).timestamp())
        usage = (APIUsageTable.select(fn.Count(APIUsageTable.trainer).alias('count'))
                 .join(TrainerTable)
                 .where((TrainerTable.snowflake == ctx.author.id) &
                        (APIUsageTable.date > month_start))
                 )
        if len(usage) < 1:
            return 0
        return usage[0].count

    @staticmethod
    def _cleanup_file(file, dst):
        filename = os.path.split(file)[1]
        dest = os.path.join(dst, filename)
        shutil.move(file, dest)
        return dest

    @staticmethod
    def _crop_tier(file):
        filename, file_extension = os.path.splitext(file)
        filename += '_c'
        original = Image.open(file)
        width, height = original.size
        left = width / 6
        top = height / 5
        right = 5 * width / 6
        bottom = 4 * height / 5
        cropped_example = original.crop((left, top, right, bottom))
        out_path = filename + file_extension
        cropped_example.save(out_path)
        return out_path

    @commands.command(name="test_gym_ident", aliases=['tgi'])
    async def test_gym_ident(self, ctx):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(ctx.guild.id)
        for name in self.test_data:
            result = location_matching_cog.location_match(name, gyms)
            results = [(match.name, score) for match, score in result]
            print(f"scanned: {name}\nproduced: {results}")
        pass

    async def _scan_wrapper(self, ctx, file, region=None):
        image_info = await image_scan.read_photo_async(file, self.bot.gcv_logger)
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(ctx.guild.id, region)
        gym = None
        possible_gyms = {}
        # Iterate through all possible names and look first for full matches
        # When a 100% match is found, the gym will be set.
        # Otherwise, track how many times we get a match with a lower score
        for name in image_info['names']:
            result = location_matching_cog.location_match(name.strip(), gyms, is_partial=False)
            results = [(match.name, score) for match, score in result]
            results = sorted(results, key=itemgetter(1), reverse=True)
            for r in results:
                if not gym and r[1] >= 98:
                    gym = next((l for l in gyms if l.name == r[0]), None)
                else:
                    if r[0] in possible_gyms:
                        possible_gyms[r[0]] += 1
                    else:
                        possible_gyms[r[0]] = 1
        # If no match was found previously, try partial matches on all possible names
        # and again set the gym if a 100% match is found and track count of lower score matches.
        if not gym:
            for name in image_info['names']:
                result = location_matching_cog.location_match(name.strip(), gyms)
                results = [(match.name, score) for match, score in result]
                results = sorted(results, key=itemgetter(1), reverse=True)
                for r in results:
                    if not gym and r[1] == 100:
                        gym = next((l for l in gyms if l.name == r[0]), None)
                    else:
                        if r[0] in possible_gyms:
                            possible_gyms[r[0]] += 1
                        else:
                            possible_gyms[r[0]] = 1
        # If no gym has yet been identified, rank all possible matches by occurrence count
        # And set the gym to the one with the highest count.
        # This may still need work but seems to be the best option overall so far.
        self.bot.gcv_logger.info(possible_gyms)
        if possible_gyms and not gym:
            pgk = list(possible_gyms.keys())
            if len(pgk) == 1:
                gym = next((l for l in gyms if l.name == pgk[0]), None)
            else:
                possible_gyms = [f"Option {i}: {g[0]}" for i, g in
                                 enumerate(sorted(possible_gyms.items(),
                                                  key=itemgetter(1),
                                                  reverse=True))][:min(3, len(possible_gyms))]
                gym = next((l for l in gyms if l.name == possible_gyms[0]), None)
        if gym:
            image_info['gym'] = gym.name
        else:
            image_info['gym'] = None
        return image_info

    async def scan_test(self, ctx, file, region=None):
        image_info = await self._scan_wrapper(ctx, file, region)

        if not image_info['phone_time']:
            image_info['phone_time'] = 'Unknown'
        gym = image_info['gym']
        if gym:
            gym_str = gym
        else:
            gym_str = ''
        if len(gym_str) < 1:
            gym_str = '\n'.join(image_info['names'])
        tier_str = '?'
        c_file = None
        if image_info['egg_time'] and not image_info['boss']:
            c_file = self._crop_tier(file)
            tiers = testident.determine_tier(c_file)
            tier_str = self._determine_tier(tiers)
        embed = discord.embeds.Embed(title="Image Scan Results", color=discord.colour.Color.blue())
        embed.add_field(name='Gym Name', value=gym_str, inline=False)
        if tier_str != '?':
            embed.add_field(name='Tier', value=tier_str, inline=False)
        elif image_info['boss']:
            embed.add_field(name='Boss', value=image_info['boss'].capitalize(), inline=False)
        embed.add_field(name='Phone Time', value=image_info['phone_time'], inline=False)
        if image_info['egg_time']:
            embed.add_field(name='Time Until Hatch', value=image_info['egg_time'], inline=False)
        if image_info['expire_time']:
            embed.add_field(name='Time Remaining', value=image_info['expire_time'], inline=False)
        self.bot.gcv_logger.info(f"result_egg: {image_info['egg_time']} "
                                 f"result_expire: {image_info['expire_time']} "
                                 f"result_boss: {image_info['boss']} "
                                 f"tier: {tier_str} "
                                 f"result_gym: {image_info['names']} "
                                 f"gym: {gym_str} "
                                 f"result_phone: {image_info['phone_time']} "
                                 f"total runtime: {image_info['runtime']}")
        await ctx.send(embed=embed)
        if c_file:
            os.remove(c_file)


def setup(bot):
    bot.add_cog(RaidAuto(bot))
