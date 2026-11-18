#!/usr/bin/env python3
"""The drawing and the editor the video editor is built on: marks drawn
textbook style (labels with leader lines, numbered markers, arrows, boxes,
highlights, braces, zoom insets, notes, redactions) and a window that
places them with the mouse and keys. editor.py adds the timeline."""
import copy
import math
import os
import sys

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import desktop, style  # noqa: E402

# ---- the house style (config.toml, see style.py) ---------------------------

hexrgb = style.hexrgb
S = style.current()
PALETTE = S.palette
ACCENT = S.accent
PAPER = S.paper
LABEL_BG = S.label_bg
INK = S.ink
INK_SOFT = S.ink_soft
HIGHLIGHT = S.highlight
DESK = S.desk
SELECT = S.select
SANS, SANS_SEMI, SANS_BOLD = (S.sans, Pango.Weight.NORMAL), (S.sans, Pango.Weight.SEMIBOLD), \
    (S.sans, Pango.Weight.BOLD)
SERIF = (S.serif, Pango.Weight.NORMAL)
MARGIN = 34          # page margin round the content
WORK = 220           # room round the shot in the editor, for margin labels

TOOLS = [("label", "L", "Label"), ("marker", "N", "Marker"), ("arrow", "A", "Arrow"),
         ("box", "B", "Box"), ("highlight", "H", "Highlight"), ("brace", "C", "Brace"),
         ("zoom", "Z", "Zoom"), ("note", "T", "Note"), ("redact", "X", "Redact"),
         ("select", "V", "Select")]
HINTS = {
    "label": "Label: drag from the point to where the label should sit, then type. Enter to finish.",
    "marker": "Marker: click to drop a numbered dot, then type what it is (it goes in the key).",
    "arrow": "Arrow: drag from tail to tip. Shift snaps to 15 degrees.",
    "box": "Box: drag round something, then type a short tag (or press Enter for none).",
    "highlight": "Highlight: drag across text or a region.",
    "brace": "Brace: drag along the edge to group, then type its label. Right-click it (or F when selected) to flip it.",
    "zoom": "Zoom: drag round a small detail; a magnified inset appears beside it (move it with V).",
    "note": "Note: click where the note goes, then type. Shift+Enter for a new line.",
    "redact": "Redact: drag over anything private to pixelate it.",
    "select": "Select: click to pick, drag to move, double-click to retype, Delete to remove.",
}
TEXT_KINDS = {"label", "marker", "box", "brace", "note"}


def font(spec, px):
    family, weight = spec
    d = Pango.FontDescription()
    d.set_family(family)
    d.set_weight(weight)
    d.set_absolute_size(px * Pango.SCALE)
    return d


def make_layout(cr, text, desc, width=None, align=Pango.Alignment.LEFT, markup=False):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(desc)
    if width:
        lay.set_width(int(width * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
    lay.set_alignment(align)
    if markup:
        lay.set_markup(text, -1)
    else:
        lay.set_text(text if text else "\u200b", -1)
    return lay


def size(lay):
    w, h = lay.get_pixel_size()
    return w, h


def rrect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def norm(x0, y0, x1, y1):
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


# ---- the figure: items, layout, painting ----------------------------------

class Figure:
    """The document: the shot, the annotations, the caption. Painting is
    shared by the editor and the export, so what you see is what you get."""

    layer = False        # True: drawing one mark onto transparency (clip.py's video layers)

    def __init__(self, path=None, surface=None):
        self.img = surface if surface is not None else cairo.ImageSurface.create_from_png(path)
        self.iw, self.ih = self.img.get_width(), self.img.get_height()
        # annotation scale: bigger shots get slightly bigger marks, times
        # the size you pick (Size in the editor: one factor for every mark,
        # its text and the caption, so they grow and shrink together)
        self.k0 = max(0.9, min(1.5, min(self.iw, self.ih) / 640))
        self.size = 1.0
        self.items = []
        self.caption = ""
        self.title = ""      # the label's word; blank: "Figure" (if there's a number)
        self.number = ""     # blank: no number, and no label unless titled
        self.plate = True
        self.scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    # sizes, scaled
    @property
    def k(self):
        return self.k0 * self.size

    @k.setter
    def k(self, v):                   # a copy taking another figure's scale whole
        self.k0, self.size = v, 1.0

    def px(self, v):
        return v * self.k

    def colour(self, it):
        return PALETTE[it.get("color", 0)][1]

    # -- per-item geometry ------------------------------------------------
    def label_box(self, it, cr=None):
        cr = cr or self.scratch
        lay = make_layout(cr, it.get("text", ""), font(SANS_SEMI, self.px(14)))
        tw, th = size(lay)
        padx, pady = self.px(8), self.px(4)
        w, h = tw + 2 * padx, th + 2 * pady
        return lay, (it["lx"] - w / 2, it["ly"] - h / 2, w, h), (padx, pady)

    def note_box(self, it, cr=None):
        cr = cr or self.scratch
        lay = make_layout(cr, it.get("text", ""), font(SERIF, self.px(14)), width=self.px(250))
        tw, th = size(lay)
        pad = self.px(10)
        bar = self.px(4)
        w = max(tw, self.px(40)) + 2 * pad + bar
        return lay, (it["x"], it["y"], w, th + 2 * pad), (pad + bar, pad)

    def brace_geom(self, it):
        x0, y0, x1, y1 = it["x0"], it["y0"], it["x1"], it["y1"]
        L = math.hypot(x1 - x0, y1 - y0) or 1
        dx, dy = (x0 - x1) / L, (y0 - y1) / L
        n = (dy, -dx)
        if self.brace_side(it) < 0:
            x0, y0, x1, y1 = x1, y1, x0, y0
            dx, dy = -dx, -dy
            n = (dy, -dx)
        w = max(self.px(8), min(self.px(18), L * 0.09))
        return (x0, y0, x1, y1, dx, dy, L, w, n)

    def brace_side(self, it):
        """Which way a brace faces: +1 or -1, the side of the line from its
        first end to its last. A brace you've flipped keeps its "side";
        otherwise it bulges away from the shot's centre."""
        if it.get("side") in (1, -1):
            return it["side"]
        x0, y0, x1, y1 = it["x0"], it["y0"], it["x1"], it["y1"]
        L = math.hypot(x1 - x0, y1 - y0) or 1
        n = ((y0 - y1) / L, (x1 - x0) / L)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        cx, cy = self.iw / 2, self.ih / 2
        toward = (mx + n[0] - cx) ** 2 + (my + n[1] - cy) ** 2 < (mx - n[0] - cx) ** 2 + (my - n[1] - cy) ** 2
        return -1 if toward else 1

    def brace_label(self, it, cr=None):
        cr = cr or self.scratch
        x0, y0, x1, y1, dx, dy, L, w, n = self.brace_geom(it)
        tx = (x0 + x1) / 2 + n[0] * (w + self.px(8))
        ty = (y0 + y1) / 2 + n[1] * (w + self.px(8))
        lay = make_layout(cr, it.get("text", ""), font(SANS_SEMI, self.px(14)))
        tw, th = size(lay)
        if abs(n[0]) > abs(n[1]):                       # beside a vertical brace
            bx = tx if n[0] > 0 else tx - tw
            by = ty - th / 2
        else:                                           # above/below a horizontal one
            bx = tx - tw / 2
            by = ty if n[1] > 0 else ty - th
        return lay, (bx, by, tw, th)

    def zoom_geom(self, it):
        sx0, sy0, sx1, sy1 = norm(it["sx0"], it["sy0"], it["sx1"], it["sy1"])
        scx, scy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        rs = math.hypot(sx1 - sx0, sy1 - sy0) / 2
        return scx, scy, max(rs, 4), it["cx"], it["cy"], it["r"]

    def bbox(self, it):
        kind = it["kind"]
        if kind == "label":
            _, (x, y, w, h), _ = self.label_box(it)
            return norm(min(x, it["ax"]), min(y, it["ay"]), max(x + w, it["ax"]), max(y + h, it["ay"]))
        if kind == "note":
            _, (x, y, w, h), _ = self.note_box(it)
            return x, y, x + w, y + h
        if kind == "marker":
            r = self.px(12)
            return it["x"] - r, it["y"] - r, it["x"] + r, it["y"] + r
        if kind == "zoom":
            scx, scy, rs, cx, cy, r = self.zoom_geom(it)
            return (min(scx - rs, cx - r), min(scy - rs, cy - r), max(scx + rs, cx + r), max(scy + rs, cy + r))
        if kind == "brace":
            x0, y0, x1, y1, dx, dy, L, w, n = self.brace_geom(it)
            tx, ty = (x0 + x1) / 2 + n[0] * w, (y0 + y1) / 2 + n[1] * w
            b = [min(x0, x1, tx), min(y0, y1, ty), max(x0, x1, tx), max(y0, y1, ty)]
            if it.get("text"):
                _, (bx, by, bw, bh) = self.brace_label(it)
                b = [min(b[0], bx), min(b[1], by), max(b[2], bx + bw), max(b[3], by + bh)]
            return tuple(b)
        x0, y0, x1, y1 = norm(it["x0"], it["y0"], it["x1"], it["y1"])
        if kind == "box" and it.get("text"):
            y0 -= self.px(22)
        return x0, y0, x1, y1

    # -- the plate's layout -------------------------------------------------
    def key_entries(self):
        out, n = [], 0
        for it in self.items:
            if it["kind"] == "marker":
                n += 1
                it["n"] = n
                if it.get("text", "").strip():
                    out.append(it)
        return out

    def heading(self):
        """The caption's label: title and number ("Figure 3", "Diagram",
        "Diagram 2"). A blank title is "Figure" when there's a number; with
        neither, there's no label at all."""
        num = str(self.number or "").strip()
        title = self.title.strip() or ("Figure" if num else "")
        return f"{title} {num}".strip()

    def layout(self, cr=None):
        """Where everything goes: the page rect, the key, the caption."""
        cr = cr or self.scratch
        x0, y0, x1, y1 = 0, 0, self.iw, self.ih
        for it in self.items:
            b = self.bbox(it)
            x0, y0, x1, y1 = min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])
        m = self.px(MARGIN) if self.plate else self.px(6)
        page = [x0 - m, y0 - m, x1 + m, y1 + m]
        width = page[2] - page[0] - 2 * m
        y = page[3] - m / 3
        key = []
        entries = self.key_entries() if self.plate else []
        if entries:
            y += self.px(16)
            desc = font(SANS, self.px(13.5))
            cols = 1 if width < self.px(420) else 2 if width < self.px(760) else 3
            colw = width / cols
            rows = math.ceil(len(entries) / cols)
            ys = []
            for c in range(cols):
                cy = y
                for r in range(rows):
                    i = c * rows + r
                    if i >= len(entries):
                        break
                    lay = make_layout(cr, entries[i]["text"], desc, width=colw - self.px(36))
                    key.append((entries[i], page[0] + m + c * colw, cy, lay))
                    cy += max(size(lay)[1], self.px(20)) + self.px(6)
                ys.append(cy)
            y = max(ys)
        cap = None
        head = self.heading()
        if self.plate and (self.caption.strip() or entries or head):
            y += self.px(8 if entries else 16)
            esc = GLib.markup_escape_text
            text = ((f'<span font_desc="{esc(font(SANS_BOLD, round(self.px(14.5), 1)).to_string())}" '
                     f'foreground="{S.hex["accent"]}">{esc(head)}</span>' if head else "")
                    + f'<span font_desc="{esc(font(SERIF, round(self.px(15), 1)).to_string())}">{"   " if head else ""}'
                    f'{GLib.markup_escape_text(self.caption.strip())}</span>')
            lay = make_layout(cr, text, font(SERIF, self.px(15)), width=width, markup=True)
            cap = (page[0] + m, y, lay)
            y += size(lay)[1]
        if key or cap:
            page[3] = y + m * 0.8
        return {"page": page, "key": key, "caption": cap}

    def layout_rule_y(self, lay):
        first = lay["key"][0][2] if lay["key"] else lay["caption"][1]
        return first - self.px(8)

    # -- painting -------------------------------------------------------------
    def halo(self, cr, width):
        cr.set_source_rgba(*LABEL_BG, 0.92)
        cr.set_line_width(width)
        cr.stroke_preserve()

    def paint(self, cr, editing=None, selected=None, temp=None):
        lay = self.layout(cr)
        x0, y0, x1, y1 = lay["page"]
        if self.plate:
            cr.set_source_rgb(*PAPER)
            cr.rectangle(x0, y0, x1 - x0, y1 - y0)
            cr.fill()
        cr.set_source_surface(self.img, 0, 0)
        cr.paint()
        if self.plate:                                  # hairline frame round the shot
            cr.set_source_rgba(*INK, 0.28)
            cr.set_line_width(1)
            cr.rectangle(-0.5, -0.5, self.iw + 1, self.ih + 1)
            cr.stroke()
        # flat things first (redactions, highlights), then marks on top
        order = sorted(self.items + ([temp] if temp else []),
                       key=lambda it: {"redact": 0, "highlight": 1, "zoom": 2}.get(it["kind"], 3))
        for it in order:
            getattr(self, "paint_" + it["kind"])(cr, it, it is editing)
        if self.plate and (lay["key"] or lay["caption"]):   # a hairline over the key and caption
            m = self.px(MARGIN)
            ry = self.layout_rule_y(lay)
            cr.set_source_rgba(*INK, 0.22)
            cr.set_line_width(1)
            cr.move_to(x0 + m, ry + 0.5)
            cr.line_to(x1 - m, ry + 0.5)
            cr.stroke()
        for it, kx, ky, tl in lay["key"]:
            r = self.px(10)
            self.badge(cr, kx + r, ky + self.px(10), r, it, ring=False)
            cr.set_source_rgb(*INK)
            cr.move_to(kx + self.px(30), ky)
            PangoCairo.show_layout(cr, tl)
        if lay["caption"]:
            cx, cy, cl = lay["caption"]
            cr.set_source_rgb(*INK)
            cr.move_to(cx, cy)
            PangoCairo.show_layout(cr, cl)
        if selected is not None and selected in self.items:
            b = self.bbox(selected)
            cr.set_source_rgba(*SELECT, 0.9)
            cr.set_line_width(1.5)
            cr.set_dash([4, 3])
            cr.rectangle(b[0] - 5, b[1] - 5, b[2] - b[0] + 10, b[3] - b[1] + 10)
            cr.stroke()
            cr.set_dash([])

    def caret(self, cr, lay, x, y, text):
        idx = len((text or "").encode())
        pos = lay.index_to_pos(idx)
        cx = x + pos.x / Pango.SCALE
        cy = y + pos.y / Pango.SCALE
        cr.set_source_rgba(*SELECT, 1)
        cr.set_line_width(1.5)
        cr.move_to(cx + 1, cy)
        cr.line_to(cx + 1, cy + pos.height / Pango.SCALE)
        cr.stroke()

    def paint_label(self, cr, it, editing):
        col = self.colour(it)
        lay, (x, y, w, h), (padx, pady) = self.label_box(it, cr)
        ax, ay = it["ax"], it["ay"]
        tx, ty = min(max(ax, x), x + w), min(max(ay, y), y + h)   # nearest point on the box
        if math.hypot(tx - ax, ty - ay) > 2:
            cr.move_to(ax, ay)
            cr.line_to(tx, ty)
            self.halo(cr, self.px(4.5))
            cr.set_source_rgb(*col)
            cr.set_line_width(self.px(1.6))
            cr.stroke()
        r = self.px(3.8)                                  # the anchor dot
        cr.arc(ax, ay, r + self.px(1.6), 0, 2 * math.pi)
        cr.set_source_rgb(*LABEL_BG)
        cr.fill()
        cr.arc(ax, ay, r, 0, 2 * math.pi)
        cr.set_source_rgb(*col)
        cr.fill()
        if not it.get("text") and not editing:
            return
        rrect(cr, x, y, w, h, self.px(3))
        cr.set_source_rgb(*LABEL_BG)
        cr.fill_preserve()
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(1.3))
        cr.stroke()
        cr.set_source_rgb(*INK)
        cr.move_to(x + padx, y + pady)
        PangoCairo.show_layout(cr, lay)
        if editing:
            self.caret(cr, lay, x + padx, y + pady, it.get("text"))

    def badge(self, cr, x, y, r, it, ring=True):
        col = self.colour(it)
        if ring:
            cr.arc(x, y, r + self.px(2), 0, 2 * math.pi)
            cr.set_source_rgb(*LABEL_BG)
            cr.fill()
        cr.arc(x, y, r, 0, 2 * math.pi)
        cr.set_source_rgb(*col)
        cr.fill()
        lay = make_layout(cr, str(it.get("n", "?")), font(SANS_BOLD, r * 1.15))
        tw, th = size(lay)
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x - tw / 2, y - th / 2)
        PangoCairo.show_layout(cr, lay)

    def paint_marker(self, cr, it, editing):
        self.key_entries()                                # number it
        self.badge(cr, it["x"], it["y"], self.px(12), it)
        if editing:                                       # show what's being typed beside it
            lay = make_layout(cr, it.get("text", ""), font(SANS, self.px(13)))
            x, y = it["x"] + self.px(18), it["y"] - size(lay)[1] / 2
            tw, th = size(lay)
            rrect(cr, x - 4, y - 2, tw + 10, th + 4, 3)
            cr.set_source_rgba(*LABEL_BG, 0.95)
            cr.fill()
            cr.set_source_rgb(*INK_SOFT)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, lay)
            self.caret(cr, lay, x, y, it.get("text"))

    def paint_arrow(self, cr, it, editing):
        col = self.colour(it)
        x0, y0, x1, y1 = it["x0"], it["y0"], it["x1"], it["y1"]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 2:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        hl, hw = self.px(15), self.px(11)
        bx, by = x1 - ux * hl, y1 - uy * hl
        nx, ny = -uy, ux
        head = [(x1, y1), (bx + nx * hw / 2, by + ny * hw / 2),
                (x1 - ux * hl * 0.72, y1 - uy * hl * 0.72), (bx - nx * hw / 2, by - ny * hw / 2)]
        sx, sy = x1 - ux * hl * 0.75, y1 - uy * hl * 0.75
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(x0, y0)
        cr.line_to(sx, sy)
        self.halo(cr, self.px(7))
        cr.new_path()
        for i, (hx, hy) in enumerate(head):
            (cr.move_to if i == 0 else cr.line_to)(hx, hy)
        cr.close_path()
        self.halo(cr, self.px(4.5))
        cr.new_path()
        cr.move_to(x0, y0)
        cr.line_to(sx, sy)
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(2.6))
        cr.stroke()
        for i, (hx, hy) in enumerate(head):
            (cr.move_to if i == 0 else cr.line_to)(hx, hy)
        cr.close_path()
        cr.fill()

    def paint_box(self, cr, it, editing):
        col = self.colour(it)
        x0, y0, x1, y1 = norm(it["x0"], it["y0"], it["x1"], it["y1"])
        rrect(cr, x0, y0, x1 - x0, y1 - y0, self.px(5))
        self.halo(cr, self.px(5.5))
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(2.4))
        cr.stroke()
        if it.get("text") or editing:                     # a tab on the top edge
            lay = make_layout(cr, it.get("text", ""), font(SANS_BOLD, self.px(12.5)))
            tw, th = size(lay)
            pad = self.px(6)
            tx, ty = x0, y0 - th - self.px(4)
            rrect(cr, tx - self.px(1.2), ty, tw + 2 * pad, th + self.px(4) + self.px(2), self.px(3))
            cr.set_source_rgb(*col)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(tx + pad - self.px(1.2), ty + self.px(2))
            PangoCairo.show_layout(cr, lay)
            if editing:
                self.caret(cr, lay, tx + pad - self.px(1.2), ty + self.px(2), it.get("text"))

    def paint_highlight(self, cr, it, editing):
        x0, y0, x1, y1 = norm(it["x0"], it["y0"], it["x1"], it["y1"])
        cr.save()
        if self.layer:      # over moving video: a plain translucent band
            cr.set_source_rgba(*HIGHLIGHT, 0.38)
        else:
            cr.set_operator(cairo.OPERATOR_MULTIPLY)
            cr.set_source_rgba(*HIGHLIGHT, 0.75)
        rrect(cr, x0, y0, x1 - x0, y1 - y0, self.px(2))
        cr.fill()
        cr.restore()

    def paint_redact(self, cr, it, editing):
        x0, y0, x1, y1 = [int(round(v)) for v in norm(it["x0"], it["y0"], it["x1"], it["y1"])]
        w, h = x1 - x0, y1 - y0
        if w < 2 or h < 2:
            return
        block = max(6, int(self.px(9)))
        sw, sh = max(1, w // block), max(1, h // block)
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
        sc = cairo.Context(small)
        sc.scale(sw / w, sh / h)
        sc.set_source_surface(self.img, -x0, -y0)
        sc.get_source().set_filter(cairo.FILTER_GOOD)
        sc.paint()
        cr.save()
        cr.rectangle(x0, y0, w, h)
        cr.clip()
        cr.translate(x0, y0)
        cr.scale(w / sw, h / sh)
        cr.set_source_surface(small, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()

    def paint_brace(self, cr, it, editing):
        col = self.colour(it)
        x0, y0, x1, y1, dx, dy, L, w, n = self.brace_geom(it)
        if L < 4:
            return
        q = 0.6
        q1 = (x0 + q * w * dy, y0 - q * w * dx)
        q2 = ((x0 - .25 * L * dx) + (1 - q) * w * dy, (y0 - .25 * L * dy) - (1 - q) * w * dx)
        t = ((x0 - .5 * L * dx) + w * dy, (y0 - .5 * L * dy) - w * dx)
        q3 = (x1 + q * w * dy, y1 - q * w * dx)
        q4 = ((x0 - .75 * L * dx) + (1 - q) * w * dy, (y0 - .75 * L * dy) - (1 - q) * w * dx)

        def quad(p0, c, p2):
            c1 = (p0[0] + 2 / 3 * (c[0] - p0[0]), p0[1] + 2 / 3 * (c[1] - p0[1]))
            c2 = (p2[0] + 2 / 3 * (c[0] - p2[0]), p2[1] + 2 / 3 * (c[1] - p2[1]))
            cr.curve_to(*c1, *c2, *p2)

        def half(p0, qa, qb):
            cr.move_to(*p0)
            quad(p0, qa, qb)
            refl = (2 * qb[0] - qa[0], 2 * qb[1] - qa[1])
            quad(qb, refl, t)

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        half((x0, y0), q1, q2)
        half((x1, y1), q3, q4)
        self.halo(cr, self.px(5.5))
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(2.2))
        cr.stroke()
        if it.get("text") or editing:
            lay, (bx, by, bw, bh) = self.brace_label(it, cr)
            rrect(cr, bx - 4, by - 2, bw + 8, bh + 4, 3)
            cr.set_source_rgba(*LABEL_BG, 0.9)
            cr.fill()
            cr.set_source_rgb(*col)
            cr.move_to(bx, by)
            PangoCairo.show_layout(cr, lay)
            if editing:
                self.caret(cr, lay, bx, by, it.get("text"))

    def paint_zoom(self, cr, it, editing):
        col = self.colour(it)
        scx, scy, rs, cx, cy, r = self.zoom_geom(it)
        f = r / rs
        # the connectors: the outer tangents of the two circles
        d = math.hypot(cx - scx, cy - scy)
        if d > abs(r - rs) + 1:
            base = math.atan2(cy - scy, cx - scx)
            a = math.acos(max(-1, min(1, (rs - r) / d)))
            cr.set_source_rgba(*col, 0.75)
            cr.set_line_width(self.px(1.3))
            for s in (1, -1):
                phi = base + s * a
                cr.move_to(scx + rs * math.cos(phi), scy + rs * math.sin(phi))
                cr.line_to(cx + r * math.cos(phi), cy + r * math.sin(phi))
            cr.stroke()
        cr.arc(scx, scy, rs, 0, 2 * math.pi)            # the source ring
        self.halo(cr, self.px(4.5))
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(1.8))
        cr.stroke()
        cr.save()                                         # the magnified view
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.clip()
        if not self.layer:  # (in a video layer, ffmpeg puts the live picture here)
            cr.set_source_rgb(*PAPER)
            cr.paint()
        cr.translate(cx, cy)
        cr.scale(f, f)
        cr.translate(-scx, -scy)
        cr.set_source_surface(self.img, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        self.halo(cr, self.px(7))
        cr.set_source_rgb(*col)
        cr.set_line_width(self.px(2.8))
        cr.stroke()
        # the magnification, on a little tab at the bottom of the circle
        lay = make_layout(cr, f"×{f:.1f}".replace(".0", ""), font(SANS_BOLD, self.px(11.5)))
        tw, th = size(lay)
        tx, ty = cx - tw / 2, cy + r - th / 2
        rrect(cr, tx - self.px(5), ty - self.px(1), tw + self.px(10), th + self.px(2), self.px(3))
        cr.set_source_rgb(*col)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, lay)

    def paint_note(self, cr, it, editing):
        col = self.colour(it)
        lay, (x, y, w, h), (padl, pad) = self.note_box(it, cr)
        bar = self.px(4)
        tint = tuple(PAPER[i] * 0.88 + col[i] * 0.12 for i in range(3))
        cr.rectangle(x, y, w, h)
        cr.set_source_rgb(*tint)
        cr.fill()
        cr.rectangle(x, y, bar, h)
        cr.set_source_rgb(*col)
        cr.fill()
        cr.set_source_rgb(*INK)
        cr.move_to(x + padl, y + pad)
        PangoCairo.show_layout(cr, lay)
        if editing:
            self.caret(cr, lay, x + padl, y + pad, it.get("text"))

    # -- export ---------------------------------------------------------------
    def export(self, out):
        lay = self.layout()
        x0, y0, x1, y1 = [round(v) for v in lay["page"]]
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, x1 - x0, y1 - y0)
        cr = cairo.Context(surf)
        cr.translate(-x0, -y0)
        self.paint(cr)
        surf.write_to_png(out)


# ---- tool icons -------------------------------------------------------------
# Each tool's button shows a small picture of the mark it makes, drawn here
# with cairo (no image files) on a 24x24 grid. Parts the tool draws in the
# chosen colour are drawn in ink, so the tool column previews that colour.

PAPER_LINE = hexrgb("#9a9ea6")     # the grey "text" lines inside icons


def _text_lines(cr, x, ys, widths, w=1.6):
    cr.set_source_rgb(*PAPER_LINE)
    cr.set_line_width(w)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for y, lw in zip(ys, widths):
        cr.move_to(x, y)
        cr.line_to(x + lw, y)
        cr.stroke()


def _curved_arrow(cr, ink):
    """Undo: a hook that goes over the top and comes down on the left."""
    cr.set_source_rgb(*ink)
    cr.set_line_width(2.4)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.arc(12.5, 13.5, 6.5, math.pi * 1.08, math.pi * 2.3)
    cr.stroke()
    cr.move_to(2.4, 11.6)
    cr.line_to(9.8, 11.6)
    cr.line_to(6.1, 17.4)
    cr.close_path()
    cr.fill()


def paint_icon(cr, name, ink):
    """Paint the icon NAME (a tool, or "undo"/"redo") in the 24x24 box at
    the origin. ink: the colour the tool would draw in."""
    cr.save()
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    dark = INK
    if name == "label":                       # a dot, a leader line, a tag
        cr.set_source_rgb(*ink)
        cr.set_line_width(1.6)
        cr.move_to(5, 19)
        cr.line_to(11, 11)
        cr.stroke()
        cr.arc(5, 19, 2.6, 0, 2 * math.pi)
        cr.fill()
        rrect(cr, 9, 3.5, 13, 8, 2.2)
        cr.set_source_rgb(*LABEL_BG)
        cr.fill_preserve()
        cr.set_source_rgb(*ink)
        cr.set_line_width(1.6)
        cr.stroke()
        _text_lines(cr, 12, [7.5], [7])
    elif name == "marker":                    # a numbered dot
        cr.set_source_rgb(*ink)
        cr.arc(12, 12, 9, 0, 2 * math.pi)
        cr.fill()
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(font(SANS_BOLD, 12))
        lay.set_text("1", -1)
        w, h = size(lay)
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(12 - w / 2, 12 - h / 2)
        PangoCairo.show_layout(cr, lay)
    elif name == "arrow":                     # tail to tip, head filled
        cr.set_source_rgb(*ink)
        cr.set_line_width(2.6)
        cr.move_to(4, 20)
        cr.line_to(15.5, 8.5)
        cr.stroke()
        cr.move_to(20.5, 3.5)
        cr.line_to(11.2, 7.4)
        cr.line_to(16.6, 12.8)
        cr.close_path()
        cr.fill()
    elif name == "box":                       # a frame round something
        cr.set_source_rgb(*PAPER_LINE)
        rrect(cr, 8, 9, 8, 6, 1)
        cr.fill()
        cr.set_source_rgb(*ink)
        cr.set_line_width(2.4)
        rrect(cr, 3, 4.5, 18, 15, 3)
        cr.stroke()
    elif name == "highlight":                 # a yellow band over a line of text
        _text_lines(cr, 4, [4.5, 19.5], [16, 11], w=2)
        cr.set_source_rgba(*HIGHLIGHT, 0.95)
        rrect(cr, 2, 8, 20, 8, 1.5)
        cr.fill()
        cr.set_source_rgb(*dark)
        cr.set_line_width(2)
        cr.move_to(4.5, 12)
        cr.line_to(17, 12)
        cr.stroke()
    elif name == "brace":                     # a curly brace and its label
        cr.set_source_rgb(*ink)
        cr.set_line_width(2)
        cr.move_to(10, 3)
        cr.curve_to(7, 3, 7, 4.5, 7, 7)
        cr.line_to(7, 9.5)
        cr.curve_to(7, 11, 6, 12, 4, 12)
        cr.curve_to(6, 12, 7, 13, 7, 14.5)
        cr.line_to(7, 17)
        cr.curve_to(7, 19.5, 7, 21, 10, 21)
        cr.stroke()
        _text_lines(cr, 12.5, [12], [8.5], w=2)
    elif name == "zoom":                      # a magnifying glass
        cr.set_source_rgb(*LABEL_BG)
        cr.arc(10, 10, 6.5, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*ink)
        cr.set_line_width(2.2)
        cr.arc(10, 10, 6.5, 0, 2 * math.pi)
        cr.stroke()
        cr.set_line_width(1.8)
        for (a, b, c, d) in ((7, 10, 13, 10), (10, 7, 10, 13)):
            cr.move_to(a, b)
            cr.line_to(c, d)
        cr.stroke()
        cr.set_source_rgb(*dark)
        cr.set_line_width(3.6)
        cr.move_to(15, 15)
        cr.line_to(20.5, 20.5)
        cr.stroke()
    elif name == "note":                      # a margin note: bar, box, lines
        rrect(cr, 3, 4, 18, 16, 1.5)
        cr.set_source_rgb(*LABEL_BG)
        cr.fill_preserve()
        cr.set_source_rgb(*PAPER_LINE)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(*ink)
        cr.rectangle(3, 4, 3.2, 16)
        cr.fill()
        _text_lines(cr, 9, [8.5, 12, 15.5], [9, 9, 6])
    elif name == "redact":                    # pixelated blocks
        shades = ["#5c6068", "#9da1a8", "#7b7f87", "#c3c6cb",
                  "#a9adb3", "#6a6e76", "#b8bbc0", "#868a91",
                  "#7f838a", "#c9ccd0", "#62666e", "#9a9ea5",
                  "#b3b6bb", "#71757d", "#a3a7ad", "#585c64"]
        for i, s in enumerate(shades):
            cr.set_source_rgb(*hexrgb(s))
            cr.rectangle(3 + (i % 4) * 4.5, 3 + (i // 4) * 4.5, 4.5, 4.5)
            cr.fill()
        cr.set_source_rgb(*dark)
        cr.set_line_width(1)
        cr.rectangle(3, 3, 18, 18)
        cr.stroke()
    elif name == "select":                    # the pointer
        cr.move_to(6, 2.5)
        cr.line_to(6, 19)
        cr.line_to(10, 15.2)
        cr.line_to(13, 21.5)
        cr.line_to(16, 20.2)
        cr.line_to(13, 13.8)
        cr.line_to(18.5, 13.8)
        cr.close_path()
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.set_source_rgb(*dark)
        cr.set_line_width(1.5)
        cr.stroke()
    elif name == "undo":
        _curved_arrow(cr, ink)
    elif name == "redo":
        cr.translate(24, 0)
        cr.scale(-1, 1)
        _curved_arrow(cr, ink)
    cr.restore()


# ---- the editor -------------------------------------------------------------

def css():
    sel = S.hex["select"]
    pressed = "#" + "".join(f"{round((0.75 + 0.25 * c) * 255):02x}" for c in SELECT)
    return f"""
.fig-tools {{ padding: 6px 4px; }}
.fig-tool, .fig-swatch, .fig-act {{ padding: 0; min-width: 0; min-height: 0; }}
.fig-tool:checked {{
    background-color: {pressed}; background-image: none;
    box-shadow: inset 0 0 0 2px {sel}, inset 1px 1px 3px rgba(0, 0, 0, 0.35);
}}
.fig-tools-head {{ font-family: "{S.sans}"; font-size: 10px; color: {S.hex["ink_soft"]}; padding: 6px 0 2px 0; }}
.fig-hint {{ font-family: "{S.sans}"; font-size: 12px; color: {S.hex["ink"]}; padding: 2px 8px; }}
.fig-done {{ font-weight: bold; }}
""".encode()


def primary_mask():
    """Ctrl, and on a Mac Cmd as well: the modifier for shortcuts."""
    mask = Gdk.ModifierType.CONTROL_MASK
    if desktop.IS_MAC:
        keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
        mask |= keymap.get_modifier_mask(Gdk.ModifierIntent.PRIMARY_ACCELERATOR)
        mask |= Gdk.ModifierType.META_MASK
    return mask
TOOL_W, TOOL_H = 62, 52       # a tool button's face
SIZE_MIN, SIZE_MAX, SIZE_STEP = 50, 300, 10    # the Size control, in %
SWATCH_H = 22


class Editor(Gtk.Window):
    def __init__(self, fig, out):
        super().__init__(title="Annotate")
        self.fig, self.out = fig, out
        self.tool, self.color = "label", 0
        self.selected = self.editing = self.temp = None
        self.drag = None
        self.undo, self.redo = [], []
        self.done = False
        self.primary = primary_mask()

        prov = Gtk.CssProvider()
        prov.load_from_data(css())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Size to the monitor under the pointer, not Gdk.Screen: on X11 the
        # "screen" is every monitor glued together, so 88% of it spans them all.
        disp = Gdk.Display.get_default()
        try:
            _, px, py = disp.get_default_seat().get_pointer().get_position()[0:3]
            mon = disp.get_monitor_at_point(px, py)
        except (AttributeError, TypeError):
            mon = None
        mon = mon or disp.get_primary_monitor() or disp.get_monitor(0)
        wa = mon.get_workarea()
        self.set_default_size(int(wa.width * 0.88), int(wa.height * 0.86))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        self.hint = Gtk.Label(xalign=0)
        self.hint.get_style_context().add_class("fig-hint")
        box.pack_start(self.hint, False, False, 0)
        # the picture with the tool column down its left side
        mid = Gtk.Box()
        box.pack_start(mid, True, True, 0)
        # (it scrolls rather than make the window taller than a small screen)
        tools = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                   vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        tools.set_propagate_natural_width(True)
        tools.set_shadow_type(Gtk.ShadowType.NONE)
        tools.add(self.tool_column())
        mid.pack_start(tools, False, False, 0)
        mid.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("scroll-event", self.on_scroll)
        mid.pack_start(self.area, True, True, 0)

        bar = Gtk.Box(spacing=4)
        bar.set_border_width(6)
        box.pack_start(bar, False, False, 0)
        # the caption's label: a title (blank: "Figure", if numbered) and a
        # number (blank: none). Both start empty: no label until you want one.
        self.title_e = Gtk.Entry(text=fig.title, width_chars=9, placeholder_text="Figure")
        self.title_e.set_tooltip_text("The label's title (blank: Figure). With no title and no number, no label.")
        self.title_e.connect("changed", self.on_caption)
        bar.pack_start(self.title_e, False, False, 0)
        self.num = Gtk.Entry(text=str(fig.number), width_chars=4, placeholder_text="No.")
        self.num.set_tooltip_text("Its number (blank: none)")
        self.num.connect("changed", self.on_caption)
        bar.pack_start(self.num, False, False, 0)
        self.cap = Gtk.Entry(placeholder_text="Caption (Tab)")
        self.cap.connect("changed", self.on_caption)
        self.cap.connect("activate", lambda *_: self.area.grab_focus())
        bar.pack_start(self.cap, True, True, 0)
        # one size for every mark, its text and the caption (- / +)
        size_l = Gtk.Label(label="Size %")
        self.size_spin = Gtk.SpinButton.new_with_range(SIZE_MIN, SIZE_MAX, SIZE_STEP)
        self.size_spin.set_value(round(fig.size * 100))
        self.size_spin.set_can_focus(False)       # its keys stay the editor's (- / + step it)
        self.size_spin.set_tooltip_text("How big every mark, its text and the caption are, "
                                        "all together (- / +)")
        self.size_spin.connect("value-changed", self.on_size)
        bar.pack_start(size_l, False, False, 0)
        bar.pack_start(self.size_spin, False, False, 0)
        self.plate_btn = Gtk.CheckButton(label="Plate", active=True)
        self.plate_btn.connect("toggled", self.on_plate)
        bar.pack_start(self.plate_btn, False, False, 0)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.quit(False))
        done = Gtk.Button(label="Done")
        done.get_style_context().add_class("fig-done")
        done.connect("clicked", lambda *_: self.quit(True))
        bar.pack_start(cancel, False, False, 0)
        bar.pack_start(done, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", lambda *_: self.quit(False) or True)
        self.set_tool("label")
        self.set_color(0)

    # -- the tool column ------------------------------------------------------
    def tool_column(self):
        """The tools as icon buttons (the picture, the name, the key), then
        the colours, then undo and redo. Returns the column's box."""
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        col.get_style_context().add_class("fig-tools")
        self.tool_buttons = {}
        group = None
        for name, key, title in TOOLS:
            b = Gtk.RadioButton.new_from_widget(group)
            b.set_mode(False)
            b.set_relief(Gtk.ReliefStyle.NORMAL)
            b.get_style_context().add_class("fig-tool")
            b.set_tooltip_text(f"{title} ({key}): {HINTS[name].split(': ', 1)[1]}")
            face = Gtk.DrawingArea()
            face.set_size_request(TOOL_W, TOOL_H)
            face.connect("draw", self.draw_tool_face, b, name, key, title)
            b.add(face)
            group = group or b
            b.connect("toggled", self.on_tool_button, name)
            col.pack_start(b, False, False, 0)
            self.tool_buttons[name] = b

        head = Gtk.Label(label="Colour", xalign=0.5)
        head.get_style_context().add_class("fig-tools-head")
        col.pack_start(head, False, False, 0)
        self.swatches = []
        for i, (cname, _) in enumerate(PALETTE):
            b = Gtk.Button()
            b.get_style_context().add_class("fig-swatch")
            b.set_tooltip_text(f"{cname.capitalize()} ({i + 1})")
            face = Gtk.DrawingArea()
            face.set_size_request(TOOL_W, SWATCH_H)
            face.connect("draw", self.draw_swatch, i)
            b.add(face)
            b.connect("clicked", lambda _b, i=i: self.set_color(i))
            col.pack_start(b, False, False, 0)
            self.swatches.append(b)

        acts = Gtk.Box(spacing=3, homogeneous=True)
        for name, tip, fn in (("undo", f"Undo ({desktop.MOD}+Z)", lambda *_: self.restore(self.undo, self.redo)),
                              ("redo", f"Redo ({desktop.MOD}+Shift+Z)",
                               lambda *_: self.restore(self.redo, self.undo))):
            b = Gtk.Button()
            b.get_style_context().add_class("fig-act")
            b.set_tooltip_text(tip)
            face = Gtk.DrawingArea()
            face.set_size_request(28, 28)
            face.connect("draw", self.draw_act, name)
            b.add(face)
            b.connect("clicked", fn)
            b.set_can_focus(False)
            acts.pack_start(b, True, True, 0)
        col.pack_end(acts, False, False, 0)
        for b in list(self.tool_buttons.values()) + self.swatches:
            b.set_can_focus(False)              # keys belong to the picture
        return col

    def draw_tool_face(self, w, cr, button, name, key, title):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        on = button.get_active()
        s = 28                                  # the icon's size
        cr.save()
        cr.translate((W - s) / 2, 4)
        cr.scale(s / 24, s / 24)
        paint_icon(cr, name, PALETTE[self.color][1])
        cr.restore()
        lay = make_layout(cr, title, font(SANS_SEMI if on else SANS, 11))
        tw, th = size(lay)
        cr.set_source_rgb(*(INK if on else INK_SOFT))
        cr.move_to((W - tw) / 2, H - th - 3)
        PangoCairo.show_layout(cr, lay)
        lay = make_layout(cr, key, font(SANS_BOLD, 9))
        tw, th = size(lay)
        cr.set_source_rgb(*(SELECT if on else INK_SOFT))
        cr.move_to(W - tw - 4, 2)
        PangoCairo.show_layout(cr, lay)
        return False

    def draw_swatch(self, w, cr, i):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        rgb = PALETTE[i][1]
        on = i == self.color
        rrect(cr, 3, 2, W - 6, H - 4, 3)
        cr.set_source_rgb(*rgb)
        cr.fill()
        if on:                                  # a white ring inside a dark one
            rrect(cr, 4.5, 3.5, W - 9, H - 7, 2)
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(2)
            cr.stroke()
            rrect(cr, 1.5, 0.5, W - 3, H - 1, 4)
            cr.set_source_rgb(*INK)
            cr.set_line_width(1.5)
            cr.stroke()
        lay = make_layout(cr, str(i + 1), font(SANS_BOLD if on else SANS_SEMI, 11))
        tw, th = size(lay)
        cr.set_source_rgba(1, 1, 1, 1 if on else 0.8)
        cr.move_to(W - tw - 9, (H - th) / 2)
        PangoCairo.show_layout(cr, lay)
        if on:
            cr.move_to(10, H / 2)               # a tick: this is the one in use
            cr.line_to(13, H / 2 + 3)
            cr.line_to(18, H / 2 - 3)
            cr.set_line_width(2)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.stroke()
        return False

    def draw_act(self, w, cr, name):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        cr.translate((W - 20) / 2, (H - 20) / 2)
        cr.scale(20 / 24, 20 / 24)
        paint_icon(cr, name, INK_SOFT)
        return False

    # -- state ----------------------------------------------------------------
    UNDO_KEPT = 40

    def state(self):
        """Everything needed to pick up exactly where you left off."""
        return {"items": self.fig.items, "caption": self.fig.caption, "number": self.fig.number,
                "title": self.fig.title,
                "plate": self.fig.plate, "tool": self.tool, "color": self.color,
                "size": self.fig.size,
                "undo": self.undo[-self.UNDO_KEPT:], "redo": self.redo[-self.UNDO_KEPT:]}

    def load_state(self, st):
        st = st or {}
        for k in ("items", "caption", "number", "title", "plate"):
            if k in st:
                setattr(self.fig, k, copy.deepcopy(st[k]))
        caption, number, title = self.fig.caption, self.fig.number, self.fig.title
        self.num.set_text(str(number))                # (each set_text re-reads every entry)
        self.title_e.set_text(title)
        self.cap.set_text(caption)
        self.plate_btn.set_active(self.fig.plate)
        self.set_size(st.get("size", 1.0) * 100)
        self.undo, self.redo = list(st.get("undo", [])), list(st.get("redo", []))
        if st.get("tool") in self.tool_buttons:
            self.set_tool(st["tool"])
        if isinstance(st.get("color"), int) and 0 <= st["color"] < len(self.swatches):
            self.set_color(st["color"])

    def flash(self, text):
        self.hint.set_text(text)

    def save(self, close=True, as_new=False):
        """Write the result; editor.py's video editor keeps working after it."""
        self.stop_editing()
        if close:
            self.quit(True)

    def snapshot(self):
        self.undo.append(copy.deepcopy(self.fig.items))
        self.redo.clear()

    def restore(self, stack, other):
        if not stack:
            return
        other.append(copy.deepcopy(self.fig.items))
        self.fig.items = stack.pop()
        self.selected = self.editing = None
        self.area.queue_draw()

    def set_tool(self, name):
        self.stop_editing()
        self.tool = name
        if not self.tool_buttons[name].get_active():
            self.tool_buttons[name].set_active(True)
        for b in self.tool_buttons.values():
            b.queue_draw()
        self.hint.set_text(HINTS[name])
        if name != "select":
            self.selected = None
        self.area.queue_draw()

    def on_tool_button(self, b, name):
        if b.get_active() and self.tool != name:
            self.set_tool(name)

    def set_color(self, i):
        self.color = i
        for b in list(self.tool_buttons.values()) + self.swatches:
            b.queue_draw()                      # icons are drawn in the colour
        target = self.editing or self.selected
        if target is not None:
            self.snapshot()
            target["color"] = i
        self.area.queue_draw()

    def on_caption(self, *_):
        self.fig.caption = self.cap.get_text()
        self.fig.title = self.title_e.get_text()
        self.fig.number = self.num.get_text().strip()
        self.area.queue_draw()

    def set_size(self, pct):
        """Size, in %: every mark, its text and the caption scale together."""
        self.size_spin.set_value(max(SIZE_MIN, min(SIZE_MAX, round(pct / SIZE_STEP) * SIZE_STEP)))
        self.on_size(self.size_spin)

    def on_size(self, spin):
        self.fig.size = spin.get_value() / 100
        self.area.queue_draw()

    def on_plate(self, b):
        self.fig.plate = b.get_active()
        self.area.queue_draw()

    def stop_editing(self):
        it = self.editing
        self.editing = None
        if it is not None and it["kind"] == "label" and not it.get("text", "").strip():
            self.fig.items.remove(it)                 # an empty label is a mistake
        if it is not None and it["kind"] == "note" and not it.get("text", "").strip():
            self.fig.items.remove(it)
        self.area.queue_draw()

    def quit(self, ok):
        self.stop_editing()
        if ok:
            self.fig.export(self.out)
        self.done = ok
        Gtk.main_quit()

    # -- view -----------------------------------------------------------------
    def view(self):
        a = self.area.get_allocation()
        lay = self.fig.layout()
        x0, y0, x1, y1 = lay["page"]
        x0, y0 = min(x0, -WORK), min(y0, -WORK * 0.6)
        x1, y1 = max(x1, self.fig.iw + WORK), max(y1, self.fig.ih + WORK * 0.6)
        s = min(2.0, (a.width - 20) / (x1 - x0), (a.height - 20) / (y1 - y0))   # small shots zoom in
        ox = (a.width - (x1 - x0) * s) / 2 - x0 * s
        oy = (a.height - (y1 - y0) * s) / 2 - y0 * s
        return s, ox, oy

    def to_doc(self, ev):
        s, ox, oy = self.view()
        return (ev.x - ox) / s, (ev.y - oy) / s

    def on_draw(self, w, cr):
        cr.set_source_rgb(*DESK)
        cr.paint()
        s, ox, oy = self.view()
        cr.translate(ox, oy)
        cr.scale(s, s)
        if self.fig.plate:                            # the page, lifted off the desk
            x0, y0, x1, y1 = self.fig.layout(cr)["page"]
            cr.set_source_rgba(0, 0, 0, 0.18)
            cr.rectangle(x0 + 3 / s, y0 + 4 / s, x1 - x0, y1 - y0)
            cr.fill()
        self.fig.paint(cr, editing=self.editing, selected=self.selected, temp=self.temp)

    # -- mouse ----------------------------------------------------------------
    def new_item(self, kind, **kw):
        it = {"kind": kind, "color": self.color}
        it.update(kw)
        return it

    def on_press(self, w, ev):
        self.area.grab_focus()
        x, y = self.to_doc(ev)
        if ev.button == 3:                            # right-click a brace: flip it
            hit = self.hit(x, y)
            if hit is None and self.editing is not None:
                hit = self.editing
            if hit is not None and hit["kind"] == "brace":
                self.flip_brace(hit)
            return
        if ev.button != 1:
            return
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            hit = self.hit(x, y)
            if hit is not None and hit["kind"] in TEXT_KINDS:
                self.stop_editing()
                self.snapshot()
                self.selected = self.editing = hit
                self.area.queue_draw()
            return
        if self.editing is not None:
            self.stop_editing()
            if self.tool in ("label", "note", "marker"):   # a click just ends typing
                return
        if self.tool == "select":
            hit = self.hit(x, y)
            self.selected = hit
            if hit is not None:
                self.snapshot()
                self.drag = ("move", x, y, self.grip(hit, x, y), copy.deepcopy(hit))
            self.area.queue_draw()
            return
        if self.tool == "marker":
            self.snapshot()
            it = self.new_item("marker", x=x, y=y, text="")
            self.fig.items.append(it)
            self.editing = it
        elif self.tool == "note":
            self.snapshot()
            it = self.new_item("note", x=x, y=y, text="")
            self.fig.items.append(it)
            self.editing = it
        else:
            self.drag = ("new", x, y)
            self.temp = self.temp_for(x, y, x, y)
        self.area.queue_draw()

    def flip_brace(self, it):
        """Turn a brace to face the other way; it stays that way when moved."""
        self.snapshot()
        it["side"] = -self.fig.brace_side(it)
        self.area.queue_draw()

    def temp_for(self, x0, y0, x1, y1):
        t = self.tool
        if t == "label":
            return self.new_item("label", ax=x0, ay=y0, lx=x1, ly=y1, text="")
        if t == "zoom":
            return self.new_item("box", x0=x0, y0=y0, x1=x1, y1=y1)     # the source, while dragging
        return self.new_item(t, x0=x0, y0=y0, x1=x1, y1=y1, text="")

    def on_motion(self, w, ev):
        if not self.drag:
            return
        x, y = self.to_doc(ev)
        if self.drag[0] == "new":
            _, x0, y0 = self.drag
            if self.tool == "arrow" and ev.state & Gdk.ModifierType.SHIFT_MASK:
                a = math.atan2(y - y0, x - x0)
                a = round(a / (math.pi / 12)) * (math.pi / 12)
                L = math.hypot(x - x0, y - y0)
                x, y = x0 + L * math.cos(a), y0 + L * math.sin(a)
            self.temp = self.temp_for(x0, y0, x, y)
        else:
            _, sx, sy, grip, orig = self.drag
            self.apply_move(self.selected, orig, grip, x - sx, y - sy)
        self.area.queue_draw()

    def on_release(self, w, ev):
        if not self.drag or ev.button != 1:
            return
        x, y = self.to_doc(ev)
        kind = self.drag[0]
        if kind == "new":
            _, x0, y0 = self.drag
            temp, self.temp, self.drag = self.temp, None, None
            far = math.hypot(x - x0, y - y0) > 6
            t = self.tool
            if t == "label":
                if not far:                           # a click: put the label up and right
                    temp["lx"], temp["ly"] = x0 + self.fig.px(70), y0 - self.fig.px(46)
                self.snapshot()
                self.fig.items.append(temp)
                self.editing = temp
            elif not far:
                pass
            elif t == "zoom":
                self.snapshot()
                self.fig.items.append(self.place_zoom(x0, y0, temp["x1"], temp["y1"]))
            else:
                self.snapshot()
                self.fig.items.append(temp)
                if t in ("box", "brace"):
                    self.editing = temp
        else:
            self.drag = None
        self.area.queue_draw()

    def on_scroll(self, w, ev):
        it = self.selected
        if it is None or it["kind"] != "zoom":
            return
        step = -8 if ev.direction == Gdk.ScrollDirection.DOWN else 8
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            step = -8 * ev.delta_y
        it["r"] = max(30, min(400, it["r"] + step))
        self.area.queue_draw()

    def place_zoom(self, x0, y0, x1, y1):
        it = self.new_item("zoom", sx0=x0, sy0=y0, sx1=x1, sy1=y1, cx=0, cy=0, r=0)
        scx, scy, rs, *_ = self.fig.zoom_geom(it)
        r = max(self.fig.px(64), min(self.fig.px(150), rs * 2.4))
        gap = rs + r + self.fig.px(28)
        iw, ih = self.fig.iw, self.fig.ih
        boxes = [self.fig.bbox(o) for o in self.fig.items]

        def cost(cx, cy):
            """Overlap with other marks counts most; then leaving the shot."""
            c = 0.0
            for b0, b1, b2, b3 in boxes:
                ox = max(0, min(cx + r, b2) - max(cx - r, b0))
                oy = max(0, min(cy + r, b3) - max(cy - r, b1))
                c += ox * oy * 4
            outside = (max(0, r - cx) + max(0, cx + r - iw) + max(0, r - cy) + max(0, cy + r - ih))
            c += outside * r * 0.6
            if not (-WORK + r <= cx <= iw + WORK - r and -WORK + r <= cy <= ih + WORK - r):
                c += 1e9
            return c

        cands = []
        for deg in range(0, 360, 20):
            a = math.radians(deg)
            for g in (gap, gap * 1.35):
                cands.append((scx + g * math.cos(a), scy + g * math.sin(a)))
        best = min(cands, key=lambda p: cost(*p))
        it["cx"], it["cy"] = best or (scx + gap, scy)
        it["r"] = r
        return it

    # -- hit testing and moving -------------------------------------------------
    def hit(self, x, y):
        for it in reversed(self.fig.items):
            k = it["kind"]
            if k == "arrow":
                if seg_dist(x, y, it["x0"], it["y0"], it["x1"], it["y1"]) < 9:
                    return it
                continue
            if k == "zoom":
                scx, scy, rs, cx, cy, r = self.fig.zoom_geom(it)
                if math.hypot(x - cx, y - cy) <= r + 6 or math.hypot(x - scx, y - scy) <= rs + 6:
                    return it
                continue
            b = self.fig.bbox(it)
            if b[0] - 6 <= x <= b[2] + 6 and b[1] - 6 <= y <= b[3] + 6:
                return it
        return None

    def grip(self, it, x, y):
        """Which part of the item the drag holds."""
        k, near = it["kind"], 11
        if k == "label":
            return "anchor" if math.hypot(x - it["ax"], y - it["ay"]) < near else "text"
        if k in ("arrow", "brace"):
            if math.hypot(x - it["x0"], y - it["y0"]) < near:
                return "p0"
            if math.hypot(x - it["x1"], y - it["y1"]) < near:
                return "p1"
            return "all"
        if k in ("box", "highlight", "redact"):
            for cx, cy, g in ((it["x0"], it["y0"], "p0"), (it["x1"], it["y1"], "p1"),
                              (it["x0"], it["y1"], "x0y1"), (it["x1"], it["y0"], "x1y0")):
                if math.hypot(x - cx, y - cy) < near:
                    return g
            return "all"
        if k == "zoom":
            scx, scy, rs, cx, cy, r = self.fig.zoom_geom(it)
            return "dst" if math.hypot(x - cx, y - cy) <= r + 6 else "src"
        return "all"

    def apply_move(self, it, orig, grip, dx, dy):
        k = it["kind"]
        moves = {
            ("label", "anchor"): ("ax", "ay"), ("label", "text"): ("lx", "ly"),
            ("zoom", "dst"): ("cx", "cy"), ("zoom", "src"): ("sx0", "sy0", "sx1", "sy1"),
        }
        if (k, grip) in moves:
            keys = moves[(k, grip)]
        elif grip == "p0":
            keys = ("x0", "y0")
        elif grip == "p1":
            keys = ("x1", "y1")
        elif grip == "x0y1":
            keys = ("x0", "y1")
        elif grip == "x1y0":
            keys = ("x1", "y0")
        else:
            keys = [key for key in orig if key in ("x", "y", "x0", "y0", "x1", "y1", "ax", "ay", "lx", "ly",
                                                    "sx0", "sy0", "sx1", "sy1", "cx", "cy")]
        for key in keys:
            it[key] = orig[key] + (dx if key.rstrip("01").endswith("x") else dy)

    # -- keys -------------------------------------------------------------------
    def on_key(self, w, ev):
        focus = self.get_focus()
        ctrl = ev.state & self.primary
        shift = ev.state & Gdk.ModifierType.SHIFT_MASK
        kv = ev.keyval
        if focus in (self.cap, self.num, self.title_e):
            if kv == Gdk.KEY_Escape or kv == Gdk.KEY_Tab:
                self.area.grab_focus()
                return True
            return False
        if self.editing is not None:
            it = self.editing
            if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                if shift and it["kind"] == "note":
                    it["text"] = it.get("text", "") + "\n"
                else:
                    self.stop_editing()
            elif kv == Gdk.KEY_Escape:
                self.stop_editing()
            elif kv == Gdk.KEY_BackSpace:
                t = it.get("text", "")
                if ctrl:
                    t = t.rstrip()
                    t = t[:t.rfind(" ") + 1] if " " in t else ""
                else:
                    t = t[:-1]
                it["text"] = t
            elif ctrl:
                return False
            else:
                ch = chr(Gdk.keyval_to_unicode(kv)) if Gdk.keyval_to_unicode(kv) else ""
                if ch and ch.isprintable():
                    it["text"] = it.get("text", "") + ch
            self.area.queue_draw()
            return True
        if ctrl and kv in (Gdk.KEY_z, Gdk.KEY_Z):
            if shift:
                self.restore(self.redo, self.undo)
            else:
                self.restore(self.undo, self.redo)
            return True
        if ctrl and kv in (Gdk.KEY_y,):
            self.restore(self.redo, self.undo)
            return True
        if ctrl and kv in (Gdk.KEY_s, Gdk.KEY_S):
            self.save(close=False, as_new=bool(shift))
            return True
        if ctrl and desktop.IS_MAC and kv in (Gdk.KEY_q, Gdk.KEY_w):
            self.quit(False)
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.quit(True)
            return True
        if kv == Gdk.KEY_Escape:
            if self.selected is not None:
                self.selected = None
                self.area.queue_draw()
            else:
                self.quit(False)
            return True
        if kv == Gdk.KEY_Tab:
            self.cap.grab_focus()
            return True
        if kv in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and self.selected is not None:
            self.snapshot()
            self.fig.items.remove(self.selected)
            self.selected = None
            self.area.queue_draw()
            return True
        if ctrl:
            return False
        ch = chr(Gdk.keyval_to_unicode(kv)).lower() if Gdk.keyval_to_unicode(kv) else ""
        if ch.isdigit() and 1 <= int(ch) <= len(PALETTE):
            self.set_color(int(ch) - 1)
            return True
        if ch == "p":
            self.plate_btn.set_active(not self.plate_btn.get_active())
            return True
        if ch in ("-", "+", "="):
            self.set_size(self.size_spin.get_value() + (SIZE_STEP if ch != "-" else -SIZE_STEP))
            self.flash(f"Size {int(self.size_spin.get_value())}%: every mark and the caption")
            return True
        if ch == "f" and self.selected is not None and self.selected["kind"] == "brace":
            self.flip_brace(self.selected)
            return True
        for name, key, _ in TOOLS:
            if ch == key.lower():
                self.set_tool(name)
                return True
        return False
