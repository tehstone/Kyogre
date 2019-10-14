import asyncio
import concurrent.futures
import cv2
import functools
import pytesseract
import re
import time
from os import listdir
from os.path import isfile, join
from kyogre import utils

boss_list = ['shinx', 'drifloon', 'patrat', 'klink', 'alolan exeggutor', 'misdreavus', 'sneasel', 'sableye', 'mawile', 'alolan raichu', 'machamp', 'gengar', 'granbull', 'piloswine', 'alolan marowak', 'dragonite', 'togetic', 'houndoom', 'absol', 'giratina', 'mewtwo']
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
    for t in vals:
        thresh = cv2.threshold(gym_name_crop, t, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.GaussianBlur(thresh, (5, 5), 0)
        img_text = pytesseract.image_to_string(thresh, lang='eng', config='--psm 4')
        img_text = [s for s in list(filter(None, img_text.split())) if len(s) > 3]
        if len(img_text) > 1:
            match = utils.get_match(boss_list, img_text[1])
            if match and match[0]:
                return match[0]
        if len(img_text) > 0:
            match = utils.get_match(list(raid_cp_list), img_text[0])
            if match and match[0]:
                return raid_cp_chart[match[0]]
        for i in img_text:
            match = utils.get_match(boss_list, i)
            if match and match[0]:
                return match[0]
            match = utils.get_match(list(raid_cp_list), i)
            if match and match[0]:
                return raid_cp_chart[match[0]]
    return None


async def read_photo_async(file, logger):
    start = time.time()
    image = cv2.imread(file, 0)
    height, width = image.shape
    if height < 400 or width < 200:
        dim = (round(width * 2), round(height * 2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result_egg = await loop.run_in_executor(
            pool, functools.partial(check_egg_time, image=image))
        result_expire = await loop.run_in_executor(
            pool, functools.partial(check_expire_time, image=image))
        result_boss = await loop.run_in_executor(
            pool, functools.partial(check_boss_cp, image=image))
        result_gym = await loop.run_in_executor(
            pool, functools.partial(check_gym_name, image=image))
        result_phone = await loop.run_in_executor(
            pool, functools.partial(check_phone_time, image=image))
    return {'egg_time': result_egg, 'expire_time': result_expire, 'boss': result_boss,
            'phone_time': result_phone, 'names': result_gym, 'runtime': time.time()-start}

def read_photo(file, logger):
    start = time.time()
    split = time.time()
    image = cv2.imread(file, 0)
    height, width = image.shape
    if height < 400 or width < 200:
        print(f"height: {height} - width: {width}")
        dim = (round(width*2), round(height*2))
        image = cv2.resize(image, dim, interpolation=cv2.INTER_AREA)
    time_str = f"{file} scan: {time.time()-split} "
    split = time.time()
    egg_time = check_egg_time(image, file)
    time_str += f"egg: {time.time()-split} "
    split = time.time()
    expire_time = None
    boss = None
    if not egg_time:
        expire_time = check_expire_time(image, file)
        time_str += f"exp: {time.time()-split} "
        split = time.time()
        boss = check_boss_cp(image, file)
        time_str += f"boss: {time.time() - split} "
        split = time.time()
    phone_time = check_phone_time(image, file)
    time_str += f"phone: {time.time()-split} "
    split = time.time()
    gym_name_options = check_gym_name(image)
    time_str += f"gym: {time.time()-split} "
    time_str += f"total: {time.time()-start}"
    logger.info(time_str)
    return {'egg_time': egg_time, 'expire_time': expire_time, 'boss': boss,
            'phone_time': phone_time, 'names': gym_name_options}
