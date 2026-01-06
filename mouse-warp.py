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
    import i3ipc
    HAS_I3IPC = True
except ImportError:
    HAS_I3IPC = False

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
        'poll_interval': 0.02,  # 20ms - balances responsiveness vs CPU usage
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
        'style': 'edge_flash',  # brackets, edge_flash (for edge wrapping)
        'monitor_cross_style': 'brackets',  # brackets, edge_flash (for monitor switches)
        'natural_cross_threshold': 200,  # pixels from edge to count as natural crossing
        'size': 40,
        'thickness': 3,
        'duration': 0.4,
        'monitor_warp_color': 'sky',
        'edge_warp_color': 'peach',
        # Brackets-specific
        'brackets_gap': 8,  # Gap around cursor
        # Edge flash-specific
        'edge_flash_length': 100,
        'edge_flash_thickness': 4,
        'edge_warp_duration': 1.0,  # Duration for edge wrap flash
        'monitor_cross_duration': 0.6,  # Duration for monitor crossing flash
    },
    'theme': {
        'mode': 'auto',
        'cache_ttl': 5.0,
    },
    'focus_warp': {
        'enabled': True,
        'position': 'center',  # center, or ratio like "0.5,0.5"
        'skip_floating': False,  # skip floating windows
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

# Lock for thread-safe X display access (Xlib is not thread-safe)
_display_lock = threading.Lock()

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
# Visual Indicators
# ============================================================================

# Thread-safe lock for indicator operations
_indicator_lock = threading.Lock()

def _create_shaped_window(td, width, height, color):
    """Create an override-redirect window with given dimensions and color."""
    troot = td.screen().root
    tscreen = td.screen()
    window = troot.create_window(
        0, 0, max(1, width), max(1, height), 0,
        tscreen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=color,
        override_redirect=True,
        event_mask=X.ExposureMask
    )

    # Set window type to notification (stacks above docks like i3bar)
    NET_WM_WINDOW_TYPE = td.intern_atom('_NET_WM_WINDOW_TYPE')
    NET_WM_WINDOW_TYPE_NOTIFICATION = td.intern_atom('_NET_WM_WINDOW_TYPE_NOTIFICATION')
    window.change_property(NET_WM_WINDOW_TYPE, td.intern_atom('ATOM'), 32, [NET_WM_WINDOW_TYPE_NOTIFICATION])

    # Also set _NET_WM_STATE_ABOVE for good measure
    NET_WM_STATE = td.intern_atom('_NET_WM_STATE')
    NET_WM_STATE_ABOVE = td.intern_atom('_NET_WM_STATE_ABOVE')
    window.change_property(NET_WM_STATE, td.intern_atom('ATOM'), 32, [NET_WM_STATE_ABOVE])

    return window


def _apply_rect_shape(window, rects):
    """Apply a shape mask from a list of (x, y, w, h) rectangles.

    Uses the X11 shape extension to make only the specified rectangles visible.
    """
    if not rects:
        return

    # Find bounding box
    min_x = min(r[0] for r in rects)
    min_y = min(r[1] for r in rects)
    max_x = max(r[0] + r[2] for r in rects)
    max_y = max(r[1] + r[3] for r in rects)
    pw = max_x - min_x
    ph = max_y - min_y

    if pw <= 0 or ph <= 0:
        return

    pixmap = window.create_pixmap(pw, ph, 1)
    gc = pixmap.create_gc(foreground=0, background=0)
    pixmap.fill_rectangle(gc, 0, 0, pw, ph)
    gc.change(foreground=1)

    for rx, ry, rw, rh in rects:
        if rw > 0 and rh > 0:
            pixmap.fill_rectangle(gc, rx - min_x, ry - min_y, rw, rh)

    window.shape_mask(shape.SO.Set, shape.SK.Bounding, min_x, min_y, pixmap)
    gc.free()
    pixmap.free()


def show_corner_brackets(x, y, color_name='sky'):
    """Show four L-shaped corner brackets around the cursor position.

    Visual: Four corners forming an implied box with a gap around the pointer.
    Behavior: Quick pop-in with slight fade/scale-down over duration.
    """
    if not config['highlight']['enabled']:
        return

    color = get_color(color_name)
    size = config['highlight']['size']
    thickness = config['highlight']['thickness']
    duration = config['highlight']['duration']
    gap = config['highlight']['brackets_gap']

    def animate():
        td = None
        window = None
        try:
            td = display.Display()

            # Bracket arm length (each L has two arms)
            arm_len = size // 3

            # Calculate window bounds (covers all 4 brackets)
            half_size = size // 2
            win_x = x - half_size - gap
            win_y = y - half_size - gap
            win_w = size + 2 * gap
            win_h = size + 2 * gap

            window = _create_shaped_window(td, win_w, win_h, color)

            # Build the 4 L-shaped brackets as rectangles
            # Each bracket is 2 rectangles forming an L
            # Positions relative to window origin

            # Center of window (cursor position)
            cx = half_size + gap
            cy = half_size + gap

            # Inner edge of brackets (gap from cursor)
            inner = gap
            # Outer edge
            outer = half_size + gap

            def make_bracket_rects(scale=1.0):
                """Generate bracket rectangles at given scale."""
                rects = []
                scaled_arm = int(arm_len * scale)
                scaled_thick = max(1, int(thickness * scale))

                # Top-left bracket
                # Horizontal arm: from (inner, inner) going left
                tl_x = cx - int(outer * scale)
                tl_y = cy - int(outer * scale)
                rects.append((tl_x, tl_y, scaled_arm, scaled_thick))  # horizontal
                rects.append((tl_x, tl_y, scaled_thick, scaled_arm))  # vertical

                # Top-right bracket
                tr_x = cx + int((outer - scaled_arm) * scale)
                tr_y = cy - int(outer * scale)
                rects.append((tr_x, tr_y, scaled_arm, scaled_thick))  # horizontal
                rects.append((tr_x + scaled_arm - scaled_thick, tr_y, scaled_thick, scaled_arm))  # vertical

                # Bottom-left bracket
                bl_x = cx - int(outer * scale)
                bl_y = cy + int((outer - scaled_thick) * scale)
                rects.append((bl_x, bl_y, scaled_arm, scaled_thick))  # horizontal
                rects.append((bl_x, bl_y - scaled_arm + scaled_thick, scaled_thick, scaled_arm))  # vertical

                # Bottom-right bracket
                br_x = cx + int((outer - scaled_arm) * scale)
                br_y = cy + int((outer - scaled_thick) * scale)
                rects.append((br_x, br_y, scaled_arm, scaled_thick))  # horizontal
                rects.append((br_x + scaled_arm - scaled_thick, br_y - scaled_arm + scaled_thick, scaled_thick, scaled_arm))  # vertical

                return rects

            # Initial display at full scale
            rects = make_bracket_rects(1.0)
            _apply_rect_shape(window, rects)
            window.configure(x=win_x, y=win_y)
            window.map()
            window.configure(stack_mode=X.Above)
            td.sync()

            # Animate: scale down slightly over duration
            scale_steps = 8
            step_time = duration / scale_steps
            for i in range(scale_steps):
                time.sleep(step_time)
                # Scale from 1.0 down to 0.7
                scale = 1.0 - (0.3 * (i + 1) / scale_steps)
                rects = make_bracket_rects(scale)
                _apply_rect_shape(window, rects)
                td.sync()
        except Exception as e:
            print(f"Brackets error: {e}")
        finally:
            if window:
                try:
                    window.destroy()
                except:
                    pass
            if td:
                try:
                    td.close()
                except:
                    pass

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()


def show_edge_flash(edge, cross_pos, color_name='peach', edge_pos=None, duration=None):
    """Show a bright segment along the screen edge where wrap occurred.

    Args:
        edge: 'left', 'right', 'top', or 'bottom'
        cross_pos: y-coordinate for left/right edges, x-coordinate for top/bottom
        color_name: color from palette
        edge_pos: exact pixel position of the edge (overrides screen bounds)
        duration: optional duration override (defaults to config duration * 0.6)
    """
    if not config['highlight']['enabled']:
        return

    color = get_color(color_name)
    flash_len = config['highlight']['edge_flash_length']
    flash_thick = config['highlight']['edge_flash_thickness']
    if duration is None:
        duration = config['highlight']['duration'] * 0.6  # Shorter for edge flash

    def animate():
        td = None
        window = None
        try:
            td = display.Display()
            tscreen = td.screen()

            # Get screen bounds
            screen_w = tscreen.width_in_pixels
            screen_h = tscreen.height_in_pixels

            # Calculate flash position and dimensions
            if edge == 'left':
                edge_x = edge_pos if edge_pos is not None else 0
                win_x = edge_x
                win_y = max(0, cross_pos - flash_len // 2)
                win_w = flash_thick
                win_h = flash_len
            elif edge == 'right':
                edge_x = edge_pos if edge_pos is not None else screen_w
                win_x = edge_x - flash_thick
                win_y = max(0, cross_pos - flash_len // 2)
                win_w = flash_thick
                win_h = flash_len
            elif edge == 'top':
                edge_y = edge_pos if edge_pos is not None else 0
                win_x = max(0, cross_pos - flash_len // 2)
                win_y = edge_y
                win_w = flash_len
                win_h = flash_thick
            elif edge == 'bottom':
                edge_y = edge_pos if edge_pos is not None else screen_h
                win_x = max(0, cross_pos - flash_len // 2)
                win_y = edge_y - flash_thick
                win_w = flash_len
                win_h = flash_thick
            else:
                return

            # Clamp to screen
            if edge in ('left', 'right'):
                win_h = min(win_h, screen_h - win_y)
            else:
                win_w = min(win_w, screen_w - win_x)

            if win_w <= 0 or win_h <= 0:
                return

            window = _create_shaped_window(td, win_w, win_h, color)

            # Simple rectangle shape (no complex mask needed)
            rects = [(0, 0, win_w, win_h)]
            _apply_rect_shape(window, rects)

            window.configure(x=win_x, y=win_y)
            window.map()
            window.configure(stack_mode=X.Above)
            td.sync()

            # Hold then fade
            time.sleep(duration * 0.4)
            fade_steps = 6
            step_time = (duration * 0.6) / fade_steps
            for _ in range(fade_steps):
                time.sleep(step_time)
        except Exception as e:
            print(f"Edge flash error: {e}")
        finally:
            if window:
                try:
                    window.destroy()
                except:
                    pass
            if td:
                try:
                    td.close()
                except:
                    pass

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()


def show_cursor_highlight(x, y, color_name='sky', from_pos=None, edge=None, edge_pos=None, is_edge_warp=False):
    """Show visual indicator at cursor position.

    Dispatches to the appropriate indicator based on config style.

    Args:
        x, y: Destination cursor position
        color_name: Color from palette
        from_pos: Unused, kept for API compatibility
        edge: Optional edge name ('left', 'right', 'top', 'bottom') for edge flash
        edge_pos: exact pixel position of the edge for edge flash
        is_edge_warp: If True, use longer duration for edge wrap
    """
    if not config['highlight']['enabled']:
        return

    style = config['highlight']['style']

    if style == 'edge_flash' and edge:
        # For edge flash, use cursor position as cross point
        cross_pos = y if edge in ('left', 'right') else x
        duration = config['highlight']['edge_warp_duration'] if is_edge_warp else None
        show_edge_flash(edge, cross_pos, color_name, edge_pos, duration)
    else:
        # Default to brackets
        show_corner_brackets(x, y, color_name)

# ============================================================================
# Focus Warp (i3 IPC)
# ============================================================================

_last_focus_warp_time = 0
_focus_warp_thread = None

def _get_warp_position(container):
    """Calculate cursor position within a container based on config."""
    rect = container.rect
    pos = config['focus_warp']['position']

    if pos == 'center':
        x = rect.x + rect.width // 2
        y = rect.y + rect.height // 2
    else:
        # Parse ratio like "0.5,0.5" or "0.33,0.33"
        try:
            rx, ry = map(float, pos.split(','))
            x = rect.x + int(rect.width * rx)
            y = rect.y + int(rect.height * ry)
        except:
            # Fallback to center
            x = rect.x + rect.width // 2
            y = rect.y + rect.height // 2

    return x, y

def _on_window_focus(i3, event):
    """Handle i3 window focus events."""
    global _last_focus_warp_time

    if not config['focus_warp']['enabled']:
        return

    container = event.container
    if not container:
        return

    # Skip floating windows if configured
    if config['focus_warp']['skip_floating'] and container.floating:
        return

    # Get current mouse position
    try:
        cur_x, cur_y = get_mouse_pos()
    except:
        return

    # Check if mouse is already inside the focused window
    rect = container.rect
    if (rect.x <= cur_x < rect.x + rect.width and
        rect.y <= cur_y < rect.y + rect.height):
        # Mouse already in window - likely clicked to focus, skip warp
        return

    # Calculate target position
    new_x, new_y = _get_warp_position(container)

    # Warp cursor
    move_mouse(new_x, new_y)
    _last_focus_warp_time = time.time()

    # Visual feedback
    if config['highlight']['enabled']:
        color = config['highlight']['monitor_warp_color']
        style = config['highlight']['monitor_cross_style']
        if style == 'brackets':
            show_corner_brackets(new_x, new_y, color)
        else:
            # Determine entry edge based on direction
            if cur_x < new_x:
                show_edge_flash('left', new_y, color, edge_pos=rect.x)
            elif cur_x > new_x:
                show_edge_flash('right', new_y, color, edge_pos=rect.x + rect.width)
            else:
                show_corner_brackets(new_x, new_y, color)

def start_focus_warp_listener():
    """Start i3 IPC listener in a background thread."""
    global _focus_warp_thread

    if not HAS_I3IPC:
        print("Warning: i3ipc not available, focus_warp disabled")
        print("  Install with: pip install i3ipc")
        return

    if not config['focus_warp']['enabled']:
        return

    def run_listener():
        try:
            i3 = i3ipc.Connection()
            i3.on(i3ipc.Event.WINDOW_FOCUS, _on_window_focus)
            print("Focus warp: listening for i3 focus events")
            i3.main()
        except Exception as e:
            print(f"Focus warp error: {e}")

    _focus_warp_thread = threading.Thread(target=run_listener, daemon=True)
    _focus_warp_thread.start()

# ============================================================================
# Input Helpers
# ============================================================================

def query_pointer():
    """Query pointer once and return all info (x, y, shift, ctrl).

    This is more efficient than separate calls - reduces X11 queries from 3 to 1.
    """
    with _display_lock:
        data = root.query_pointer()
        return (
            data.root_x,
            data.root_y,
            bool(data.mask & X.ShiftMask),
            bool(data.mask & X.ControlMask),
        )

def get_mouse_pos():
    """Get mouse position (legacy helper)."""
    x, y, _, _ = query_pointer()
    return x, y

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

def warp_to_monitor(idx, from_x=None, from_y=None):
    """Warp cursor to center of monitor at given index.

    Args:
        idx: Monitor index
        from_x, from_y: Previous cursor position for trail indicator
    """
    global last_warp_time
    if 0 <= idx < len(mon_list):
        mx1, my1, mx2, my2 = mon_list[idx]
        new_x = (mx1 + mx2) // 2
        new_y = (my1 + my2) // 2
        move_mouse(new_x, new_y)

        # Use monitor_cross_style for Shift+move monitor switching
        if config['highlight']['enabled']:
            color = config['highlight']['monitor_warp_color']
            style = config['highlight']['monitor_cross_style']
            if style == 'brackets':
                show_corner_brackets(new_x, new_y, color)
            else:
                # Determine entry edge based on direction
                if from_x is not None and from_x < new_x:
                    show_edge_flash('left', new_y, color, edge_pos=mx1)
                elif from_x is not None and from_x > new_x:
                    show_edge_flash('right', new_y, color, edge_pos=mx2)
                else:
                    show_corner_brackets(new_x, new_y, color)

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
prev_monitor = None

def main():
    global prev_x, prev_y, last_warp_time, prev_shift_pressed, accel_edge_pressure, prev_monitor

    print(f"Mouse warp started. Monitors: {len(mon_list)}, Screen: {SCREEN_W}x{SCREEN_H}")
    print(f"Config: {CONFIG_PATH}")
    print("Send SIGHUP to reload config" + (" (or monitors will auto-refresh)" if HAS_RANDR else ""))

    # Start focus warp listener (i3 IPC)
    start_focus_warp_listener()

    while True:
        # Check for RandR screen change events (non-blocking)
        if HAS_RANDR:
            while d.pending_events():
                event = d.next_event()
                if _randr_event_base and event.type == _randr_event_base:
                    refresh_monitor_geometry()

        x, y, shift_pressed, ctrl_pressed = query_pointer()
        now = time.time()

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
                        warp_to_monitor(cur - 1, x, y)
                        x, y = get_mouse_pos()
                elif delta > threshold:
                    cur = get_monitor_at(x, y)
                    if cur < len(mon_list) - 1:
                        warp_to_monitor(cur + 1, x, y)
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
                        # Flash at entry edge (bottom of screen where we arrive)
                        show_cursor_highlight(x, new_y, edge_color,
                                              from_pos=(x, y), edge='bottom', edge_pos=my2,
                                              is_edge_warp=True)
                        edge_resistance.clear_edge('top')
                elif y >= my2 - 1:
                    if edge_resistance.should_allow_wrap('bottom', x, y, now):
                        new_y = my1 + 1
                        move_mouse(x, new_y)
                        # Flash at entry edge (top of screen where we arrive)
                        show_cursor_highlight(x, new_y, edge_color,
                                              from_pos=(x, y), edge='top', edge_pos=my1,
                                              is_edge_warp=True)
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
                        # Flash at entry edge (right side of screen where we arrive)
                        show_cursor_highlight(new_x, y, edge_color,
                                              from_pos=(x, y), edge='right', edge_pos=bounds_max_x,
                                              is_edge_warp=True)
                        edge_resistance.clear_edge('left')
                        last_warp_time = now
                        prev_monitor = get_monitor_at(new_x, y)
                elif x >= bounds_max_x - 1:
                    if edge_resistance.should_allow_wrap('right', x, y, now):
                        new_x = bounds_min_x + 1
                        move_mouse(new_x, y)
                        # Flash at entry edge (left side of screen where we arrive)
                        show_cursor_highlight(new_x, y, edge_color,
                                              from_pos=(x, y), edge='left', edge_pos=bounds_min_x,
                                              is_edge_warp=True)
                        edge_resistance.clear_edge('right')
                        last_warp_time = now
                        prev_monitor = get_monitor_at(new_x, y)
                else:
                    edge_resistance.clear_edge('left')
                    edge_resistance.clear_edge('right')

        # Detect natural monitor crossing (not from warping)
        # This must be AFTER edge wrapping to avoid double-flash
        cur_mon = get_monitor_at(x, y)
        if prev_monitor is not None and cur_mon != prev_monitor and (now - last_warp_time) > 0.1:
            # Cursor moved to a different monitor
            # Distinguish natural mouse crossing (at edge) from teleport (i3 workspace switch)
            if config['highlight']['enabled']:
                edge_color = config['highlight']['monitor_warp_color']
                new_mx1, new_my1, new_mx2, new_my2 = mon_list[cur_mon]
                old_mx1, old_my1, old_mx2, old_my2 = mon_list[prev_monitor]

                # Check if cursor is near the shared edge (natural crossing)
                # vs. teleported to arbitrary position (i3 workspace switch)
                edge_threshold = config['highlight']['natural_cross_threshold']
                is_natural_crossing = False
                entry_edge = None
                entry_edge_pos = None

                if new_mx1 > old_mx1:  # New monitor is to the RIGHT
                    if x < new_mx1 + edge_threshold:
                        is_natural_crossing = True
                        entry_edge = 'left'
                        entry_edge_pos = new_mx1
                elif new_mx1 < old_mx1:  # New monitor is to the LEFT
                    if x > new_mx2 - edge_threshold:
                        is_natural_crossing = True
                        entry_edge = 'right'
                        entry_edge_pos = new_mx2
                elif new_my1 > old_my1:  # New monitor is BELOW
                    if y < new_my1 + edge_threshold:
                        is_natural_crossing = True
                        entry_edge = 'top'
                        entry_edge_pos = new_my1
                elif new_my1 < old_my1:  # New monitor is ABOVE
                    if y > new_my2 - edge_threshold:
                        is_natural_crossing = True
                        entry_edge = 'bottom'
                        entry_edge_pos = new_my2

                if is_natural_crossing:
                    # Natural mouse crossing at boundary - always use edge_flash
                    cross_duration = config['highlight']['monitor_cross_duration']
                    cross_pos = y if entry_edge in ('left', 'right') else x
                    show_edge_flash(entry_edge, cross_pos, edge_color, edge_pos=entry_edge_pos, duration=cross_duration)
                    last_warp_time = now  # Prevent double-trigger
                else:
                    # Teleport (i3 workspace switch) - use monitor_cross_style
                    style = config['highlight']['monitor_cross_style']
                    if style == 'brackets':
                        show_corner_brackets(x, y, edge_color)
                    else:
                        # Determine direction for edge_flash
                        cross_duration = config['highlight']['monitor_cross_duration']
                        if new_mx1 > old_mx1:
                            show_edge_flash('left', y, edge_color, edge_pos=new_mx1, duration=cross_duration)
                        elif new_mx1 < old_mx1:
                            show_edge_flash('right', y, edge_color, edge_pos=new_mx2, duration=cross_duration)
                        elif new_my1 > old_my1:
                            show_edge_flash('top', x, edge_color, edge_pos=new_my1, duration=cross_duration)
                        elif new_my1 < old_my1:
                            show_edge_flash('bottom', x, edge_color, edge_pos=new_my2, duration=cross_duration)
                    last_warp_time = now  # Prevent double-trigger
        prev_monitor = cur_mon

        # Update edge resistance tracking (must be at end of loop)
        edge_resistance.update(x, y, now)

        time.sleep(config['general']['poll_interval'])

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
