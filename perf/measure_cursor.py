#!/usr/bin/env python3
"""Measure the real main loop on the current X server using synthetic input.

The benchmark window is forced offscreen, cursor hide/show calls are suppressed,
and all warp/focus actions are disabled. Never moves or hides the user's pointer.
Reported response time is synthetic event-to-XSync completion, not input-to-photon
latency. Do not compare runs made on different X servers as an A/B result.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import math
from pathlib import Path
import statistics
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, required=True)
parser.add_argument('--seconds', type=float, default=9)
args = parser.parse_args()
sys.path.insert(0, str(args.repo.resolve()))


def stats(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'median': round(statistics.median(values), 3),
            'p95': round(values[math.ceil(.95*len(values))-1], 3),
            'p99': round(values[math.ceil(.99*len(values))-1], 3),
            'max': round(values[-1], 3)}


class Finished(Exception):
    pass


with contextlib.redirect_stdout(io.StringIO()) as logs:
    spec = importlib.util.spec_from_file_location('mouse_warp', args.repo/'mouse-warp.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.config['general']['poll_interval'] = .04
    for key in ('edge_wrap', 'monitor_switch', 'acceleration', 'focus_warp', 'highlight'):
        module.config[key]['enabled'] = False
    module.config['shake_find']['enabled'] = True
    module.config['shake_find']['appearance'] = 'theme'
    module.mon_list = [(0, 0, 10000, 10000)]
    module.HAS_RANDR = False
    module.start_focus_warp_listener = lambda: None
    module.move_mouse = lambda *_: (_ for _ in ()).throw(AssertionError('warp forbidden'))
    records = []
    import shake_find
    original_notifications = shake_find.latest_cursor_name

    def drain_notifications(display, on_event=None):
        original_notifications(display)  # discard live shape/theme changes
        return None
    shake_find.latest_cursor_name = drain_notifications
    base = module.CursorMagnifier

    class MeasuredMagnifier(base):
        def __init__(self):
            super().__init__()
            self.root.xfixes_hide_cursor = lambda: None
            self.root.xfixes_show_cursor = lambda: None
            configure = self.window.configure

            def offscreen(**kwargs):
                kwargs.update(x=-20000, y=-20000)
                return configure(**kwargs)
            self.window.configure = offscreen

        def trigger(self, now):
            super().trigger(now)
            self.cursor_name, self.cursor_kind = 'left_ptr', 'arrow'

        def update(self, x, y, *positional, **kwargs):
            begin = time.perf_counter()
            super().update(x, y, *positional, **kwargs)
            end = time.perf_counter()
            if self.started is not None and self.hidden:
                records.append((end-origin, int(y-500), self.started, (end-begin)*1000))

    module.CursorMagnifier = MeasuredMagnifier
    origin = time.perf_counter()
    cpu_start = time.process_time()

    def pointer():
        elapsed = time.perf_counter()-origin
        if elapsed >= args.seconds:
            raise Finished()
        cycle = int(elapsed/4.5)
        moving_time = cycle*4.5 + min(elapsed-cycle*4.5, 3)
        seq = int(moving_time/.01)
        return 300 + abs(seq % 24 - 12)*12, 500+seq, False, False

    module.query_pointer = pointer
    try:
        module.main()
    except Finished:
        pass
    finally:
        if module.magnifier:
            module.magnifier.close()
    elapsed = time.perf_counter()-origin
    cpu = time.process_time()-cpu_start

intervals, responses = [], []
for previous, current in zip(records, records[1:]):
    if previous[2] != current[2]:
        continue
    intervals.append((current[0]-previous[0])*1000)
    if current[1] > previous[1]:
        for seq in range(previous[1]+1, current[1]+1):
            # Input is paused for the final 1.5 seconds of each cycle.
            if (seq*.01) % 4.5 <= 3:
                responses.append((current[0]-seq*.01)*1000)
result = {'repo': str(args.repo), 'wall_seconds': round(elapsed, 3),
          'cpu_seconds': round(cpu, 3), 'cpu_percent_one_core': round(cpu/elapsed*100, 2),
          'cursor_theme': module.magnifier.cursor_theme,
          'cursor_size': module.magnifier.cursor_size, 'cursor_name': 'left_ptr',
          'frame_gap_ms': stats(intervals), 'update_ms': stats([r[3] for r in records]),
          'synthetic_event_to_submission_ms': stats(responses),
          'frame_gaps_over_25ms': sum(v > 25 for v in intervals)}
if not records:
    raise SystemExit('No active animation frames measured: '+logs.getvalue())
print(json.dumps(result, indent=2))
