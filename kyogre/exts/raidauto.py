import datetime
import os
import random
import re
from operator import itemgetter

import requests
import shutil
import time
from PIL import Image

import discord
from discord.ext import commands

import google.cloud.vision as vision

from kyogre import image_scan, testident, utils, checks
from kyogre.context import Context
from kyogre.exts.db.kyogredb import APIUsageTable, GuildTable, TrainerTable, fn
from kyogre.exts.pokemon import Pokemon


class RaidAuto(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hashes = {}
        self.test_data = ["""EX RAID CG

=* Burnett Linear Park O

<< oe |

, a WO am OY a Ve |""",
"""EX RAID C

=< Burnett Linear Park O

a, be
7 ww. |""",
"""* Renton Civic Theatre So

oo I I
q a, wa) | we""",
""". Renton Civic Theatre O

SUI
yw. av a *""",
"""EX RAID C
Untitled Mural by
toy ata (=) ©""",
"""EX RAID C
Untitled Mural by 5
Bonnie Branson 1989

0 NO ee Le Ca""",
"""EX RAID C

Tee CS
ae)

| a oe Le _""",
"""EX RAID C

pre 1900s O
a""",
"""' Wat Lao Mixayaram O

VSUve""",
"""\ . Wat Lao Mixayaram O

AAA""",
"""4.
Renton Library O

y eRe)
> fle AF A Ff""",
"""Renton Library So

© ee)
| a a a""",
"""ar ;
aT aren S
y

Roadhouse

Ue &
or rh""",
"""aan S

Roadhouse

ty
orm rhe""",
"""Renton Brown Bear O""",
"""Renton Brown Bear So""",
""") 8-Bit Arcade-Bar So""",
""") 8-Bit Arcade-Bar O""",
"""yeah ea So""",
"""yea hea O"""]

    async def create_raid(self, ctx, raid_info):
        guild = ctx.guild
        channel = ctx.channel
        author = ctx.author
        raidexp, now = 0, None
        # Determine current time based on raid_info["phone"] or just use current time
        if raid_info["phone"]:
            offset = self.bot.guild_dict[guild.id]['configure_dict']['settings']['offset']
            start = utils.parse_time_str(offset, raid_info["phone"])
        # Determine hatch time based on raid_info["egg"] or use default
        if raid_info["egg"]:
            raidexp = await utils.time_to_minute_count(self.bot.guild_dict, channel, raid_info["egg"], current=start)
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
            await raid_cog.finish_raid_report(ctx, raid_info["gym"], None, raid_info["level"],
                                              None, raidexp, auto=True)
        else:
            raid_pokemon = Pokemon.get_pokemon(self.bot, raid_info["boss"])
            await raid_cog.finish_raid_report(ctx, raid_info["gym"], raid_pokemon, raid_pokemon.raid_level,
                                              None, raidexp, auto=True)
        pass

    @commands.Cog.listener()
    async def on_message(self, message):
        ctx = await self.bot.get_context(message, cls=Context)
        if len(message.attachments) < 1 \
                or ((message.attachments[0].height is None) and
                    (message.attachments[0].width is None))\
                or message.author == self.bot.user:
            return
        if message.channel.id in [628670877826940951]:
            file = self._image_pre_check(message)
            return await ctx.send(await self.newtest(ctx, file))
        return
        # if not checks.check_raidreport(ctx) and not checks.check_raidchannel(ctx):
        #     return
        # if not self.bot.vision_api_enabled:
        #     return await ctx.send(embed=discord.Embed(
        #             colour=discord.Colour.red(),
        #             description="Screenshot reporting is not enabled at this time. "
        #                         "Please report with the command instead:\n `!r <boss/tier> <gym name> <time>`"))
        # await self._process_message_attachments(ctx, message)

    async def _process_message_attachments(self, ctx, message):
        # TODO Determine if it's worth handling multiple attachments and refactor to accommodate
        a = message.attachments[0]
        file = self._image_pre_check(message)
        if self.already_scanned(file):
            os.remove(file)
            return await ctx.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="This image has already been scanned. If a raid was not created previously from this "
                                "image, please report using the command instead:\n `!r <boss/tier> <gym name> <time>`"))
        usage = await self._get_usage(ctx)
        if usage > self.bot.api_usage_limit:
            return await ctx.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="You have used your maximum number of reports via screenshot allowed this month, "
                                "please report using the command instead:\n `!r <boss/tier> <gym name> <time>`"))
        self.bot.gcv_logger.info(file)
        tier = self._determine_raid(file)
        raid_info, file = await self._build_raid_info(tier, file)
        if not raid_info:
            return await message.add_reaction(self.bot.failed_react)
        # raid_info = dict(await self._call_cloud(file), **raid_info)
        raid_info = dict(await self._fake_cloud(), **raid_info)
        self._count_usage(ctx)
        if raid_info["gym"] is None:
            # self._cleanup_file(file, "screenshots/gcvapi_failed")
            return await message.channel.send(
                embed=discord.Embed(
                    colour=discord.Colour.red(),
                    description="Could not determine gym name from screenshot, unable to create raid channel. "
                                "Please report using the command instead: `!r <boss/tier> <gym name> <time>`"))
            pass
        return await self.create_raid(ctx, raid_info)

    def _image_pre_check(self, message):
        file = self._save_image(message.attachments[0])
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

    def _save_image(self, attachment):
        url = attachment.url
        __, file_extension = os.path.splitext(attachment.filename)
        if not url.startswith('https://cdn.discordapp.com/attachments'):
            return None
        r = requests.get(url, stream=True)
        filename = f"{attachment.id}{file_extension}"
        #### TODO revert path
        filepath = os.path.join('screenshotsz', filename)
        with open(filepath, 'wb') as out_file:
            shutil.copyfileobj(r.raw, out_file)
        self.bot.saved_files[filename] = {"time": round(time.time()), "fullpath": filepath}
        return filepath

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

    def _determine_raid(self, file):
        tier = testident.determine_tier(file)
        self.bot.gcv_logger.info(tier)
        tier = tier[0]
        if tier[0].startswith("none"):
            return "0"
        elif tier[0].startswith("tier"):
            return str(tier[0][4])
        else:
            pokemon = tier[0][1:]
            if pokemon.startswith('a-'):
                pokemon = 'alolan ' + pokemon[2:]
            return pokemon

    async def _call_cloud(self, file):
        # Hook into cloud api call and process data returned into correct format
        # {"phone": "3:10", "egg": "45", "gym": ""}
        # The three keys here are required, any and all can be None
        with open(file, "rb") as image_file:
            content = image_file.read()
        client = vision.ImageAnnotatorClient()
        image = vision.types.Image(content=content)
        response = client.text_detection(image=image)
        texts = response.text_annotations

        phone_time, egg_time = None, None
        gym_name = []
        text = texts[0]
        # match phone time display of form 5:23 or 13:23
        p_time_regex = re.compile(r'1*[0-9]{1}:[0-5]{1}[0-9]{1}')
        # match hatch/expire countdown of form 0:11:28
        e_time_regex = re.compile(r'[0-1]{1}:[0-5]{1}[0-9]{1}:[0-5]{1}[0-9]{1}')
        cp_regex = re.compile(r'[0-9]{5,6}')
        batt_regex = re.compile(r'^[0-9]{1,3}%*$')
        search_gym = True
        self.bot.gcv_logger.info(text.description)
        for line in text.description.split('\n'):
            if 'LTE' in line or len(line) < 2:
                continue
            e_search = e_time_regex.search(line)
            if e_search:
                egg_all = e_search[0]
                egg_split = egg_all.split(':')
                egg_time = str(int(60*egg_split[0]) + int(egg_split[1]))
                break
            p_search = p_time_regex.search(line)
            if p_search:
                phone_time = p_search[0]
                continue
            if line == 'EX RAID GYM':
                continue
            cp_search = cp_regex.search(line)
            if cp_search:
                search_gym = False
                continue
            batt_search = batt_regex.search(line)
            if batt_search:
                continue
            if search_gym:
                line = re.sub(r"\b[a-zA-Z0-9]{1,2}\b", "", line)
                gym_name.append(line)
        gym = None
        if len(gym_name) > 1:
            gym = ' '.join(gym_name)
        self.bot.gcv_logger.info(f"Read gym as: {gym}. Read phone time as: {phone_time}. "
                                 f"Read egg time as: {egg_time}")
        return {"phone": phone_time, "egg": egg_time, "gym": gym}

    async def _fake_cloud(self):
        text = '''6:421
.lLTE
Renton Diamond
Jubilee
3472
RVtor
0:43:54
Walk closer to interact with this Gym.
'''
        phone_time, egg_time = None, None
        gym_name = []
        # match phone time display of form 5:23 or 13:23
        p_time_regex = re.compile(r'1*[0-9]{1}:[0-5]{1}[0-9]{1}')
        # match hatch/expire countdown of form 0:11:28
        e_time_regex = re.compile(r'[0-1]{1}:[0-5]{1}[0-9]{1}:[0-5]{1}[0-9]{1}')
        cp_regex = re.compile(r'[0-9]{5,6}')
        batt_regex = re.compile(r'^[0-9]{1,3}%*$')
        search_gym = True
        for line in text.split('\n'):
            if 'LTE' in line or len(line) < 2:
                continue
            e_search = e_time_regex.search(line)
            if e_search:
                egg_all = e_search[0]
                egg_split = egg_all.split(':')
                egg_time = str(int(60 * egg_split[0]) + int(egg_split[1]))
                break
            p_search = p_time_regex.search(line)
            if p_search:
                phone_time = p_search[0]
                continue
            if line == 'EX RAID GYM':
                continue
            cp_search = cp_regex.search(line)
            if cp_search:
                search_gym = False
                continue
            batt_search = batt_regex.search(line)
            if batt_search:
                continue
            if search_gym:
                line = re.sub(r"\b[a-zA-Z0-9]{1,2}\b", "", line)
                gym_name.append(line)
        gym = None
        if len(gym_name) > 1:
            gym = ' '.join(gym_name)
        self.bot.gcv_logger.info(f"Read gym as: {gym}. Read phone time as: {phone_time}. "
                                 f"Read egg time as: {egg_time}")
        return {"phone": phone_time, "egg": egg_time, "gym": gym}

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

    @commands.command(name="test_gym_ident", aliases=['tgi'])
    async def test_gym_ident(self, ctx):
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(ctx.guild.id)
        for name in self.test_data:
            result = location_matching_cog.location_match(name, gyms)
            results = [(match.name, score) for match, score in result]
            print(f"scanned: {name}\nproduced: {results}")
        pass

    async def newtest(self, ctx, file):
        image_info = await image_scan.read_photo_async(file, self.bot.gcv_logger)
        # {'egg': egg_time, 'expire': expire_time, 'phone': phone_time, 'names': gym_name_options}
        location_matching_cog = self.bot.cogs.get('LocationMatching')
        gyms = location_matching_cog.get_gyms(ctx.guild.id)
        gym = None
        for name in image_info['names']:
            result = location_matching_cog.location_match(name.strip(), gyms, is_partial=False)
            results = [(match.name, score) for match, score in result]
            results = sorted(results, key=itemgetter(1), reverse=True)
            if len(results) > 0:
                gym = next((l for l in gyms if l.name == results[0][0]), None)
                break
        if not image_info['phone_time']:
            image_info['phone_time'] = 'Unknown'
        if gym:
            if image_info['boss'] and not image_info['egg_time']:
                if not image_info['expire_time']:
                    image_info['expire_time'] = 'Unknown'
                return f"{image_info['boss']} raid at {gym.name}. Expires in {image_info['expire_time']}, current time: {image_info['phone_time']}"
            else:
                tiers = testident.determine_tier(file)
                for tier in tiers:
                    if tier[0].startswith("tier"):
                        if not image_info['egg_time']:
                            image_info['egg_time'] = 'Unknown'
                        return f"Level {tier[0][4]} egg at {gym.name}. Hatches in {image_info['egg_time']}, current time: {image_info['phone_time']}"
                return "none"
            # if False:
            #     tiers = [t[0] for t in tiers]
            #     if image_info['egg_time']:
            #         for tier in tiers:
            #             if tier.startswith("tier"):
            #                 #make channel
            #                 return f"Level {tier[4]} egg at {gym.name}. Hatches in {image_info['egg_time']}, current time: {image_info['phone_time']}"
            #     pokes = []
            #     first, first_none = True, False
            #     if image_info['boss']:
            #         pokemon = Pokemon.get_pokemon(self.bot, image_info['boss'])
            #         pokes.append(pokemon)
            #     else:
            #         for tier in tiers:
            #             if first and tier.startswith("none"):
            #                 first_none = True
            #             first = False
            #             if not tier.startswith("none") and not tier.startswith("tier"):
            #                 pokemon = tier[1:]
            #                 if pokemon.startswith('a-'):
            #                     pokemon = 'alolan ' + pokemon[2:]
            #                 pokemon = Pokemon.get_pokemon(self.bot, pokemon)
            #                 if pokemon.is_raid:
            #                     pokes.append(pokemon)
            #     if len(pokes) < 1:
            #         return f"found: {gym.name} but no egg or pokemon identified"
            #     if image_info['expire_time']:
            #         # make channel
            #         return f"{pokes[0]} raid at {gym.name}. Expires in {image_info['expire_time']}, current time: {image_info['phone_time']}"
            #         pass
            #     if not first_none:
            #         # make channel
            #         return f"{pokes[0]} raid at {gym.name}. Current time: {image_info['phone_time']}"
            #         pass
        else:
            # error of some kind
            return "Unable to determine gym name"
            pass


def setup(bot):
    bot.add_cog(RaidAuto(bot))
