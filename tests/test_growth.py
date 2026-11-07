import unittest
from shake_find import DEFAULTS, ShakeDetector, ShakeGrowth, arrival_scale, frame_delay


class GrowthTests(unittest.TestCase):
    def test_motion_holds_without_growing_until_pointer_rests(self):
        growth = ShakeGrowth(0)
        size = growth.step(.1, True, DEFAULTS)
        for now in (.2, .7, 1.5, 3):
            self.assertEqual(growth.step(now, False, DEFAULTS, moving=True), size)
        self.assertEqual(growth.step(3.5, False, DEFAULTS), size)
        shrinking = growth.step(3.8, False, DEFAULTS)
        self.assertLess(shrinking, size)
        self.assertEqual(growth.step(3.81, False, DEFAULTS, moving=True), shrinking)
        self.assertEqual(growth.step(4, False, DEFAULTS), shrinking)
        self.assertIsNone(growth.step(5, False, DEFAULTS))

    def test_arrival_curve_and_adaptive_cadence(self):
        self.assertEqual(arrival_scale(0, 0), 1)
        self.assertAlmostEqual(arrival_scale(.2, 0), 2.4)
        self.assertTrue(1 < arrival_scale(.5, 0) < 2.4)
        self.assertIsNone(arrival_scale(.7, 0))
        self.assertAlmostEqual(frame_delay(.04, False, False, .003), .037)
        self.assertAlmostEqual(frame_delay(.04, False, True, .003), .017)
        self.assertAlmostEqual(frame_delay(.04, True, False, .003), 1/60 - .003)
        self.assertEqual(frame_delay(.04, True, False, .03), 0)

    def test_pause_freezes_and_resume_continues(self):
        growth = ShakeGrowth(0)
        for i in range(1, 21):
            size = growth.step(i*.02, True, DEFAULTS)
        self.assertGreater(size, 1)
        self.assertLess(size, DEFAULTS['scale'])
        self.assertEqual(growth.step(.5, False, DEFAULTS), size)
        self.assertEqual(growth.step(.6, False, DEFAULTS), size)
        self.assertGreater(growth.step(.62, True, DEFAULTS), size)
        self.assertIsNone(growth.step(2, False, DEFAULTS))

    def test_continuous_shake_reaches_max_and_resume_during_shrink_is_smooth(self):
        growth = ShakeGrowth(0)
        for i in range(1, 71):
            size = growth.step(i*.02, True, DEFAULTS)
        self.assertEqual(size, 5)
        self.assertIsNotNone(growth.peak_at)
        shrinking = growth.step(2.2, False, DEFAULTS)
        resumed = growth.step(2.22, True, DEFAULTS)
        self.assertGreater(resumed, shrinking)
        self.assertLess(resumed, 5)

    def test_stationary_sample_stops_growth_signal(self):
        detector = ShakeDetector()
        for i, x in enumerate([0, 60, 0, 60, 0]):
            detector.update(x, 0, i*.04, DEFAULTS)
        self.assertTrue(detector.is_shaking(.16))
        detector.update(0, 0, .18, DEFAULTS)
        self.assertFalse(detector.is_shaking(.18))
