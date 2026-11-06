# mouse-warp

Screen edge wrapping, monitor switching, and shake-to-find for X11.

## Features

- Edge wrapping with optional time/distance/velocity resistance
- Shift + mouse: jump between monitors
- Ctrl + mouse: accelerated cursor movement
- Focus-following cursor warp for i3 (optional `i3ipc` dependency)
- Theme-aware warp highlights
- Shake-to-find using the current cursor theme's original artwork

## Install and service

```bash
make install enable start
```

`mouse-warp.service` runs `mouse-warp.py`, which includes shake-to-find. No
separate shake process is needed. Installation preserves an existing
`~/.config/mouse-warp/config.toml`. Commands:

```bash
make start stop restart status reload-config
```

Run one command at a time, e.g. `make restart`.

## Shake to find

Quickly move back and forth to activate. Continued shaking gradually enlarges
the cursor along a smooth curve, up to 5× after 1.2 seconds of active shaking.
Pausing immediately stops growth. The cursor holds its current size for 0.7
seconds, then shrinks back over 0.25 seconds. Resuming shaking during the hold or
shrink continues from the current size. Two full-color inversions flash at the
maximum size; continued shaking does not restart those flashes.

Horizontal, vertical, and diagonal gestures work. Small jitter, slow gestures,
straight travel, and large teleports are filtered. Mouse-warp's own warps reset
detection; Ctrl/Shift gestures suppress it.

Standalone preview using defaults (Ctrl+C exits):

```bash
python3 shake_find.py
```

Avoid running the preview alongside the service, since both would detect shakes.
The service reads `[shake_find]` from `~/.config/mouse-warp/config.toml`:

```toml
[shake_find]
enabled = true
appearance = "theme"
scale = 5.0
growth_time = 1.2
hold = 0.7
shrink = 0.25
blink = true
```

**Existing configs specifying `appearance = "vector"` must switch to `"theme"`
to use matching artwork.** `growth_time` controls active shaking time to maximum
size. `scale` controls maximum enlargement. Increase `min_distance` or
`reversals` for fewer accidental activations. Sampling follows
`general.poll_interval` (20–40 ms recommended).

## Cursor appearance and theme changes

`appearance = "theme"` loads the original artwork through libXcursor. It retains
exact cursor names (including hands, carets, resize handles, and theme aliases),
colors, outlines, hotspots, and animated frames. It follows `Xcursor.theme` and
`Xcursor.size` from the X11 RESOURCE_MANAGER property, including changes while
already enlarged. Catppuccin supplies white Capitaine cursors for Mocha and
black ones for Latte. Unknown or missing cursor names use the theme's arrow.
Application-defined custom bitmap cursors without a theme name cannot be matched
exactly in this mode.

The renderer loads large artwork (Capitaine supplies 96–144px images, depending
on the shape), then resamples it with Lanczos at each requested size. Thus it
avoids magnifying the small on-screen cursor bitmap. Above the largest supplied
asset size, resampling is still necessary; this is not an SVG renderer. Cached
frames keep steady-size rendering inexpensive. Pillow and libXcursor are required.

The click-through SHAPE overlay works without a compositor. It preserves opaque
artwork colors but uses a binary transparency mask, so translucent edge/shadow
pixels cannot match the native hardware cursor exactly. The current renderer
requires a standard 24-bit RGB X11 visual; native Wayland is not supported.

Alternative appearances remain available:

- `"vector"`: custom polygon shapes, theme-aware black/white color and nominal size;
  these are approximations rather than the original theme artwork.
- `"captured"`: enlarge the cursor snapshot taken at activation; this retains
  custom bitmap appearance but can look pixelated and does not follow shape changes.

XFixes cursor-name notifications update live theme/vector shapes without reading
cursor images. If X11 denies an activation snapshot (`BadAccess`/`BadCursor`),
theme/vector modes use the last reported name or the theme arrow; captured mode
skips that activation and can retry later. Cleanup restores native visibility,
and closing the owning X connection also releases its cursor-hide request.

## Verification

`make test` runs detector, growth, and error-handling unit tests.
`bash .verify/check` also checks X11 rendering, input pass-through, restoration,
and (when Capitaine is installed) original theme artwork and pause/resume growth.
It requires Xvfb and xauth.

```bash
xvfb-run -a python3 tests/theme_toggle_smoke.py
```

That host test exercises both Capitaine themes at 24, 32, 36, and 48px through
`xrdb -merge` / `xsetroot -xcf`, while enlarged and between activations. It accepts
an old `refresh-mouse-cursors` helper path as an optional argument. All tests use
isolated displays; they do not modify the live desktop or Catppuccin configuration.

## Normal cursor size

Catppuccin controls the normal cursor size. `integration/catppuccin-cursor-size32.patch`
updates the original 24px hook to 32px. `integration/catppuccin-cursor-size48.patch`
updates an already-32px hook to 48px for better visibility. Capitaine maps requests
of 32, 36, and 40px to its 36px artwork; 48px is the next native size. Apply only
the appropriate patch from the Catppuccin repository and refresh its theme.
Applications that cache cursors may need reopening.
