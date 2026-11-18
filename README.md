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

## Install on a Mac

1. Download this folder (Code → Download ZIP, then unzip it) or `git clone` it.
2. Open Terminal, `cd` into the folder, and run:

   ```sh
   ./install.sh
   ```

   Or double-click **Install Clip.command**. If macOS says it's from an
   unidentified developer, right-click it and choose Open.

The installer:

- installs [Homebrew](https://brew.sh) if you don't have it (it asks first, and
  Homebrew asks for your password);
- runs `brew install ffmpeg gtk+3 pygobject3 adwaita-icon-theme` and the
  optional Fira Sans font (the first run takes a few minutes);
- copies Clip to `~/Library/Application Support/Clip/app` (you can delete the
  downloaded folder afterwards);
- makes **~/Applications/Clip.app**: double-click it to pick a recording, or
  drag it to the Dock and drop videos onto it;
- links `~/.local/bin/clip` for terminal use;
- runs `clip --check`.

To update, run `./install.sh` again from a newer copy. To remove Clip, run
`./install.sh --uninstall` (your settings and exports stay).

Recordings from ⌘⇧5 / QuickTime (`.mov`) open as they are. The file picker
starts in the folder your Mac saves screen recordings to.

## Install on Linux

You need `ffmpeg` and PyGObject with GTK 3 and pycairo from your package
manager (`install.sh` lists the package names if any are missing). Then run
`./install.sh`, or run `bin/clip` straight from this folder.

## Use

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
| K | chapter at the playhead |
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

Run `clip --edit-config`. It creates `~/.config/clip/config.toml` from
[`clip/config.example.toml`](clip/config.example.toml), which lists every
setting with its default, and opens it. All keys are optional. For example:

```toml
[colors]
palette = { teal = "#2c8a7e", pink = "#d6336c", navy = "#1c2c5b" }   # keys 1, 2, 3
paper = "#ffffff"

[fonts]
sans = ["Inter", "Helvetica Neue"]
serif = ["Georgia"]

[export]
folder = "~/Desktop/Clips"
format = "gif"
reveal = true
```

- `palette` holds 1 to 9 named colours, in key order.
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
  session); `install.sh` and `--uninstall` into a scratch home; a bad config
  value giving a clear error.
- **Not run on a Mac yet**: the Homebrew install, the `osacompile` app,
  Cmd shortcuts, the clipboard / notification AppleScript, and how the GTK
  window looks there. If something is off, `~/Library/Logs/Clip.log` and
  `clip --check` are the first places to look.
- The window is GTK, so on a Mac it looks like a Linux app rather than a
  native one. It opens as "Python" in the Dock.
