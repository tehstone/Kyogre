import os
import shutil

from PIL import Image


async def image_pre_check(attachment):
    file = await _save_image(attachment)
    img = Image.open(file)
    img = await exif_transpose(img)
    filesize = os.stat(file).st_size
    img = await check_resize(img, filesize)
    img.save(file)
    return file


async def check_resize(image, filesize):
    if filesize > 2500000:
        factor = 1.05
        if filesize > 5000000:
            factor = 1.2
        width, height = image.size
        width = int(width / factor)
        height = int(height / factor)
        image = image.resize((width, height))
    return image


async def exif_transpose(img):
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


async def _save_image(attachment):
    __, file_extension = os.path.splitext(attachment.filename)
    filename = f"{attachment.id}{file_extension}"
    filepath = os.path.join('screenshots', filename)
    with open(filepath, 'wb') as out_file:
        await attachment.save(out_file)
    return filepath


def cleanup_file(file, dst):
    try:
        filename = os.path.split(file)[1]
        dest = os.path.join(dst, filename)
        shutil.move(file, dest)
        return dest
    except:
        return file
