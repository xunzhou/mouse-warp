"""Load original Xcursor artwork, retaining names, hotspots and animation."""
import ctypes as c
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
    dimensions = tuple(max(1, round(n * ratio)) for n in image.size)
    # Resample premultiplied colors to avoid dark fringes around transparency.
    image = image.resize(dimensions, Image.Resampling.LANCZOS).convert('RGBA')
    if invert:
        red, green, blue, alpha = image.split()
        image = Image.merge('RGBA', tuple(channel.point(lambda v: 255-v)
                                         for channel in (red, green, blue)) + (alpha,))
    return image, round(xhot * ratio), round(yhot * ratio)
