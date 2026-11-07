"""Xvfb integration: original theme names/artwork, blink, growth and input."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Xlib import X, Xatom, display
from PIL import Image
from shake_find import CursorMagnifier, DEFAULTS
from theme_cursor import render_artwork, load_artwork

observer = display.Display()
root = observer.screen().root
atom = observer.intern_atom('RESOURCE_MANAGER')
root.change_property(atom, Xatom.STRING, 8,
                     b'Xcursor.theme: capitaine-cursors\nXcursor.size: 48\n')
observer.sync()
m = CursorMagnifier()
errors = []
m.display.set_error_handler(lambda error, request: errors.append(error))
try:
    for theme in ('capitaine-cursors', 'capitaine-cursors-light'):
        m.cursor_theme = theme
        for name in ('left_ptr', 'text', 'vertical-text', 'pointer', 'grab',
                     'ew-resize', 'ns-resize', 'nwse-resize', 'nesw-resize', 'wait'):
            m.cursor_name = name
            m._free_frames()
            original, size, hx, hy, _ = load_artwork(theme, name)[0]
            assert size >= 96, 'expected high-resolution theme artwork'
            expected = Image.new('RGBA', (original.width + 4, original.height + 4))
            expected.paste(original.convert('RGBA'), (2, 2))
            image, xhot, yhot, _ = render_artwork(theme, name, size, 0)
            assert image.tobytes() == expected.tobytes(), (theme, name)
            assert (xhot, yhot) == (hx + 2, hy + 2)
            for color in (None, 0xffffff):
                p, w, h, rects, xhot, yhot = m._theme_frame(size / 48, color, 0)
                raw = p.get_image(0, 0, w, h, X.ZPixmap, 0xffffffff).data
                for x, y, length, _ in rects:
                    r, g, b, a = expected.getpixel((x, y))
                    actual = int.from_bytes(raw[(y*w+x)*4:(y*w+x+1)*4], sys.byteorder) & 0xffffff
                    wanted = (r << 16) | (g << 8) | b
                    if color == 0xffffff:
                        wanted ^= 0xffffff
                    assert actual == wanted, (theme, name, x, y)
                    assert a >= 128
    unknown = render_artwork('capitaine-cursors', 'does-not-exist-xyz', 144, 0)[0]
    arrow = render_artwork('capitaine-cursors', 'left_ptr', 144, 0)[0]
    assert unknown.tobytes() == arrow.tobytes()
    m.trigger(0)
    sizes = []
    for i in range(1, 31):
        m.update(300, 300, i*.02, DEFAULTS, shaking=True)
        sizes.append(max(r.x + r.width for r in m.window.shape_get_rectangles(m.shape.SK.Bounding).rectangles))
    assert sizes[-1] > sizes[0] and sizes == sorted(sizes)
    m.update(300, 300, .7, DEFAULTS, shaking=False)
    assert max(r.x + r.width for r in m.window.shape_get_rectangles(m.shape.SK.Bounding).rectangles) == sizes[-1], 'pause must freeze enlargement'
    m.update(300, 300, .8, DEFAULTS, shaking=False)
    assert max(r.x + r.width for r in m.window.shape_get_rectangles(m.shape.SK.Bounding).rectangles) == sizes[-1]
    m.update(300, 300, .82, DEFAULTS, shaking=True)
    assert max(r.x + r.width for r in m.window.shape_get_rectangles(m.shape.SK.Bounding).rectangles) >= sizes[-1]
    m.update(300, 300, 2, DEFAULTS, shaking=False)
    assert not m.hidden and not m.frames
    m.pulse(3)
    m.update(300, 300, 3.2, dict(DEFAULTS, enabled=False), shaking=False)
    assert m.hidden, 'arrival should work with shake detection disabled'
    m.update(300, 300, 3.8, dict(DEFAULTS, enabled=False), shaking=False)
    assert not m.hidden
    m.trigger(4)
    m.growth.progress = m.growth.hold_progress = 1
    m.pulse(4.1)
    m.update(300, 300, 4.2, DEFAULTS, shaking=False)
    assert max(r.x + r.width for r in m.window.shape_get_rectangles(m.shape.SK.Bounding).rectangles) >= 100, 'arrival must not shrink an active 5x shake'
    m.hide()
    m.display.sync()
    assert not errors, errors
    print('PASS: original artwork pixels/hotspots for 10 names in both themes; inversion, fallback, gradual growth, pause/resume, cleanup')
finally:
    m.close()
    observer.close()
