# Clip

Annotate a screen recording, textbook style, and export it as MP4, GIF or WebM.

Open a recording, then drop labels, numbered markers, arrows, boxes, highlights,
braces, zoom insets, notes and redactions onto it. Each mark shows for 3 seconds
from the playhead; drag its bar on the timeline to change when. You can trim
the ends, add chapters (they become real chapters in the MP4), and open with a
title card. Enter exports, and the file lands on the clipboard.

Clip started as `clip.py` / `figure.py` in a set of Linux dotfiles. This is the
same editor, standalone: it has no other dependencies, works on macOS, and its
colours and fonts are configurable.

## Set up a Mac

1. Download this folder (Code → Download ZIP, then unzip it) or `git clone` it,
   and keep it wherever you like. Clip runs from here.
2. Open Terminal, `cd` into the folder, and run:

   ```sh
   ./setup.sh
   ```

   Or double-click **Set up this Mac.command**. If macOS says it's from an
   unidentified developer, right-click it and choose Open.

`setup.sh` only prepares the machine. It doesn't install Clip anywhere. It:

- installs [Homebrew](https://brew.sh) if you don't have it (it asks first, and
  Homebrew asks for your password);
- runs `brew install ffmpeg gtk+3 pygobject3 adwaita-icon-theme` and the
  optional Fira Sans font (the first run takes a few minutes);
- writes the settings file `~/.config/clip/config.toml` with every setting at
  its default, unless one is already there;
- runs `bin/clip --check`.

Running it again is safe. It updates nothing that's already in place.

Then start Clip from the folder: double-click **Open Clip.command**, or run
`bin/clip` in Terminal (`bin/clip VIDEO` to open a file directly). To update
Clip, replace the folder with a newer copy. Your settings and saved sessions
live outside it.

Recordings from ⌘⇧5 / QuickTime (`.mov`) open as they are. The file picker
starts in the folder your Mac saves screen recordings to.

## Set up Linux

You need `ffmpeg` and PyGObject with GTK 3 and pycairo from your package
manager. `./setup.sh` checks for them, lists the package names for any that
are missing, and writes the settings file. Then run `bin/clip`.

## Use

Inside the folder `clip` is `bin/clip` (or put `bin/` on your PATH):

```
clip                 pick a recording
clip VIDEO           open that one
clip --latest        the newest video in the recordings folder
clip --fresh VIDEO   ignore the marks kept from last time
clip --keys          every key
clip --check         what's installed, which fonts and folders are used
clip --edit-config   create the settings file and open it
```

The most-used keys (on a Mac, Cmd works wherever Ctrl is listed):

| Key | |
|---|---|
| L N A B H C Z T X V | label, marker, arrow, box, highlight, brace, zoom, note, redact, select |
| 1–5 | colour |
| Space | play / pause |
| ← → (Shift: 1 s) | step a frame |
| I / O | trim start / end at the playhead |
| K (or **+ Chapter**) | chapter at the playhead |
| - / + | size of every mark |
| Ctrl+Z / Ctrl+Shift+Z | undo / redo |
| Ctrl+O | open another recording |
| Enter | export and close |
| Ctrl+S / Ctrl+Shift+S | export and keep working / export to a new file |
| Esc | close |

Exports go to `~/Movies/Clips` (Mac) or `~/Videos/Clips` (Linux) as
`<recording> (annotated).mp4`. The original recording is never changed.

Clip keeps your marks, trim, chapters and undo history for each recording, so
reopening one picks up where you left off. It stores them in
`~/Library/Application Support/Clip/sessions` on a Mac and
`~/.local/state/clip/sessions` on Linux. Enter then re-exports over the same
file; Ctrl+Shift+S writes a new one.

## Colours and fonts

Edit `~/.config/clip/config.toml`. `setup.sh` writes it from
[`clip/config.example.toml`](clip/config.example.toml), which lists every
setting with its default. `clip --edit-config` opens it, and creates it first
if it's missing. All keys are optional. For example:

```toml
[colors]
palette = { teal = "#2c8a7e", pink = "#d6336c", navy = "#1c2c5b" }   # keys 1, 2, 3
paper = "#ffffff"

[fonts]
sans = ["Inter", "Helvetica Neue"]
serif = ["Georgia"]

[cards]                       # title card and chapters card
background = "#1c2c5b"
text = "#ffffff"
heading = "#ffd84d"

[chapter_titles]              # the chapter name banner on the picture
background = "#000000"
text = "#ffffff"

[export]
folder = "~/Desktop/Clips"
format = "gif"
reveal = true
```

- `palette` holds 1 to 9 named colours, in key order.
- `[cards]` and `[chapter_titles]` colour what Clip generates: the title card,
  the chapters card and the chapter banner. Anything left blank follows
  `[colors]`.
- Each font setting is a list of families; Clip uses the first one installed.
- Set `CLIP_CONFIG=/path/to/file.toml` to use a different settings file.
- `clip --check` names any bad value and shows which fonts were picked.

## How it's built

- `clip/figure.py` draws the marks (cairo + Pango) and holds the base editor
  window (GTK 3).
- `clip/editor.py` holds the video editor: timeline, preview playback through
  ffmpeg (sound through ffplay), sessions, and the export, which renders each
  mark to a PNG and composites them with one ffmpeg filter graph.
- `clip/style.py` reads the settings; `clip/desktop.py` handles the Mac / Linux
  differences (clipboard, notifications, folders).
- `bin/clip` finds a Python that has GTK (Homebrew's on a Mac) and runs
  `python -m clip`.

## Tests

```sh
make test
```

The tests cover export timing, chapters, title cards, every mark kind, a
configured colour reaching the output, sessions, the settings file and the
per-platform commands. They need ffmpeg and PyGObject and use no display.

## What's checked, and what isn't

- Checked on Linux: the test suite; the editor driven through its own input
  handlers (draw, type, trim, chapter, undo / redo, export, reopen with the
  session); `setup.sh` in a scratch home (writes the settings file once,
  keeps it on a second run); a bad config value giving a clear error.
- **Not run on a Mac yet**: the Homebrew setup, `Open Clip.command`, Cmd
  shortcuts, the clipboard / notification AppleScript, and how the GTK window
  looks there. If something is off, run `bin/clip` in Terminal to see its
  errors, and `bin/clip --check`.
- The window is GTK, so on a Mac it looks like a Linux app rather than a
  native one. It opens as "Python" in the Dock.
