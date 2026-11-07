# mouse-warp

Screen edge wrapping, monitor switching, and shake-to-find for X11.

- Wrap the pointer at screen edges, with optional resistance.
- Hold Shift and move horizontally to jump between monitors.
- Hold Ctrl to accelerate pointer movement.
- Shake to enlarge the pointer using your cursor theme.
- Optionally move the pointer to the focused window in i3.

## Installation

Requires Python 3, virtual environment support, `xdotool`, and an X11 session.
Theme artwork requires libXcursor. Install `xrandr` and `xdpyinfo` for monitor
detection, and `gsettings` for automatic light/dark palette detection.
The installer creates a virtual environment for the Python dependencies.
Service management requires systemd user services.

```bash
make install
make enable
```

Installation preserves an existing `~/.config/mouse-warp/config.toml`.
To control the service, use `make start`, `make stop`, `make restart`,
`make status`, or `make reload-config`.

If the service cannot connect to your display, run this from your X11 session,
then restart it:

```bash
make import-env
make restart
```

## Configuration

Edit `~/.config/mouse-warp/config.toml`, then run `make reload-config`.
See [config.toml](config.toml) for all settings, including edge resistance,
acceleration, feedback colors, and optional i3 focus warping (`i3ipc` required).

Shake-to-find enlarges the pointer while you shake. Continued movement holds
its size; resting lets it shrink back. The main controls are:

```toml
[shake_find]
enabled = true
appearance = "theme"
scale = 5.0
growth_time = 1.2
window = 0.5
reversals = 4
min_stroke = 36
min_distance = 240
hold = 0.7
shrink = 0.25
blink = true
```

Increase `min_distance` or `reversals` to reduce accidental activation.
`scale` sets maximum enlargement; `growth_time` sets how long to shake to reach it.
The `theme` appearance follows Xcursor theme and size changes. Alternatives are
`vector` (simplified shapes) and `captured` (a snapshot of the cursor at activation).

Monitor jumps use a brief cursor pulse. To use edge flashes instead, set
`highlight.monitor_cross_style = "edge_flash"`. Wraps and natural monitor
crossings use edge flashes in either mode.

## Preview

From the checkout, using a Python environment with [requirements.txt](requirements.txt)
installed:

```bash
python3 preview.py --pause-service
```

The preview uses the checkout's config, pauses the installed service, and restores
it on exit. Press Ctrl+C to quit. Add `--installed-config` to use your user config.

## Compatibility

Requires a standard 24-bit RGB X11 display; native Wayland is unsupported.
The cursor overlay is click-through and works without a compositor, but translucent
edges may differ from the native cursor. Custom application cursors without a
theme name may use the theme's arrow instead.

Some applications show repaint artifacts while the enlarged cursor moves without
a compositor. If needed, install `xcompmgr` and enable the optional compositor:

```bash
make enable-compositor
make restart
```

It skips startup when another compositor is present. Use `make disable-compositor`
to disable it, or add `--compositor` to the preview command for a temporary trial.

## Development

```bash
make test
bash .verify/check
```

The full check requires Xvfb and xauth; additional checks run when Capitaine cursor
themes or `xcompmgr` are installed. X11 smoke tests use isolated displays.
See [perf/README.md](perf/README.md) for the measurement harness and results.
