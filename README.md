# Clip

Annotate a screen recording (arrows, labels, boxes, highlights, zooms, notes,
blur-outs, chapters, a title card) and export it as an MP4 or GIF.

## Set up (once)

1. Unzip this folder and keep it somewhere handy. Clip runs from here.
2. Double-click **Set up this Mac.command**. If macOS blocks it, right-click it
   and choose **Open**.

It installs what Clip needs and takes a few minutes the first time. It may ask
for your Mac password.

## Use

Double-click **Open Clip.command** and pick a recording. Recordings made with
⌘⇧5 work as they are.

| Key | |
|---|---|
| A · B · L · H · Z · T · X | arrow · box · label · highlight · zoom · note · blur out |
| V | select and move marks (Delete removes) |
| 1–5 | colour |
| Space | play / pause |
| ← → | step a frame (Shift: a second) |
| I / O | trim start / end here |
| K or **+ Chapter** | add a chapter here |
| ⌘Z / ⌘⇧Z | undo / redo |
| Enter | export and close |
| Esc | close |

Each mark shows for 3 seconds. Drag its bar on the timeline to change when.

Exports go to **Movies → Clips** and are copied to the clipboard, ready to
paste. Your recording is never changed. Reopening a recording brings back your
marks.

## Colours and fonts

Open `~/.config/clip/config.toml` in any text editor and change the hex
colours or font names. Every setting is listed there with its default.

## If something goes wrong

Open Terminal, drag `bin/clip` from this folder into it, add ` --check`, and
press Return. It shows what's missing. Send that output to whoever gave you
Clip.

---

Developer notes: [docs/DEVELOPING.md](docs/DEVELOPING.md)
