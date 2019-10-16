import asyncio
import concurrent.futures
import cv2
import functools
import pytesseract
import re
import time
from kyogre import utils

boss_list = ['shinx', 'drifloon', 'patrat', 'klink', 'alolan exeggutor', 'misdreavus', 'sneasel', 'sableye', 'mawile', 'alolan raichu', 'machamp', 'gengar', 'granbull', 'piloswine', 'alolan marowak', 'dragonite', 'togetic', 'houndoom', 'absol', 'giratina', 'mewtwo', 'marowak', 'raichu', 'exeggutor']
raid_cp_chart = {"2873": "Shinx",
                 "3151": "Drifloon",
                 "2596": "Patrat",
                 "3227": "Klink",
                 "13472": "Alolan Exeggutor",
                 "10038": "Misdreavus",
                 "10981": "Sneasel",
                 "8132": "Sableye",
                 "9008": "Mawile",
                 "16848": "Alolan Raichu",
                 "19707": "Machamp",
                 "21207": "Gengar",
                 "16457": "Granbull",
                 "14546": "Piloswine",
                 "21385": "Alolan Marowak",
                 "38490": "Dragonite",
                 "20453": "Togetic",
                 "28590": "Houndoom",
                 "28769": "Absol",
                 "38326": "Altered Giratina"
                 }
raid_cp_list = raid_cp_chart.keys()

def check_match(image, regex):
    img_text = pytesseract.image_to_string(image, lang='eng', config='--psm 11 -c tessedit_char_whitelist=:0123456789')
    match = re.search(regex, img_text)
    if match:
        return match[0]
    else:
        return None


def check_val_range(egg_time_crop, vals, regex=None, blur=False):
    for i in vals:
        thresh = cv2.threshold(egg_time_crop, i, 255, cv2.THRESH_BINARY)[1]
        if blur:
            thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        match = check_match(thresh, regex)
        if match:
            return match
    for i in vals:
        thresh = cv2.threshold(egg_time_crop, i, 255, cv2.THRESH_BINARY)[1]
        image = cv2.GaussianBlur(thresh, (5, 5), 0)
        match = check_match(image, regex)
        if match:
            return match
        image = cv2.medianBlur(thresh, 3)
        match = check_match(image, regex)
        if match:
            return match
        image = cv2.bilateralFilter(thresh, 9, 75, 75)
        match = check_match(image, regex)
        if match:
            return match
    return None


def check_phone_time(image):
    height, width = image.shape
    maxy = round(height * .15)
    miny = 0
    maxx = width
    minx = 0
    phone_time_crop = image[miny:maxy, minx:maxx]
    regex = r'1{0,1}[0-9]{1}:[0-9]{2}'
    vals = [0, 10]
    result = check_val_range(phone_time_crop, vals, regex, blur=True)
    if not result:
        phone_time_crop = cv2.bitwise_not(phone_time_crop)
        result = check_val_range(phone_time_crop, vals, regex, blur=True)
    return result


def check_egg_time(image):
    image = cv2.bitwise_not(image)
    height, width = image.shape
    maxy = round(height * .33)
    miny = round(height * .16)
    maxx = round(width * .75)
    minx = round(width * .25)
    egg_time_crop = image[miny:maxy, minx:maxx]
    regex = r'[0-9]{1}:[0-9]{2}:[0-9]{2}'
    result = check_val_range(egg_time_crop, [0, 70, 10, 80], regex)
    return result


def check_expire_time(image):
    image = cv2.bitwise_not(image)
    height, width = image.shape
    maxy = round(height * .64)
    miny = round(height * .52)
    maxx = round(width * .96)
    minx = round(width * .7)
    expire_time_crop = image[miny:maxy, minx:maxx]
    regex = r'[0-9]{1}:[0-9]{2}:[0-9]{2}'
    result = check_val_range(expire_time_crop, [0, 70, 10], regex)
    return result


def check_gym_name(image):
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
        img_text = pytesseract.image_to_string(thresh, lang='eng',
                                               config='--psm 4 tessedit_char_whitelist=:0123456789abcdefghijklmnopqrstuvwxyz')
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


def check_boss_cp(image):
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
            match = utils.get_match(boss_list, img_text[1], score_cutoff=70)
            if match and match[0]:
                return match[0]
        if len(img_text) > 0:
            match = utils.get_match(list(raid_cp_list), img_text[0], score_cutoff=70)
            if match and match[0]:
                return raid_cp_chart[match[0]]
        for i in img_text:
            match = utils.get_match(boss_list, i, score_cutoff=70)
            if match and match[0]:
                return match[0]
            match = utils.get_match(list(raid_cp_list), i, score_cutoff=70)
            if match and match[0]:
                return raid_cp_chart[match[0]]
    return None


async def read_photo_async(file, logger):
    start = time.time()
    split = time.time()
    image = cv2.imread(file, 0)
    height, width = image.shape
    if height < 400 or width < 200:
        dim = (round(width * 2), round(height * 2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    time_str = f"{file} scan: {time.time() - split} "
    loop = asyncio.get_event_loop()
    result_egg, result_expire, result_boss, result_phone, result_gym = None, None, None, None, None
    with concurrent.futures.ProcessPoolExecutor(max_workers=5) as pool:
        result_egg, result_expire, result_boss, result_phone = None, None, None, None
        result_gym = await loop.run_in_executor(
            pool, functools.partial(check_gym_name, image=image))
        time_str += f"gym: {time.time() - split} "
        split = time.time()
        # If we don't have a gym, no point in checking anything else
        if result_gym:
            result_egg = await loop.run_in_executor(
                pool, functools.partial(check_egg_time, image=image))
            time_str += f"egg: {time.time() - split} "
            split = time.time()
            # Only check for expire time and boss if no egg time found
            # May make sense to reverse this. Tough call.
            if not result_egg:
                result_boss = await loop.run_in_executor(
                    pool, functools.partial(check_boss_cp, image=image))
                time_str += f"boss: {time.time() - split} "
                split = time.time()
                # If we don't find a boss, don't look for expire time
                if result_boss:
                    result_expire = await loop.run_in_executor(
                        pool, functools.partial(check_expire_time, image=image))
                    time_str += f"expire: {time.time() - split} "
                    split = time.time()
            # If we don't find an egg time or a boss, we don't need the phone's time
            # Even if it's picked up as an egg later, the time won't be correct without egg time
            if result_egg or result_boss:
                result_phone = await loop.run_in_executor(
                    pool, functools.partial(check_phone_time, image=image))
                time_str += f"phone: {time.time() - split} "
    logger.info(time_str)

    return {'egg_time': result_egg, 'expire_time': result_expire, 'boss': result_boss,
            'phone_time': result_phone, 'names': result_gym, 'runtime': time.time() - start}


