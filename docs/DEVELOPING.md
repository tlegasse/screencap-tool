# Developing Clip

Clip started as `clip.py` / `figure.py` in a set of Linux dotfiles. This is the
same editor as a standalone project: it runs on macOS and Linux, and its
colours and fonts come from a config file.

## Setup

`./setup.sh` prepares the machine only; it doesn't copy Clip anywhere.

- Mac: installs Homebrew if missing (asks first), then
  `brew install ffmpeg gtk+3 pygobject3 adwaita-icon-theme` and the Fira Sans
  font cask.
- Linux: checks for ffmpeg, PyGObject (GTK 3) and pycairo, and lists the
  package names if any are missing.
- Both: write `config.toml` in the Clip folder from `config.example.toml` if
  there isn't one, then run `bin/clip --check`.

## Command line

```
bin/clip                 pick a recording or screenshot
bin/clip FILE            open that one
bin/clip --latest        the newest recording or screenshot in the recordings folder
bin/clip --fresh VIDEO   ignore the session kept from last time
bin/clip --keys          every key
bin/clip --check         what's installed, which fonts and folders are used
bin/clip --edit-config   create the settings file if needed and open it
```

Settings are read from `config.toml` in the Clip folder (git-ignored; setup
writes it). `CLIP_CONFIG=/path/to/file.toml` uses a different file.

## Keys beyond the README

N marker, C brace (F flips it), `[` / `]` set the selected mark's start / end, M sound on/off, - / + size of every mark,
Ctrl+O open another recording, Ctrl+S export and keep working,
Ctrl+Shift+S export to a new file. On a Mac Cmd works wherever Ctrl does.

## Files Clip writes

- Exports: `~/Movies/Clips` (Mac) or `~/Videos/Clips` (Linux), named
  `<recording> (annotated).mp4`; `[export] folder` changes it.
- Sessions (marks, trim, chapters, undo history per recording):
  `~/Library/Application Support/Clip/sessions` (Mac) or
  `~/.local/state/clip/sessions` (Linux).

## Layout

- `clip/figure.py`: drawing the marks (cairo + Pango) and the base editor
  window (GTK 3).
- `clip/shot.py`: the screenshot editor: `figure.py`'s editor on a picture
  (loaded through GdkPixbuf, so JPEG works too), exporting a PNG plate, with
  the same sessions and clipboard as videos. `editor.run` sends a file to
  one editor or the other by its extension.
- `clip/editor.py`: the video editor: timeline, preview through ffmpeg (sound
  through ffplay), sessions, and the export, which renders each mark to a PNG
  and composites them with one ffmpeg filter graph.
- `clip/style.py`: the settings. `clip/desktop.py`: Mac / Linux differences
  (clipboard, notifications, folders).
- `bin/clip`: finds a Python that has GTK (Homebrew's on a Mac) and runs
  `python -m clip`.

## Tests

`make test` covers export timing, chapters, title cards, every mark kind,
configured colours reaching the output, sessions, the settings file and the
per-platform commands. It needs ffmpeg and PyGObject and uses no display.

`make battery` (needs a display) drives the real editor window to make two
annotated videos with two different configs, then checks them: every mark
kind, trim, size, title card, chapters (button and K) and their times in the
file, chapter banners, sound, card and mark colours from each config, the
fonts picked, a GIF export, and reopening with the saved session. It also
annotates a screenshot per config (all mark kinds, the plate with key and
caption, the plate's paper colour, reopening). The videos,
their configs and a contact sheet of frames each land in `battery-output/`.
`CLIP_STATE_DIR` keeps its sessions out of your real ones.

## What's been checked

- On Linux: the test suite; the editor driven through its own input handlers
  (draw, type, trim, chapters, undo / redo, export, reopen with the session);
  `setup.sh` in a scratch home; a bad config value giving a clear error.
- **Not yet run on a Mac**: the Homebrew setup, the `.command` files, Cmd
  shortcuts, the clipboard / notification AppleScript, and how the GTK window
  looks there.
- The window is GTK, so on a Mac it looks like a Linux app, and it shows as
  "Python" in the Dock.
