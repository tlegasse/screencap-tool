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
        here = os.path.dirname(style.__file__)
        ex = style.read_config(os.path.join(here, "config.example.toml"))
        self.assertEqual(ex["colors"], style.DEFAULTS["colors"])
        self.assertEqual(ex["fonts"], style.DEFAULTS["fonts"])
        self.assertEqual(ex["export"], style.DEFAULTS["export"])


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

    def test_folders(self):
        self.assertTrue(desktop.default_clips(mac=True).endswith("Movies/Clips"))
        self.assertTrue(desktop.state_dir(mac=True).endswith("Application Support/Clip"))


if __name__ == "__main__":
    unittest.main()
