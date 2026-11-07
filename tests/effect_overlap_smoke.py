"""Xvfb: effects retain ownership, stable color, and click-through borders."""
import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Xlib import X, display
from Xlib.ext import shape
from shake_find import CursorMagnifier, DEFAULTS

m = CursorMagnifier()
background = m.root.create_window(0, 0, 640, 480, 0, m.display.screen().root_depth,
                                  X.InputOutput, X.CopyFromParent,
                                  background_pixel=0x345678)
background.map()
m.display.sync()

def assert_transparent_surroundings():
    g = m.window.get_geometry()
    rects = m.window.shape_get_rectangles(shape.SK.Bounding).rectangles
    covered = set()
    for rect in rects:
        for y in range(rect.y, rect.y + rect.height):
            covered.update((x, y) for x in range(rect.x, rect.x + rect.width))
    width = max(r.x + r.width for r in rects) + 8
    height = max(r.y + r.height for r in rects) + 8
    data = m.root.get_image(g.x, g.y, width, height, X.ZPixmap, 0xffffffff).data
    for y in range(height):
        for x in range(width):
            if (x, y) not in covered:
                offset = (y*width+x)*4
                pixel = int.from_bytes(data[offset:offset+4], sys.byteorder) & 0xffffff
                assert pixel == 0x345678, (x, y, hex(pixel))
    assert len(covered) < width*height*.7, 'opaque rectangle around cursor'

try:
    m.pulse(0)
    m.update(200, 200, .2, DEFAULTS, shaking=True)
    assert m.growth.progress == 0, 'unconfirmed movement must not start shake growth'
    assert_transparent_surroundings()
    canvas = m.window.get_geometry().width
    scale = m._displayed_scale
    m.pulse(.2)
    assert m.arrival[0] == 0, 'repeated crossing must not restart arrival'
    m.update(200, 200, .2, DEFAULTS, shaking=False)
    assert m._displayed_scale == scale
    m.trigger(.2)
    m.update(200, 200, .2, DEFAULTS, shaking=True)
    assert abs(m._displayed_scale - scale) < 1e-6, 'shake handoff jumped'
    assert m.arrival is None
    m.growth.progress = m.growth.hold_progress = 1
    m.growth.peak_at = .3
    m.update(200, 200, .5, DEFAULTS, shaking=True)
    assert_transparent_surroundings()
    assert m.window.get_geometry().width == canvas, 'animation resized the X window'
    before = m._last_presentation
    m.pulse(.5)
    m.update(200, 200, .5, DEFAULTS, shaking=True)
    assert m.arrival is None and m._last_presentation == before, 'crossing changed shake color'
finally:
    background.destroy()
    m.close()

spec = importlib.util.spec_from_file_location('mouse_warp', Path(__file__).resolve().parents[1] / 'mouse-warp.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.get_color = lambda _: 0xffa000
app.config['highlight']['enabled'] = True
observer = display.Display()
root = observer.screen().root

def windows():
    return [w for w in root.query_tree().children if w.get_attributes().map_state == X.IsViewable]

try:
    app.show_edge_flash('left', 240, edge_pos=320, duration=.6)
    deadline = time.monotonic() + 2
    while not windows() and time.monotonic() < deadline:
        time.sleep(.005)
    visible = windows()
    assert len(visible) == 1
    window = visible[0]
    assert not window.shape_get_rectangles(shape.SK.Input).rectangles
    initial = window.get_geometry().height
    app.show_edge_flash('right', 240, edge_pos=320, duration=.6)
    time.sleep(.4)
    assert len(windows()) == 1, 'crossings stacked border indicators'
    rects = window.shape_get_rectangles(shape.SK.Bounding).rectangles
    assert max(r.height for r in rects) < initial, 'border did not retract'
    assert window.get_geometry().height == initial, 'border window must stay fixed'
    app.magnifier = SimpleNamespace(started=1)
    time.sleep(.05)
    assert not windows(), 'border competed with active cursor effect'
    app.show_edge_flash('left', 240, edge_pos=320, duration=.6)
    time.sleep(.05)
    assert not windows(), 'active cursor effect allowed new border flash'
    print('PASS: arrival coalescing, continuous shake handoff, stable blink, retracting click-through borders, effect priority')
finally:
    observer.close()
    app.d.close()
