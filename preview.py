"""Run a desktop preview, optionally owning a compositor and pausing the service."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys

from compositor_support import compositor_needed

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--compositor', action='store_true')
parser.add_argument('--installed-config', action='store_true')
parser.add_argument('--pause-service', action='store_true')
args = parser.parse_args()
repo = Path(__file__).resolve().parent
main = compositor = None
restore_service = False


def stop(*_):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    if args.pause_service:
        restore_service = subprocess.run(['systemctl', '--user', 'is-active', '--quiet',
                                          'mouse-warp.service']).returncode == 0
        subprocess.run(['systemctl', '--user', 'stop', 'mouse-warp.service'], check=True)
    if args.compositor and compositor_needed():
        compositor = subprocess.Popen(['xcompmgr', '-n'])
    environment = os.environ.copy()
    if not args.installed_config:
        environment['MOUSE_WARP_CONFIG'] = str(repo / 'config.toml')
    main = subprocess.Popen([sys.executable, '-u', str(repo / 'mouse-warp.py')], env=environment)
    raise SystemExit(main.wait())
finally:
    for child in (main, compositor):
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    if restore_service:
        subprocess.run(['systemctl', '--user', 'start', 'mouse-warp.service'], check=True)
