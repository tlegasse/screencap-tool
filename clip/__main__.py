import argparse
import os
import shutil
import sys

from . import __version__, style

HERE = os.path.dirname(os.path.realpath(__file__))
EXAMPLE = os.path.join(HERE, "config.example.toml")


def check():
    """What clip needs, found or not; exit 0 when it can run."""
    ok = True

    def line(good, what, detail):
        nonlocal ok
        ok = ok and good is not False
        mark = {True: "ok  ", False: "MISS", None: "--  "}[good]
        print(f"  {mark} {what:<12} {detail}")

    print(f"clip {__version__}, Python {sys.version.split()[0]} ({sys.executable})")
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        import cairo
        line(True, "GTK", f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, "
                          f"PyGObject {gi.__version__}, pycairo {cairo.version}")
    except (ImportError, ValueError) as e:
        line(False, "GTK", f"PyGObject / GTK 3 / pycairo not importable: {e}")
    for tool in ("ffmpeg", "ffprobe"):
        line(bool(shutil.which(tool)), tool, shutil.which(tool) or "not found")
    line(True if shutil.which("ffplay") else None, "ffplay", shutil.which("ffplay") or
         "not found (the preview plays without sound)")
    path = style.config_path()
    line(None if not os.path.exists(path) else True, "config", path if os.path.exists(path) else
         f"{path} (none: the defaults; clip --edit-config makes one)")
    try:
        s = style.load()
        line(True, "fonts", f"sans: {s.sans}, serif: {s.serif}")
        line(True, "clips", f"exports go to {s.clips}")
        line(True, "recordings", f"the file picker opens in {s.recordings}")
    except style.ConfigError as e:
        line(False, "config", str(e))
    except (ImportError, ValueError):
        pass
    return 0 if ok else 1


def edit_config():
    path = style.config_path()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(EXAMPLE, path)
        print(f"clip: wrote {path}")
    from . import desktop
    if not desktop.open_file(path):
        print(path)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="clip", description="Annotate a screen recording, textbook style, and export it.",
        epilog="Keys and everything else: clip --keys")
    p.add_argument("video", nargs="?", help="the recording to open (default: pick one)")
    p.add_argument("--latest", action="store_true", help="open the newest video in the recordings folder")
    p.add_argument("--fresh", action="store_true", help="start clean, ignoring the marks kept from last time")
    p.add_argument("--keys", action="store_true", help="list the keys and what export does")
    p.add_argument("--check", action="store_true", help="check that everything clip needs is installed")
    p.add_argument("--edit-config", action="store_true", help="create the config file if needed and open it")
    p.add_argument("--version", action="version", version=f"clip {__version__}")
    a = p.parse_args(argv)

    if a.check:
        return check()
    if a.edit_config:
        return edit_config()
    try:
        style.current()
        from . import editor
    except style.ConfigError as e:
        return fail(f"There's a problem in the config file:\n{e}")
    if a.keys:
        print(editor.__doc__)
        return 0
    path = a.video
    if a.latest:
        path = editor.newest_video(style.current().recordings)
        if not path:
            return fail(f"No videos in {style.current().recordings}.")
    if path and not os.path.isfile(path):
        return fail(f"{path}: no such file.")
    return editor.run([path] if path else [], fresh=a.fresh)


def fail(text):
    print(f"clip: {text}", file=sys.stderr)
    if not sys.stderr.isatty():
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            d = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text="Clip")
            d.format_secondary_text(text)
            d.run()
            d.destroy()
        except Exception:                                # noqa: BLE001
            pass
    return 2


if __name__ == "__main__":
    sys.exit(main())
