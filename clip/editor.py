#!/usr/bin/env python3
"""clip [VIDEO] - annotate a screen recording, textbook style.

Each mark appears at the playhead for 3 seconds; drag its bar on the
timeline to move it, or its ends to change when it shows. Without VIDEO,
a file picker opens in the recordings folder (--latest: the newest video
there). Reopening a video picks up its marks, trim and chapters where you
left them (--fresh starts clean).

  Space play/pause (with sound)   Left/Right a frame (Shift: a second)
  I / O  trim start / end at the playhead     [ / ]  the selected mark's
  start / end at the playhead     Home/End  jump     M  sound on/off
  K  a chapter at the playhead, in the current colour (1-5), then its name
     (on the timeline: drag its flag to move it, double-click to rename,
     right-click or Delete to remove)
  - / +  size of every mark and its text, together
  Ctrl+Z / Ctrl+Shift+Z undo / redo (Cmd on a Mac)
"Chapter titles" shows each chapter's name on the picture for a few
seconds from its start, in the preview and the export.

  Enter  export and close     Ctrl+S  export, keep working
  Ctrl+Shift+S  export to a new file          Esc  close without exporting

Export: MP4 (or GIF / WebM) to the clips folder, the file put on the
clipboard, a notification. Marks fade in and out; zoom insets magnify the
live picture; redactions pixelate it. "Title card" opens with the label
and caption, cross-fading into the clip. Chapters, if any, follow as a
card listing them and go into the MP4 / WebM as real chapters. "Sound"
keeps the recording's audio (a GIF is always silent). The recording
itself is never changed.
"""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from array import array

from . import figure as F
from . import desktop, style

import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

S = F.S
VIDEO_EXTS = (".mov", ".mp4", ".m4v", ".mkv", ".webm", ".avi")
SHOW_FOR = 3.0         # seconds a new mark stays up
FADE = 0.18
CARD = 2.6             # title card length, and its cross-fade
XFADE = 0.45
THUMB_H = 44
WAVE_H = 20            # the waveform band under the filmstrip (recordings with sound)
LANE_H = 18
FLAG_H, FLAG_W = 15, 22   # a chapter's flag on the filmstrip
WAVE_N = 1200          # waveform buckets across the whole recording
CHAPTER_SHOW = 3.5     # seconds a chapter's title stays on the picture ("Chapter titles")
SOUND_WAIT = 1.5       # seconds the preview waits for its sound to start before going on without it


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height,r_frame_rate:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1) if float(num) else 30.0
    return {"w": int(v["width"]), "h": int(v["height"]), "fps": min(fps, 60.0),
            "dur": float(d["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def peaks(path, n=WAVE_N, rate=8000):
    """The recording's loudness as n peaks from 0 to 1, for the waveform.
    Decodes the audio mono at a low rate; [] if there's none."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate),
                        "-f", "s16le", "-"], capture_output=True)
    a = array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if not a:
        return []
    step = len(a) / n
    out = []
    for i in range(n):
        sl = a[int(i * step): max(int(i * step) + 1, int((i + 1) * step))]
        out.append(max(max(sl), -min(sl)) / 32768 if sl else 0.0)
    top = max(out) or 1.0
    return [v / top for v in out]


def parse_clock(line):
    """ffplay's -stats line ("  1.23 M-A:  0.000 fd= ...") -> 1.23, its
    clock in seconds from the start of what it plays; None for other lines."""
    m = re.match(rb"\s*(-?\d+(?:\.\d+)?)\s+M-A", line)
    return float(m.group(1)) if m else None


def fmt_time(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def bgra_surface(buf, w, h):
    return cairo.ImageSurface.create_for_data(bytearray(buf), cairo.FORMAT_ARGB32, w, h, w * 4)


# ---- frames from ffmpeg ----------------------------------------------------

class Frames:
    """Stills for scrubbing (latest request wins), thumbnails for the
    filmstrip, and a paced decode for preview playback, with its sound.

    The sound: ffmpeg cuts it from the playhead (ffplay's own -ss is ignored
    by ffplay 9, which played from the start of the recording: the sound ran
    ahead of the picture by wherever you pressed Space) and pipes it to
    ffplay, whose clock (-stats) the frames follow, so they keep to the
    sound however long ffplay takes to start."""

    def __init__(self, path, info, on_frame, on_thumb):
        self.path, self.info = path, info
        self.on_frame, self.on_thumb = on_frame, on_thumb
        self.want = None
        self.cv = threading.Condition()
        self.player = None
        self.speaker = None
        self.cutter = None             # ffmpeg feeding the speaker
        self.aclock = None             # (seconds of sound played, monotonic() when read)
        threading.Thread(target=self._grabber, daemon=True).start()

    def request(self, t):
        with self.cv:
            self.want = t
            self.cv.notify()

    def _grab(self, t):
        w, h = self.info["w"], self.info["h"]
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", self.path,
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgra", "-"],
                           capture_output=True)
        return r.stdout if len(r.stdout) >= w * h * 4 else None

    def _grabber(self):
        while True:
            with self.cv:
                while self.want is None:
                    self.cv.wait()
                t, self.want = self.want, None
            buf = self._grab(t)
            if buf:
                GLib.idle_add(self.on_frame, t, buf[: self.info["w"] * self.info["h"] * 4])

    def thumbs(self, n):
        def run():
            w, h, dur = self.info["w"], self.info["h"], self.info["dur"]
            tw = max(2, int(round(w * THUMB_H / h / 2)) * 2)
            p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", self.path, "-vf",
                                  f"fps={n / max(dur, 0.1):.5f},scale={tw}:{THUMB_H}",
                                  "-f", "rawvideo", "-pix_fmt", "bgra", "-"], stdout=subprocess.PIPE)
            size, i = tw * THUMB_H * 4, 0
            while True:
                buf = p.stdout.read(size)
                if len(buf) < size:
                    break
                GLib.idle_add(self.on_thumb, i, buf, tw)
                i += 1
            p.wait()
        threading.Thread(target=run, daemon=True).start()

    def waveform(self, on_peaks):
        threading.Thread(target=lambda: GLib.idle_add(on_peaks, peaks(self.path)), daemon=True).start()

    def start_sound(self, t0, t1):
        """The sound from t0 to t1: ffmpeg cuts it, ffplay plays it and
        reports its clock, read into self.aclock."""
        self.aclock = None
        self.cutter = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", self.path,
             "-vn", "-sn", "-f", "wav", "-"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sp = self.speaker = subprocess.Popen(
            ["ffplay", "-hide_banner", "-loglevel", "error", "-nodisp", "-autoexit", "-stats", "-i", "-"],
            stdin=self.cutter.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.cutter.stdout.close()

        def read_clock():
            buf = b""
            while True:
                c = sp.stderr.read(1)
                if not c:
                    break
                if c in b"\r\n":
                    v = parse_clock(buf)
                    if v is not None and self.speaker is sp:
                        self.aclock = (v, time.monotonic())
                    buf = b""
                else:
                    buf += c
        threading.Thread(target=read_clock, daemon=True).start()

    def clock(self, start, sound):
        """Seconds into the playback: the sound's clock while there is one
        (None until it starts), else the wall clock since start."""
        if sound and self.speaker is not None:
            a = self.aclock
            if a is not None:
                return a[0] + (time.monotonic() - a[1])
            if time.monotonic() - start < SOUND_WAIT:
                return None
        return time.monotonic() - start           # no sound (or it never came): keep time ourselves

    def play(self, t0, t1, on_tick, on_end, sound=False):
        self.stop()
        sound = bool(sound and self.info["audio"] and shutil.which("ffplay"))
        if sound:
            self.start_sound(t0, t1)
        w, h, fps = self.info["w"], self.info["h"], min(self.info["fps"], 30)
        pw = min(w, 1280)
        ph = int(round(h * pw / w / 2)) * 2
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                                 "-i", self.path, "-vf", f"fps={fps},scale={pw}:{ph}",
                                 "-f", "rawvideo", "-pix_fmt", "bgra", "-"], stdout=subprocess.PIPE)
        self.player = proc

        def run():
            size, k, start = pw * ph * 4, 0, time.monotonic()
            while self.player is proc:
                buf = proc.stdout.read(size)
                if len(buf) < size:
                    break
                due, late = k / fps, False
                while self.player is proc:             # wait for the clock to reach this frame
                    now = self.clock(start, sound)
                    if now is None:                    # the sound hasn't started yet
                        time.sleep(0.005)
                        continue
                    lag = due - now
                    if lag <= 0:
                        late = lag < -0.25             # behind: drop this one
                        break
                    time.sleep(min(lag, 0.02))
                if late:
                    k += 1
                    continue
                GLib.idle_add(on_tick, t0 + k / fps, buf, pw, ph)
                k += 1
            if self.player is proc:
                self.player = None
                GLib.idle_add(on_end)
                self.stop_sound()
            proc.kill()
        threading.Thread(target=run, daemon=True).start()

    def stop_sound(self):
        for name in ("speaker", "cutter"):
            p = getattr(self, name)
            setattr(self, name, None)
            if p:
                p.kill()
                p.wait()
        self.aclock = None

    def stop(self):
        p, self.player = self.player, None
        if p:
            p.kill()
        self.stop_sound()


# ---- the document: a Figure that knows the time --------------------------

class ClipFigure(F.Figure):
    def __init__(self, w, h):
        super().__init__(surface=cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h))
        self.plate = False
        self.time = 0.0

    def visible(self, it):
        return it.get("t0", 0) - 1e-6 <= self.time <= it.get("t1", 1e9) + 1e-6

    def key_entries(self):
        """Number markers across the whole clip, not just the ones showing
        now (paint() narrows self.items to those); a layer keeps its own."""
        if self.layer:
            return []
        n = 0
        for it in getattr(self, "_all", None) or self.items:
            if it["kind"] == "marker":
                n += 1
                it["n"] = n
        return []

    def paint(self, cr, editing=None, selected=None, temp=None):
        everything = self._all = self.items
        self.items = [it for it in everything if self.visible(it) or it is editing]
        try:
            super().paint(cr, editing=editing, selected=selected, temp=temp)
        finally:
            self.items = everything
            self._all = None


# ---- the editor -------------------------------------------------------------

class ClipEditor(F.Editor):
    def __init__(self, path, info, state=None):
        self.path, self.info = path, info
        self.fig_ = ClipFigure(info["w"], info["h"])
        super().__init__(self.fig_, None)
        self.set_title(f"Clip \u2014 {os.path.basename(path)}")
        self.t_in, self.t_out = 0.0, info["dur"]
        self.playing = False
        self.thumbs = {}
        self.wave = []
        self.wave_h = WAVE_H if info["audio"] else 0
        self.tl_drag = None
        self.exporting = False
        self.chapters = []           # {"t", "name", "color"}, in time order
        self.sel_chapter = None

        # the toolbar: no plate for video; a format menu and a title card
        bar = self.plate_btn.get_parent()
        bar.remove(self.plate_btn)
        self.cap.set_placeholder_text("Title card caption (Tab)")
        kids = bar.get_children()
        cancel_pos = len(kids) - 2
        self.chapter_btn = Gtk.Button(label="+ Chapter")
        self.chapter_btn.set_tooltip_text("Add a chapter at the playhead, in the current colour (K)")
        self.chapter_btn.set_can_focus(False)
        self.chapter_btn.connect("clicked", lambda *_: self.add_chapter())
        self.card_btn = Gtk.CheckButton(label="Title card", active=False)
        self.card_btn.set_tooltip_text("Open with a title card (its label, if any, and the caption) that fades into the clip")
        self.titles_btn = Gtk.CheckButton(label="Chapter titles", active=False)
        self.titles_btn.set_tooltip_text(
            f"Show each chapter's name on the picture when it starts, for {CHAPTER_SHOW:g} seconds")
        self.titles_btn.connect("toggled", lambda *_: self.queue())
        self.fmt = Gtk.ComboBoxText()
        for f in ("MP4", "GIF", "WebM"):
            self.fmt.append_text(f)
        self.fmt.set_active(FORMATS.index(S.format))
        self.sound_btn = Gtk.CheckButton(label="Sound", active=info["audio"])
        self.sound_btn.set_sensitive(info["audio"])
        self.sound_btn.set_tooltip_text(
            "Keep the recording's sound in the preview and the export (M); a GIF is always silent"
            if info["audio"] else "This recording has no sound")
        self.sound_btn.connect("toggled", self.on_sound)
        bar.pack_start(self.chapter_btn, False, False, 0)
        bar.pack_start(self.card_btn, False, False, 0)
        bar.pack_start(self.titles_btn, False, False, 0)
        bar.pack_start(self.fmt, False, False, 0)
        bar.pack_start(self.sound_btn, False, False, 0)
        for i, w in enumerate((self.chapter_btn, self.card_btn, self.titles_btn, self.fmt, self.sound_btn)):
            bar.reorder_child(w, cancel_pos + i)
        self.cap.connect("changed", self.on_card_caption)

        # the timeline, between the picture and the toolbar
        vbox = self.get_child()
        self.tl = Gtk.DrawingArea()
        self.tl.set_size_request(-1, self.lanes_y() + 4 * LANE_H + 12)
        self.tl.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                           | Gdk.EventMask.POINTER_MOTION_MASK)
        self.tl.connect("draw", self.tl_draw)
        self.tl.connect("button-press-event", self.tl_press)
        self.tl.connect("motion-notify-event", self.tl_motion)
        self.tl.connect("button-release-event", self.tl_release)
        vbox.pack_start(self.tl, False, False, 0)
        vbox.reorder_child(self.tl, 2)

        self.load_state(state)
        start = (state or {}).get("time", 0.0)
        self.out = (state or {}).get("out")
        self.welcome = (f"Picked up where you left off. Enter exports and closes, {desktop.MOD}+S exports "
                        "and keeps working, Esc closes; clip --fresh starts clean." if state else None)

        self.frames = Frames(path, info, self.got_frame, self.got_thumb)
        self.n_thumbs = 0
        self.fig.time = max(0.0, min(info["dur"] - 1 / info["fps"], start))
        self.frames.request(self.fig.time)

    # -- state ----------------------------------------------------------------
    def state(self):
        st = super().state()
        st.pop("plate", None)
        st.update(t_in=self.t_in, t_out=self.t_out, card=self.card_btn.get_active(),
                  fmt=self.fmt.get_active_text().lower(), time=self.fig.time,
                  sound=self.sound_btn.get_active(), chapters=self.chapters,
                  titles=self.titles_btn.get_active())
        return st

    def load_state(self, st):
        st = st or {}
        self._card_auto = True                      # a loaded caption doesn't tick the card
        super().load_state(st)
        self.t_in = max(0.0, st.get("t_in", 0.0))
        self.t_out = min(self.info["dur"], st.get("t_out", self.info["dur"]))
        self.card_btn.set_active(st.get("card", False))
        fmt = st.get("fmt", S.format)
        self.fmt.set_active(FORMATS.index(fmt) if fmt in FORMATS else 0)
        self.sound_btn.set_active(self.info["audio"] and st.get("sound", True))
        self.chapters = sorted(copy.deepcopy(st.get("chapters", [])), key=lambda c: c["t"])
        self.sel_chapter = None
        self.titles_btn.set_active(st.get("titles", False))

    def on_card_caption(self, entry):
        """Typing a caption turns the title card on (once; untick it to skip)."""
        if entry.get_text().strip() and not getattr(self, "_card_auto", False):
            self._card_auto = True
            self.card_btn.set_active(True)

    @property
    def sound(self):
        return self.info["audio"] and self.sound_btn.get_active()

    def on_sound(self, btn):
        """Sound on or off; a preview that's playing restarts with or without it."""
        if self.playing:
            self.toggle_play()
            self.toggle_play()
        if hasattr(self, "tl"):
            self.queue()

    # -- undo: the marks and the chapters together ----------------------------
    def snapshot(self):
        self.undo.append({"items": copy.deepcopy(self.fig.items),
                          "chapters": copy.deepcopy(self.chapters)})
        self.redo.clear()

    def restore(self, stack, other):
        if not stack:
            return
        other.append({"items": copy.deepcopy(self.fig.items), "chapters": copy.deepcopy(self.chapters)})
        e = stack.pop()
        if isinstance(e, dict):
            self.fig.items, self.chapters = e["items"], e["chapters"]
        else:                                       # saved before chapters: the marks alone
            self.fig.items = e
        self.selected = self.editing = self.sel_chapter = None
        self.queue()

    # -- chapters -------------------------------------------------------------
    def add_chapter(self):
        """A chapter at the playhead in the current colour; asks its name."""
        if self.playing:
            self.toggle_play()
        t = round(self.now, 3)
        name = self.ask_name("New chapter", f"Chapter {len(self.chapters) + 1}")
        if name is None:
            return
        self.snapshot()
        ch = {"t": t, "name": name, "color": self.color}
        self.chapters = sorted(self.chapters + [ch], key=lambda c: c["t"])
        self.sel_chapter = None      # so 1-5 next picks the next one's colour, not this one's
        self.queue()

    def rename_chapter(self, ch):
        name = self.ask_name("Rename chapter", ch["name"])
        if name is not None and name != ch["name"]:
            self.snapshot()
            ch["name"] = name
            self.queue()

    def remove_chapter(self, ch):
        self.snapshot()
        self.chapters.remove(ch)
        self.sel_chapter = None
        self.queue()

    def ask_name(self, title, text):
        """A small dialog with one line to type; None if cancelled."""
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        e = Gtk.Entry(text=text, activates_default=True, width_chars=36)
        e.set_margin_start(10)
        e.set_margin_end(10)
        e.set_margin_top(10)
        d.get_content_area().pack_start(e, False, False, 6)
        d.show_all()
        e.grab_focus()
        ok = d.run() == Gtk.ResponseType.OK
        name = e.get_text().strip()
        d.destroy()
        self.area.grab_focus()
        return (name or text) if ok else None

    def set_color(self, i):
        """1-5 also recolours the selected chapter."""
        if getattr(self, "sel_chapter", None) is not None and self.editing is None and self.selected is None:
            self.snapshot()
            self.sel_chapter["color"] = i
        super().set_color(i)
        if hasattr(self, "tl"):
            self.queue()

    def chapter_at(self, x, y):
        """The chapter whose flag is under (x, y) on the timeline."""
        fy = 26
        if not fy <= y <= fy + FLAG_H + 2:
            return None
        for ch in reversed(self.chapters):
            cx = self.t_to_x(ch["t"])
            if cx - 3 <= x <= cx + FLAG_W:
                return ch
        return None

    # -- frames -------------------------------------------------------------
    @property
    def now(self):
        return self.fig.time

    def seek(self, t):
        t = max(0.0, min(self.info["dur"] - 1 / self.info["fps"], t))
        self.fig.time = t
        if not self.playing:
            self.frames.request(t)
        self.queue()

    def got_frame(self, t, buf):
        if self.playing:
            return False
        self.fig.img = bgra_surface(buf, self.info["w"], self.info["h"])
        self.queue()
        return False

    def got_wave(self, wave):
        self.wave = wave
        self.tl.queue_draw()
        return False

    def got_thumb(self, i, buf, tw):
        self.thumbs[i] = bgra_surface(buf, tw, THUMB_H)
        self.tl.queue_draw()
        return False

    def tick(self, t, buf, pw, ph):
        if not self.playing:
            return False
        small = bgra_surface(buf, pw, ph)
        full = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.info["w"], self.info["h"])
        cr = cairo.Context(full)
        cr.scale(self.info["w"] / pw, self.info["h"] / ph)
        cr.set_source_surface(small, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_FAST)
        cr.paint()
        self.fig.img = full
        self.fig.time = t
        self.queue()
        return False

    def toggle_play(self):
        if self.playing:
            self.playing = False
            self.frames.stop()
            self.frames.request(self.now)
        else:
            self.stop_editing()
            start = self.now if self.t_in <= self.now < self.t_out - 0.1 else self.t_in
            self.playing = True
            self.frames.play(start, self.t_out, self.tick, self.play_ended, sound=self.sound)
        self.queue()

    def play_ended(self):
        self.playing = False
        self.frames.request(self.now)
        self.queue()
        return False

    def queue(self):
        self.area.queue_draw()
        self.tl.queue_draw()
        state = "Playing" if self.playing else "Paused"
        if self.info["audio"] and not self.sound_btn.get_active():
            state += " (muted)"
        here = [c for c in self.chapters if c["t"] <= self.now + 1e-6]
        chap = f"   chapter: {here[-1]['name']}" if here else ""
        self.hint.set_text(f"{state}  {fmt_time(self.now)} / {fmt_time(self.info['dur'])}"
                           f"   trim {fmt_time(self.t_in)} to {fmt_time(self.t_out)}{chap}"
                           f"      {F.HINTS[self.tool]}   K chapter")

    # -- editor hooks -------------------------------------------------------
    def set_tool(self, name):
        super().set_tool(name)
        if hasattr(self, "tl"):
            self.queue()

    def new_item(self, kind, **kw):
        it = super().new_item(kind, **kw)
        it["t0"] = round(self.now, 3)
        it["t1"] = round(min(self.t_out, self.now + SHOW_FOR), 3)
        if it["t1"] - it["t0"] < 0.5:
            it["t0"] = max(0.0, it["t1"] - SHOW_FOR)
        return it

    def hit(self, x, y):
        everything = self.fig.items
        self.fig.items = [it for it in everything if self.fig.visible(it)]
        try:
            return super().hit(x, y)
        finally:
            self.fig.items = everything

    def view(self):
        a = self.area.get_allocation()
        iw, ih = self.info["w"], self.info["h"]
        s = min(2.0, (a.width - 24) / iw, (a.height - 24) / ih)
        return s, (a.width - iw * s) / 2, (a.height - ih * s) / 2

    def on_draw(self, w, cr):
        cr.set_source_rgb(*F.DESK)
        cr.paint()
        s, ox, oy = self.view()
        cr.translate(ox, oy)
        cr.scale(s, s)
        self.fig.paint(cr, editing=self.editing, selected=self.selected, temp=self.temp)
        if self.titles_btn.get_active():
            on = [c for c in self.chapters if c["t"] - 1e-6 <= self.now < c["t"] + CHAPTER_SHOW]
            if on:
                ch = on[-1]
                age = self.now - ch["t"]
                alpha = max(0.0, min(1.0, age / FADE + 0.001, (CHAPTER_SHOW - age) / FADE))
                cr.push_group()
                chapter_title(cr, self.fig, ch["name"], ch.get("color", 0))
                cr.pop_group_to_source()
                cr.paint_with_alpha(alpha)
        if self.playing or not (self.t_in <= self.now <= self.t_out):
            cr.set_source_rgba(0, 0, 0, 0.0 if self.playing else 0.35)
            cr.rectangle(0, 0, self.info["w"], self.info["h"])
            cr.fill()

    def on_press(self, w, ev):
        if self.playing:
            self.toggle_play()
        return super().on_press(w, ev)

    def on_key(self, w, ev):
        if self.exporting:
            return True
        ctrl = ev.state & self.primary
        if ctrl and ev.keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.open_other()
            return True
        if self.editing is not None or self.get_focus() in (self.cap, self.num, self.title_e):
            return super().on_key(w, ev)
        kv, shift = ev.keyval, ev.state & Gdk.ModifierType.SHIFT_MASK
        step = 1.0 if shift else 1 / self.info["fps"]
        if kv == Gdk.KEY_space:
            self.toggle_play()
        elif kv == Gdk.KEY_Left:
            self.seek(self.now - step)
        elif kv == Gdk.KEY_Right:
            self.seek(self.now + step)
        elif kv == Gdk.KEY_Home:
            self.seek(self.t_in)
        elif kv == Gdk.KEY_End:
            self.seek(self.t_out - 0.05)
        elif kv in (Gdk.KEY_i, Gdk.KEY_I) and not ctrl:
            self.t_in = min(self.now, self.t_out - 0.2)
            self.queue()
        elif kv in (Gdk.KEY_o, Gdk.KEY_O) and not ctrl:
            self.t_out = max(self.now, self.t_in + 0.2)
            self.queue()
        elif kv in (Gdk.KEY_k, Gdk.KEY_K) and not ctrl:
            self.add_chapter()
        elif kv in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and self.sel_chapter is not None \
                and self.selected is None:
            self.remove_chapter(self.sel_chapter)
        elif kv in (Gdk.KEY_m, Gdk.KEY_M) and not ctrl and self.info["audio"]:
            self.sound_btn.set_active(not self.sound_btn.get_active())
        elif kv == Gdk.KEY_bracketleft and self.selected is not None:
            self.snapshot()
            self.selected["t0"] = min(self.now, self.selected["t1"] - 0.2)
            self.queue()
        elif kv == Gdk.KEY_bracketright and self.selected is not None:
            self.snapshot()
            self.selected["t1"] = max(self.now, self.selected["t0"] + 0.2)
            self.queue()
        else:
            r = super().on_key(w, ev)
            self.queue()
            return r
        return True

    def stop_editing(self):
        super().stop_editing()
        if hasattr(self, "tl"):
            self.tl.queue_draw()

    # -- the timeline -----------------------------------------------------------
    def tl_geom(self):
        a = self.tl.get_allocation()
        x0, x1 = 14, a.width - 14
        return x0, x1, a.width, a.height

    def t_to_x(self, t):
        x0, x1, *_ = self.tl_geom()
        return x0 + (x1 - x0) * t / self.info["dur"]

    def x_to_t(self, x):
        x0, x1, *_ = self.tl_geom()
        return max(0.0, min(self.info["dur"], (x - x0) / (x1 - x0) * self.info["dur"]))

    def lanes_y(self):
        """Where the marks' bars start: under the ruler, filmstrip and waveform."""
        return 26 + THUMB_H + self.wave_h + 10

    def lanes(self):
        """Stack the marks' bars so overlapping ones don't collide."""
        ends, out = [], []
        for it in sorted(self.fig.items, key=lambda i: i["t0"]):
            for li, e in enumerate(ends):
                if it["t0"] >= e - 1e-6:
                    ends[li] = it["t1"]
                    break
            else:
                li = len(ends)
                ends.append(it["t1"])
            out.append((it, min(li, 3)))
        return out

    def tl_draw(self, w, cr):
        x0, x1, W, H = self.tl_geom()
        cr.set_source_rgb(*S.timeline)
        cr.paint()
        # the ruler
        dur = self.info["dur"]
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if (x1 - x0) / (dur / s) >= 60)
        lay_font = F.font(F.SANS, 11)
        t = 0.0
        while t <= dur + 1e-6:
            x = self.t_to_x(t)
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.rectangle(int(x), 14, 1, 8)
            cr.fill()
            lay = F.make_layout(cr, fmt_time(t).rstrip("0").rstrip("."), lay_font)
            cr.set_source_rgba(1, 1, 1, 0.7)
            cr.move_to(x + 3, 2)
            PangoCairo.show_layout(cr, lay)
            t += step
        # the filmstrip
        fy = 26
        if self.thumbs:
            n = max(self.thumbs) + 1
            cr.save()
            cr.rectangle(x0, fy, x1 - x0, THUMB_H)
            cr.clip()
            tw = next(iter(self.thumbs.values())).get_width()
            x = x0
            while x < x1:
                i = min(n - 1, int((x - x0) / (x1 - x0) * n))
                if i in self.thumbs:
                    cr.set_source_surface(self.thumbs[i], x, fy)
                    cr.paint()
                x += tw
            cr.restore()
        else:
            cr.set_source_rgb(*shade(S.timeline, 0.08))
            cr.rectangle(x0, fy, x1 - x0, THUMB_H)
            cr.fill()
        # trimmed-off ends, dimmed; the trim brackets
        cr.set_source_rgba(0, 0, 0, 0.62)
        cr.rectangle(x0, fy, self.t_to_x(self.t_in) - x0, THUMB_H)
        cr.rectangle(self.t_to_x(self.t_out), fy, x1 - self.t_to_x(self.t_out), THUMB_H)
        cr.fill()
        cr.set_source_rgb(*S.trim)
        for t, d in ((self.t_in, 1), (self.t_out, -1)):
            x = self.t_to_x(t)
            cr.rectangle(x - (0 if d > 0 else 4), fy - 2, 4, THUMB_H + 4)
            cr.rectangle(x - (0 if d > 0 else 9), fy - 2, 9, 3)
            cr.rectangle(x - (0 if d > 0 else 9), fy + THUMB_H - 1, 9, 3)
        cr.fill()
        # the waveform: peaks mirrored round a centre line, dim when muted or trimmed off
        if self.wave_h:
            wy, wh = fy + THUMB_H + 2, self.wave_h - 2
            cr.set_source_rgb(*shade(S.timeline, -0.05))
            cr.rectangle(x0, wy, x1 - x0, wh)
            cr.fill()
            if self.wave:
                n, mid = len(self.wave), wy + wh / 2
                lit = S.waveform if self.sound_btn.get_active() else (0.5, 0.5, 0.5)
                kept = []                           # one column per pixel, filled in two goes
                for px in range(int(x0), int(x1)):
                    i0 = int((px - x0) / (x1 - x0) * n)
                    i1 = max(i0 + 1, int((px + 1 - x0) / (x1 - x0) * n))
                    hh = max(0.5, max(self.wave[i0:i1] or [0]) * wh / 2)
                    kept.append((px, hh, self.t_in <= self.x_to_t(px) <= self.t_out))
                for inside, alpha in ((True, 0.9), (False, 0.3)):
                    for px, hh, k in kept:
                        if k == inside:
                            cr.rectangle(px, mid - hh, 1, 2 * hh)
                    cr.set_source_rgba(*lit, alpha)
                    cr.fill()
        # the marks' bars
        ly = self.lanes_y()
        for it, li in self.lanes():
            bx0, bx1 = self.t_to_x(it["t0"]), max(self.t_to_x(it["t1"]), self.t_to_x(it["t0"]) + 6)
            by = ly + li * LANE_H
            F.rrect(cr, bx0, by + 1, bx1 - bx0, LANE_H - 3, 3)
            cr.set_source_rgb(*self.fig.colour(it))
            cr.fill_preserve()
            if it is self.selected:
                cr.set_source_rgb(1, 1, 1)
                cr.set_line_width(1.5)
                cr.stroke()
            cr.new_path()
            name = it.get("text") or it["kind"]
            if it["kind"] == "marker":
                name = f'{it.get("n", "")} {it.get("text", "")}'.strip()
            lay = F.make_layout(cr, name, F.font(F.SANS_SEMI, 11))
            lay.set_width(int(max(1, bx1 - bx0 - 8) * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(bx0 + 4, by + 2)
            PangoCairo.show_layout(cr, lay)
        # the chapters: a line in their colour down the filmstrip and a
        # numbered flag on it, its name running to the next one
        fy = 26
        for i, ch in enumerate(self.chapters):
            cx = self.t_to_x(ch["t"])
            nx = self.t_to_x(self.chapters[i + 1]["t"]) if i + 1 < len(self.chapters) else x1
            col = F.PALETTE[ch.get("color", 0) % len(F.PALETTE)][1]
            cr.set_source_rgb(*col)
            cr.rectangle(cx - 1, fy, 2, THUMB_H + self.wave_h)
            cr.fill()
            lay = F.make_layout(cr, f"{i + 1}  {ch['name']}", F.font(F.SANS_SEMI, 10.5))
            lay.set_width(int(max(FLAG_W - 8, min(nx - cx - 10, 220)) * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            fw = min(F.size(lay)[0] + 8, max(FLAG_W, nx - cx - 2))
            F.rrect(cr, cx, fy, fw, FLAG_H, 2)
            cr.set_source_rgb(*col)
            cr.fill_preserve()
            if ch is self.sel_chapter:
                cr.set_source_rgb(1, 1, 1)
                cr.set_line_width(1.5)
                cr.stroke()
            cr.new_path()
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(cx + 4, fy + 1)
            PangoCairo.show_layout(cr, lay)
        # the playhead
        x = self.t_to_x(self.now)
        cr.set_source_rgb(*S.playhead)
        cr.rectangle(x - 1, 10, 2, H - 14)
        cr.fill()
        cr.move_to(x - 6, 6)
        cr.line_to(x + 6, 6)
        cr.line_to(x, 14)
        cr.close_path()
        cr.fill()

    def tl_hit_bar(self, x, y):
        ly = self.lanes_y()
        for it, li in self.lanes():
            by = ly + li * LANE_H
            bx0, bx1 = self.t_to_x(it["t0"]), max(self.t_to_x(it["t1"]), self.t_to_x(it["t0"]) + 6)
            if by <= y <= by + LANE_H and bx0 - 4 <= x <= bx1 + 4:
                part = "t0" if abs(x - bx0) < 6 else "t1" if abs(x - bx1) < 6 else "body"
                return it, part
        return None, None

    def tl_press(self, w, ev):
        ch = self.chapter_at(ev.x, ev.y)
        if ev.button == 3 and ch is not None:
            self.remove_chapter(ch)
            return
        if ev.button != 1:
            return
        if self.playing:
            self.toggle_play()
        self.stop_editing()
        x, y = ev.x, ev.y
        if ch is not None:
            if ev.type == Gdk.EventType._2BUTTON_PRESS:
                self.tl_drag = None
                self.rename_chapter(ch)
                return
            self.snapshot()
            self.selected, self.sel_chapter = None, ch
            self.tl_drag = ("chapter", ch, ch["t"], self.x_to_t(x))
            self.seek(ch["t"])
            return
        self.sel_chapter = None
        if y >= self.lanes_y() - 4:
            it, part = self.tl_hit_bar(x, y)
            if it is not None:
                self.snapshot()
                self.selected = it
                self.tl_drag = ("bar", it, part, self.x_to_t(x), it["t0"], it["t1"])
                if part == "body" and not self.fig.visible(it):
                    self.seek(it["t0"])
                self.queue()
                return
        for name, t in (("in", self.t_in), ("out", self.t_out)):
            if abs(x - self.t_to_x(t)) < 7 and 22 <= y <= 26 + THUMB_H + self.wave_h + 4:
                self.tl_drag = ("trim", name)
                return
        self.tl_drag = ("seek",)
        self.seek(self.x_to_t(x))

    def tl_motion(self, w, ev):
        if not self.tl_drag:
            return
        t = self.x_to_t(ev.x)
        kind = self.tl_drag[0]
        if kind == "seek":
            self.seek(t)
        elif kind == "trim":
            if self.tl_drag[1] == "in":
                self.t_in = min(t, self.t_out - 0.2)
                self.seek(self.t_in)
            else:
                self.t_out = max(t, self.t_in + 0.2)
                self.seek(self.t_out - 0.02)
        elif kind == "chapter":
            _, ch, t0, ts = self.tl_drag
            ch["t"] = round(max(0.0, min(self.info["dur"], t0 + t - ts)), 3)
            self.chapters.sort(key=lambda c: c["t"])
            self.seek(ch["t"])
        else:
            _, it, part, ts, a, b = self.tl_drag
            d = t - ts
            dur = self.info["dur"]
            if part == "body":
                d = max(-a, min(dur - b, d))
                it["t0"], it["t1"] = round(a + d, 3), round(b + d, 3)
            elif part == "t0":
                it["t0"] = round(max(0.0, min(b - 0.2, a + d)), 3)
                self.seek(it["t0"])
            else:
                it["t1"] = round(min(dur, max(a + 0.2, b + d)), 3)
                self.seek(it["t1"])
        self.queue()

    def tl_release(self, w, ev):
        self.tl_drag = None

    # -- closing and exporting ------------------------------------------------
    def keep_session(self):
        try:
            save_session(self.path, self.state() | {"out": self.out})
        except OSError as e:
            print(f"clip: couldn't keep this session: {e}", file=sys.stderr)

    def quit(self, ok):
        if self.exporting:
            return
        self.stop_editing()
        if not ok:
            self.frames.stop()
            self.keep_session()
            self.done = False
            Gtk.main_quit()
            return
        self.save(close=True)

    def open_other(self):
        """Ctrl+O: keep this one's session and open another recording here."""
        path = choose_video(self, os.path.dirname(self.path))
        if not path:
            return
        self.keep_session()
        self.frames.stop()
        self.reopen = path
        self.done = False
        Gtk.main_quit()

    def save(self, close=True, as_new=False):
        """Render the clip (in the background); the session is kept with it."""
        self.stop_editing()
        if self.exporting:
            return
        fmt = self.fmt.get_active_text().lower()
        if as_new or not self.out or not os.path.isdir(os.path.dirname(self.out)):
            out = export_path(self.path, S.clips, fmt)
        else:
            out = os.path.splitext(self.out)[0] + "." + fmt
        if close:
            self.frames.stop()
        if self.playing:
            self.toggle_play()
        self.exporting = True
        self.set_sensitive(False)
        threading.Thread(target=self.export, args=(out, fmt, close), daemon=True).start()

    def progress(self, text):
        GLib.idle_add(lambda: self.hint.set_text(text) and False)

    def export(self, out, fmt, close=True):
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            render(self.path, self.info, self.fig, self.t_in, self.t_out, out, fmt,
                   card=self.card_btn.get_active(), sound=self.sound, progress=self.progress,
                   chapters=self.chapters, titles=self.titles_btn.get_active())
            ok, err = True, None
        except Exception as e:                       # noqa: BLE001
            print(f"clip: export failed: {e}", file=sys.stderr)
            ok, err = False, str(e)
        GLib.idle_add(self.finished, out if ok else None, err, close)

    def finished(self, out, err, close=True):
        self.exporting = False
        self.set_sensitive(True)
        if err:
            self.hint.set_text("Export failed: " + err[-300:])
            return False
        self.out = out
        self.keep_session()
        name = os.path.basename(out)
        copied = S.copy_to_clipboard and desktop.copy_file(out)
        if S.notify:
            desktop.notify("Clip exported", f"{name} is in {S.clips}" + (", and on the clipboard" if copied else ""))
        if S.reveal:
            desktop.reveal(out)
        if close:
            self.done = True
            Gtk.main_quit()
            return False
        self.flash(f"Exported {name}{' (on the clipboard)' if copied else ''}. {desktop.MOD}+S exports it "
                   f"again, {desktop.MOD}+Shift+S to a new file, Enter exports and closes.")
        self.area.grab_focus()
        return False


def shade(rgb, d):
    return tuple(max(0.0, min(1.0, c + d)) for c in rgb)


FORMATS = style.FORMATS


def export_path(video, folder, fmt):
    """Where an export goes: "<recording> (annotated).mp4" in folder,
    numbered if that's taken."""
    stem = os.path.splitext(os.path.basename(video))[0]
    base = os.path.join(folder, f"{stem} (annotated)")
    out, n = f"{base}.{fmt}", 2
    while os.path.exists(out):
        out, n = f"{base} {n}.{fmt}", n + 1
    return out


# ---- sessions: each recording's marks, trim and chapters, kept between runs --

def session_path(video):
    real = os.path.realpath(video)
    key = hashlib.sha1(f"{real}\0{os.path.getsize(real)}".encode()).hexdigest()[:16]
    return os.path.join(desktop.state_dir(), "sessions", key + ".json")


def save_session(video, state):
    path = session_path(video)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state | {"video": os.path.realpath(video)}, f)
    os.replace(tmp, path)


def load_session(video):
    try:
        with open(session_path(video)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---- rendering with ffmpeg -------------------------------------------------

def layer_png(fig, it, path):
    """One mark, drawn alone on transparency, cropped to where it is."""
    lf = ClipFigure(fig.iw, fig.ih)
    lf.layer = True
    lf.k = fig.k
    lf.items = [copy.deepcopy(it)]
    lf.items[0].pop("t0", None)
    lf.items[0].pop("t1", None)
    b = lf.bbox(lf.items[0])
    pad = 14 * fig.k
    x0 = max(0, int(math.floor(b[0] - pad)))
    y0 = max(0, int(math.floor(b[1] - pad)))
    x1 = min(fig.iw, int(math.ceil(b[2] + pad)))
    y1 = min(fig.ih, int(math.ceil(b[3] + pad)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, x1 - x0, y1 - y0)
    cr = cairo.Context(surf)
    cr.translate(-x0, -y0)
    getattr(lf, "paint_" + it["kind"])(cr, lf.items[0], False)
    surf.write_to_png(path)
    return x0, y0


def chapter_title(cr, fig, name, color, draw=True):
    """A chapter's title on the picture, at the lower left: drawn as a Note
    mark is (paper tinted with the chapter's colour, a stripe of it down the
    left, serif text) at heading size, and sized with the marks (fig.k).
    Returns its box (x, y, w, h)."""
    z = 22 / 14                                          # heading size, against a note's 14
    px = fig.px
    lay = F.make_layout(cr, name, F.font(F.SERIF, px(14 * z)))
    lay.set_width(int(fig.iw * 0.6 * Pango.SCALE))
    lay.set_ellipsize(Pango.EllipsizeMode.END)
    tw, th = F.size(lay)
    pad, bar = px(10 * z), px(4 * z)
    w, h = tw + 2 * pad + bar, th + 2 * pad
    x, y = px(28), fig.ih - px(28) - h
    if draw:
        col = F.PALETTE[color % len(F.PALETTE)][1]
        cr.rectangle(x, y, w, h)
        cr.set_source_rgb(*(S.title_background or tuple(F.PAPER[i] * 0.88 + col[i] * 0.12 for i in range(3))))
        cr.fill()
        cr.rectangle(x, y, bar, h)
        cr.set_source_rgb(*(S.title_stripe or col))
        cr.fill()
        cr.set_source_rgb(*S.title_text)
        cr.move_to(x + bar + pad, y + pad)
        PangoCairo.show_layout(cr, lay)
    return x, y, w, h


def chapter_title_png(fig, name, color, path):
    """A chapter's title alone on transparency, cropped; its (x, y)."""
    probe_cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    x, y, w, h = chapter_title(probe_cr, fig, name, color, draw=False)
    x0, y0 = max(0, int(x) - 2), max(0, int(y) - 2)
    x1, y1 = min(fig.iw, int(math.ceil(x + w)) + 2), min(fig.ih, int(math.ceil(y + h)) + 2)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, x1 - x0, y1 - y0)
    cr = cairo.Context(surf)
    cr.translate(-x0, -y0)
    chapter_title(cr, fig, name, color)
    surf.write_to_png(path)
    return x0, y0


def card_png(fig, w, h, path):
    """The title card: the label (title and number, if given) and the caption."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.set_source_rgb(*S.card_background)
    cr.paint()
    width = w * 0.68
    z = fig.size
    num = F.make_layout(cr, fig.heading(), F.font(F.SANS_BOLD, h * 0.05 * z))
    cap = F.make_layout(cr, fig.caption.strip(), F.font(F.SERIF, h * 0.058 * z), width=width,
                        align=Pango.Alignment.LEFT)
    nw, nh = F.size(num) if fig.heading() else (0, 0)
    cw, ch = F.size(cap)
    gap = h * 0.03 if fig.heading() and fig.caption.strip() else 0
    top = (h - (nh + gap + ch)) / 2
    left = (w - width) / 2
    cr.set_source_rgb(*S.card_rule)
    cr.rectangle(left, top - h * 0.035, h * 0.06, max(2, h * 0.006))
    cr.fill()
    cr.set_source_rgb(*(S.card_heading or F.ACCENT))
    cr.move_to(left, top)
    PangoCairo.show_layout(cr, num)
    cr.set_source_rgb(*S.card_text)
    cr.move_to(left, top + nh + gap)
    PangoCairo.show_layout(cr, cap)
    surf.write_to_png(path)


def chapters_card_png(fig, rows, w, h, path):
    """The chapters card: each chapter's colour, name and its time in the
    exported file (as a player shows it), one per line."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    cr.set_source_rgb(*S.card_background)
    cr.paint()
    width = w * 0.68
    left = (w - width) / 2
    z = fig.size
    while True:                                   # shrink until the list fits the frame
        head = F.make_layout(cr, "Chapters", F.font(F.SANS_BOLD, h * 0.05 * z))
        lays = [(F.make_layout(cr, name, F.font(F.SERIF, h * 0.045 * z)),
                 F.make_layout(cr, f"{int(t // 60)}:{int(t % 60):02d}", F.font(F.SANS_SEMI, h * 0.035 * z)), col)
                for name, t, col in rows]
        hh = F.size(head)[1]
        rh = max([F.size(a)[1] for a, _, _ in lays] or [0]) * 1.35
        tall = hh + h * 0.04 + rh * len(lays)
        if tall <= h * 0.86 or z < 0.3:
            break
        z *= 0.9
    top = (h - tall) / 2
    cr.set_source_rgb(*S.card_rule)
    cr.rectangle(left, top - h * 0.035, h * 0.06, max(2, h * 0.006))
    cr.fill()
    cr.set_source_rgb(*(S.card_heading or S.card_text))
    cr.move_to(left, top)
    PangoCairo.show_layout(cr, head)
    y = top + hh + h * 0.04
    mark = rh * 0.28
    for name, when, col in lays:
        nw, nh = F.size(name)
        cr.set_source_rgb(*F.PALETTE[col % len(F.PALETTE)][1])
        cr.rectangle(left, y + nh / 2 - mark / 2, mark, mark)
        cr.fill()
        name.set_width(int((width - mark * 2 - F.size(when)[0] - h * 0.03) * Pango.SCALE))
        name.set_ellipsize(Pango.EllipsizeMode.END)
        cr.set_source_rgb(*S.card_text)
        cr.move_to(left + mark * 2, y)
        PangoCairo.show_layout(cr, name)
        tw, th = F.size(when)
        cr.set_source_rgb(*S.card_times)
        cr.move_to(left + width - tw, y + (nh - th) / 2)
        PangoCairo.show_layout(cr, when)
        y += rh
    surf.write_to_png(path)


def clip_chapters(chapters, t_in, t_out):
    """The chapters inside the trim, as (name, seconds into the clip, colour).
    One that starts before the trim still holds at its start, so it is kept
    there; any earlier ones are covered by it and dropped."""
    out = []
    for ch in sorted(chapters, key=lambda c: c["t"]):
        t = ch["t"] - t_in
        if ch["t"] >= t_out - 0.05:
            break
        row = (ch["name"], max(0.0, t), ch.get("color", 0))
        if out and out[-1][1] == 0.0 and row[1] == 0.0:
            out[-1] = row
        else:
            out.append(row)
    return out


def ffmeta_escape(v):
    return re.sub(r"([=;#\\\n])", r"\\\1", v)


def chapters_meta(marks, total, path):
    """An ffmetadata file of chapters: (title, start) in output seconds."""
    lines = [";FFMETADATA1"]
    for i, (title, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else total
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}",
                  f"END={int(end * 1000)}", f"title={ffmeta_escape(title)}"]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def render(path, info, fig, t_in, t_out, out, fmt, card=False, sound=True, progress=print, chapters=(),
           titles=False):
    tmp = tempfile.mkdtemp(prefix="clip-")
    try:
        return _render(tmp, path, info, fig, t_in, t_out, out, fmt, card, sound, progress, chapters, titles)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _render(tmp, path, info, fig, t_in, t_out, out, fmt, card, sound, progress, chapters=(), titles=False):
    w, h, fps = info["w"], info["h"], info["fps"]
    L = t_out - t_in
    fig.key_entries()
    args = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
            "-ss", f"{t_in:.3f}", "-to", f"{t_out:.3f}", "-i", path]
    inputs = 1
    chain = []
    cur = "[0:v]"
    n = 0

    def label():
        nonlocal n
        n += 1
        return f"[v{n}]"

    items = []
    for it in fig.items:
        a, b = it.get("t0", 0) - t_in, it.get("t1", info["dur"]) - t_in
        a, b = max(0.0, a), min(L, b)
        if b - a > 0.05:
            items.append((it, a, b))
    enable = lambda a, b: f"enable='between(t,{a:.3f},{b:.3f})'"  # noqa: E731

    def fades(a, b):
        f = min(FADE, (b - a) / 3)
        return (f"fade=t=in:st={a:.3f}:d={f:.3f}:alpha=1,"
                f"fade=t=out:st={max(a, b - f):.3f}:d={f:.3f}:alpha=1")

    # live-picture effects first: redactions, then zoom magnifications
    for it, a, b in items:
        if it["kind"] == "redact":
            x0, y0, x1, y1 = [int(round(v)) for v in F.norm(it["x0"], it["y0"], it["x1"], it["y1"])]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            rw, rh = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
            if rw < 4 or rh < 4:
                continue
            blk = max(6, int(9 * fig.k))
            base, src, pix, nxt = label(), label(), label(), label()
            chain.append(f"{cur}split{base}{src}")
            chain.append(f"{src}crop={rw}:{rh}:{x0}:{y0},scale={max(1, rw // blk)}:{max(1, rh // blk)},"
                         f"scale={rw}:{rh}:flags=neighbor{pix}")
            chain.append(f"{base}{pix}overlay={x0}:{y0}:{enable(a, b)}{nxt}")
            cur = nxt
    for it, a, b in items:
        if it["kind"] == "zoom":
            scx, scy, rs, cx, cy, r = fig.zoom_geom(it)
            side = max(2, int(round(2 * rs)))
            sx = int(round(min(max(0, scx - rs), w - side)))
            sy = int(round(min(max(0, scy - rs), h - side)))
            d = max(2, int(round(2 * r)) // 2 * 2)
            R = d / 2
            base, src, mag, nxt = label(), label(), label(), label()
            chain.append(f"{cur}split{base}{src}")
            chain.append(f"{src}crop={min(side, w)}:{min(side, h)}:{sx}:{sy},scale={d}:{d},format=rgba,"
                         f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                         f"a='if(lte(hypot(X-{R - 0.5},Y-{R - 0.5}),{R}),255,0)',{fades(a, b)}{mag}")
            chain.append(f"{base}{mag}overlay={int(round(cx - R))}:{int(round(cy - R))}:{enable(a, b)}{nxt}")
            cur = nxt
    # every mark's own drawing, as a still layer that fades in and out
    for i, (it, a, b) in enumerate(items):
        if it["kind"] == "redact":
            continue
        png = os.path.join(tmp, f"layer{i}.png")
        pos = layer_png(fig, it, png)
        if not pos:
            continue
        args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{L:.3f}", "-i", png]
        li = inputs
        inputs += 1
        lay, nxt = label(), label()
        chain.append(f"[{li}:v]format=rgba,{fades(a, b)}{lay}")
        chain.append(f"{cur}{lay}overlay={pos[0]}:{pos[1]}:{enable(a, b)}:eof_action=pass{nxt}")
        cur = nxt
    # each chapter's title, for a few seconds from its start
    rows = clip_chapters(chapters, t_in, t_out)
    for i, (name, a, col) in enumerate(rows if titles else []):
        b = min(L, a + CHAPTER_SHOW)
        if b - a < 0.3:
            continue
        png = os.path.join(tmp, f"title{i}.png")
        x, y = chapter_title_png(fig, name, col, png)
        args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{L:.3f}", "-i", png]
        lay, nxt = label(), label()
        chain.append(f"[{inputs}:v]format=rgba,{fades(a, b)}{lay}")
        chain.append(f"{cur}{lay}overlay={x}:{y}:{enable(a, b)}:eof_action=pass{nxt}")
        inputs += 1
        cur = nxt
    # even size, constant frame rate
    nxt = label()
    chain.append(f"{cur}scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={fps:g},format=yuv420p,setsar=1{nxt}")
    cur = nxt
    audio = info["audio"] and sound and fmt != "gif"
    # the sound with its timestamps made continuous from 0: a recording's
    # gaps or late start would otherwise slide it against the picture
    acur = None
    if audio:
        chain.append("[0:a]aresample=async=1:first_pts=0[a0]")
        acur = "[a0]"
    # what comes before the clip: the title card, then the chapters card,
    # each cross-fading into the next
    intro = []
    title = card and (fig.caption.strip() or fig.heading())
    lens = ([CARD] if title else []) + ([min(6.0, 2.2 + 0.45 * len(rows))] if rows else [])
    lead = sum(lens) - XFADE * len(lens)     # where the clip will begin
    if title:
        png = os.path.join(tmp, "card.png")
        card_png(fig, w // 2 * 2, h // 2 * 2, png)
        intro.append((png, lens[0]))
    if rows:
        png = os.path.join(tmp, "chapters.png")
        chapters_card_png(fig, [(nm, lead + t, c) for nm, t, c in rows], w // 2 * 2, h // 2 * 2, png)
        intro.append((png, lens[-1]))
    start = 0.0                              # where the clip itself begins in the output
    if intro:
        segs = []
        for png, d in intro:
            args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{d:.3f}", "-i", png]
            sv = label()
            chain.append(f"[{inputs}:v]fps={fps:g},format=yuv420p,setsar=1{sv}")
            inputs += 1
            segs.append((sv, d))
        segs.append((cur, L))
        acc_v, acc = segs[0][0], segs[0][1]
        for sv, d in segs[1:]:
            off = acc - XFADE
            nxt = label()
            chain.append(f"{acc_v}{sv}xfade=transition=fade:duration={XFADE}:offset={off:.3f}{nxt}")
            acc_v, acc = nxt, off + d
            start = off
        cur = acc_v
    total = start + L
    if audio and start > 0:
        chain.append(f"{acur}adelay={int(start * 1000)}:all=1,apad=whole_dur={total:.3f}[a1]")
        acur = "[a1]"
    meta = None
    if rows and fmt in ("mp4", "webm"):
        marks = [(name, start + t) for name, t, _ in rows]
        if start > 0 and marks[0][1] > 0.05:
            marks.insert(0, ("Intro", 0.0))
        elif marks[0][1] <= 0.05:
            marks[0] = (marks[0][0], 0.0)
        meta = os.path.join(tmp, "chapters.txt")
        chapters_meta(marks, total, meta)
    if fmt == "gif":
        nxt = label()
        chain.append(f"{cur}fps=15,scale='min(960,iw)':-2:flags=lanczos,split[g0][g1];"
                     f"[g0]palettegen=stats_mode=diff[pal];[g1][pal]paletteuse=dither=bayer:bayer_scale=4{nxt}")
        cur = nxt
    if meta:
        args += ["-f", "ffmetadata", "-i", meta]
        args += ["-map_chapters", str(inputs)]
        inputs += 1
    args += ["-filter_complex", ";".join(chain), "-map", cur]
    if acur:
        args += ["-map", acur]
    if fmt == "mp4":
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart"]
        if acur:
            args += ["-c:a", "aac", "-b:a", "160k"]
    elif fmt == "webm":
        args += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                 "-cpu-used", "4"]
        if acur:
            args += ["-c:a", "libopus", "-b:a", "128k"]
    args += ["-t", f"{total:.3f}", out]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        m = re.match(r"out_time_us=(\d+)", line)
        if m:
            pct = min(100, int(int(m.group(1)) / 1e6 / max(total, 0.01) * 100))
            progress(f"Exporting {fmt.upper()}... {pct}%")
    err = p.stderr.read()
    if p.wait() != 0:
        raise RuntimeError(err.strip() or "ffmpeg failed")
    return out


def newest_video(folder):
    try:
        names = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(VIDEO_EXTS)]
    except OSError:
        return None
    return max(names, key=os.path.getmtime) if names else None


def choose_video(parent=None, folder=None):
    """The system's file picker on the recordings folder; None if cancelled."""
    d = Gtk.FileChooserNative.new("Open a screen recording", parent, Gtk.FileChooserAction.OPEN, "Open", "Cancel")
    flt = Gtk.FileFilter()
    flt.set_name("Videos")
    for ext in VIDEO_EXTS:
        flt.add_pattern("*" + ext)
        flt.add_pattern("*" + ext.upper())
    d.add_filter(flt)
    folder = folder or S.recordings
    if os.path.isdir(folder):
        d.set_current_folder(folder)
    ok = d.run() == Gtk.ResponseType.ACCEPT
    path = d.get_filename() if ok else None
    d.destroy()
    return path


def error_dialog(text):
    from .__main__ import fail
    fail(text)


def edit(path, fresh=False):
    """One editing session; the next video to open (Ctrl+O), or None."""
    try:
        info = probe(path)
    except (subprocess.CalledProcessError, StopIteration, KeyError, ValueError):
        error_dialog(f"{os.path.basename(path)} doesn't look like a video ffmpeg can read.")
        return None
    ed = ClipEditor(path, info, None if fresh else load_session(path))
    ed.reopen = None
    ed.show_all()
    ed.area.grab_focus()
    ed.frames.thumbs(60)
    if info["audio"]:
        ed.frames.waveform(ed.got_wave)
    ed.queue()
    if ed.welcome:
        ed.flash(ed.welcome)
    Gtk.main()
    ed.destroy()
    return ed.reopen


def run(paths, fresh=False):
    GLib.set_prgname("Clip")
    GLib.set_application_name("Clip")
    path = paths[0] if paths else choose_video()
    while path:
        path = edit(path, fresh)
        fresh = False
    return 0
