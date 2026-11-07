import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import theme_cursor


class SubpixelTests(unittest.TestCase):
    def test_fractional_growth_keeps_hotspot_center_still(self):
        image = Image.new('RGBa', (21, 21))
        ImageDraw.Draw(image).ellipse((7, 7, 13, 13), fill=(255, 255, 255, 255))
        source = [(image, 21, 10, 10, 1)]
        with patch.object(theme_cursor, 'load_artwork', return_value=source):
            for step in range(64):
                rendered, xhot, yhot, _ = theme_cursor.render_artwork(
                    'hotspot-test', 'center', 25 + step/8, 0)
                alpha = rendered.getchannel('A')
                total = sx = sy = 0
                for y in range(alpha.height):
                    for x in range(alpha.width):
                        weight = alpha.getpixel((x, y))
                        total += weight
                        sx += x * weight
                        sy += y * weight
                self.assertAlmostEqual(sx/total, xhot, delta=.06)
                self.assertAlmostEqual(sy/total, yhot, delta=.06)
        theme_cursor._scaled_artwork.cache_clear()

    def test_fractional_sizes_do_not_repeat_integer_resize_frames(self):
        image = Image.new('RGBa', (21, 21))
        ImageDraw.Draw(image).ellipse((5, 5, 15, 15), fill=(255, 255, 255, 255))
        with patch.object(theme_cursor, 'load_artwork', return_value=[(image, 21, 10, 10, 1)]):
            a = theme_cursor.render_artwork('fraction-test', 'center', 30.125, 0)[0]
            b = theme_cursor.render_artwork('fraction-test', 'center', 30.375, 0)[0]
            self.assertEqual(a.size, b.size)
            self.assertNotEqual(a.tobytes(), b.tobytes())
        theme_cursor._scaled_artwork.cache_clear()
