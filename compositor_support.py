"""Check whether the optional compositor may start without replacing another."""
import shutil
from Xlib import display


def compositor_needed():
    if shutil.which('xcompmgr') is None:
        print('Compositor skipped: install xcompmgr to enable composited cursor effects.', flush=True)
        return False
    connection = display.Display()
    try:
        atom = connection.intern_atom(f'_NET_WM_CM_S{connection.get_default_screen()}')
        if connection.get_selection_owner(atom):
            print('Compositor skipped: this display already has a compositor.', flush=True)
            return False
        return True
    finally:
        connection.close()


if __name__ == '__main__':
    raise SystemExit(0 if compositor_needed() else 1)
