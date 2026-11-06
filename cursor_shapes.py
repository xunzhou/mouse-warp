"""Named X11 cursors and resolution-independent locator geometry."""
import struct
from types import SimpleNamespace


def cursor_kind(name):
    name = name.lower().replace('_', '-')
    groups = {
        'text': ('text', 'xterm', 'ibeam'),
        'vertical-text': ('vertical-text',),
        'ew-resize': ('ew-resize', 'e-resize', 'w-resize', 'col-resize',
                      'sb-h-double-arrow', 'h-double-arrow', 'left-side', 'right-side'),
        'ns-resize': ('ns-resize', 'n-resize', 's-resize', 'row-resize',
                      'sb-v-double-arrow', 'v-double-arrow', 'top-side', 'bottom-side'),
        'nwse-resize': ('nwse-resize', 'nw-resize', 'se-resize', 'bd-double-arrow',
                        'top-left-corner', 'bottom-right-corner'),
        'nesw-resize': ('nesw-resize', 'ne-resize', 'sw-resize', 'fd-double-arrow',
                        'top-right-corner', 'bottom-left-corner'),
    }
    return next((kind for kind, aliases in groups.items() if name in aliases), 'arrow')


def geometry(kind):
    """Return canvas, hotspot, and filled polygon in logical pixels."""
    if kind == 'arrow':
        return (26, 34), (3, 2), [(3, 2), (3, 26), (9, 20), (14, 30),
                                  (19, 27.5), (14, 17.5), (23, 17.5)]
    if kind in ('text', 'vertical-text'):
        points = [(10, 3), (22, 3), (22, 6), (18, 6), (18, 26), (22, 26),
                  (22, 29), (10, 29), (10, 26), (14, 26), (14, 6), (10, 6)]
        if kind == 'vertical-text':
            points = [(y, x) for x, y in points]
    else:
        points = [(3, 16), (10, 9), (10, 13), (22, 13), (22, 9), (29, 16),
                  (22, 23), (22, 19), (10, 19), (10, 23)]
        if kind == 'ns-resize':
            points = [(y, x) for x, y in points]
        elif kind in ('nwse-resize', 'nesw-resize'):
            import math
            angle = math.pi / 4 if kind == 'nwse-resize' else -math.pi / 4
            c, s = math.cos(angle), math.sin(angle)
            points = [(16 + (x-16)*c - (y-16)*s, 16 + (x-16)*s + (y-16)*c)
                      for x, y in points]
    return (32, 32), (16, 16), points


def capture_cursor(display):
    """Read the current image/name, or None when X11 denies cursor access."""
    from Xlib.protocol import rq
    from Xlib.error import BadAccess, BadCursor

    class ImageAndName(rq.ReplyRequest):
        _request = rq.Struct(rq.Card8('opcode'), rq.Opcode(25), rq.RequestLength())
        _reply = rq.Struct(rq.ReplyCode(), rq.Pad(1), rq.Card16('sequence_number'),
                           rq.ReplyLength(), rq.Int16('x'), rq.Int16('y'),
                           rq.Card16('width'), rq.Card16('height'),
                           rq.Card16('xhot'), rq.Card16('yhot'),
                           rq.Card32('cursor_serial'), rq.Card32('name_atom'),
                           rq.Card16('name_length'), rq.Pad(2), rq.Binary('payload'))

    try:
        reply = ImageAndName(display=display.display,
                            opcode=display.display.get_extension_major('XFIXES'))
    except (BadAccess, BadCursor):
        # A displayed cursor may outlive its creating client's resource, notably
        # after xsetroot/XFixes replacement. Image access is not guaranteed.
        return None
    count = reply.width * reply.height
    pixels = struct.unpack_from(f'={count}I', reply.payload)
    name = reply.payload[count * 4:count * 4 + reply.name_length].decode('utf-8', 'replace')
    return SimpleNamespace(width=reply.width, height=reply.height, xhot=reply.xhot,
                           yhot=reply.yhot, cursor_serial=reply.cursor_serial,
                           cursor_image=pixels, name=name)


def subscribe_cursor_names(display, root):
    """Decode the XFixes v2 name atom omitted by python-xlib's event class."""
    from Xlib.protocol import rq
    from Xlib.ext import xfixes

    class NamedCursorNotify(rq.Event):
        _fields = rq.Struct(rq.Card8('type'), rq.Card8('sub_code'),
                            rq.Card16('sequence_number'), rq.Window('window'),
                            rq.Card32('cursor_serial'), rq.Card32('timestamp'),
                            rq.Card32('cursor_name'), rq.Pad(12))

    info = display.query_extension('XFIXES')
    display.extension_add_subevent(info.first_event + xfixes.XFixesCursorNotify,
                                  xfixes.XFixesDisplayCursorNotify, NamedCursorNotify)
    display.xfixes_select_cursor_input(root, xfixes.XFixesDisplayCursorNotifyMask)


def latest_cursor_name(display, on_event=None):
    """Coalesce queued notifications; None means no cursor event was received."""
    from Xlib.error import BadAtom
    atom = None
    while display.pending_events():
        event = display.next_event()
        if on_event is not None:
            on_event(event)
        if hasattr(event, 'cursor_name'):
            atom = event.cursor_name
    if atom is None:
        return None
    if not atom:
        return 'left_ptr'
    try:
        return display.get_atom_name(atom)
    except BadAtom:
        return 'left_ptr'


def cursor_style(resources):
    """Read the X resources published by Catppuccin's cursor hook.

    Return nominal size and vector fill color. Unknown themes retain the
    high-contrast black/white default; explicit sizes are bounded for rendering.
    """
    if isinstance(resources, bytes):
        resources = resources.decode('utf-8', 'replace')
    values = {}
    for line in resources.splitlines():
        key, separator, value = line.partition(':')
        if separator:
            values[key.strip().lower()] = value.strip()
    try:
        size = int(values.get('xcursor.size', '24'))
    except ValueError:
        size = 24
    if not 8 <= size <= 128:
        size = 24
    theme = values.get('xcursor.theme', '')
    return size, 0xffffff if theme == 'capitaine-cursors-light' else 0


def latest_cursor_kind(display, on_event=None):
    name = latest_cursor_name(display, on_event)
    return None if name is None else cursor_kind(name)


def cursor_theme(resources):
    if isinstance(resources, bytes):
        resources = resources.decode('utf-8', 'replace')
    for line in resources.splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip().lower() == 'xcursor.theme':
            return value.strip() or 'default'
    return 'default'
