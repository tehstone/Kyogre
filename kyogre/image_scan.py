import asyncio
import concurrent.futures
import cv2
import functools
import pytesseract
import re
import time
from kyogre import utils

boss_list = ['Bulbasaur','Charmander','Squirtle','Misdreavus','Drifloon','Klink','Sneasel','Sableye','Mawile','Yamask','Alolan Raichu','Gengar','Granbull','Sharpedo','Skuntank','Alolan Marowak','Umbreon','Houndoom','Tyranitar','Absol','Darkrai','Raichu','Marowak']
# Need to import base attack and stamina and  calculate these
# Raid CP Formula: ((attack+15)*math.sqrt(defense+15)*math.sqrt(stamina))/10
"""
Raid Level    Stamina
Level 1    600
Level 2    1800
Level 3    3600
Level 4    9000
Level 5    15000
Level 6    22500 * NEED TO CONFIRM - this was back calculated from formula above with Darkrai's CP
"""
raid_cp_chart = {"2873": "Shinx",
                 "3113": "Squirtle",
                 "3151": "Drifloon",
                 "3334": "Charmander",
                 "3656": "Bulbasaur",
                 "2596": "Patrat",
                 "3227": "Klink",
                 "13472": "Alolan Exeggutor",
                 "10038": "Misdreavus",
                 "10981": "Sneasel",
                 "8132": "Sableye",
                 "9008": "Mawile",
                 "5825": "Yamask",
                 "15324": "Sharpedo",
                 "16848": "Alolan Raichu",
                 "19707": "Machamp",
                 "21207": "Gengar",
                 "16457": "Granbull",
                 "14546": "Piloswine",
                 "14476": "Skuntank",
                 "21385": "Alolan Marowak",
                 "21360": "Umbreon",
                 "38490": "Dragonite",
                 "65675": "Tyranitar",
                 "20453": "Togetic",
                 "28590": "Houndoom",
                 "28769": "Absol",
                 "38326": "Altered Giratina",
                 "65675": "Darkrai"
                 }
raid_cp_list = raid_cp_chart.keys()


async def check_match(image, regex):
    img_text = pytesseract.image_to_string(image, lang='eng', config='--psm 11 -c tessedit_char_whitelist=:0123456789')
    match = re.search(regex, img_text)
    if match:
        return match[0]
    else:
        return None


async def check_val_range(egg_time_crop, vals, regex=None, blur=False):
    for i in vals:
        thresh = cv2.threshold(egg_time_crop, i, 255, cv2.THRESH_BINARY)[1]
        if blur:
            thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        match = await check_match(thresh, regex)
        if match:
            return match
    for i in vals:
        thresh = cv2.threshold(egg_time_crop, i, 255, cv2.THRESH_BINARY)[1]
        image = cv2.GaussianBlur(thresh, (5, 5), 0)
        match = await check_match(image, regex)
        if match:
            return match
        image = cv2.medianBlur(thresh, 3)
        match = await check_match(image, regex)
        if match:
            return match
        image = cv2.bilateralFilter(thresh, 9, 75, 75)
        match = await check_match(image, regex)
        if match:
            return match
    return None


async def check_phone_time(image):
    height, width = image.shape
    maxy = round(height * .15)
    miny = 0
    maxx = width
    minx = 0
    phone_time_crop = image[miny:maxy, minx:maxx]
    regex = r'1{0,1}[0-9]{1}:[0-9]{2}'
    vals = [0, 10]
    result = await check_val_range(phone_time_crop, vals, regex, blur=True)
    if not result:
        phone_time_crop = cv2.bitwise_not(phone_time_crop)
        result = await check_val_range(phone_time_crop, vals, regex, blur=True)
    return result


async def check_egg_time(image):
    image = cv2.bitwise_not(image)
    height, width = image.shape
    maxy = round(height * .33)
    miny = round(height * .16)
    maxx = round(width * .75)
    minx = round(width * .25)
    egg_time_crop = image[miny:maxy, minx:maxx]
    regex = r'[0-1]{1}:[0-9]{2}:[0-9]{2}'
    result = await check_val_range(egg_time_crop, [0, 70, 10, 80], regex)
    return result


async def check_egg_tier(image):
    height, width = image.shape
    maxy = round(height * .37)
    miny = round(height * .27)
    maxx = round(width * .78)
    minx = round(width * .22)
    gym_name_crop = image[miny:maxy, minx:maxx]
    vals = [251, 252]
    for th in vals:
        thresh = cv2.threshold(gym_name_crop, th, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh,
                                               lang='eng', config='--psm 7 --oem 0 -c tessedit_char_whitelist=@Q®© '
                                                                  '--tessdata-dir "/usr/local/share/tessdata/"')
        tier = img_text.replace(' ', '')
        if len(tier) > 0:
            return str(len(tier))
    return None


async def check_expire_time(image):
    image = cv2.bitwise_not(image)
    height, width = image.shape
    maxy = round(height * .64)
    miny = round(height * .52)
    maxx = round(width * .96)
    minx = round(width * .7)
    expire_time_crop = image[miny:maxy, minx:maxx]
    regex = r'[0-2]{1}:[0-9]{2}:[0-9]{2}'
    result = await check_val_range(expire_time_crop, [0, 70, 10], regex)
    return result


async def check_profile_name(image):
    height, width, __ = image.shape
    regex = r'\S{5,20}\n+&'
    vals = [180, 190]
    maxx = round(width * .56)
    minx = round(width * .05)
    yvals = [(.13, .24), (.2, .4)]
    for pair in yvals:
        maxy = round(height * pair[1])
        miny = round(height * pair[0])
        profile_name_crop = image[miny:maxy, minx:maxx]
        for i in vals:
            thresh = cv2.threshold(profile_name_crop, i, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
            img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
            match = re.search(regex, img_text)
            if match:
                return match[0].split('&')[0].strip()


def determine_team(image):
    b, g, r = image[300, 5]
    if r >= 200 and g >= 200:
        return "instinct"
    if b >= 200:
        return "mystic"
    if r >= 200:
        return "valor"
    return None


async def check_profile_level(image):
    height, width, __ = image.shape
    vals = [220, 230, 240]
    regex = r'[1-4]{0,1}[0-9]{1}'
    maxx = round(width * .2)
    minx = round(width * .05)
    yvals = [(.5, .7), (.6, .8)]
    for pair in yvals:
        maxy = round(height * pair[1])
        miny = round(height * pair[0])
        level_crop = image[miny:maxy, minx:maxx]
        for i in vals:
            thresh = cv2.threshold(level_crop, i, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
            img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
            match = re.search(regex, img_text)
            if match:
                return match[0]


async def get_xp(image):
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = image.shape
    maxy = round(height * .78)
    miny = round(height * .55)
    maxx = round(width * .96)
    minx = round(width * .55)
    xp_crop = image[miny:maxy, minx:maxx]
    vals = [210, 220]
    regex = r'[0-9,\.]{3,9}/*\s*[0-9,\.]{3,12}'
    for t in vals:
        thresh = cv2.threshold(xp_crop, t, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
        match = re.search(regex, img_text)
        if match:
            xp_str = match[0]
            if '/' in xp_str:
                return xp_str.split('/')[0].strip().replace(',', '').replace('.', '')
            else:
                return xp_str.split(' ')[0].strip().replace(',', '').replace('.', '')


async def scan_profile(file):
    image = cv2.imread(file)
    height, width, __ = image.shape
    if height < 400 or width < 200:
        print(f"height: {height} - width: {width}")
        dim = (round(width*2), round(height*2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    team = determine_team(image)
    if team == 'grey':
        return None, None, None, None
    level = await check_profile_level(image)
    trainer_name = await check_profile_name(image)
    xp = None
    if level:
        try:
            lev_int = int(level)
            if lev_int < 40:
                xp = await get_xp(image)
        except ValueError:
            pass
    return team, level, trainer_name, xp


async def check_gym_name(image):
    height, width = image.shape
    maxy = round(height * .19)
    miny = round(height * .04)
    maxx = round(width * .92)
    minx = round(width * .15)
    gym_name_crop = image[miny:maxy, minx:maxx]
    vals = [200, 210]
    possible_names = []
    for i in vals:
        thresh = cv2.threshold(gym_name_crop, i, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
        img_text = [s for s in list(filter(None, img_text.split('\n'))) if len(s) > 3]
        possible_text = []
        for line in img_text:
            if 'EXRAID' in line or 'EX RAID' in line:
                continue
            if len(line) < 5:
                continue
            if _word_length(line) < 4:
                continue
            line = _remove_trailings(line)
            possible_text.append(line)
        possible_names.append(' '.join(possible_text))
    return possible_names


def sub(m):
    s = {'o', 'os', 'oS', 'So', 'S', 'C', 'CS', 'O', ' )', 'Q'}
    return '' if m.group() in s else m.group()


def _remove_trailings(line):
    return re.sub(r'\w+', sub, line)


def _word_length(line):
    longest = 0
    for word in line.split():
        longest = max(longest, len(word))
    return longest


async def check_boss_cp(image, bot):
    height, width = image.shape
    maxy = round(height * .32)
    miny = round(height * .15)
    maxx = round(width * .84)
    minx = round(width * .16)
    gym_name_crop = image[miny:maxy, minx:maxx]
    gym_name_crop = cv2.bitwise_not(gym_name_crop)
    vals = [30, 40, 20]
    # This doesn't fully handle Alolan forms
    # For example, in one particular screenshot of an Alolan Marowak no boss was ever identified.
    # The img_text contained 'Marowak' but fuzzy match threshold was too high for that to match
    # Cut off can't be lower or else other issues arise (houndoom instead of absol for example)
    # Additionally, no match was ever made on the CP value as it never got a clear read.
    # Likely need to refactor this so that if an alolan species is read in, additional scans are made
    # To try and pick up the CP and make sure we have the right form
    for t in vals:
        thresh = cv2.threshold(gym_name_crop, t, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
        img_text = [s for s in list(filter(None, img_text.split())) if len(s) > 3]
        if len(img_text) > 1:
            match = utils.get_match(bot.boss_list, img_text[1], score_cutoff=70)
            if match and match[0]:
                return match[0]
        if len(img_text) > 0:
            match = utils.get_match(list(raid_cp_list), img_text[0], score_cutoff=70)
            if match and match[0]:
                return raid_cp_chart[match[0]]
        for i in img_text:
            match = utils.get_match(bot.boss_list, i, score_cutoff=70)
            if match and match[0]:
                return match[0]
            match = utils.get_match(list(raid_cp_list), i, score_cutoff=70)
            if match and match[0]:
                return raid_cp_chart[match[0]]
    return None


async def check_gym_ex(file):
    image = cv2.imread(file, 0)
    height, width = image.shape
    if height < 400 or width < 200:
        print(f"height: {height} - width: {width}")
        dim = (round(width*2), round(height*2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    height, width = image.shape
    maxy = round(height * .38)
    miny = round(height * .19)
    maxx = round(width * .87)
    minx = round(width * .13)
    gym_name_crop = image[miny:maxy, minx:maxx]
    vals = [200, 210]
    result = {'date': None, 'gym': None, 'location': None}
    regex = r'(?P<date>[A-Za-z]{3,10} [0-9]{1,2} [0-9]{1,2}:[0-9]{1,2}\s*[APM]{2}\s*[-—]*\s*[0-9]{1,2}:[0-9]{1,' \
            r'2}\s*[APM]{2})\s+(?P<gym>[\S+ ]+)\s*(?P<location>[A-Za-z ]+[,\.]+ [A-Za-z]+[,\.]+ [A-Za-z ]+) '
    for i in vals:
        thresh = cv2.threshold(gym_name_crop, i, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
        regex_result = re.search(regex, img_text)
        if regex_result:
            results = regex_result.groupdict()
            result['date'] = results['date']
            result['gym'] = results['gym']
            result['location'] = results['location']
            break
    return result


async def read_photo_async(file, bot, logger):
    start = time.time()
    image = cv2.imread(file, 0)
    height, width = image.shape
    if height < 400 or width < 200:
        dim = (round(width * 2), round(height * 2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    result_gym = await check_gym_name(image)
    result_egg, result_expire, result_boss, result_tier, result_phone = None, None, None, None, None
    # If we don't have a gym, no point in checking anything else
    if result_gym:
        result_egg = await check_egg_time(image)
        # Only check for expire time and boss if no egg time found
        # May make sense to reverse this. Tough call.
        if not result_egg:
            result_boss = await check_boss_cp(image, bot)
            # If we don't find a boss, don't look for expire time
            if result_boss:
                result_expire = await check_expire_time(image)
        else:
            try:
                result_tier = await check_egg_tier(image)
            except Exception as e:
                logger.info(f"Could not read egg tier from text. Error: {e}")
        # If we don't find an egg time or a boss, we don't need the phone's time
        # Even if it's picked up as an egg later, the time won't be correct without egg time
        if result_egg or result_boss:
            result_phone = await check_phone_time(image)
    return {'egg_time': result_egg, 'expire_time': result_expire, 'boss': result_boss, 's_tier': result_tier,
            'phone_time': result_phone, 'names': result_gym, 'runtime': time.time() - start}
