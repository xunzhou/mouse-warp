"""Run with xvfb-run -a python3 tests/x11_smoke.py."""
import sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Xlib import X, Xatom, display
from Xlib.ext import shape
from shake_find import CursorMagnifier, DEFAULTS as CURRENT_DEFAULTS
DEFAULTS = dict(CURRENT_DEFAULTS, appearance='vector')

observer = display.Display()
errors = []
observer.set_error_handler(lambda error, request: errors.append(error))
# Fix the baseline explicitly; later assertions exercise live theme/size changes.
resource_atom = observer.intern_atom('RESOURCE_MANAGER')
observer.screen().root.change_property(resource_atom, Xatom.STRING, 8,
    b'Xcursor.size: 32\nXcursor.theme: capitaine-cursors\n')
observer.sync()
m = CursorMagnifier()
m.display.set_error_handler(lambda error, request: errors.append(error))
under = observer.screen().root.create_window(0, 0, 640, 480, 0,
    observer.screen().root_depth, X.InputOutput, X.CopyFromParent,
    background_pixel=0x336699)
under.map()
under.warp_pointer(220, 220)
observer.sync()
m.trigger(0)
for i in range(1, 25):
    m.update(220, 220, i / 30, DEFAULTS)
assert m.hidden
assert not m.window.shape_get_rectangles(shape.SK.Input).rectangles
assert observer.screen().root.query_pointer().child.id == under.id, 'overlay intercepts input'
assert m.window.get_geometry().width > m.source.width
assert m.window.get_image(0, 0, m.window.get_geometry().width,
    m.window.get_geometry().height, X.ZPixmap, 0xffffffff).data
m.update(220, 220, 1, DEFAULTS)
assert not m.hidden and not m.frames
m.trigger(2)
m.update(220, 220, 2.2, DEFAULTS)
assert m.hidden
# A known cursor verifies the actual rendered outline and inverted fill.
from types import SimpleNamespace
m.hide()
m.trigger(2)
m.source = SimpleNamespace(width=3, height=3, xhot=1, yhot=1,
                           cursor_image=[0, 0, 0, 0, 0xffff0000, 0, 0, 0, 0])

def pixel(x, y):
    data = m.window.get_image(x, y, 1, 1, X.ZPixmap, 0xffffffff).data
    return int.from_bytes(data, sys.byteorder) & 0xffffff

for now, border in [(2.13, 0), (2.28, 0xffffff), (2.42, 0), (2.56, 0xffffff)]:
    m.update(220, 220, now, dict(DEFAULTS, appearance='captured'))
    geometry = m.window.get_geometry()
    assert geometry.width == 21, geometry.width  # 3 pixels * 5 + 6 outline padding
    assert geometry.x + 8 == 220 and geometry.y + 8 == 220, 'hotspot moved'
    assert pixel(6, 10) == border, 'outline did not alternate black/white'
    assert pixel(10, 10) == (0xff0000 ^ border), 'captured fill did not invert'
    assert not m.window.shape_get_rectangles(shape.SK.Input).rectangles
    assert observer.screen().root.query_pointer().child.id == under.id
m.update(220, 220, 2.6, dict(DEFAULTS, blink=False, appearance='captured'))
assert m.window.get_geometry().width == 15, 'disabled blink retained outline'
assert pixel(7, 7) == 0xff0000
# Switching to vector mode redraws geometry at full resolution. It must not
# depend on the synthetic 3x3 captured image or its hotspot above.
for now, border in [(2.13, 0), (2.28, 0xffffff)]:
    m.update(220, 220, now, DEFAULTS)
    geometry = m.window.get_geometry()
    assert (geometry.width, geometry.height) == (138, 178)
    assert (geometry.x + 19, geometry.y + 14) == (220, 220)
    assert pixel(19, 70) == (border ^ 0xffffff), 'vector outline did not contrast'
    assert pixel(16, 70) == border, 'outer edge did not invert'
    assert pixel(30, 70) == border, 'vector fill did not invert'
    assert not m.window.shape_get_rectangles(shape.SK.Input).rectangles
    assert observer.screen().root.query_pointer().child.id == under.id
m.update(220, 220, 2.3, dict(DEFAULTS, blink=False))
assert pixel(19, 70) == 0xffffff
# Real XFixes names/events must switch shapes while the native cursor is hidden.
from Xlib import Xcursorfont
from Xlib.protocol import rq
from cursor_shapes import capture_cursor

class SetName(rq.Request):
    _request = rq.Struct(rq.Card8('opcode'), rq.Opcode(23), rq.RequestLength(),
                         rq.Card32('cursor'), rq.LengthOf('name', 2), rq.Pad(2),
                         rq.String8('name'))

observer.xfixes_query_version()
font = observer.open_font('cursor')
cursors = []
for name, glyph, expected in [('text', Xcursorfont.xterm, 'text'),
                              ('vertical-text', Xcursorfont.xterm, 'vertical-text'),
                              ('ew-resize', Xcursorfont.sb_h_double_arrow, 'ew-resize'),
                              ('ns-resize', Xcursorfont.sb_v_double_arrow, 'ns-resize'),
                              ('nwse-resize', Xcursorfont.bottom_right_corner, 'nwse-resize'),
                              ('nesw-resize', Xcursorfont.bottom_left_corner, 'nesw-resize'),
                              ('custom-unknown', Xcursorfont.left_ptr, 'arrow')]:
    cursor = font.create_glyph_cursor(font, glyph, glyph + 1, (0, 0, 0), (65535,)*3)
    cursors.append(cursor)
    SetName(display=observer.display, opcode=observer.display.get_extension_major('XFIXES'),
            cursor=cursor.id, name=name)
    under.change_attributes(cursor=cursor)
    observer.sync()
    m.display.sync()
    assert capture_cursor(m.display).name == name, 'cursor name protocol mismatch'
    with patch('shake_find.capture_cursor', side_effect=AssertionError('active vector must not read image')):
        m.update(220, 220, 2.3, DEFAULTS)
    assert m.cursor_kind == expected, (m.cursor_kind, expected)
    geom = m.window.get_geometry()
    if expected != 'arrow':
        assert (geom.width, geom.height) == (168, 168)
        assert (geom.x + 84, geom.y + 84) == (220, 220), 'center hotspot moved'
        assert pixel(84, 84) == 0xffffff, 'shape center should be filled during white pulse'
    assert observer.screen().root.query_pointer().child.id == under.id
    assert not m.window.shape_get_rectangles(shape.SK.Input).rectangles
m.hide()
for cursor in cursors:
    cursor.free()
font.close()
assert not m.frames and not m.hidden, 'vector resources were not released'
# Catppuccin publishes size and palette via RESOURCE_MANAGER. Apply changes
# during one effect and assert the fill follows the theme at an unchanged scale.
m.trigger(2)
m.cursor_kind = 'arrow'
for theme, color in [('capitaine-cursors-light', 0xffffff), ('capitaine-cursors', 0)]:
    observer.screen().root.change_property(resource_atom, Xatom.STRING, 8,
        f'Xcursor.size: 24\nXcursor.theme: {theme}\n'.encode())
    observer.sync()
    m.display.sync()
    m.update(220, 220, 2.2, dict(DEFAULTS, blink=False))
    assert m.cursor_size == 24 and m.base_fill == color
    assert m.window.get_geometry().width == 106  # 26 * 3.75 + padding
    assert pixel(25, 50) == color, 'vector fill did not follow theme'
    m.update(220, 220, 2.3, DEFAULTS)
    assert pixel(25, 50) == color ^ 0xffffff, 'blink did not invert theme fill'
m.hide()
# A denied activation read must not kill the preview or leave a hidden cursor.
with patch('shake_find.capture_cursor', return_value=None):
    m.trigger(3)
    m.update(220, 220, 3.2, DEFAULTS)
    assert m.hidden, 'vector mode should work without a readable image'
    m.update(220, 220, 4, DEFAULTS)
    assert not m.hidden
    m.trigger(5)
    m.update(220, 220, 5.2, dict(DEFAULTS, appearance='captured'))
    assert not m.hidden and m.started is None, 'captured mode must skip unreadable image'
m.close()
observer.sync()
assert not errors, errors
under.destroy()
observer.close()
print('PASS: vector and captured rendering, 5x scaling, full color flips, live named caret/resize changes, hotspot alignment, blink disable, empty input shape, pointer pass-through, timeout, cleanup, no protocol errors')
