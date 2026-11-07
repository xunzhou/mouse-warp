import unittest
from cursor_shapes import cursor_kind, geometry
from shake_find import DEFAULTS, ShakeDetector, animation_scale, blink_color


class DetectorTests(unittest.TestCase):
    def trace(self, points, interval=0.04):
        detector = ShakeDetector()
        return [detector.update(x, y, i * interval, DEFAULTS)
                for i, (x, y) in enumerate(points)]

    def test_horizontal_vertical_and_diagonal_shakes(self):
        for points in ([(x, 0) for x in [0, 60, 0, 60, 0, 60]],
                       [(0, y) for y in [0, 60, 0, 60, 0, 60]],
                       [(x, x) for x in [0, 60, 0, 60, 0, 60]]):
            self.assertTrue(self.trace(points)[-1])

    def test_straight_travel_jitter_slow_motion_and_teleports(self):
        for points, interval in (([(x, 0) for x in range(0, 1000, 40)], .04),
                                 ([(x, 0) for x in [0, 4, 0, 4, 0, 4]], .04),
                                 ([(x, 0) for x in [0, 60, 0, 60, 0, 60]], .3),
                                 ([(x, 0) for x in [0, 1000, 0, 1000, 0]], .04)):
            self.assertFalse(any(self.trace(points, interval)))

    def test_fast_sweeps_and_small_corrections_do_not_activate(self):
        traces = [
            [0, 400, 800, 1200, 1600],  # Fast straight travel.
            [0, 300, 0, 300, 0],  # Three reversals are no longer enough.
            [0, 400, 380, 400, 380, 400, 380],  # Small corrections.
            [0, 400, 364, 400, 364, 400],  # Sweep cannot supply all distance.
        ]
        for xs in traces:
            with self.subTest(xs=xs):
                self.assertFalse(any(self.trace([(x, 0) for x in xs])))

    def test_deliberate_shake_with_multiple_samples_per_stroke(self):
        xs = [0, 20, 40, 60, 80, 60, 40, 20, 0,
              20, 40, 60, 80, 60, 40, 20, 0, 20, 40, 60, 80]
        self.assertTrue(any(self.trace([(x, 0) for x in xs], .02)))

    def test_reset_discards_partial_gesture(self):
        detector = ShakeDetector()
        for i, x in enumerate([0, 60, 0, 60]):
            detector.update(x, 0, i * .04, DEFAULTS)
        detector.reset()
        self.assertFalse(detector.update(0, 0, .16, DEFAULTS))

    def test_cursor_name_aliases_and_fallback(self):
        for name, expected in [('xterm', 'text'), ('col-resize', 'ew-resize'),
                               ('sb_v_double_arrow', 'ns-resize'),
                               ('bottom_left_corner', 'nesw-resize'),
                               ('top_left_corner', 'nwse-resize'),
                               ('custom-bitmap', 'arrow'), ('', 'arrow')]:
            self.assertEqual(cursor_kind(name), expected)
        for kind in ('arrow', 'text', 'vertical-text', 'ew-resize', 'ns-resize',
                     'nwse-resize', 'nesw-resize'):
            (w, h), (hx, hy), points = geometry(kind)
            self.assertTrue(0 <= hx < w and 0 <= hy < h)
            self.assertTrue(all(0 <= x < w and 0 <= y < h for x, y in points))

    def test_animation_and_renewal(self):
        self.assertEqual(animation_scale(0, 0, 0, DEFAULTS), 1)
        self.assertEqual(animation_scale(.2, 0, 0, DEFAULTS), 5)
        self.assertGreater(animation_scale(.8, 0, 0, DEFAULTS), 1)
        self.assertEqual(animation_scale(1, 0, 0, DEFAULTS), 1)
        self.assertEqual(animation_scale(1, 0, .8, DEFAULTS), 5)

    def test_blink_two_pulses_then_stops_even_when_hold_is_extended(self):
        for now, expected in [(0, None), (.13, 0), (.28, 0xffffff),
                              (.42, 0), (.56, 0xffffff), (.69, None)]:
            self.assertEqual(blink_color(now, 0, 0, DEFAULTS), expected)
        self.assertIsNone(blink_color(1, 0, .8, DEFAULTS))
        self.assertIsNone(blink_color(.13, 0, 0, dict(DEFAULTS, blink=False)))
        self.assertIsNone(blink_color(.13, 0, 0, dict(DEFAULTS, hold=.1)))


if __name__ == '__main__':
    unittest.main()
