"""Shake detection and a compositor-independent X11 cursor magnifier."""
from collections import deque
import math
import re

from cursor_shapes import (capture_cursor, cursor_kind, geometry,
                           subscribe_cursor_names, latest_cursor_name, cursor_style, cursor_theme)

DEFAULTS = dict(enabled=True, window=0.5, reversals=4, min_stroke=36,
                min_distance=240, max_jump=500, scale=5.0, hold=0.7,
                grow=0.12, growth_time=1.2, shrink=0.25, blink=True, appearance='theme')


class ShakeDetector:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.moving = False
        self.last_reversal = None
        self.turns = [deque(), deque()]
        self.direction = [0, 0]
        self.stroke = [0.0, 0.0]

    def update(self, x, y, now, options):
        previous = self.previous
        self.previous = (x, y, now)
        if previous is None:
            return False
        dx, dy = x - previous[0], y - previous[1]
        self.moving = bool(dx or dy)
        if now - previous[2] > options['window'] or math.hypot(dx, dy) > options['max_jump']:
            self.reset()
            self.previous = (x, y, now)
            return False
        for axis, delta in enumerate((dx, dy)):
            turns = self.turns[axis]
            while turns and now - turns[0][0] > options['window']:
                turns.popleft()
            if delta == 0:
                continue
            # Accumulate signed displacement: small opposite jitter does not
            # count as a reversal until it travels a complete minimum stroke.
            self.stroke[axis] += delta
            if abs(self.stroke[axis]) < options['min_stroke']:
                continue
            direction = 1 if self.stroke[axis] > 0 else -1
            if direction != self.direction[axis]:
                if self.direction[axis]:
                    self.last_reversal = now
                turns.append((now, abs(self.stroke[axis])))
                self.direction[axis] = direction
            elif turns:
                stamp, distance = turns[-1]
                turns[-1] = (stamp, distance + abs(self.stroke[axis]))
            self.stroke[axis] = 0
            if (len(turns) >= options['reversals'] + 1 and
                    # A fast sweep cannot pay for several tiny corrections.
                    sum(min(distance, 2 * options['min_stroke'])
                        for _, distance in turns) >= options['min_distance']):
                self.reset()
                self.previous = (x, y, now)
                self.last_reversal = now
                self.moving = True
                return True
        return False


    def is_shaking(self, now):
        return (self.moving and self.last_reversal is not None
                and now - self.last_reversal <= 0.18)


class ShakeGrowth:
    """Accumulate only active shake time; hold still on pauses, then recede."""
    def __init__(self, now):
        self.last_time = self.last_motion = now
        self.progress = self.hold_progress = 0.0
        self.peak_at = None

    def step(self, now, shaking, options, moving=False):
        dt = max(0.0, now - self.last_time)
        self.last_time = now
        if shaking:
            # Bound a delayed poll: blocked work is not evidence of shaking.
            self.progress = min(1.0, self.progress + min(dt, 0.1) / options['growth_time'])
            self.hold_progress = self.progress
            self.last_motion = now
            if self.progress >= 1 and self.peak_at is None:
                self.peak_at = now
        elif moving:
            # Once found, ordinary motion holds the current size without
            # adding growth. Only a resting pointer starts the release timer.
            self.hold_progress = self.progress
            self.last_motion = now
        else:
            elapsed = now - self.last_motion - options['hold']
            if elapsed >= options['shrink']:
                return None
            if elapsed > 0:
                t = elapsed / options['shrink']
                self.progress = self.hold_progress * (1 - t*t*(3-2*t))
        t = self.progress
        return 1 + (options['scale'] - 1) * t*t*(3-2*t)


def animation_scale(now, started, last_shake, options):
    maximum = options['scale']
    if now < last_shake + options['hold']:
        fraction = min(1.0, (now - started) / options['grow'])
    else:
        fraction = max(0.0, 1 - (now - last_shake - options['hold']) / options['shrink'])
    smooth = fraction * fraction * (3 - 2 * fraction)
    return 1 + (maximum - 1) * smooth


def blink_color(now, started, last_shake, options):
    """Two full-cursor black/white pulses, once per activation, at peak size."""
    elapsed = now - started - options['grow']
    if (not options['blink'] or elapsed < 0 or elapsed >= 0.56
            or now >= last_shake + options['hold']):
        return None
    return 0x000000 if int(elapsed / 0.14) % 2 == 0 else 0xffffff


def arrival_scale(now, started, maximum=2.4, duration=0.7):
    """A restrained arrival cue: ease up, briefly hold, then ease down."""
    t = max(0, (now - started) / duration)
    if t >= 1:
        return None
    if t < 0.2:
        v = t / 0.2
    elif t < 0.45:
        v = 1
    else:
        v = (1 - t) / 0.55
    return 1 + (maximum - 1) * v*v*(3-2*v)


def frame_delay(interval, active, moved, elapsed):
    """Idle at configured cadence, sample movement at 50Hz, animate at 60Hz."""
    target = min(interval, 1/60 if active else .02) if active or moved else interval
    return max(0, target - elapsed)


class CursorMagnifier:
    """Own connection: disconnect also restores XFixes cursor visibility."""
    def __init__(self):
        from Xlib import X, display
        from Xlib.ext import shape
        self.X, self.shape = X, shape
        self.display = display.Display()
        self.root = self.display.screen().root
        self.window = None
        self.hidden = False
        self.frames = {}
        self.cursor_kind = 'arrow'
        self.cursor_name = 'left_ptr'
        self.cursor_theme = 'default'
        self.cursor_size, self.base_fill = 24, 0
        self.started = self.last_shake = None
        self.arrival = None
        self._pulse_only = False
        self._displayed_scale = 1.0
        self._handoff_scale = None
        self._canvas_size = 0
        self._last_presentation = None
        try:
            if not self.display.has_extension('XFIXES') or not self.display.has_extension('SHAPE'):
                raise RuntimeError('XFIXES and SHAPE extensions are required')
            if self.display.xfixes_query_version().major_version < 4:
                raise RuntimeError('XFIXES 4 or newer is required')
            version = self.display.shape_query_version()
            if (version.major_version, version.minor_version) < (1, 1):
                raise RuntimeError('SHAPE 1.1 or newer is required')
            screen = self.display.screen()
            if screen.root_depth != 24:
                raise RuntimeError('cursor magnification currently requires a 24-bit X11 visual')
            visual = next(v for depth in screen.allowed_depths for v in depth.visuals
                          if v.visual_id == screen.root_visual)
            if (visual.red_mask, visual.green_mask, visual.blue_mask) != (0xff0000, 0xff00, 0xff):
                raise RuntimeError('unsupported X11 color masks')
            self.window = self.root.create_window(0, 0, 1, 1, 0, screen.root_depth,
                X.InputOutput, X.CopyFromParent, override_redirect=True,
                background_pixel=0)
            self.resource_atom = self.display.intern_atom('RESOURCE_MANAGER')
            self.root.change_attributes(event_mask=X.PropertyChangeMask)
            self._read_cursor_style()
            subscribe_cursor_names(self.display, self.root)
            self.window.set_wm_name('mouse-warp shake cursor')
            self.window.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])
        except Exception:
            self.close()
            raise

    def _read_cursor_style(self):
        prop = self.root.get_full_property(self.resource_atom, self.display.intern_atom('STRING'))
        resources = prop.value if prop is not None else b''
        style = cursor_style(resources)
        theme = cursor_theme(resources)
        if style != (self.cursor_size, self.base_fill) or theme != self.cursor_theme:
            self._free_frames()
            self.cursor_size, self.base_fill = style
            self.cursor_theme = theme

    def _style_event(self, event):
        if event.type == self.X.PropertyNotify and event.atom == self.resource_atom:
            self._read_cursor_style()

    def trigger(self, now):
        if self.started is not None and self._pulse_only:
            # Hand an arrival over to a real shake at its visible size.
            self._handoff_scale = self._displayed_scale
            self.arrival = None
            self.growth = ShakeGrowth(now)
        self._pulse_only = False
        if self.started is None:
            name = latest_cursor_name(self.display, self._style_event)
            if name is not None:
                self.cursor_name = name
                self.cursor_kind = cursor_kind(name)
            self.source = capture_cursor(self.display)
            if self.source is not None:
                self.cursor_name = self.source.name or 'left_ptr'
                self.cursor_kind = cursor_kind(self.cursor_name)
                if not self.source.width or not self.source.height:
                    self.source = None
            if self.source is not None and max(self.source.width, self.source.height) > 256:
                raise RuntimeError("cursor image exceeds the supported 256-pixel size")
            self.started = now
            self.growth = ShakeGrowth(now)
        self.last_shake = now

    def pulse(self, now, maximum=2.4, duration=0.7):
        """An active effect already locates the pointer; never restart it."""
        if self.started is not None:
            return
        self.trigger(now)
        self._pulse_only = True
        self.arrival = (now, maximum, duration)

    def _frame(self, scale, outline=None):
        """Cache nearest-neighbor scaled cursor frames, with binary alpha.

        Shape masks work without a compositor. Alpha < 128 is transparent;
        retained premultiplied colors are unpremultiplied before painting.
        """
        key = (scale, outline)
        if key in self.frames:
            return self.frames[key]
        source, X = self.source, self.X
        padding = 3 if outline is not None else 0
        width = round(source.width * scale) + 2 * padding
        height = round(source.height * scale) + 2 * padding
        pixmap = self.root.create_pixmap(width, height, 24)
        gc = pixmap.create_gc(foreground=0)
        pixmap.fill_rectangle(gc, 0, 0, width, height)
        rectangles = []
        colored_rectangles = []
        try:
            for y in range(source.height):
                x = 0
                while x < source.width:
                    pixel = source.cursor_image[y * source.width + x]
                    end = x + 1
                    while end < source.width and source.cursor_image[y * source.width + end] == pixel:
                        end += 1
                    alpha = pixel >> 24
                    if alpha >= 128:
                        color = sum(min(255, ((pixel >> shift) & 255) * 255 // alpha) << shift
                                    for shift in (0, 8, 16))
                        if outline == 0xffffff:
                            color ^= 0xffffff
                        rect = (round(x * scale) + padding, round(y * scale) + padding,
                                round(end * scale) - round(x * scale),
                                round((y + 1) * scale) - round(y * scale))
                        colored_rectangles.append((color, rect))
                    x = end
            if outline is not None:
                gc.change(foreground=outline)
                for _, (x, y, w, h) in colored_rectangles:
                    rect = (x - padding, y - padding, w + 2 * padding, h + 2 * padding)
                    pixmap.fill_rectangle(gc, *rect)
                    rectangles.append(rect)
            # Paint original or color-inverted pixels over the expanded silhouette;
            # padding keeps the outline clear of clipping.
            for color, rect in colored_rectangles:
                gc.change(foreground=color)
                pixmap.fill_rectangle(gc, *rect)
                if outline is None:
                    rectangles.append(rect)
        except Exception:
            pixmap.free()
            raise
        finally:
            gc.free()
        self.frames[key] = (pixmap, width, height, rectangles,
                            round(source.xhot * scale) + padding,
                            round(source.yhot * scale) + padding)
        return self.frames[key]

    def _vector_frame(self, scale, outline):
        """Rasterize vector geometry at the target size, never upscale pixels.

        The same polygon/stroke generates both the color image and the bounding
        mask. Fill and outline invert together for high contrast. X11 draws
        these shapes without an extra dependency.
        """
        key = ('vector', self.cursor_kind, scale, outline, self.base_fill)
        if key in self.frames:
            return self.frames[key]
        X = self.X
        stroke = max(2, round(scale * 0.7))
        outer_stroke = stroke + 2
        padding = math.ceil(outer_stroke / 2) + 1
        canvas, hotspot, polygon = geometry(self.cursor_kind)
        width = round(canvas[0] * scale) + 2 * padding
        height = round(canvas[1] * scale) + 2 * padding
        points = [(round(x * scale) + padding, round(y * scale) + padding)
                  for x, y in polygon]
        fill = self.base_fill ^ (0xffffff if outline == 0xffffff else 0)
        border = fill ^ 0xffffff
        pixmap = self.root.create_pixmap(width, height, 24)
        mask = self.root.create_pixmap(width, height, 1)
        gc = pixmap.create_gc(foreground=0, join_style=X.JoinRound,
                              cap_style=X.CapRound)
        mask_gc = mask.create_gc(foreground=0, line_width=outer_stroke,
                                join_style=X.JoinRound, cap_style=X.CapRound)
        try:
            pixmap.fill_rectangle(gc, 0, 0, width, height)
            mask.fill_rectangle(mask_gc, 0, 0, width, height)
            mask_gc.change(foreground=1)
            mask.fill_poly(mask_gc, X.Complex, X.CoordModeOrigin, points)
            mask.poly_line(mask_gc, X.CoordModeOrigin, points + [points[0]])
            gc.change(foreground=fill)
            pixmap.fill_poly(gc, X.Complex, X.CoordModeOrigin, points)
            gc.change(foreground=fill, line_width=outer_stroke)
            pixmap.poly_line(gc, X.CoordModeOrigin, points + [points[0]])
            gc.change(foreground=border, line_width=stroke)
            pixmap.poly_line(gc, X.CoordModeOrigin, points + [points[0]])
        except Exception:
            mask.free()
            pixmap.free()
            raise
        finally:
            gc.free()
            mask_gc.free()
        # All frames carry their own hotspot; changing renderers cannot offset
        # the pointer, including when configuration is reloaded mid-animation.
        self.frames[key] = (pixmap, width, height, mask,
                            round(hotspot[0] * scale) + padding, round(hotspot[1] * scale) + padding)
        return self.frames[key]

    def _theme_frame(self, scale, outline, elapsed):
        from theme_cursor import render_artwork
        # Retain subpixel scale; rounding both scale and nominal size made
        # early growth alternate between identical frames and visible jumps.
        nominal = max(1, round(self.cursor_size * scale * 8) / 8)
        image, xhot, yhot, index = render_artwork(
            self.cursor_theme, self.cursor_name, nominal, elapsed, outline == 0xffffff)
        key = ('theme', self.cursor_theme, self.cursor_name, nominal, outline, index)
        if key in self.frames:
            return self.frames[key]
        # Bound animation caches (animated wait cursors can have many frames).
        if len(self.frames) >= 32:
            self._free_frames()
        width, height = image.size
        # Pillow converts channels in C; avoid allocating one Python tuple
        # and integer for every pixel on every animation frame.
        server_little = self.display.display.info.image_byte_order == self.X.LSBFirst
        data = image.convert('RGB').tobytes('raw', 'BGRX' if server_little else 'XRGB')
        alpha = image.getchannel('A').tobytes()
        pixmap = self.root.create_pixmap(width, height, 24)
        gc = pixmap.create_gc()
        rectangles = []
        try:
            # Keep each PutImage below the X11 request size limit.
            rows = max(1, 60000 // (width * 4))
            for y in range(0, height, rows):
                count = min(rows, height - y)
                pixmap.put_image(gc, 0, y, width, count, self.X.ZPixmap, 24, 0,
                                 data[y*width*4:(y+count)*width*4])
            for y in range(height):
                for run in re.finditer(rb'[\x80-\xff]+', alpha[y*width:(y+1)*width]):
                    rectangles.append((run.start(), y, run.end()-run.start(), 1))
        except Exception:
            pixmap.free()
            raise
        finally:
            gc.free()
        self.frames[key] = (pixmap, width, height, rectangles, xhot, yhot)
        return self.frames[key]

    def update(self, x, y, now, options, shaking=None, moving=False):
        # Drain notifications even when idle so cursor changes cannot queue up.
        name = latest_cursor_name(self.display, self._style_event)
        if name is not None and name != self.cursor_name:
            self.cursor_name = name
            self.cursor_kind = cursor_kind(name)
            if options['appearance'] != 'captured':
                self._free_frames()
        if self.started is None:
            return
        pulse = arrival_scale(now, *self.arrival) if self.arrival else None
        had_pulse = self.arrival is not None
        if pulse is None:
            self.arrival = None
        if pulse is None and (not options['enabled'] or
                (shaking is None and now >= self.last_shake + options['hold'] + options['shrink']) or
                (had_pulse and self._pulse_only and self.growth.progress == 0)):
            self.hide()
            return
        if options['appearance'] == 'captured' and self.source is None:
            self.hide()
            return
        if self._handoff_scale is not None:
            target = min(1.0, max(0.0, (self._handoff_scale - 1) /
                                      max(0.001, options['scale'] - 1)))
            low, high = 0.0, 1.0
            for _ in range(24):
                mid = (low + high) / 2
                if mid*mid*(3 - 2*mid) < target:
                    low = mid
                else:
                    high = mid
            self.growth.progress = self.growth.hold_progress = (low + high) / 2
            self._handoff_scale = None
        if self._pulse_only:
            scale, outline = 1, None
        elif shaking is None:
            # Preserve timed activation for callers that don't supply motion.
            scale = animation_scale(now, self.started, self.last_shake, options)
            outline = blink_color(now, self.started, self.last_shake, options)
        else:
            scale = self.growth.step(now, shaking, options, moving=moving)
            if scale is None:
                if pulse is None:
                    self.hide()
                    return
                scale = 1
            outline = None if self.growth.peak_at is None else blink_color(
                now, self.growth.peak_at, self.growth.last_motion, dict(options, grow=0))
        if pulse is not None and (pulse >= scale or not options['enabled']):
            scale, outline = pulse, None
        self._displayed_scale = scale
        if options['appearance'] != 'theme':
            scale = round(scale * 32) / 32
        if options['appearance'] == 'vector':
            # Geometry uses a nominal 32px design grid; match Xcursor.size.
            scale *= self.cursor_size / 32
        if options['appearance'] == 'theme':
            frame = self._theme_frame(scale, outline, now - self.started)
        else:
            render = self._vector_frame if options['appearance'] == 'vector' else self._frame
            frame = render(scale, outline)
        pixmap, width, height, mask, xhot, yhot = frame
        # Install the next artwork and transparency before resizing: X11
        # repaints exposed areas during ConfigureWindow using the background.
        # Resizing first briefly paints the previous frame at the new size.
        # At a held size only the position changes; avoid redundant shape,
        # background and expose requests on every frame.
        if self._last_presentation != pixmap.id:
            self.window.change_attributes(background_pixmap=pixmap)
            if isinstance(mask, list):
                self.window.shape_rectangles(self.shape.SO.Set, self.shape.SK.Bounding,
                                             self.X.Unsorted, 0, 0, mask)
            else:
                self.window.shape_mask(self.shape.SO.Set, self.shape.SK.Bounding, 0, 0, mask)
        if options['appearance'] == 'theme':
            # Keep the X window stationary in size throughout the animation.
            # Only its explicit bounding shape is visible; the unused canvas
            # has neither paint nor input coverage. Repeated window resizes
            # cause transient rectangular damage on accelerated app surfaces.
            self._canvas_size = max(self._canvas_size, self.cursor_size * 12 + 16,
                                    width, height)
            window_width = window_height = self._canvas_size
        else:
            window_width, window_height = width, height
        self.window.configure(x=x - xhot,
                              y=y - yhot,
                              width=window_width, height=window_height,
                              stack_mode=self.X.Above)
        if self._last_presentation != pixmap.id:
            self.window.clear_area()
            self._last_presentation = pixmap.id
        if not self.hidden:
            self.window.map()
        # Establish the visible replacement before hiding the real pointer.
        self.display.sync()
        if not self.hidden:
            self.root.xfixes_hide_cursor()
            self.hidden = True
        self.display.flush()

    def hide(self):
        if self.hidden:
            self.root.xfixes_show_cursor()
            self.hidden = False
        if self.window:
            self.window.unmap()
        self._free_frames()
        self.arrival = None
        self._handoff_scale = None
        self._displayed_scale = 1.0
        self._canvas_size = 0
        self.started = None
        self.display.sync()

    def _free_frames(self):
        self._last_presentation = None
        for pixmap, _, _, mask, *_ in self.frames.values():
            pixmap.free()
            if not isinstance(mask, list):
                mask.free()
        self.frames.clear()

    def close(self):
        try:
            self.hide()
            if self.window:
                self.window.destroy()
        finally:
            self.display.close()


def preview():
    """Standalone shake-only preview; does not start any warp features."""
    import signal
    import time
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    magnifier = CursorMagnifier()
    detector = ShakeDetector()
    print('Shake quickly back and forth to enlarge the cursor. Ctrl+C exits.', flush=True)
    try:
        while True:
            frame_started = time.monotonic()
            pointer = magnifier.root.query_pointer()
            now = time.monotonic()
            if detector.update(pointer.root_x, pointer.root_y, now, DEFAULTS):
                magnifier.trigger(now)
            magnifier.update(pointer.root_x, pointer.root_y, now, DEFAULTS,
                             shaking=detector.is_shaking(now), moving=detector.moving)
            time.sleep(frame_delay(.02, magnifier.started is not None, detector.moving,
                                   time.monotonic() - frame_started))
    except KeyboardInterrupt:
        pass
    finally:
        magnifier.close()


if __name__ == '__main__':
    preview()
