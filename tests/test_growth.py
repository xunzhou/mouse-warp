import unittest
from shake_find import DEFAULTS, ShakeDetector, ShakeGrowth


class GrowthTests(unittest.TestCase):
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
