"""Run under Xvfb: preview owns only its compositor and cleans up on exit."""
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from Xlib import display

repo = Path(__file__).resolve().parents[1]
x = display.Display()
selection = x.intern_atom('_NET_WM_CM_S0')
assert not x.get_selection_owner(selection), 'requires isolated display'


def owner():
    window = x.get_selection_owner(selection)
    return window.id if window else None


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, 'timed out'
        time.sleep(.02)


def run_preview():
    with tempfile.TemporaryFile(mode='w+') as log:
        child = subprocess.Popen([sys.executable, '-u', str(repo/'preview.py'),
                                  '--compositor'], stdout=log, stderr=subprocess.STDOUT)
        try:
            def ready():
                assert child.poll() is None
                log.seek(0)
                return 'Shake-to-find:' in log.read()
            wait_for(ready)
            wait_for(owner)
            return owner()
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=8)
            assert child.returncode == 0


external = None
try:
    run_preview()
    wait_for(lambda: owner() is None)
    external = subprocess.Popen(['xcompmgr', '-n'])
    wait_for(owner)
    existing = owner()
    assert run_preview() == existing
    assert external.poll() is None and owner() == existing
    print('PASS: preview cleans up its compositor and preserves an existing compositor')
finally:
    if external:
        external.terminate()
        external.wait(timeout=5)
    x.close()
