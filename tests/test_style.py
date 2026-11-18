"""The config file and the per-platform commands; no display or ffmpeg needed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clip import desktop, style  # noqa: E402

FONTS = {"helvetica neue", "charter", "georgia", "arial"}


def load(text):
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
    try:
        return style.load(f.name, installed=FONTS)
    finally:
        os.unlink(f.name)


class Config(unittest.TestCase):
    def test_no_file_is_the_defaults(self):
        s = style.load("/nonexistent/config.toml", installed=FONTS)
        self.assertEqual([n for n, _ in s.palette], ["blue", "red", "green", "ochre", "ink"])
        self.assertEqual(s.format, "mp4")

    def test_fonts_fall_back_to_the_first_installed(self):
        s = style.load("/nonexistent/config.toml", installed=FONTS)
        self.assertEqual((s.sans, s.serif), ("Helvetica Neue", "Charter"))
        s = load('[fonts]\nsans = "Nope, Arial"\nserif = ["Georgia"]\n')
        self.assertEqual((s.sans, s.serif), ("Arial", "Georgia"))

    def test_colours_override_and_keep_the_rest(self):
        s = load('[colors]\npaper = "#000"\npalette = { teal = "#2c8a7e", pink = "#ff69b4" }\n')
        self.assertEqual(s.paper, (0, 0, 0))
        self.assertEqual([n for n, _ in s.palette], ["teal", "pink"])
        self.assertEqual(s.hex["ink"], "#1f2329")

    def test_bad_values_say_which_setting(self):
        with self.assertRaisesRegex(style.ConfigError, "colors.palette.red"):
            load('[colors]\npalette = { red = "crimson" }\n')
        with self.assertRaisesRegex(style.ConfigError, "export.format"):
            load('[export]\nformat = "avi"\n')
        with self.assertRaisesRegex(style.ConfigError, "1 to 9"):
            load('[colors]\npalette = {}\n')

    def test_the_example_config_is_the_defaults(self):
        ex = style.read_config(os.path.join(style.ROOT, "config.example.toml"))
        self.assertEqual(ex["colors"], style.DEFAULTS["colors"])
        self.assertEqual(ex["fonts"], style.DEFAULTS["fonts"])
        self.assertEqual(ex["export"], style.DEFAULTS["export"])
        self.assertEqual(ex["cards"], style.DEFAULTS["cards"])
        self.assertEqual(ex["chapter_titles"], style.DEFAULTS["chapter_titles"])

    def test_card_colours_follow_the_page_unless_set(self):
        s = load('[colors]\npaper = "#111111"\n')
        self.assertEqual(s.card_background, s.paper)
        self.assertEqual(s.card_text, s.ink)
        self.assertIsNone(s.card_heading)
        self.assertIsNone(s.title_background)
        s = load('[cards]\nbackground = "#000000"\nheading = "#ff0000"\n[chapter_titles]\ntext = "#fff"\n')
        self.assertEqual((s.card_background, s.card_heading, s.title_text), ((0, 0, 0), (1, 0, 0), (1, 1, 1)))
        with self.assertRaisesRegex(style.ConfigError, "cards.text"):
            load('[cards]\ntext = "white"\n')


class Desktop(unittest.TestCase):
    def test_mac_passes_paths_as_arguments_not_script(self):
        path = '/Users/x/Movies/a "quoted" name.mp4'
        argv, data = desktop.copy_commands(path, mac=True)
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[-1], path)
        self.assertFalse(any(path in a for a in argv[:-1]))
        self.assertIsNone(data)
        self.assertEqual(desktop.reveal_command(path, mac=True), ["open", "-R", path])

    def test_linux_clipboard_prefers_wayland_then_x(self):
        everything = lambda name: "/usr/bin/" + name  # noqa: E731
        argv, data = desktop.copy_commands("/a b.mp4", mac=False, env={"WAYLAND_DISPLAY": "w"}, have=everything)
        self.assertEqual(argv[0], "wl-copy")
        self.assertEqual(data, b"file:///a%20b.mp4\n")
        argv, _ = desktop.copy_commands("/a.mp4", mac=False, env={}, have=everything)
        self.assertEqual(argv[0], "xclip")
        self.assertIsNone(desktop.copy_commands("/a.mp4", mac=False, env={}, have=lambda n: None))

    def test_png_goes_on_the_clipboard_as_a_picture(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG fake")
        try:
            everything = lambda name: "/usr/bin/" + name  # noqa: E731
            argv, data = desktop.copy_commands(f.name, mac=False, env={}, have=everything)
            self.assertEqual(argv[-1], "image/png")
            self.assertEqual(data, b"\x89PNG fake")
            argv, data = desktop.copy_commands(f.name, mac=True)
            self.assertIn("PNGf", " ".join(argv))
            self.assertEqual(argv[-1], f.name)
        finally:
            os.unlink(f.name)

    def test_folders(self):
        self.assertTrue(desktop.default_clips(mac=True).endswith("Movies/Clips"))
        self.assertTrue(desktop.state_dir(mac=True).endswith("Application Support/Clip"))


if __name__ == "__main__":
    unittest.main()
