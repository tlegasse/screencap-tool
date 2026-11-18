"""The editor's export and timing, without a display: run with
`make test` (needs ffmpeg and PyGObject with pycairo; skipped without)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def have_gi():
    r = subprocess.run([sys.executable, "-c", "import cairo, gi; gi.require_version('Gtk', '3.0');"
                        "gi.require_version('PangoCairo', '1.0'); from gi.repository import Gtk, PangoCairo"],
                       capture_output=True)
    return r.returncode == 0


OK = bool(shutil.which("ffmpeg") and shutil.which("ffprobe")) and have_gi()


def run_py(code, env=None):
    """Run code with clip.editor as C and clip.figure as F; its last stdout line as JSON."""
    head = "import sys, json; from clip import editor as C; F = C.F\n"
    e = {**os.environ, "PYTHONPATH": ROOT, "CLIP_CONFIG": os.devnull + ".none", **(env or {})}
    r = subprocess.run([sys.executable, "-c", head + code], capture_output=True, text=True, timeout=120, env=e)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_streams", "-show_format",
                        "-of", "json", path], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@unittest.skipUnless(OK, "needs ffmpeg and PyGObject")
class Clip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="clip-test-")
        cls.src = os.path.join(cls.tmp, "in.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.src],
                       check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_size_scales_every_mark_together(self):
        out = run_py("f = F.Figure(surface=C.cairo.ImageSurface(C.cairo.FORMAT_ARGB32, 1280, 720)); k = f.k;"
                     "f.size = 2.0; k2 = f.k; g = F.Figure(surface=C.cairo.ImageSurface(C.cairo.FORMAT_ARGB32, 10, 10));"
                     "g.k = k2; print(json.dumps([k, k2, g.k, g.size]))")
        k, k2, gk, gsize = out
        self.assertAlmostEqual(k2, 2 * k)
        self.assertAlmostEqual(gk, k2)
        self.assertEqual(gsize, 1.0)

    def test_sound_clock_from_ffplay_stats(self):
        out = run_py("print(json.dumps([C.parse_clock(b'   1.23 M-A:  0.000 fd=   0'),"
                     "C.parse_clock(b'nan    :  0.000'), C.parse_clock(b'  -0.05 M-A: 0.0')]))")
        self.assertEqual(out, [1.23, None, -0.05])

    def test_chapters_inside_the_trim(self):
        out = run_py("print(json.dumps(C.clip_chapters(["
                     "{'t': 0.5, 'name': 'gone', 'color': 0}, {'t': 1.0, 'name': 'held', 'color': 1},"
                     "{'t': 3.0, 'name': 'mid', 'color': 2}, {'t': 9.0, 'name': 'after', 'color': 3}], 2.0, 5.0)))")
        self.assertEqual(out, [["held", 0.0, 1], ["mid", 1.0, 2]])

    def test_export_with_title_card_and_chapters(self):
        dst = os.path.join(self.tmp, "out.mp4")
        info = run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']);"
                      "fig.caption = 'A test; with = signs'; fig.size = 1.5;"
                      "chs = [{'t': 1.0, 'name': 'One', 'color': 0}, {'t': 3.5, 'name': 'Two; #2', 'color': 1}];"
                      f"C.render({self.src!r}, info, fig, 1.0, 5.0, {dst!r}, 'mp4', card=True,"
                      " progress=lambda *_: None, chapters=chs); print(json.dumps(info))")
        p = probe(dst)
        n = 2
        chap_card = min(6.0, 2.2 + 0.45 * n)
        start = (2.6 - 0.45) + chap_card - 0.45
        total = start + 4.0
        self.assertAlmostEqual(float(p["format"]["duration"]), total, delta=0.15)
        streams = {s["codec_type"]: s for s in p["streams"]}
        self.assertAlmostEqual(float(streams["audio"]["duration"]), float(streams["video"]["duration"]),
                               delta=0.1)
        titles = [c["tags"]["title"] for c in p["chapters"]]
        self.assertEqual(titles, ["Intro", "One", "Two; #2"])
        self.assertAlmostEqual(float(p["chapters"][1]["start_time"]), start, delta=0.01)
        self.assertAlmostEqual(float(p["chapters"][2]["start_time"]), start + 2.5, delta=0.01)
        self.assertTrue(info["audio"])

    def test_every_mark_kind_renders(self):
        dst = os.path.join(self.tmp, "marks.mp4")
        run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']);"
               "fig.items = ["
               "{'kind': 'label', 'color': 0, 'ax': 40, 'ay': 40, 'lx': 120, 'ly': 30, 'text': 'here', 't0': 0, 't1': 2},"
               "{'kind': 'marker', 'color': 1, 'x': 60, 'y': 120, 'text': 'one', 't0': 0, 't1': 3},"
               "{'kind': 'arrow', 'color': 2, 'x0': 10, 'y0': 200, 'x1': 100, 'y1': 150, 't0': 1, 't1': 4},"
               "{'kind': 'box', 'color': 3, 'x0': 150, 'y0': 100, 'x1': 220, 'y1': 160, 'text': 'tag', 't0': 0, 't1': 5},"
               "{'kind': 'highlight', 'color': 0, 'x0': 20, 'y0': 20, 'x1': 200, 'y1': 35, 't0': 0, 't1': 5},"
               "{'kind': 'brace', 'color': 4, 'x0': 280, 'y0': 40, 'x1': 280, 'y1': 140, 'text': 'b', 't0': 0, 't1': 5},"
               "{'kind': 'zoom', 'color': 0, 'sx0': 10, 'sy0': 10, 'sx1': 40, 'sy1': 40, 'cx': 200, 'cy': 200, 'r': 30, 't0': 0, 't1': 5},"
               "{'kind': 'note', 'color': 1, 'x': 180, 'y': 20, 'text': 'a note', 't0': 2, 't1': 5},"
               "{'kind': 'redact', 'color': 0, 'x0': 100, 'y0': 180, 'x1': 160, 'y1': 230, 't0': 0, 't1': 5}];"
               f"C.render({self.src!r}, info, fig, 0.0, 5.0, {dst!r}, 'mp4', progress=lambda *_: None);"
               "print('[]')")
        self.assertAlmostEqual(float(probe(dst)["format"]["duration"]), 5.0, delta=0.15)

    def test_chapter_titles_show_for_a_while(self):
        dst = os.path.join(self.tmp, "titles.mp4")
        run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']);"
               f"C.render({self.src!r}, info, fig, 0.0, 6.0, {dst!r}, 'mp4', progress=lambda *_: None,"
               " chapters=[{'t': 0.0, 'name': 'Start', 'color': 1}], titles=True); print('[]')")

        def pixel(t):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", dst, "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
            x, y = 40, 240 - 28 - 6
            return raw[(y * 320 + x) * 3:(y * 320 + x) * 3 + 3]
        start = min(6.0, 2.2 + 0.45) - 0.45
        self.assertTrue(all(c > 215 for c in pixel(start + 1.5)), pixel(start + 1.5))
        self.assertFalse(all(c > 215 for c in pixel(start + 5.0)), pixel(start + 5.0))

    def test_card_uses_the_configured_background(self):
        cfg = os.path.join(self.tmp, "paper.toml")
        with open(cfg, "w") as f:
            f.write('[colors]\npaper = "#ffffff"\n[cards]\nbackground = "#203040"\n')
        dst = os.path.join(self.tmp, "paper.mp4")
        run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']); fig.caption = 'x';"
               f"C.render({self.src!r}, info, fig, 0.0, 2.0, {dst!r}, 'mp4', card=True,"
               " progress=lambda *_: None); print('[]')", env={"CLIP_CONFIG": cfg})
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", dst, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        r, g, b = raw[(5 * 320 + 5) * 3:(5 * 320 + 5) * 3 + 3]
        self.assertTrue(abs(r - 0x20) < 12 and abs(g - 0x30) < 12 and abs(b - 0x40) < 12, (r, g, b))

    def test_chapter_title_colours_from_the_config(self):
        cfg = os.path.join(self.tmp, "titles.toml")
        with open(cfg, "w") as f:
            f.write('[chapter_titles]\nbackground = "#102030"\n')
        dst = os.path.join(self.tmp, "titles-coloured.mp4")
        run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']);"
               f"C.render({self.src!r}, info, fig, 1.0, 6.0, {dst!r}, 'mp4', progress=lambda *_: None,"
               " chapters=[{'t': 1.0, 'name': 'Start', 'color': 1}], titles=True); print('[]')",
               env={"CLIP_CONFIG": cfg})
        start = min(6.0, 2.2 + 0.45) - 0.45
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start + 1.5), "-i", dst, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        x, y = 40, 240 - 28 - 6
        r, g, b = raw[(y * 320 + x) * 3:(y * 320 + x) * 3 + 3]
        self.assertTrue(abs(r - 0x10) < 14 and abs(g - 0x20) < 14 and abs(b - 0x30) < 14, (r, g, b))

    def test_gif_has_no_chapters_and_still_renders(self):
        dst = os.path.join(self.tmp, "out.gif")
        run_py(f"info = C.probe({self.src!r}); fig = C.ClipFigure(info['w'], info['h']);"
               f"C.render({self.src!r}, info, fig, 0.0, 2.0, {dst!r}, 'gif', progress=lambda *_: None,"
               " chapters=[{'t': 0.5, 'name': 'x', 'color': 0}]); print('[]')")
        self.assertTrue(os.path.getsize(dst) > 0)

    def test_sessions_round_trip_and_exports_get_unique_names(self):
        out = run_py(f"import os; v = {self.src!r};"
                     "C.save_session(v, {'items': [], 't_in': 1.5}); s = C.load_session(v);"
                     f"d = {self.tmp!r}; a = C.export_path(v, d, 'mp4'); open(a, 'w').close();"
                     "b = C.export_path(v, d, 'mp4'); print(json.dumps([s['t_in'], os.path.basename(a),"
                     " os.path.basename(b)]))", env={"XDG_STATE_HOME": self.tmp})
        self.assertEqual(out, [1.5, "in (annotated).mp4", "in (annotated) 2.mp4"])


if __name__ == "__main__":
    unittest.main()
