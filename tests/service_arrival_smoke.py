"""Run under Xvfb: drive the real main loop with Shift and two virtual monitors."""
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from Xlib import X, XK, display
from Xlib.ext import xtest, shape

source = Path(__file__).resolve().parents[1] / 'mouse-warp.py'
child = '''
import importlib.util, signal, sys
spec=importlib.util.spec_from_file_location('mouse_warp',sys.argv[1])
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.mon_list=[(0,0,320,480),(320,0,640,480)]
m.config['general']['poll_interval']=.04
m.config['highlight']['monitor_cross_style']='cursor'
m.config['highlight']['cursor_scale']=2.4
m.config['highlight']['cursor_duration']=.7
m.config['shake_find']['enabled']=False
m.config['edge_wrap']['enabled']=False
m.config['focus_warp']['enabled']=False
signal.signal(signal.SIGTERM,lambda *_: sys.exit(0))
try: m.main()
finally:
    if m.magnifier: m.magnifier.close()
'''
x = display.Display()
root = x.screen().root
root.warp_pointer(100, 240)
x.sync()
shift = x.keysym_to_keycode(XK.string_to_keysym('Shift_L'))
with tempfile.TemporaryFile(mode='w+') as log:
    proc = subprocess.Popen([sys.executable, '-u', '-c', child, str(source)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=source.parent)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            log.seek(0)
            if 'Shake-to-find:' in log.read():
                break
            assert proc.poll() is None, 'main loop exited during startup'
            time.sleep(.02)
        else:
            raise AssertionError('main loop did not initialize')
        time.sleep(.1)
        xtest.fake_input(x, X.KeyPress, shift)
        root.warp_pointer(240, 240)
        x.sync()
        widths = []
        positions = []
        start = time.monotonic()
        overlay = None
        while time.monotonic() - start < 1.2:
            if time.monotonic() - start > .15:
                xtest.fake_input(x, X.KeyRelease, shift)
                x.flush()
            pointer = root.query_pointer()
            positions.append(pointer.root_x)
            for window in root.query_tree().children:
                if window.get_wm_name() == 'mouse-warp shake cursor':
                    overlay = window
                    if window.get_attributes().map_state == X.IsViewable:
                        widths.append(max(r.x + r.width for r in window.shape_get_rectangles(shape.SK.Bounding).rectangles))
                        assert not window.shape_get_rectangles(shape.SK.Input).rectangles
            time.sleep(.01)
        assert 480 in positions, 'Shift+move did not reach monitor center'
        assert widths and max(widths) > min(widths) * 1.5, widths
        assert overlay.get_attributes().map_state == X.IsUnmapped
        assert len(root.query_tree().children) == 1, 'unexpected bracket/flash window'
        assert proc.poll() is None
        log.seek(0)
        assert 'disabled after error' not in log.read()
        print(f'PASS: real Shift+move -> monitor center, themed arrival pulse ({min(widths)}–{max(widths)}px), click-through, expiry with shake disabled')
    finally:
        xtest.fake_input(x, X.KeyRelease, shift)
        x.sync()
        proc.terminate()
        proc.wait(timeout=5)
        x.close()
