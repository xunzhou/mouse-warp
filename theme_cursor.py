"""Load original Xcursor artwork, retaining names, hotspots and animation."""
import ctypes as c
import math
from functools import lru_cache
from PIL import Image


class CursorImage(c.Structure):
    _fields_ = [(name, c.c_uint) for name in
                ('version', 'size', 'width', 'height', 'xhot', 'yhot', 'delay')]
    _fields_.append(('pixels', c.POINTER(c.c_uint32)))


class CursorImages(c.Structure):
    _fields_ = [('nimage', c.c_int), ('images', c.POINTER(c.POINTER(CursorImage))),
                ('name', c.c_char_p)]


@lru_cache(maxsize=24)
def load_artwork(theme, name):
    """Use the largest Capitaine artwork, not a screenshot of the small cursor.

    libXcursor handles theme search paths, aliases and inheritance. Missing
    names fall back to that theme's arrow, never to a custom vector drawing.
    """
    lib = c.CDLL('libXcursor.so.1')
    lib.XcursorLibraryLoadImages.argtypes = [c.c_char_p, c.c_char_p, c.c_int]
    lib.XcursorLibraryLoadImages.restype = c.POINTER(CursorImages)
    lib.XcursorImagesDestroy.argtypes = [c.POINTER(CursorImages)]
    names = list(dict.fromkeys([name or 'left_ptr', 'left_ptr']))
    for candidate in names:
        images = lib.XcursorLibraryLoadImages(candidate.encode(), theme.encode() or None, 144)
        if not images:
            continue
        try:
            frames = []
            for i in range(min(images.contents.nimage, 128)):
                native = images.contents.images[i].contents
                if not (0 < native.width <= 1024 and 0 < native.height <= 1024 and native.size):
                    raise ValueError('Invalid cursor theme image dimensions')
                # Xcursor pixels are native-endian premultiplied ARGB uint32s.
                rgba = bytearray()
                for pixel in native.pixels[:native.width * native.height]:
                    rgba.extend(((pixel >> 16) & 255, (pixel >> 8) & 255,
                                 pixel & 255, pixel >> 24))
                image = Image.frombytes('RGBa', (native.width, native.height), bytes(rgba))
                frames.append((image, native.size, native.xhot, native.yhot,
                               max(1, native.delay)))
            if frames:
                return frames
        finally:
            lib.XcursorImagesDestroy(images)
    raise RuntimeError(f'No cursor artwork found for theme {theme!r}')


def render_artwork(theme, name, nominal_size, elapsed, invert=False):
    frames = load_artwork(theme, name)
    position = int(max(0, elapsed) * 1000) % sum(frame[4] for frame in frames)
    index = 0
    for index, frame in enumerate(frames):
        if position < frame[4]:
            break
        position -= frame[4]
    image, xhot, yhot = _scaled_artwork(theme, name, nominal_size, index, invert)
    return image, xhot, yhot, index


@lru_cache(maxsize=48)
def _scaled_artwork(theme, name, nominal_size, index, invert):
    image, source_size, xhot, yhot, _ = load_artwork(theme, name)[index]
    ratio = nominal_size / source_size
    if ratio == 1:
        # Preserve original pixels while keeping the same padding convention
        # as fractional frames, so canvas dimensions stay monotonic.
        original = image.convert('RGBA')
        image = Image.new('RGBA', (original.width + 4, original.height + 4))
        image.paste(original, (2, 2))
        xhot, yhot = xhot + 2, yhot + 2
    else:
        # Keep the hotspot pixel center fixed as fractional scale changes.
        # A plain resize plus independently rounded hotspot makes the pointer
        # tip wobble by up to half a pixel; align during resampling instead.
        padding = 2
        new_xhot, new_yhot = round(xhot * ratio) + padding, round(yhot * ratio) + padding
        dimensions = tuple(max(1, math.ceil(n * ratio)) + 2 * padding for n in image.size)
        transform = (1 / ratio, 0, xhot + .5 - (new_xhot + .5) / ratio,
                     0, 1 / ratio, yhot + .5 - (new_yhot + .5) / ratio)
        # One premultiplied affine pass avoids double filtering, fringes and
        # integer-size stepping. Padding prevents fractional translations clipping.
        image = image.transform(dimensions, Image.Transform.AFFINE, transform,
                                Image.Resampling.BICUBIC).convert('RGBA')
        xhot, yhot = new_xhot, new_yhot
    if invert:
        red, green, blue, alpha = image.split()
        image = Image.merge('RGBA', tuple(channel.point(lambda v: 255-v)
                                         for channel in (red, green, blue)) + (alpha,))
    return image, xhot, yhot
