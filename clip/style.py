"""The look: colours, fonts and where files go, from config.toml over the defaults.

The config is config.toml in the Clip folder (or $CLIP_CONFIG). Every key
is optional; config.example.toml beside it lists them all with their defaults.
"""
import copy
import os
import sys

try:
    import tomllib
except ImportError:          # Python < 3.11
    tomllib = None

DEFAULTS = {
    "colors": {
        "palette": {
            "blue": "#1d5fa6",
            "red": "#b8352c",
            "green": "#2e7a4c",
            "ochre": "#c98a12",
            "ink": "#23272e",
        },
        "accent": "#1d5fa6",
        "paper": "#fbf9f4",
        "label_bg": "#fffefb",
        "ink": "#1f2329",
        "ink_soft": "#4a4f57",
        "highlight": "#ffd84d",
        "desk": "#8c8f96",
        "select": "#2f6fed",
        "timeline": "#383a42",
        "playhead": "#b8352c",
        "trim": "#c98a12",
        "waveform": "#7ac799",
    },
    "cards": {
        "background": "",
        "text": "",
        "heading": "",
        "rule": "",
        "times": "",
    },
    "chapter_titles": {
        "background": "",
        "text": "",
        "stripe": "",
    },
    "fonts": {
        "sans": ["Fira Sans", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans", "Sans"],
        "serif": ["C059", "Century Schoolbook", "Charter", "Georgia", "DejaVu Serif", "Serif"],
    },
    "export": {
        "folder": "",
        "format": "mp4",
        "copy_to_clipboard": True,
        "notify": True,
        "reveal": False,
    },
    "open": {
        "folder": "",
    },
}

FORMATS = ("mp4", "gif", "webm")
MAX_COLOURS = 9


class ConfigError(Exception):
    pass


ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def config_path():
    return os.path.expanduser(os.environ.get("CLIP_CONFIG") or os.path.join(ROOT, "config.toml"))


def hexrgb(h, where="colour"):
    s = str(h).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        raise ConfigError(f"{where}: {h!r} is not a colour like \"#1d5fa6\"")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


def optional(value, where):
    """A colour, or None for a blank one (it then follows another setting)."""
    return hexrgb(value, where) if str(value).strip() else None


def merge(base, over, where=""):
    """over's keys onto a copy of base, one level of tables deep at a time;
    a key base doesn't have is reported, not silently kept."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        name = f"{where}.{k}" if where else k
        if k not in base:
            print(f"clip: ignoring unknown setting {name} in {config_path()}", file=sys.stderr)
        elif isinstance(base[k], dict) and isinstance(v, dict) and k != "palette":
            out[k] = merge(base[k], v, name)
        else:
            out[k] = v
    return out


def read_config(path=None):
    path = path or config_path()
    if not os.path.exists(path):
        return {}
    if tomllib is None:
        print("clip: Python 3.11 or newer is needed to read config.toml; using the defaults",
              file=sys.stderr)
        return {}
    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from None


def families(value):
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in value if str(v).strip()]


def installed_families():
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    return {f.get_name().lower() for f in PangoCairo.FontMap.get_default().list_families()}


def pick_family(wanted, installed):
    """The first of the wanted families that's installed (else the last one,
    which Pango will stand in for)."""
    for name in wanted:
        if name.lower() in installed:
            return name
    return wanted[-1] if wanted else "Sans"


class Style:
    def __init__(self, cfg, installed=None):
        c = cfg["colors"]
        pal = c["palette"]
        if not isinstance(pal, dict) or not 1 <= len(pal) <= MAX_COLOURS:
            raise ConfigError(f"colors.palette: give 1 to {MAX_COLOURS} colours, "
                              "like { blue = \"#1d5fa6\", red = \"#b8352c\" }")
        self.palette = [(str(name), hexrgb(v, f"colors.palette.{name}")) for name, v in pal.items()]
        for key in DEFAULTS["colors"]:
            if key != "palette":
                setattr(self, key, hexrgb(c[key], f"colors.{key}"))
        self.hex = {k: "#" + str(v).strip().lstrip("#") for k, v in c.items() if k != "palette"}

        cards = cfg["cards"]
        self.card_background = optional(cards["background"], "cards.background") or self.paper
        self.card_text = optional(cards["text"], "cards.text") or self.ink
        self.card_heading = optional(cards["heading"], "cards.heading")
        self.card_rule = optional(cards["rule"], "cards.rule") or self.accent
        self.card_times = optional(cards["times"], "cards.times") or hexrgb("#6b6b70")
        titles = cfg["chapter_titles"]
        self.title_background = optional(titles["background"], "chapter_titles.background")
        self.title_text = optional(titles["text"], "chapter_titles.text") or self.ink
        self.title_stripe = optional(titles["stripe"], "chapter_titles.stripe")

        if installed is None:
            installed = installed_families()
        f = cfg["fonts"]
        self.sans = pick_family(families(f["sans"]), installed)
        self.serif = pick_family(families(f["serif"]), installed)

        e = cfg["export"]
        fmt = str(e["format"]).lower()
        if fmt not in FORMATS:
            raise ConfigError(f"export.format: {e['format']!r} isn't one of {', '.join(FORMATS)}")
        self.format = fmt
        from . import desktop
        self.clips = os.path.expanduser(e["folder"] or desktop.default_clips())
        self.recordings = os.path.expanduser(cfg["open"]["folder"] or desktop.default_recordings())
        self.copy_to_clipboard = bool(e["copy_to_clipboard"])
        self.notify = bool(e["notify"])
        self.reveal = bool(e["reveal"])


def load(path=None, installed=None):
    return Style(merge(DEFAULTS, read_config(path)), installed)


_current = None


def current():
    global _current
    if _current is None:
        _current = load()
    return _current
