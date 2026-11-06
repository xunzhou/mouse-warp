"""Denied image access is recoverable; unexpected protocol errors are not hidden."""
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from Xlib import error
from cursor_shapes import capture_cursor, cursor_style


class CursorAccessTests(unittest.TestCase):
    def test_expected_access_failures_return_no_snapshot(self):
        display = SimpleNamespace(display=Mock())
        for cls, code in [(error.BadAccess, 10), (error.BadCursor, 6)]:
            with self.subTest(error=cls.__name__):
                packet = struct.pack('=BBHIHB21x', 0, code, 1, 1118, 25, 138)
                failure = cls(display.display, packet)
                with patch('Xlib.protocol.rq.ReplyRequest.__init__', side_effect=failure):
                    self.assertIsNone(capture_cursor(display))

    def test_theme_resources(self):
        self.assertEqual(cursor_style(b'Xcursor.theme: capitaine-cursors-light\nXcursor.size: 24'), (24, 0xffffff))
        self.assertEqual(cursor_style('Xcursor.theme: capitaine-cursors\nXcursor.size: 36'), (36, 0))
        for size in ('broken', '-1', '10000'):
            self.assertEqual(cursor_style(f'Xcursor.size: {size}'), (24, 0))
        self.assertEqual(cursor_style(''), (24, 0))

    def test_unexpected_errors_are_not_swallowed(self):
        display = SimpleNamespace(display=Mock())
        with patch('Xlib.protocol.rq.ReplyRequest.__init__', side_effect=RuntimeError('broken')):
            with self.assertRaisesRegex(RuntimeError, 'broken'):
                capture_cursor(display)
