# Clip

Annotate a screen recording or a screenshot: arrows, labels, numbered
markers, boxes, highlights, zooms, notes and blur-outs. Recordings also get
chapters and a title card, and export as an MP4 or GIF. Screenshots export
as a PNG figure with a caption.

## Set up (once)

1. Unzip this folder and keep it somewhere handy. Clip runs from here.
2. Double-click **Set up this Mac.command**. If macOS blocks it, right-click it
   and choose **Open**.

It installs what Clip needs and takes a few minutes the first time. It may ask
for your Mac password.

## Use

Double-click **Open Clip.command** and pick a recording or a screenshot.
Anything made with ⌘⇧5 works as it is.

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

In a recording, each mark shows for 3 seconds. Drag its bar on the timeline
to change when. On a screenshot, N numbers things and lists them under the
picture, Tab types a caption, and P turns the frame around it on or off.

Exports go to **Movies → Clips** and are copied to the clipboard, ready to
paste. Your original file is never changed. Reopening it brings back your
marks.

## Colours and fonts

Open `config.toml` in this folder with any text editor and change the hex
colours or font names. Every setting is listed there with its default.

## If something goes wrong

Open Terminal, drag `bin/clip` from this folder into it, add ` --check`, and
press Return. It shows what's missing. Send that output to whoever gave you
Clip.

---

Developer notes: [docs/DEVELOPING.md](docs/DEVELOPING.md)
