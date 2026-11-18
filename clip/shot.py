"""The screenshot editor: figure.py's editor on a picture, exporting a PNG
beside the clips, with the same sessions, clipboard and keys as the video
editor. P turns the plate (frame, key and caption) on or off."""
import os
import sys

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from . import desktop  # noqa: E402
from . import editor as E  # noqa: E402
from . import figure as F  # noqa: E402

S = F.S


def is_image(path):
    return path.lower().endswith(E.IMAGE_EXTS)


def load_image(path):
    pb = GdkPixbuf.Pixbuf.new_from_file(path).apply_embedded_orientation()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pb.get_width(), pb.get_height())
    cr = cairo.Context(surf)
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
    return surf


class ShotEditor(F.Editor):
    def __init__(self, path, state=None):
        self.path = path
        super().__init__(F.Figure(surface=load_image(path)), None)
        self.set_title(f"Clip — {os.path.basename(path)}")
        self.reopen = None
        self.load_state(state)
        self.out = (state or {}).get("out")
        self.welcome = (f"Picked up where you left off. Enter exports and closes, {desktop.MOD}+S exports "
                        "and keeps working, Esc closes; clip --fresh starts clean." if state else None)

    def keep_session(self):
        try:
            E.save_session(self.path, self.state() | {"out": self.out})
        except OSError as e:
            print(f"clip: couldn't keep this session: {e}", file=sys.stderr)

    def quit(self, ok):
        self.stop_editing()
        if ok:
            return self.save(close=True)
        self.keep_session()
        self.done = False
        Gtk.main_quit()

    def save(self, close=True, as_new=False):
        self.stop_editing()
        if as_new or not self.out or not os.path.isdir(os.path.dirname(self.out)):
            out = E.export_path(self.path, S.clips, "png")
        else:
            out = self.out
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            self.fig.export(out)
        except (OSError, cairo.Error) as e:
            self.flash(f"Export failed: {e}")
            return
        self.out = out
        self.keep_session()
        name = os.path.basename(out)
        copied = S.copy_to_clipboard and desktop.copy_file(out)
        if S.notify:
            desktop.notify("Screenshot exported",
                           f"{name} is in {S.clips}" + (", and on the clipboard" if copied else ""))
        if S.reveal:
            desktop.reveal(out)
        if close:
            self.done = True
            Gtk.main_quit()
            return
        self.flash(f"Exported {name}{' (on the clipboard)' if copied else ''}. {desktop.MOD}+S exports it "
                   f"again, {desktop.MOD}+Shift+S to a new file, Enter exports and closes.")

    def on_key(self, w, ev):
        if ev.state & self.primary and ev.keyval in (Gdk.KEY_o, Gdk.KEY_O) and self.editing is None:
            path = E.choose_video(self, os.path.dirname(self.path))
            if path:
                self.keep_session()
                self.reopen = path
                self.done = False
                Gtk.main_quit()
            return True
        return super().on_key(w, ev)


def edit(path, fresh=False):
    """One screenshot; the next file to open (Ctrl+O), or None."""
    try:
        ed = ShotEditor(path, None if fresh else E.load_session(path))
    except GLib.Error:
        E.error_dialog(f"{os.path.basename(path)} doesn't look like a picture Clip can open.")
        return None
    ed.show_all()
    ed.area.grab_focus()
    if ed.welcome:
        ed.flash(ed.welcome)
    Gtk.main()
    ed.destroy()
    return ed.reopen
