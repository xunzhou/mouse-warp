"""Compare repaint requests beneath a moving/growing overlay on isolated Xvfb.

Run: xvfb-run -a python3 perf/measure_exposure.py --isolated-display
Requires xcompmgr. Never run this probe on the live desktop.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Xlib import X, display
from shake_find import CursorMagnifier, DEFAULTS
from compositor_support import compositor_needed

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--isolated-display', action='store_true', required=True)
parser.parse_args()
x = display.Display()
root = x.screen().root
selection = x.intern_atom('_NET_WM_CM_S0')
if x.get_selection_owner(selection):
    raise SystemExit('Refusing to run on a display with an existing compositor')


def probe():
    under = root.create_window(40, 40, 700, 500, 0, x.screen().root_depth,
                               X.InputOutput, X.CopyFromParent,
                               background_pixel=0xcccccc,
                               backing_store=X.NotUseful, event_mask=X.ExposureMask)
    under.map()
    gc = under.create_gc(foreground=0x345678)
    under.fill_rectangle(gc, 0, 0, 700, 500)
    x.sync()
    while x.pending_events():
        x.next_event()
    magnifier = CursorMagnifier()
    events = area = 0
    try:
        magnifier.trigger(0)
        for i in range(1, 41):
            magnifier.update(150 + i*8, 200 + i*2, i*.02, DEFAULTS,
                             shaking=True, moving=True)
            x.sync()
            while x.pending_events():
                event = x.next_event()
                if event.type == X.Expose and event.window.id == under.id:
                    events += 1
                    area += event.width * event.height
            time.sleep(.01)
        return dict(expose_events=events, exposed_pixel_area=area)
    finally:
        magnifier.close()
        gc.free()
        under.destroy()
        x.sync()


compositor = None
try:
    assert compositor_needed(), 'empty display should permit compositor startup'
    result = {'without_compositor': probe()}
    compositor = subprocess.Popen(['xcompmgr', '-n'])
    deadline = time.monotonic() + 3
    while not x.get_selection_owner(selection):
        if compositor.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError('test compositor failed to start')
        time.sleep(.02)
    assert not compositor_needed(), 'must not start over an existing compositor'
    result['with_compositor'] = probe()
    print(json.dumps(result, indent=2))
finally:
    if compositor:
        compositor.terminate()
        compositor.wait(timeout=5)
    x.close()
