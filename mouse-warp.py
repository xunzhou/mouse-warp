#!/usr/bin/env python3
# Mouse warp utility - screen edge wrapping and monitor switching

import shutil
import subprocess
import sys
import signal
import time
import threading
import re
from pathlib import Path

# TOML support (Python 3.11+ has tomllib, fallback to tomli)
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

try:
    from Xlib import X, display
    from Xlib.ext import shape
except ImportError:
    print("Error: python-xlib is required. Install with: pip install python-xlib")
    sys.exit(1)

try:
    from Xlib.ext import randr
    HAS_RANDR = True
except ImportError:
    HAS_RANDR = False

# ============================================================================
# Binary Dependencies
# ============================================================================

REQUIRED_BINARIES = ['xdotool']
OPTIONAL_BINARIES = ['xrandr', 'xdpyinfo', 'gsettings']

_available_binaries = {}

def check_binaries():
    """Check for required and optional binaries at startup."""
    missing_required = []

    for binary in REQUIRED_BINARIES:
        path = shutil.which(binary)
        _available_binaries[binary] = path
        if not path:
            missing_required.append(binary)

    for binary in OPTIONAL_BINARIES:
        _available_binaries[binary] = shutil.which(binary)

    if missing_required:
        print(f"Error: Required binaries not found: {', '.join(missing_required)}")
        print("Install with your package manager (e.g., apt install xdotool)")
        sys.exit(1)

    # Report optional missing binaries
    missing_optional = [b for b in OPTIONAL_BINARIES if not _available_binaries[b]]
    if missing_optional:
        print(f"Warning: Optional binaries not found: {', '.join(missing_optional)}")
        print("  Some features may be limited.")

def has_binary(name):
    """Check if a binary is available."""
    return _available_binaries.get(name) is not None

check_binaries()

# ============================================================================
# Configuration
# ============================================================================

CONFIG_PATH = Path.home() / ".config" / "mouse-warp" / "config.toml"

DEFAULT_CONFIG = {
    'general': {
        'poll_interval': 0.01,
    },
    'edge_wrap': {
        'enabled': True,
        'horizontal': True,
        'vertical': True,
    },
    'edge_resistance': {
        'enabled': False,
        'mode': 'distance',
        'time_delay': 0.15,
        'distance_threshold': 30,
        'velocity_threshold': 800,
    },
    'monitor_switch': {
        'enabled': True,
        'shift_threshold': 100,
    },
    'acceleration': {
        'enabled': True,
        'multiplier': 2.0,  # How much to multiply movement by
        'edge_resistance': 50,  # Pixels of resistance at monitor edges (0 to disable)
    },
    'highlight': {
        'enabled': True,
        'size': 80,
        'duration': 0.6,
        'monitor_warp_color': 'sky',
        'edge_warp_color': 'peach',
    },
    'theme': {
        'mode': 'auto',
        'cache_ttl': 5.0,
    },
}

def deep_merge(base, override):
    """Deep merge override into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_config():
    """Load configuration from TOML file."""
    config = deep_merge({}, DEFAULT_CONFIG)  # Deep copy defaults

    if CONFIG_PATH.exists():
        if not tomllib:
            print(f"Error: Config file exists at {CONFIG_PATH}")
            print("  but tomllib/tomli is not available to parse it.")
            print("  Install with: pip install tomli (Python < 3.11)")
            print("  Or remove the config file to use defaults.")
            sys.exit(1)
        try:
            with open(CONFIG_PATH, 'rb') as f:
                user_config = tomllib.load(f)
            config = deep_merge(DEFAULT_CONFIG, user_config)
            print(f"Config: {CONFIG_PATH}")
        except Exception as e:
            print(f"Error: Failed to parse config: {e}")
            print(f"  Fix TOML syntax at {CONFIG_PATH}")
            sys.exit(1)
    else:
        print(f"Config: {CONFIG_PATH} (not found, using defaults)")
        print(f"  Run 'make install' to create default config")

    return config

# Global config
config = load_config()

def reload_config(signum=None, frame=None):
    """Reload configuration and refresh monitor geometry on SIGHUP."""
    global config
    config = load_config()
    # Refresh monitor geometry (function defined later, guard for module load time)
    if 'refresh_monitor_geometry' in globals():
        refresh_monitor_geometry(force=True)
    print("Configuration reloaded")

# Register SIGHUP handler
signal.signal(signal.SIGHUP, reload_config)

# ============================================================================
# Display Initialization
# ============================================================================

try:
    d = display.Display()
    root = d.screen().root
    screen = d.screen()
except Exception as e:
    print(f"Error: Cannot connect to X display: {e}")
    print("This tool requires an X11 session.")
    sys.exit(1)

# Monitor geometry (refreshed on RandR events)
mon_list = []
SCREEN_W = 0
SCREEN_H = 0
_last_geometry_refresh = 0
GEOMETRY_REFRESH_DEBOUNCE = 0.2  # seconds

def refresh_monitor_geometry(force=False):
    """Refresh monitor list and screen dimensions from xrandr/xdpyinfo.

    Returns True if geometry changed, False otherwise.
    Debounces rapid calls unless force=True.
    """
    global mon_list, SCREEN_W, SCREEN_H, _last_geometry_refresh

    now = time.time()
    if not force and (now - _last_geometry_refresh) < GEOMETRY_REFRESH_DEBOUNCE:
        return False
    _last_geometry_refresh = now

    old_mon_list = mon_list[:]
    old_screen = (SCREEN_W, SCREEN_H)

    new_mon_list = []
    new_screen_w = 0
    new_screen_h = 0

    if has_binary('xrandr'):
        try:
            output = subprocess.run(['xrandr'], capture_output=True, text=True, timeout=5)
            if output.returncode == 0:
                for line in output.stdout.split('\n'):
                    if ' connected' in line:
                        match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                        if match:
                            w, h, x, y = map(int, match.groups())
                            new_mon_list.append((x, y, x + w, y + h))
        except Exception as e:
            print(f"Warning: xrandr failed: {e}")

    if has_binary('xdpyinfo'):
        try:
            output = subprocess.run(['xdpyinfo'], capture_output=True, text=True, timeout=5)
            if output.returncode == 0:
                for line in output.stdout.split('\n'):
                    if 'dimensions:' in line:
                        dims = line.split()[1].split('x')
                        new_screen_w = int(dims[0])
                        new_screen_h = int(dims[1])
                        break
        except Exception as e:
            print(f"Warning: xdpyinfo failed: {e}")

    # Fallback: use root window geometry if xrandr/xdpyinfo failed
    if not new_mon_list or new_screen_w == 0:
        geom = root.get_geometry()
        new_screen_w = geom.width
        new_screen_h = geom.height
        if not new_mon_list:
            new_mon_list = [(0, 0, new_screen_w, new_screen_h)]

    # Sort monitors by x position for horizontal arrangement
    new_mon_list.sort(key=lambda m: (m[0], m[1]))

    # Update globals
    mon_list = new_mon_list
    SCREEN_W = new_screen_w
    SCREEN_H = new_screen_h

    changed = (mon_list != old_mon_list or (SCREEN_W, SCREEN_H) != old_screen)
    if changed and old_mon_list:  # Don't print on initial load
        print(f"Monitors updated: {len(mon_list)} monitor(s), {SCREEN_W}x{SCREEN_H}")
        # Reset edge resistance state (edge_resistance defined later, guard for initial call)
        if 'edge_resistance' in globals():
            edge_resistance.reset()
        # Reset prev position to avoid spurious deltas after geometry change
        global prev_x, prev_y
        if 'prev_x' in globals():
            prev_x = None
            prev_y = None

    return changed

# Initial geometry detection
refresh_monitor_geometry(force=True)

# Subscribe to RandR screen change events
_randr_event_base = None
if HAS_RANDR:
    try:
        ext_info = d.query_extension('RANDR')
        if ext_info.present:
            _randr_event_base = ext_info.first_event
            root.xrandr_select_input(randr.RRScreenChangeNotifyMask)
        else:
            HAS_RANDR = False
    except Exception as e:
        print(f"Warning: RandR event subscription failed: {e}")
        HAS_RANDR = False

# ============================================================================
# Color Palettes
# ============================================================================

CATPPUCCIN_MOCHA = {
    'rosewater': 0xf5e0dc, 'flamingo': 0xf2cdcd, 'pink': 0xf5c2e7,
    'mauve': 0xcba6f7, 'red': 0xf38ba8, 'maroon': 0xeba0ac,
    'peach': 0xfab387, 'yellow': 0xf9e2af, 'green': 0xa6e3a1,
    'teal': 0x94e2d5, 'sky': 0x89dceb, 'sapphire': 0x74c7ec,
    'blue': 0x89b4fa, 'lavender': 0xb4befe,
}

CATPPUCCIN_LATTE = {
    'rosewater': 0xdc8a78, 'flamingo': 0xdd7878, 'pink': 0xea76cb,
    'mauve': 0x8839ef, 'red': 0xd20f39, 'maroon': 0xe64553,
    'peach': 0xfe640b, 'yellow': 0xdf8e1d, 'green': 0x40a02b,
    'teal': 0x179299, 'sky': 0x04a5e5, 'sapphire': 0x209fb5,
    'blue': 0x1e66f5, 'lavender': 0x7287fd,
}

# Theme detection cache
_theme_cache = {'value': None, 'time': 0}

def is_dark_mode():
    """Detect system dark/light mode via gsettings (cached)."""
    global _theme_cache

    theme_mode = config['theme']['mode']
    if theme_mode == 'dark':
        return True
    elif theme_mode == 'light':
        return False

    # Auto-detect (requires gsettings)
    if not has_binary('gsettings'):
        return True  # Default to dark mode

    now = time.time()
    cache_ttl = config['theme']['cache_ttl']

    if _theme_cache['value'] is not None and (now - _theme_cache['time']) < cache_ttl:
        return _theme_cache['value']

    result = True  # Default to dark mode
    try:
        proc = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
            capture_output=True, text=True, timeout=0.5
        )
        if proc.returncode == 0:
            scheme = proc.stdout.strip().strip("'")
            if 'dark' in scheme.lower():
                result = True
            elif 'light' in scheme.lower():
                result = False
            _theme_cache = {'value': result, 'time': now}
            return result

        proc = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'],
            capture_output=True, text=True, timeout=0.5
        )
        if proc.returncode == 0:
            theme = proc.stdout.strip().strip("'").lower()
            result = 'dark' in theme
    except Exception:
        pass

    _theme_cache = {'value': result, 'time': now}
    return result

def get_color(name):
    """Get color from appropriate palette based on system dark/light mode."""
    palette = CATPPUCCIN_MOCHA if is_dark_mode() else CATPPUCCIN_LATTE
    return palette.get(name, palette['sky'])

# ============================================================================
# Cursor Highlight
# ============================================================================

HIGHLIGHT_STEPS = 20

def show_cursor_highlight(x, y, color_name='sky'):
    """Show animated highlight at cursor position."""
    if not config['highlight']['enabled']:
        return

    color = get_color(color_name)
    size = config['highlight']['size']
    duration = config['highlight']['duration']

    def animate():
        try:
            td = display.Display()
            troot = td.screen().root
            tscreen = td.screen()

            window = troot.create_window(
                0, 0, size, size, 0,
                tscreen.root_depth,
                X.InputOutput,
                X.CopyFromParent,
                background_pixel=color,
                override_redirect=True,
                event_mask=X.ExposureMask
            )

            # Make it circular ring
            pixmap = window.create_pixmap(size, size, 1)
            gc = pixmap.create_gc(foreground=0, background=0)
            pixmap.fill_rectangle(gc, 0, 0, size, size)
            gc.change(foreground=1)
            pixmap.fill_arc(gc, 0, 0, size, size, 0, 360 * 64)

            center_size = size // 2
            offset = (size - center_size) // 2
            gc.change(foreground=0)
            pixmap.fill_arc(gc, offset, offset, center_size, center_size, 0, 360 * 64)

            window.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, pixmap)
            gc.free()
            pixmap.free()

            for i in range(HIGHLIGHT_STEPS):
                progress = i / HIGHLIGHT_STEPS
                scale = 1.5 - (0.5 * progress)
                cur_size = int(size * scale)

                pos_x = x - cur_size // 2
                pos_y = y - cur_size // 2

                window.configure(x=pos_x, y=pos_y, width=cur_size, height=cur_size)
                window.map()
                td.sync()
                time.sleep(duration / HIGHLIGHT_STEPS)

            window.destroy()
            td.close()
        except Exception as e:
            print(f"Highlight error: {e}")

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()

# ============================================================================
# Input Helpers
# ============================================================================

def is_shift_pressed():
    """Check if Shift key is pressed using modifier state."""
    data = root.query_pointer()
    return bool(data.mask & X.ShiftMask)

def is_ctrl_pressed():
    """Check if Ctrl key is pressed using modifier state."""
    data = root.query_pointer()
    return bool(data.mask & X.ControlMask)

def get_mouse_pos():
    data = root.query_pointer()
    return data.root_x, data.root_y

def move_mouse(x, y):
    """Move mouse to position. Returns True on success."""
    try:
        result = subprocess.run(['xdotool', 'mousemove', str(x), str(y)],
                                capture_output=True, timeout=1)
        return result.returncode == 0
    except Exception as e:
        print(f"Warning: Failed to move mouse: {e}")
        return False

def get_monitor_at(cx, cy):
    """Get monitor index at given coordinates."""
    for i, (mx1, my1, mx2, my2) in enumerate(mon_list):
        if mx1 <= cx < mx2 and my1 <= cy < my2:
            return i
    # Fallback: find closest monitor
    min_dist = float('inf')
    closest = 0
    for i, (mx1, my1, mx2, my2) in enumerate(mon_list):
        center_x = (mx1 + mx2) // 2
        center_y = (my1 + my2) // 2
        dist = (cx - center_x) ** 2 + (cy - center_y) ** 2
        if dist < min_dist:
            min_dist = dist
            closest = i
    return closest

def get_screen_bounds():
    """Get actual screen bounds from monitor list (not X screen dimensions)."""
    if not mon_list:
        return 0, 0, SCREEN_W, SCREEN_H
    min_x = min(m[0] for m in mon_list)
    min_y = min(m[1] for m in mon_list)
    max_x = max(m[2] for m in mon_list)
    max_y = max(m[3] for m in mon_list)
    return min_x, min_y, max_x, max_y

def warp_to_monitor(idx):
    global last_warp_time
    if 0 <= idx < len(mon_list):
        mx1, my1, mx2, my2 = mon_list[idx]
        new_x = (mx1 + mx2) // 2
        new_y = (my1 + my2) // 2
        move_mouse(new_x, new_y)
        show_cursor_highlight(new_x, new_y, config['highlight']['monitor_warp_color'])
        last_warp_time = time.time()

# ============================================================================
# Edge Resistance
# ============================================================================

class EdgeResistance:
    """Handles edge resistance logic for all three modes."""

    def __init__(self):
        self.reset()

    def reset(self):
        # Time mode
        self.edge_hit_time = {'left': None, 'right': None, 'top': None, 'bottom': None}
        # Distance mode
        self.edge_pressure = {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}
        # Velocity tracking
        self.last_pos = None
        self.last_time = None

    def should_allow_wrap(self, edge, x, y, now):
        """Check if wrap should be allowed based on resistance mode."""
        if not config['edge_resistance']['enabled']:
            return True

        mode = config['edge_resistance']['mode']

        if mode == 'none':
            return True
        elif mode == 'time':
            return self._check_time(edge, now)
        elif mode == 'distance':
            return self._check_distance(edge, x, y)
        elif mode == 'velocity':
            return self._check_velocity(x, y, now)

        return True

    def _check_time(self, edge, now):
        """Time-based: wait at edge before allowing wrap."""
        delay = config['edge_resistance']['time_delay']

        if self.edge_hit_time[edge] is None:
            self.edge_hit_time[edge] = now
            return False
        elif now - self.edge_hit_time[edge] >= delay:
            self.edge_hit_time[edge] = None
            return True
        return False

    def _check_distance(self, edge, x, y):
        """Distance-based: accumulate pressure while at edge."""
        threshold = config['edge_resistance']['distance_threshold']

        if self.last_pos:
            # When at edge, cursor position is clamped, so we track movement
            # along the edge as "pressure" - more movement = more intent to cross
            dx = abs(x - self.last_pos[0])
            dy = abs(y - self.last_pos[1])

            # For horizontal edges (left/right), track vertical movement as pressure
            # For vertical edges (top/bottom), track horizontal movement as pressure
            if edge in ('left', 'right'):
                self.edge_pressure[edge] += dy
            else:
                self.edge_pressure[edge] += dx

        if self.edge_pressure[edge] >= threshold:
            self.edge_pressure[edge] = 0
            return True
        return False

    def _check_velocity(self, x, y, now):
        """Velocity-based: only fast movements trigger wrap."""
        threshold = config['edge_resistance']['velocity_threshold']

        if self.last_pos and self.last_time:
            dt = now - self.last_time
            if dt > 0:
                dx = x - self.last_pos[0]
                dy = y - self.last_pos[1]
                distance = (dx**2 + dy**2) ** 0.5
                velocity = distance / dt
                return velocity >= threshold
        return False

    def update(self, x, y, now):
        """Update tracking state."""
        self.last_pos = (x, y)
        self.last_time = now

    def clear_edge(self, edge):
        """Clear resistance state for an edge when cursor moves away."""
        self.edge_hit_time[edge] = None
        self.edge_pressure[edge] = 0

edge_resistance = EdgeResistance()

# ============================================================================
# Main Loop
# ============================================================================

prev_x = None
prev_y = None
last_warp_time = 0
prev_shift_pressed = False
accel_edge_pressure = {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}

def main():
    global prev_x, prev_y, last_warp_time, prev_shift_pressed, accel_edge_pressure

    print(f"Mouse warp started. Monitors: {len(mon_list)}, Screen: {SCREEN_W}x{SCREEN_H}")
    print(f"Config: {CONFIG_PATH}")
    print("Send SIGHUP to reload config" + (" (or monitors will auto-refresh)" if HAS_RANDR else ""))

    while True:
        # Check for RandR screen change events (non-blocking)
        if HAS_RANDR:
            while d.pending_events():
                event = d.next_event()
                if _randr_event_base and event.type == _randr_event_base:
                    refresh_monitor_geometry()

        x, y = get_mouse_pos()
        now = time.time()
        shift_pressed = is_shift_pressed()
        ctrl_pressed = is_ctrl_pressed()

        # Ctrl + movement: accelerate cursor within monitor
        if config['acceleration']['enabled'] and ctrl_pressed and prev_x is not None:
            dx = x - prev_x
            dy = y - prev_y
            if dx != 0 or dy != 0:
                multiplier = config['acceleration']['multiplier']
                edge_resist = config['acceleration']['edge_resistance']
                cur_mon = get_monitor_at(prev_x, prev_y)
                mx1, my1, mx2, my2 = mon_list[cur_mon]

                # Calculate new position with acceleration
                new_x = prev_x + int(dx * multiplier)
                new_y = prev_y + int(dy * multiplier)

                # Apply edge resistance - accumulate pressure before allowing edge crossing
                if edge_resist > 0:
                    # Check each edge and apply resistance
                    if new_x < mx1:
                        overflow = mx1 - new_x
                        accel_edge_pressure['left'] += overflow
                        if accel_edge_pressure['left'] < edge_resist:
                            new_x = mx1  # Hold at edge
                        else:
                            accel_edge_pressure['left'] = 0  # Reset and allow crossing
                    else:
                        accel_edge_pressure['left'] = 0

                    if new_x >= mx2:
                        overflow = new_x - (mx2 - 1)
                        accel_edge_pressure['right'] += overflow
                        if accel_edge_pressure['right'] < edge_resist:
                            new_x = mx2 - 1  # Hold at edge
                        else:
                            accel_edge_pressure['right'] = 0  # Reset and allow crossing
                    else:
                        accel_edge_pressure['right'] = 0

                    if new_y < my1:
                        overflow = my1 - new_y
                        accel_edge_pressure['top'] += overflow
                        if accel_edge_pressure['top'] < edge_resist:
                            new_y = my1  # Hold at edge
                        else:
                            accel_edge_pressure['top'] = 0  # Reset and allow crossing
                    else:
                        accel_edge_pressure['top'] = 0

                    if new_y >= my2:
                        overflow = new_y - (my2 - 1)
                        accel_edge_pressure['bottom'] += overflow
                        if accel_edge_pressure['bottom'] < edge_resist:
                            new_y = my2 - 1  # Hold at edge
                        else:
                            accel_edge_pressure['bottom'] = 0  # Reset and allow crossing
                    else:
                        accel_edge_pressure['bottom'] = 0
                else:
                    # No edge resistance - just clamp to monitor bounds
                    new_x = max(mx1, min(mx2 - 1, new_x))
                    new_y = max(my1, min(my2 - 1, new_y))

                if new_x != x or new_y != y:
                    move_mouse(new_x, new_y)
                    x, y = new_x, new_y
        else:
            # Reset edge pressure when not in acceleration mode
            accel_edge_pressure['left'] = 0
            accel_edge_pressure['right'] = 0
            accel_edge_pressure['top'] = 0
            accel_edge_pressure['bottom'] = 0

        # Reset cooldown on shift re-press
        if shift_pressed and not prev_shift_pressed:
            last_warp_time = 0

        # Shift + movement: fast monitor switch
        if config['monitor_switch']['enabled']:
            threshold = config['monitor_switch']['shift_threshold']
            if prev_x is not None and shift_pressed and (now - last_warp_time) > 0.4:
                delta = x - prev_x
                if delta < -threshold:
                    cur = get_monitor_at(x, y)
                    if cur > 0:
                        warp_to_monitor(cur - 1)
                        x, y = get_mouse_pos()
                elif delta > threshold:
                    cur = get_monitor_at(x, y)
                    if cur < len(mon_list) - 1:
                        warp_to_monitor(cur + 1)
                        x, y = get_mouse_pos()

        prev_x = x
        prev_y = y
        prev_shift_pressed = shift_pressed

        # Edge wrapping
        if config['edge_wrap']['enabled']:
            cur_mon = get_monitor_at(x, y)
            mx1, my1, mx2, my2 = mon_list[cur_mon]
            edge_color = config['highlight']['edge_warp_color']

            # Vertical wrap
            if config['edge_wrap']['vertical']:
                if y <= my1:
                    if edge_resistance.should_allow_wrap('top', x, y, now):
                        new_y = my2 - 2
                        move_mouse(x, new_y)
                        show_cursor_highlight(x, new_y, edge_color)
                        edge_resistance.clear_edge('top')
                elif y >= my2 - 1:
                    if edge_resistance.should_allow_wrap('bottom', x, y, now):
                        new_y = my1 + 1
                        move_mouse(x, new_y)
                        show_cursor_highlight(x, new_y, edge_color)
                        edge_resistance.clear_edge('bottom')
                else:
                    edge_resistance.clear_edge('top')
                    edge_resistance.clear_edge('bottom')

            # Horizontal wrap (use actual monitor bounds, not X screen dimensions)
            if config['edge_wrap']['horizontal']:
                bounds_min_x, _, bounds_max_x, _ = get_screen_bounds()
                if x <= bounds_min_x:
                    if edge_resistance.should_allow_wrap('left', x, y, now):
                        new_x = bounds_max_x - 2
                        move_mouse(new_x, y)
                        show_cursor_highlight(new_x, y, edge_color)
                        edge_resistance.clear_edge('left')
                elif x >= bounds_max_x - 1:
                    if edge_resistance.should_allow_wrap('right', x, y, now):
                        new_x = bounds_min_x + 1
                        move_mouse(new_x, y)
                        show_cursor_highlight(new_x, y, edge_color)
                        edge_resistance.clear_edge('right')
                else:
                    edge_resistance.clear_edge('left')
                    edge_resistance.clear_edge('right')

        # Update edge resistance tracking (must be at end of loop)
        edge_resistance.update(x, y, now)

        time.sleep(config['general']['poll_interval'])

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
