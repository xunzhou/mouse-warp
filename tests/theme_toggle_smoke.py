"""Host integration: run only on an isolated Xvfb display.

xvfb-run -a python3 tests/theme_toggle_smoke.py [optional-refresh-helper]
Exercises actual theme assets and refresh helper without gsettings, systemd,
or writes to the user's configuration. Paths are supplied explicitly.
"""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shake_find import CursorMagnifier, DEFAULTS
from cursor_shapes import capture_cursor

helper = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
m = CursorMagnifier()
try:
    m.trigger(0)
    m.update(220, 220, .2, DEFAULTS)
    denied = 0
    for size, theme in [(size, theme) for size in (24, 32, 36, 48)
                        for theme in ('capitaine-cursors-light', 'capitaine-cursors')]:
        asset = Path('/usr/share/icons') / theme / 'cursors/left_ptr'
        subprocess.run(['xrdb', '-merge'], input=f'Xcursor.theme: {theme}\nXcursor.size: {size}\n', text=True, check=True)
        subprocess.run(['xsetroot', '-xcf', str(asset), str(size)], check=True)
        if helper:
            subprocess.run([sys.executable, str(helper), theme], check=True)
        m.display.sync()
        denied += capture_cursor(m.display) is None
        m.update(220, 220, .3, DEFAULTS)
        assert m.cursor_size == size
        assert m.base_fill == (0xffffff if theme.endswith('-light') else 0)
        assert m.hidden, 'toggle interrupted an active vector animation'
        m.hide()
        m.trigger(0)
        m.update(220, 220, .3, DEFAULTS)
        assert m.hidden, 'activation after toggle failed'
    m.update(220, 220, 1, DEFAULTS)
    assert not m.hidden and not m.frames
    print(f'PASS: 8 theme replacements while enlarged + 8 post-toggle activations; '
          f'{denied} unreadable cursor snapshots handled; visibility restored')
finally:
    m.close()
