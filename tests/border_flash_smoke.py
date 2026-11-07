"""Xvfb: inspect painted border pixels as both ends retract to the crossing."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from Xlib import X, display

source = Path(os.environ.get('MOUSE_WARP_SOURCE', Path(__file__).resolve().parents[1]/'mouse-warp.py'))
spec = importlib.util.spec_from_file_location('mouse_warp', source)
app = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(source.parent))
spec.loader.exec_module(app)
app.get_color = lambda _: 0xffa000
app.config['highlight'].update(enabled=True, edge_flash_length=120, edge_flash_thickness=8)
observer = display.Display()
root = observer.screen().root
compositor = None
try:
    if shutil.which('xcompmgr'):
        compositor = subprocess.Popen(['xcompmgr', '-n'])
        atom = observer.intern_atom('_NET_WM_CM_S0')
        deadline = time.monotonic()+3
        while not observer.get_selection_owner(atom):
            assert time.monotonic()<deadline
            time.sleep(.01)
    for edge, cross in [('left',240),('right',240),('top',240),('bottom',240),('left',15)]:
        app.show_edge_flash(edge, cross, edge_pos=320, duration=.5)
        spans=[]
        start=time.monotonic()
        while time.monotonic()-start<.7:
            vertical=edge in ('left','right')
            # Sample a fixed screen strip, so stale pixels outside the current
            # window/shape cannot escape detection.
            x,y,w,h=(312,0,16,480) if vertical else (0,312,480,16)
            data=root.get_image(x,y,w,h,X.ZPixmap,0xffffffff).data
            locations=[]
            for row in range(h):
                for col in range(w):
                    offset=(row*w+col)*4
                    if int.from_bytes(data[offset:offset+4],sys.byteorder)&0xffffff==0xffa000:
                        locations.append(row if vertical else col)
            if locations:
                low,high=min(locations),max(locations)
                spans.append(high-low+1)
                if low>0:
                    assert abs((low+high)/2-cross)<=1, (edge,cross,low,high)
            time.sleep(.005)
        assert spans and min(spans)<12, (edge,spans)
        assert max(spans)>50, (edge,spans)
        assert not locations, 'border left painted pixels after expiry'
    print('PASS: painted borders retract from both ends to crossing point, including near screen corner')
finally:
    if compositor:
        compositor.terminate();compositor.wait(timeout=5)
    observer.close();app.d.close()
