"""What differs between a Mac and Linux: folders, the clipboard,
notifications, showing a file, and the shortcut modifier's name."""
import os
import shutil
import subprocess
import sys

IS_MAC = sys.platform == "darwin"
MOD = "Cmd" if IS_MAC else "Ctrl"


def default_recordings(mac=IS_MAC):
    """Where screen recordings land: on a Mac, the screenshot folder set in
    Screenshot's Options (the Desktop unless changed)."""
    if mac:
        r = subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
                           capture_output=True, text=True)
        where = os.path.expanduser(r.stdout.strip()) if r.returncode == 0 else ""
        return where if where and os.path.isdir(where) else os.path.expanduser("~/Desktop")
    return os.path.expanduser("~/Videos")


def default_clips(mac=IS_MAC):
    return os.path.expanduser("~/Movies/Clips" if mac else "~/Videos/Clips")


def state_dir(mac=IS_MAC):
    if os.environ.get("CLIP_STATE_DIR"):
        return os.environ["CLIP_STATE_DIR"]
    if mac:
        return os.path.expanduser("~/Library/Application Support/Clip")
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "clip")


def applescript(*lines):
    """osascript running lines, with the file path as argv (never pasted
    into the script, so any name is safe)."""
    args = ["osascript", "-e", "on run argv"]
    for line in lines:
        args += ["-e", line]
    return args + ["-e", "end run"]


def copy_commands(path, mac=IS_MAC, env=None, have=shutil.which):
    """(argv, stdin bytes) that put the file on the clipboard, or None: a PNG
    as the picture itself (it pastes into chat and documents), anything
    else as the file."""
    env = os.environ if env is None else env
    if path.lower().endswith(".png"):
        if mac:
            return applescript("set the clipboard to (read (POSIX file (item 1 of argv)) as \u00abclass PNGf\u00bb)") \
                + [path], None
        with open(path, "rb") as f:
            png = f.read()
        if env.get("WAYLAND_DISPLAY") and have("wl-copy"):
            return ["wl-copy", "--type", "image/png"], png
        if have("xclip"):
            return ["xclip", "-selection", "clipboard", "-t", "image/png"], png
        return None
    if mac:
        return applescript("set the clipboard to (POSIX file (item 1 of argv))") + [path], None
    from urllib.parse import quote
    uri = ("file://" + quote(path) + "\n").encode()
    if env.get("WAYLAND_DISPLAY") and have("wl-copy"):
        return ["wl-copy", "--type", "text/uri-list"], uri
    if have("xclip"):
        return ["xclip", "-selection", "clipboard", "-t", "text/uri-list"], uri
    return None


def notify_command(title, body, mac=IS_MAC, have=shutil.which):
    if mac:
        return applescript("display notification (item 2 of argv) with title (item 1 of argv)") + [title, body]
    if have("notify-send"):
        return ["notify-send", "-a", "Clip", "-i", "video-x-generic", title, body]
    return None


def reveal_command(path, mac=IS_MAC, have=shutil.which):
    if mac:
        return ["open", "-R", path]
    if have("xdg-open"):
        return ["xdg-open", os.path.dirname(path)]
    return None


def open_command(path, mac=IS_MAC, have=shutil.which):
    if mac:
        return ["open", "-t", path]
    if have("xdg-open"):
        return ["xdg-open", path]
    return None


def run(argv, stdin=None, wait=True):
    if not argv:
        return False
    try:
        if wait:
            return subprocess.run(argv, input=stdin, capture_output=True).returncode == 0
        p = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if stdin:
            p.stdin.write(stdin)
            p.stdin.close()
        return True
    except OSError:
        return False


def copy_file(path):
    cmd = copy_commands(path)
    if not cmd:
        return False
    argv, data = cmd
    return run(argv, data)


def notify(title, body):
    return run(notify_command(title, body))


def reveal(path):
    return run(reveal_command(path), wait=False)


def open_file(path):
    return run(open_command(path), wait=False)
