"""The feature battery: two annotated videos made through the real editor
window, one per config, then checked with ffprobe and pixel samples.

    python3 tests/battery.py [OUT]      (default: battery-output/ in the Clip folder)

Needs a display. Leaves the videos, their configs and a contact sheet of
frames per video in OUT."""
import json
import os
import shutil
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, SRC_LEN = 1280, 720, 14.0
T_IN, T_OUT = 1.0, 13.0
CHAPTERS = [(1.0, "Overview"), (5.0, "Details"), (9.0, "Privacy")]

CONFIGS = {
    "A-textbook": {
        "toml": "",
        "card_bg": "#fbf9f4",
        "banner_bg": None,
        "box": "#b8352c",
        "fonts": [["Fira Sans", "Helvetica Neue"], ["C059", "Charter"]],
        "format": "mp4",
    },
    "B-dark": {
        "toml": """
[colors]
palette = { teal = "#0f766e", magenta = "#c026d3", orange = "#ea580c", slate = "#334155" }
highlight = "#a3e635"

[cards]
background = "#0f172a"
text = "#f8fafc"
heading = "#fbbf24"
rule = "#fbbf24"
times = "#94a3b8"

[chapter_titles]
background = "#0f172a"
text = "#f8fafc"
stripe = "#fbbf24"

[fonts]
sans = ["Noto Sans", "DejaVu Sans", "Helvetica Neue"]
serif = ["DejaVu Serif", "Georgia"]
""",
        "card_bg": "#0f172a",
        "banner_bg": "#0f172a",
        "box": "#c026d3",
        "fonts": [["Noto Sans", "DejaVu Sans", "Helvetica Neue"], ["DejaVu Serif", "Georgia"]],
        "format": "mp4",
        "also_gif": True,
    },
}


# ---- inside the editor process ---------------------------------------------

def drive(video, out_dir, also_gif):
    sys.path.insert(0, ROOT)
    from clip import editor as C
    from gi.repository import Gdk, GLib, Gtk

    ed = C.ClipEditor(video, C.probe(video))
    ed.show_all()
    ed.queue()
    names = iter([n for _, n in CHAPTERS])
    ed.ask_name = lambda title, text: next(names)
    log = {}

    def ev(x=0, y=0, kv=0, state=0):
        return types.SimpleNamespace(x=x, y=y, button=1, keyval=kv, state=state,
                                     type=Gdk.EventType.BUTTON_PRESS, direction=None)

    def win(x, y):
        s, ox, oy = ed.view()
        return x * s + ox, y * s + oy

    def key(k, state=0):
        ed.on_key(ed, ev(kv=k if isinstance(k, int) else Gdk.keyval_from_name(k), state=state))

    def typed(text):
        for ch in text:
            key(ord(ch))
        key(Gdk.KEY_Return)

    def drag(tool, a, b, text=None):
        key(tool)
        ed.on_press(None, ev(*win(*a)))
        ed.on_motion(None, ev(*win(*b)))
        ed.on_release(None, ev(*win(*b)))
        if text is not None:
            typed(text)

    def click(tool, p, text):
        key(tool)
        ed.on_press(None, ev(*win(*p)))
        ed.on_release(None, ev(*win(*p)))
        typed(text)

    def script():
        ed.seek(T_IN)
        key(Gdk.KEY_i)
        ed.seek(T_OUT)
        key(Gdk.KEY_o)
        key(Gdk.KEY_plus)
        key(Gdk.KEY_plus)
        ed.title_e.set_text("Demo")
        ed.num.set_text("1")
        ed.cap.set_text("Every feature, one config")
        ed.titles_btn.set_active(True)

        ed.seek(1.0)
        ed.chapter_btn.clicked()
        ed.seek(1.5)
        key(Gdk.KEY_1)
        drag("l", (300, 220), (420, 140), "Search box")
        key(Gdk.KEY_2)
        click("n", (700, 300), "Results")

        ed.seek(3.5)
        key(Gdk.KEY_3)
        drag("a", (200, 500), (480, 380))
        key(Gdk.KEY_2)
        drag("b", (760, 360), (1060, 560), "New")

        ed.seek(5.0)
        key(Gdk.KEY_k)
        ed.seek(5.5)
        drag("h", (120, 90), (620, 130))
        key(Gdk.KEY_4)
        drag("c", (1180, 150), (1180, 450), "Group")

        ed.seek(7.5)
        key(Gdk.KEY_1)
        drag("z", (560, 330), (640, 400))
        click("t", (860, 120), "Tip: drag a bar to retime")

        ed.seek(9.0)
        ed.chapter_btn.clicked()
        ed.seek(9.5)
        drag("x", (900, 560), (1200, 680))

        key(Gdk.KEY_z, Gdk.ModifierType.CONTROL_MASK)
        key(Gdk.KEY_z, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        log["items"] = sorted(it["kind"] for it in ed.fig.items)
        log["chapters"] = [c["name"] for c in ed.chapters]
        log["size"] = ed.fig.size
        log["trim"] = [ed.t_in, ed.t_out]
        log["fonts"] = [C.S.sans, C.S.serif]

        w = ed.get_window()
        Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height()).savev(
            os.path.join(out_dir, "editor.png"), "png", [], [])

        if also_gif:
            key(Gdk.KEY_s, Gdk.ModifierType.CONTROL_MASK)
            GLib.timeout_add(200, then_gif)
        else:
            key(Gdk.KEY_Return)
        return False

    def then_gif():
        if ed.exporting:
            return True
        log["first"] = ed.out
        ed.fmt.set_active(1)
        key(Gdk.KEY_s, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        GLib.timeout_add(200, then_close)
        return False

    def then_close():
        if ed.exporting:
            return True
        log["gif"] = ed.out
        ed.selected = None
        key(Gdk.KEY_Escape)
        return False

    GLib.timeout_add(1500, script)
    Gtk.main()
    log["out"] = log.get("first", ed.out)
    print("BATTERY " + json.dumps(log))


def reopen(video):
    sys.path.insert(0, ROOT)
    from clip import editor as C
    st = C.load_session(video)
    print("BATTERY " + json.dumps({"items": sorted(i["kind"] for i in st["items"]),
                                   "chapters": [c["name"] for c in st["chapters"]],
                                   "out": st.get("out")}))


# ---- checking ---------------------------------------------------------------

def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def frame(path, t, w=W, h=H):
    return subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout


def pixel(raw, x, y, w=W):
    i = (y * w + x) * 3
    return tuple(raw[i:i + 3])


def near(a, b, tol):
    return max(abs(p - q) for p, q in zip(a, b)) <= tol


def child(env, *args):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), *args], env=env,
                       capture_output=True, text=True, timeout=300)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("BATTERY ")]
    if r.returncode or not lines:
        raise SystemExit(f"editor run failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(lines[-1][8:])


def contact_sheet(path, times, dest):
    shots = []
    for i, t in enumerate(times):
        p = f"{dest}.{i}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", "scale=640:-2", p], check=True)
        shots.append(p)
    args = ["ffmpeg", "-v", "error", "-y"]
    for p in shots:
        args += ["-i", p]
    args += ["-filter_complex", f"xstack=inputs={len(shots)}:layout=0_0|w0_0|0_h0|w0_h0|0_h0+h1|w0_h0+h1:fill=black",
             dest + ".png"]
    subprocess.run(args, check=True)
    for p in shots:
        os.unlink(p)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "battery-output"))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    src = os.path.join(out, "source recording.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000", "-t", str(SRC_LEN),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src], check=True)

    results, failures = [], []
    for name, spec in CONFIGS.items():
        d = os.path.join(out, name)
        os.makedirs(d)
        cfg = os.path.join(d, "config.toml")
        with open(cfg, "w") as f:
            f.write(spec["toml"] + f'\n[export]\nfolder = "{d}"\nformat = "{spec["format"]}"\n'
                    "copy_to_clipboard = false\nnotify = false\n")
        video = os.path.join(d, "recording.mp4")
        shutil.copyfile(src, video)
        env = {**os.environ, "CLIP_CONFIG": cfg, "CLIP_STATE_DIR": os.path.join(d, "state")}
        log = child(env, "--drive", video, d, "1" if spec.get("also_gif") else "")

        checks = []

        def check(what, ok, detail=""):
            checks.append((what, bool(ok), detail))
            if not ok:
                failures.append(f"{name}: {what} {detail}")

        mp4 = log["out"]
        p = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_streams",
                                       "-show_format", "-of", "json", mp4],
                                      capture_output=True, text=True, check=True).stdout)
        kinds = ["arrow", "box", "brace", "highlight", "label", "marker", "note", "redact", "zoom"]
        check("all 9 mark kinds placed", log["items"] == kinds, log["items"])
        check("3 chapters (button, K, button)", log["chapters"] == [n for _, n in CHAPTERS], log["chapters"])
        check("trim set with I / O", log["trim"] == [T_IN, T_OUT], log["trim"])
        check("fonts from config (first installed)", log["fonts"][0] in spec["fonts"][0] and
              log["fonts"][1] in spec["fonts"][1], log["fonts"])
        check("size raised with +", abs(log["size"] - 1.2) < 1e-6, log["size"])

        lead = 2.6 + min(6.0, 2.2 + 0.45 * 3) - 2 * 0.45
        total = lead + (T_OUT - T_IN)
        dur = float(p["format"]["duration"])
        check("length = title card + chapters card + trimmed clip", abs(dur - total) < 0.15,
              f"{dur:.2f}s vs {total:.2f}s")
        titles = [c["tags"]["title"] for c in p["chapters"]]
        check("chapters in the MP4", titles == ["Intro"] + [n for _, n in CHAPTERS], titles)
        starts = [round(float(c["start_time"]), 2) for c in p["chapters"]]
        want = [0.0] + [round(lead + t - T_IN, 2) for t, _ in CHAPTERS]
        check("chapter times", all(abs(a - b) < 0.05 for a, b in zip(starts, want)), starts)
        streams = {s["codec_type"]: s for s in p["streams"]}
        check("sound kept and in step", "audio" in streams and
              abs(float(streams["audio"]["duration"]) - float(streams["video"]["duration"])) < 0.15)

        card = frame(mp4, 1.0)
        check("title card background from config", near(pixel(card, 10, 10), hexrgb(spec["card_bg"]), 10),
              pixel(card, 10, 10))
        chap_card = frame(mp4, 3.6)
        check("chapters card background from config",
              near(pixel(chap_card, 10, 10), hexrgb(spec["card_bg"]), 10), pixel(chap_card, 10, 10))

        k = max(0.9, min(1.5, H / 640)) * 1.2
        banner = frame(mp4, lead + (5.0 - T_IN) + 1.0)
        bx, by = int(28 * k + 4 * 22 / 14 * k + 4), int(H - 28 * k - 4)
        got = pixel(banner, bx, by)
        if spec["banner_bg"]:
            check("chapter banner background from config", near(got, hexrgb(spec["banner_bg"]), 14), got)
        else:
            check("chapter banner on the picture (paper tint)", min(got) > 200, got)

        boxed = frame(mp4, lead + (3.6 - T_IN) + 0.5)
        plain = frame(video, 3.6 + 0.5)
        want = hexrgb(spec["box"])
        changed = [pixel(boxed, x, 460) for x in range(750, 771)
                   if not near(pixel(boxed, x, 460), pixel(plain, x, 460), 30)]
        got = min(changed, key=lambda c: max(abs(p - q) for p, q in zip(c, want))) if changed else None
        check("box drawn in the chosen palette colour", got and near(got, want, 40), got)

        red = frame(mp4, lead + (9.6 - T_IN) + 1.0)
        block = {pixel(red, x, y) for x in range(1000, 1010) for y in range(600, 606)}
        clear = frame(mp4, lead + (2.0 - T_IN))
        before = {pixel(clear, x, y) for x in range(1000, 1010) for y in range(600, 606)}
        check("redaction pixelates (fewer distinct pixels)", len(block) < len(before), f"{len(block)} vs {len(before)}")

        if spec.get("also_gif"):
            gif = log.get("gif") or ""
            gp = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", gif],
                                           capture_output=True, text=True).stdout or "{}")
            check("GIF exported as a new file, silent", gif.endswith(".gif") and os.path.exists(gif) and
                  all(s["codec_type"] == "video" for s in gp.get("streams", [])), os.path.basename(gif))

        again = child(env, "--reopen", video)
        check("reopening restores marks, chapters and export path",
              again["items"] == kinds and again["chapters"] == log["chapters"] and again["out"], "")

        sheet = os.path.join(d, "contact-sheet")
        contact_sheet(mp4, [1.0, 3.6, lead + 0.6, lead + 2.6, lead + 4.6, lead + 8.6], sheet)
        results.append((name, mp4, checks))

    for name, mp4, checks in results:
        print(f"\n{name}: {os.path.relpath(mp4, out)}")
        for what, ok, detail in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  ({detail})" if detail != "" and not ok else ""))
    print(f"\n{sum(len(c) for *_, c in results) - len(failures)} passed, {len(failures)} failed. Output in {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--drive"]:
        drive(sys.argv[2], sys.argv[3], bool(sys.argv[4]))
    elif sys.argv[1:2] == ["--reopen"]:
        reopen(sys.argv[2])
    else:
        sys.exit(main())
