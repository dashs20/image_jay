"""Image Jay - measure real-world dimensions from photos / screenshots, sketch-style.

Workflow
  1. Fix the image (optional): Straighten (draw along an edge that should be level) or Perspective
     (click the 4 corners of something rectangular; it gets warped square-on, optionally to a known size).
  2. Scale: click two points of known separation (e.g. first and last header pin) and type the real distance
     (math OK: 3*2.54), or type mm/px in the side panel.
  3. Origin (optional): coordinates are reported relative to it.
  4. Draw lines, rectangles (corner to corner), circles (centre, then radius) and points. Click-click or
     click-drag. Clicks snap to the centroid of the blob under the cursor (pads, holes, pins).
  5. Edit by dragging line ends, rectangle edges/corners, circle rim/centre, points. Lock shapes in the table.
  6. Save (Ctrl+S) bundles the image and the whole session into one .ijay file; Open loads it back.
"""
import copy
import csv
import io
import json
import math
import os
import re
import sys
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np
from PIL import Image, ImageGrab, ImageOps, ImageTk

APP = "Image Jay"
# resources live next to the script, or in PyInstaller's unpack dir when frozen
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SESSION_EXT = ".ijay"
# name, hotkey, hint, snap first click, snap second click
TOOLS = [("Line", "l", "click/drag two points: length + angle", True, True),
         ("Rect", "r", "rectangle: click/drag corner to corner", False, False),
         ("Circle", "c", "circle: click the centre (snaps to holes), then the radius", True, False),
         ("Point", "p", "click: coordinates relative to the origin", True, None),
         ("Origin", "o", "click: set the origin", True, None),
         ("Scale", "k", "click two points of known separation, then type the real distance", True, True),
         ("Straighten", "a", "draw along an edge that should be level/plumb: the image rotates to match", False, False),
         ("Perspective", "w", "click the 4 corners of a rectangular object, drag them to adjust, Enter to warp", False, False)]
TOOL = {t[0]: t for t in TOOLS}
NO_EDIT_TOOLS = ("Origin", "Straighten", "Perspective")
PALETTE = ["#ffd400", "#00e5ff", "#39ff14", "#ff8c00", "#4d9dff", "#ff4d6d", "#b388ff", "#00ffa3",
           "#ffe066", "#7ef9ff", "#ff9ecf", "#c6ff00", "#ffb347", "#66ffcc", "#e0e0e0", "#ff6ef0"]
SCALE_COL, ORIGIN_COL, SEL_COL, LIVE_COL, BLOB_COL = "#ff3df2", "#ff3030", "#ffffff", "#ffffff", "#00ff9c"
QUAD_COL = "#ffb000"
HIT = 7            # handle grab distance, screen px
MAX_WARP_PX = 8000  # cap on the warped image's longest side
SAFE_EXPR = re.compile(r"^[0-9eE+\-*/(). ]+$")


def eval_number(s):
    s = (s or "").strip().replace(",", ".")
    if not s or not SAFE_EXPR.match(s):
        raise ValueError("enter a number or simple math like 3*2.54")
    v = float(eval(s, {"__builtins__": {}}, {}))  # only digits/operators reach eval
    if not math.isfinite(v) or v <= 0:
        raise ValueError("value must be > 0")
    return v


class Blob:
    def __init__(self, cx, cy, area, bbox):
        self.cx, self.cy, self.area, self.bbox = cx, cy, area, tuple(bbox)  # bbox x0,y0,x1,y1 (continuous)

    @property
    def diameter(self):
        return 2 * math.sqrt(self.area / math.pi)

    def to_json(self):
        return {"cx": self.cx, "cy": self.cy, "area": self.area, "bbox": list(self.bbox)}

    @staticmethod
    def from_json(d):
        return Blob(d["cx"], d["cy"], d["area"], d["bbox"]) if d else None


def _flood(mask, sy, sx):
    """4-connected region of mask containing (sy, sx), by repeated vectorised dilation"""
    comp = np.zeros_like(mask)
    comp[sy, sx] = True
    while True:
        g = comp.copy()
        g[1:] |= comp[:-1]
        g[:-1] |= comp[1:]
        g[:, 1:] |= comp[:, :-1]
        g[:, :-1] |= comp[:, 1:]
        g &= mask
        if np.array_equal(g, comp):
            return comp
        comp = g


def find_blob(arr, x, y, tol, max_r=512):
    """Connected region of similar colour around (x, y); None if it leaks into the background.
    Coordinates are continuous: pixel (i, j) spans [i, i+1) x [j, j+1). Searches in growing windows
    so small pads/holes are found instantly."""
    h, w = arr.shape[:2]
    xi, yi = int(math.floor(x)), int(math.floor(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return None
    seed = arr[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2].reshape(-1, arr.shape[2]).astype(np.float32).mean(0)
    r = 32
    while r <= max_r:
        x0, y0, x1, y1 = max(0, xi - r), max(0, yi - r), min(w, xi + r + 1), min(h, yi + r + 1)
        win = arr[y0:y1, x0:x1].astype(np.float32)
        mask = np.sqrt(((win - seed) ** 2).sum(-1)) <= tol
        sy, sx = yi - y0, xi - x0
        if not mask[sy, sx]:
            return None
        comp = _flood(mask, sy, sx)
        ys, xs = np.nonzero(comp)
        if (xs.min() == 0 and x0 > 0) or (ys.min() == 0 and y0 > 0) or                 (xs.max() == comp.shape[1] - 1 and x1 < w) or (ys.max() == comp.shape[0] - 1 and y1 < h):
            r *= 2  # reaches the window edge: look wider
            continue
        return Blob(float(xs.mean() + x0 + 0.5), float(ys.mean() + y0 + 0.5), int(len(xs)),
                    (int(xs.min() + x0), int(ys.min() + y0), int(xs.max() + x0 + 1), int(ys.max() + y0 + 1)))
    return None  # leaks into the background


def ideal_text(hexcol):
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff"


def homography(src, dst):
    """3x3 H with H @ [x, y, 1] ~ [u, v, 1] for 4 point pairs"""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(A, float), np.array(b, float))
    return np.append(h, 1).reshape(3, 3)


def apply_h(H, p):
    x, y, w = H @ np.array([p[0], p[1], 1.0])
    return (float(x / w), float(y / w))


def order_quad(pts):
    """sort 4 points as top-left, top-right, bottom-right, bottom-left (screen coords, y down)"""
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    pts = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # clockwise on screen
    i = min(range(4), key=lambda k: pts[k][0] + pts[k][1])            # top-left = smallest x+y
    return pts[i:] + pts[:i]


class App:
    CURSORS = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow", "t": "sb_v_double_arrow",
               "b": "sb_v_double_arrow", "lt": "size_nw_se", "rb": "size_nw_se", "rt": "size_ne_sw",
               "lb": "size_ne_sw", "center": "fleur", "rim": "sizing", "p0": "fleur", "p1": "fleur"}

    def __init__(self, root, path=None):
        self.root = root
        root.title(APP)
        root.geometry("1500x940")
        self._set_icon()
        self.img = self.arr = self.path = None
        self.z, self.ox, self.oy = 1.0, 0.0, 0.0
        self.items = []           # dict(type, pts, blobs, color, locked, [real], [note])
        self.mm_per_px = None
        self.origin = None
        self.rotation = 0.0       # total rotation from Straighten / 90° buttons (deg, CCW)
        self.warped = False       # perspective-corrected?
        self.active = None        # 2-point shape being drawn
        self.quad = []            # perspective corners (editable until applied)
        self.quad_drag = None     # index of the perspective corner being dragged
        self.shift = False        # Shift held: invert snapping
        self.edit = None          # (item index, handle) being dragged
        self.maybe_edit = None    # handle pressed, waiting to see if it's a drag
        self.history = []         # undo snapshots
        self.pan_start = None
        self.cursor = None
        self.color_i = 0
        self.tool = tk.StringVar(value="Line")
        self.snap = tk.BooleanVar(value=True)
        self.tol = tk.DoubleVar(value=40)
        self.yup = tk.BooleanVar(value=True)
        self.decimals = tk.IntVar(value=2)
        self._photo = None
        self._build()
        if path:
            self.load(path)

    def _set_icon(self):
        self._splash = None
        try:
            logo = Image.open(os.path.join(HERE, "logo.png")).convert("RGBA")
            self._icon = ImageTk.PhotoImage(logo.resize((64, 64), Image.LANCZOS))
            self.root.iconphoto(True, self._icon)
            self._splash = ImageTk.PhotoImage(logo.resize((220, 220), Image.LANCZOS))
        except Exception:
            pass
        ico = os.path.join(HERE, "image_jay.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except tk.TclError:
                pass

    # ================================================================== UI
    def _build(self):
        ttk.Style().configure("Treeview", rowheight=24)
        bar = ttk.Frame(self.root, padding=4)
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Open", command=self.open, width=6).pack(side="left")
        ttk.Button(bar, text="Paste", command=self.paste, width=6).pack(side="left", padx=2)
        ttk.Button(bar, text="Save", command=self.save, width=6).pack(side="left", padx=(0, 10))
        for name, key, *_ in TOOLS:
            ttk.Radiobutton(bar, text=f"{name} [{key.upper()}]", value=name, variable=self.tool,
                            command=self.cancel_active, style="Toolbutton").pack(side="left", padx=1)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Checkbutton(bar, text="Snap [S]", variable=self.snap).pack(side="left")
        ttk.Label(bar, text="tol").pack(side="left", padx=(4, 2))
        ttk.Scale(bar, from_=5, to=150, variable=self.tol, length=80).pack(side="left")
        self.tol_lbl = ttk.Label(bar, width=4, text="40")
        self.tol_lbl.pack(side="left")
        self.tol.trace_add("write", lambda *a: self.tol_lbl.config(text=f"{self.tol.get():.0f}"))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="↔", width=3, command=lambda: self.mirror("h")).pack(side="left")
        ttk.Button(bar, text="↕", width=3, command=lambda: self.mirror("v")).pack(side="left", padx=1)
        ttk.Button(bar, text="⟲90", width=5, command=lambda: self.rotate(90)).pack(side="left", padx=1)
        ttk.Button(bar, text="⟳90", width=5, command=lambda: self.rotate(-90)).pack(side="left", padx=1)
        ttk.Button(bar, text="Fit [F]", command=self.fit).pack(side="left", padx=(4, 0))
        self.apply_btn = ttk.Button(bar, text="Apply warp [Enter]", command=self.apply_warp, state="disabled")
        self.apply_btn.pack(side="left", padx=(6, 0))

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.cv = tk.Canvas(body, bg="#202124", highlightthickness=0, cursor="crosshair")
        body.add(self.cv, weight=4)
        side = ttk.Frame(body, padding=6)
        body.add(side, weight=1)

        sc = ttk.LabelFrame(side, text="Scale & origin", padding=6)
        sc.pack(fill="x")
        self.scale_lbl = ttk.Label(sc)
        self.scale_lbl.pack(anchor="w")
        row = ttk.Frame(sc)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="mm/px").pack(side="left")
        self.scale_entry = ttk.Entry(row, width=10)
        self.scale_entry.pack(side="left", padx=4)
        self.scale_entry.bind("<Return>", lambda e: self.set_scale_manual())
        ttk.Button(row, text="Set", command=self.set_scale_manual, width=5).pack(side="left")
        ttk.Button(row, text="Clear", command=self.clear_scale, width=6).pack(side="left", padx=2)
        row2 = ttk.Frame(sc)
        row2.pack(fill="x", pady=(4, 0))
        self.origin_lbl = ttk.Label(row2)
        self.origin_lbl.pack(side="left")
        ttk.Button(row2, text="Reset", command=self.reset_origin, width=6).pack(side="right")
        row3 = ttk.Frame(sc)
        row3.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(row3, text="Y axis up", variable=self.yup, command=self.refresh_all).pack(side="left")
        ttk.Label(row3, text="decimals").pack(side="left", padx=(10, 2))
        ttk.Spinbox(row3, from_=0, to=5, width=3, textvariable=self.decimals, command=self.refresh_all).pack(side="left")
        self.rot_lbl = ttk.Label(sc, foreground="#666")
        self.rot_lbl.pack(anchor="w", pady=(4, 0))

        lst = ttk.LabelFrame(side, text="Dimensions  (click 🔓 to lock a shape)", padding=6)
        lst.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("lock", "type", "size", "where")
        self.tree = ttk.Treeview(lst, columns=cols, show="headings", selectmode="extended")
        for cname, head, w, st in (("lock", "", 34, False), ("type", "shape", 90, False),
                                   ("size", "dimensions", 210, True), ("where", "position", 190, True)):
            self.tree.heading(cname, text=head)
            self.tree.column(cname, width=w, stretch=st, anchor="center" if cname == "lock" else "w")
        self.tree.pack(side="top", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.redraw())
        self.tree.bind("<Button-1>", self.on_tree_click, add="+")
        btns = ttk.Frame(lst)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Delete [Del]", command=self.delete_selected).pack(side="left")
        ttk.Button(btns, text="Undo [Ctrl+Z]", command=self.undo).pack(side="left", padx=2)
        ttk.Button(btns, text="Lock all", command=lambda: self.lock_all(True)).pack(side="left")
        ttk.Button(btns, text="Unlock all", command=lambda: self.lock_all(False)).pack(side="left", padx=2)
        btns2 = ttk.Frame(lst)
        btns2.pack(fill="x", pady=(4, 0))
        ttk.Button(btns2, text="Copy table", command=self.copy_table).pack(side="left")
        ttk.Button(btns2, text="Export CSV…", command=self.export_csv).pack(side="left", padx=2)
        ttk.Button(btns2, text="Clear all", command=self.clear_all).pack(side="left")

        ttk.Label(side, foreground="#666", wraplength=440, justify="left",
                  text="Wheel: zoom · right/middle drag: pan · Esc: cancel · 1: 100% · F: fit · Ctrl+S: save\n"
                       "Hold Shift while clicking to flip snapping on/off for that click.\n"
                       "Drag line ends, rectangle edges/corners, circle rim/centre to adjust (unless locked). "
                       "Ctrl+Z undoes anything, including rotations and warps.").pack(fill="x", pady=(8, 0))

        self.status = ttk.Label(self.root, anchor="w", padding=(6, 2))
        self.status.pack(side="bottom", fill="x")

        c = self.cv
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        for b in ("2", "3"):
            c.bind(f"<ButtonPress-{b}>", self.pan_begin)
            c.bind(f"<B{b}-Motion>", self.pan_move)
            c.bind(f"<ButtonRelease-{b}>", lambda e: setattr(self, "pan_start", None))
        c.bind("<Motion>", self.on_motion)
        c.bind("<MouseWheel>", lambda e: self.zoom_at(e.x, e.y, 1.25 if e.delta > 0 else 0.8))
        r = self.root
        r.bind("<Control-o>", lambda e: self.open())
        r.bind("<Control-v>", lambda e: self.paste())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-z>", lambda e: self.undo())
        r.bind("<Escape>", lambda e: self.cancel_active())
        r.bind("<Return>", lambda e: self._hot(self.apply_warp))
        for k in ("Shift_L", "Shift_R"):
            r.bind(f"<KeyPress-{k}>", lambda e: self._set_shift(True))
            r.bind(f"<KeyRelease-{k}>", lambda e: self._set_shift(False))
        r.bind("<Delete>", lambda e: self.delete_selected())
        for name, key, *_ in TOOLS:
            r.bind(f"<KeyPress-{key}>", lambda e, n=name: self._hot(lambda: (self.tool.set(n), self.cancel_active())))
        r.bind("<KeyPress-s>", lambda e: self._hot(lambda: self.snap.set(not self.snap.get())))
        r.bind("<KeyPress-f>", lambda e: self._hot(self.fit))
        r.bind("<KeyPress-1>", lambda e: self._hot(lambda: self.set_zoom(1.0)))
        self.refresh_all()

    def _set_shift(self, state):
        if self.shift != state:
            self.shift = state
            self.update_status()

    def _hot(self, fn):
        if not isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox)):
            fn()

    # ================================================================== undo
    def snapshot(self):
        self.history.append({"img": self.img, "items": copy.deepcopy(self.items), "mm": self.mm_per_px,
                             "origin": self.origin, "rotation": self.rotation, "warped": self.warped,
                             "color_i": self.color_i})
        del self.history[:-60]

    def undo(self):
        if self.quad:
            self.quad.pop()  # remove the last perspective corner
            self.quad_drag = None
        elif self.active:
            self.active = None
        elif self.history:
            s = self.history.pop()
            size_changed = self.img is None or s["img"].size != self.img.size
            self.img, self.items, self.mm_per_px = s["img"], s["items"], s["mm"]
            self.origin, self.rotation, self.warped, self.color_i = s["origin"], s["rotation"], s["warped"], s["color_i"]
            self.arr = np.asarray(self.img)
            self.tree.selection_set([])
            if size_changed:
                self.fit()
        self.refresh_all()

    # ================================================================== files
    def open(self):
        p = filedialog.askopenfilename(filetypes=[("Images & Image Jay sessions",
                                                   "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *" + SESSION_EXT),
                                                  ("Image Jay session", "*" + SESSION_EXT), ("All", "*.*")])
        if p:
            self.load(p)

    def paste(self):
        try:
            data = ImageGrab.grabclipboard()
        except Exception as e:
            messagebox.showerror(APP, f"Clipboard read failed: {e}")
            return
        if isinstance(data, list) and data and os.path.isfile(data[0]):
            self.load(data[0])
        elif isinstance(data, Image.Image):
            self.set_image(data, "clipboard")
        else:
            messagebox.showinfo(APP, "No image on the clipboard.")

    def load(self, path):
        if path.lower().endswith(SESSION_EXT):
            return self.load_session(path)
        try:
            im = Image.open(path)
            im.load()
        except Exception as e:
            messagebox.showerror(APP, f"Could not open {path}:\n{e}")
            return
        self.set_image(im, path)

    def set_image(self, im, name):
        if im.mode in ("RGBA", "LA", "P"):
            im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im.convert("RGBA"))
        self.img = im.convert("RGB")
        self.arr = np.asarray(self.img)
        self.path = name
        self.items, self.active, self.quad, self.edit, self.origin = [], None, [], None, None
        self.color_i, self.rotation, self.warped, self.mm_per_px, self.history = 0, 0.0, False, None, []
        self.fit()
        self.refresh_all()

    def save(self):
        if self.img is None:
            return
        base = os.path.splitext(os.path.basename(self.path or "measurement"))[0]
        p = filedialog.asksaveasfilename(defaultextension=SESSION_EXT, initialfile=base + SESSION_EXT,
                                         filetypes=[("Image Jay session", "*" + SESSION_EXT)])
        if not p:
            return
        items = []
        for it in self.items:
            d = {k: v for k, v in it.items() if k != "blobs"}
            d["pts"] = [[float(c) for c in q] for q in it["pts"]]
            d["blobs"] = [b.to_json() if b else None for b in it["blobs"]]
            items.append(d)
        session = {"app": APP, "version": 1, "source": self.path, "image": "image.png", "items": items,
                   "mm_per_px": self.mm_per_px, "origin": list(self.origin) if self.origin else None,
                   "rotation": self.rotation, "warped": self.warped, "color_i": self.color_i,
                   "yup": self.yup.get(), "decimals": self.decimals.get(), "snap": self.snap.get(), "tol": self.tol.get(),
                   "view": [self.z, self.ox, self.oy]}
        buf = io.BytesIO()
        self.img.save(buf, "PNG")
        try:
            with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("image.png", buf.getvalue())
                z.writestr("session.json", json.dumps(session, indent=1))
                z.writestr("measurements.csv", self.csv_text())
        except OSError as e:
            messagebox.showerror(APP, f"Could not save {p}:\n{e}")
            return
        self.path = p
        self.refresh_all()
        self.status.config(text=f"Saved {p}")

    def load_session(self, p):
        try:
            with zipfile.ZipFile(p) as z:
                s = json.loads(z.read("session.json"))
                im = Image.open(io.BytesIO(z.read(s.get("image", "image.png"))))
                im.load()
        except Exception as e:
            messagebox.showerror(APP, f"Could not open session {p}:\n{e}")
            return
        self.set_image(im, p)
        self.items = []
        for d in s.get("items", []):
            d["pts"] = [tuple(q) for q in d["pts"]]
            d["blobs"] = [Blob.from_json(b) for b in d.get("blobs", [])]
            d.setdefault("locked", False)
            self.items.append(d)
        self.mm_per_px = s.get("mm_per_px")
        self.origin = tuple(s["origin"]) if s.get("origin") else None
        self.rotation, self.warped = s.get("rotation", 0.0), s.get("warped", False)
        self.color_i = s.get("color_i", len(self.items))
        self.yup.set(s.get("yup", True))
        self.decimals.set(s.get("decimals", 2))
        self.snap.set(s.get("snap", True))
        self.tol.set(s.get("tol", 40))
        if s.get("view"):
            self.z, self.ox, self.oy = s["view"]
        self.refresh_all()

    # ================================================================== image transforms
    def _transform_all(self, f):
        """apply a point transform to every shape, blob and the origin"""
        for it in self.items:
            it["pts"] = [f(p) for p in it["pts"]]
            for b in it["blobs"]:
                if b:
                    b.cx, b.cy = f((b.cx, b.cy))
                    x0, y0, x1, y1 = b.bbox
                    cs = [f(q) for q in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
                    b.bbox = (min(q[0] for q in cs), min(q[1] for q in cs), max(q[0] for q in cs), max(q[1] for q in cs))
            if it["type"] == "Rect":  # stay axis-aligned: re-fit to the transformed corners
                (ax, ay), (bx, by) = it["pts"]
                it["pts"] = [(min(ax, bx), min(ay, by)), (max(ax, bx), max(ay, by))]
            if it["type"] == "Scale":  # the calibration distance changed in pixels: rescale
                d = math.hypot(it["pts"][1][0] - it["pts"][0][0], it["pts"][1][1] - it["pts"][0][1])
                if d > 0.5:
                    self.mm_per_px = it["real"] / d
        if self.origin:
            self.origin = f(self.origin)
        self.active = self.edit = None
        self.quad = []

    def mirror(self, axis):
        if self.img is None:
            return
        self.snapshot()
        w, h = self.img.size
        self.img = ImageOps.mirror(self.img) if axis == "h" else ImageOps.flip(self.img)
        self.arr = np.asarray(self.img)
        self._transform_all((lambda p: (w - p[0], p[1])) if axis == "h" else (lambda p: (p[0], h - p[1])))
        self.refresh_all()

    def rotate(self, deg):
        """rotate the image CCW by deg, keeping every shape attached to the image"""
        if self.img is None or abs(deg) < 1e-6:
            return
        self.snapshot()
        w, h = self.img.size
        exact90 = abs(deg % 90) < 1e-9
        self.img = self.img.rotate(deg, resample=Image.NEAREST if exact90 else Image.BICUBIC, expand=True,
                                   fillcolor=(255, 255, 255))
        self.arr = np.asarray(self.img)
        W, H = self.img.size
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        self._transform_all(lambda p: (W / 2 + ca * (p[0] - w / 2) + sa * (p[1] - h / 2),
                                       H / 2 - sa * (p[0] - w / 2) + ca * (p[1] - h / 2)))
        self.rotation = (self.rotation + deg + 180) % 360 - 180
        self.fit()
        self.refresh_all()

    def perspective(self, quad):
        tl, tr, br, bl = order_quad(quad)
        wpx = (math.dist(tl, tr) + math.dist(bl, br)) / 2
        hpx = (math.dist(tl, bl) + math.dist(tr, br)) / 2
        if wpx < 2 or hpx < 2:
            messagebox.showwarning(APP, "Those corners are too close together.")
            return
        s = simpledialog.askstring(APP, f"Corrected rectangle is about {wpx:.0f} x {hpx:.0f} px.\n\n"
                                        "Real size W x H in mm (optional, e.g. 40 x 25)\n"
                                        "- sets the exact proportions and the scale.\n"
                                        "Leave blank to keep the measured proportions.", parent=self.root)
        if s is None:
            self.redraw()
            return
        real = None
        if s.strip():
            m = re.match(r"^\s*([0-9.eE+\-*/() ]+?)\s*[xX×,]\s*([0-9.eE+\-*/() ]+)\s*$", s)
            try:
                if not m:
                    raise ValueError("type it as W x H, e.g. 40 x 25")
                real = (eval_number(m.group(1)), eval_number(m.group(2)))
            except ValueError as err:
                messagebox.showerror(APP, str(err))
                return
            hpx = wpx * real[1] / real[0]
        dst = [(0, 0), (wpx, 0), (wpx, hpx), (0, hpx)]
        try:
            H = homography([tl, tr, br, bl], dst)
        except np.linalg.LinAlgError:
            messagebox.showerror(APP, "Those 4 points don't form a usable quadrilateral (3 in a line?).")
            return
        # output bounds: the whole image if it maps sanely, else the rectangle plus a generous margin
        w, h = self.img.size
        corners = [(0, 0), (w, 0), (w, h), (0, h)]
        ws = [(H @ np.array([x, y, 1.0]))[2] for x, y in corners]
        mapped = [apply_h(H, p) for p in corners]
        xs, ys = [p[0] for p in mapped], [p[1] for p in mapped]
        if min(ws) > 0 and max(xs) - min(xs) < 6 * wpx + w and max(ys) - min(ys) < 6 * hpx + h:
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        else:
            bx0, by0, bx1, by1 = -wpx, -hpx, 2 * wpx, 2 * hpx
        k = min(1.0, MAX_WARP_PX / max(bx1 - bx0, by1 - by0))
        F = np.array([[k, 0, -k * bx0], [0, k, -k * by0], [0, 0, 1]]) @ H  # source px -> output px
        G = np.linalg.inv(F)
        G /= G[2, 2]
        out = (max(1, int(math.ceil((bx1 - bx0) * k))), max(1, int(math.ceil((by1 - by0) * k))))
        self.snapshot()
        self.img = self.img.transform(out, Image.PERSPECTIVE, tuple(G.flatten()[:8]), Image.BICUBIC,
                                      fillcolor=(255, 255, 255))
        self.arr = np.asarray(self.img)
        self._transform_all(lambda p: apply_h(F, p))
        self.warped = True
        if real:
            self.items = [it for it in self.items if it["type"] != "Scale"]
            self.mm_per_px = real[0] / (wpx * k)
            self.add({"type": "Rect", "pts": [apply_h(F, tl), apply_h(F, br)], "blobs": [None, None],
                      "note": f"reference {real[0]:g} x {real[1]:g} mm"}, snapshot=False)
        self.fit()
        self.refresh_all()
        return True

    # ================================================================== view
    def to_canvas(self, x, y):
        return (x - self.ox) * self.z, (y - self.oy) * self.z

    def to_image(self, cx, cy):
        return cx / self.z + self.ox, cy / self.z + self.oy

    def fit(self):
        if self.img is None:
            return
        self.root.update_idletasks()
        W, H = max(self.cv.winfo_width(), 50), max(self.cv.winfo_height(), 50)
        self.z = min(W / self.img.width, H / self.img.height) * 0.95
        self.ox, self.oy = (self.img.width - W / self.z) / 2, (self.img.height - H / self.z) / 2
        self.redraw()

    def set_zoom(self, z):
        self.zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, z / self.z)

    def zoom_at(self, cx, cy, f):
        if self.img is None:
            return
        ix, iy = self.to_image(cx, cy)
        self.z = min(max(self.z * f, 0.02), 80)
        self.ox, self.oy = ix - cx / self.z, iy - cy / self.z
        self.redraw()
        self.update_status()

    def pan_begin(self, e):
        self.pan_start = (e.x, e.y, self.ox, self.oy)

    def pan_move(self, e):
        if self.pan_start:
            x, y, ox, oy = self.pan_start
            self.ox, self.oy = ox - (e.x - x) / self.z, oy - (e.y - y) / self.z
            self.redraw()

    # ================================================================== formatting
    def L(self, px):
        d = self.decimals.get()
        return f"{px * self.mm_per_px:.{d}f}" if self.mm_per_px else f"{px:.1f}"

    @property
    def unit(self):
        return "mm" if self.mm_per_px else "px"

    def coord(self, x, y):
        ox, oy = self.origin or (0.0, 0.0)
        dx, dy = x - ox, y - oy
        if self.yup.get():
            dy = -dy
        return f"({self.L(dx)}, {self.L(dy)})"

    def describe(self, it):
        t, p, u = it["type"], it["pts"], self.unit
        if t in ("Line", "Scale"):
            (x1, y1), (x2, y2) = p
            d = math.hypot(x2 - x1, y2 - y1)
            ang = math.degrees(math.atan2(-(y2 - y1) if self.yup.get() else (y2 - y1), x2 - x1))
            if t == "Scale":
                return f"{it['real']:g} mm = {d:.2f} px", f"{it['real'] / d:.5f} mm/px"
            return (f"L {self.L(d)} {u}  ∠{ang:.1f}°  (Δx {self.L(abs(x2 - x1))}, Δy {self.L(abs(y2 - y1))})",
                    f"{self.coord(x1, y1)} → {self.coord(x2, y2)}")
        if t == "Rect":
            (x1, y1), (x2, y2) = p
            note = f"   [{it['note']}]" if it.get("note") else ""
            return (f"{self.L(abs(x2 - x1))} × {self.L(abs(y2 - y1))} {u}{note}",
                    f"centre {self.coord((x1 + x2) / 2, (y1 + y2) / 2)}")
        if t == "Circle":
            (cx, cy), (ex, ey) = p
            r = math.hypot(ex - cx, ey - cy)
            return f"Ø {self.L(2 * r)} {u}  (r {self.L(r)})", f"centre {self.coord(cx, cy)}"
        if t == "Point":
            b = it["blobs"][0]
            size = ""
            if b:
                x0, y0, x1, y1 = b.bbox
                size = f"blob Ø {self.L(b.diameter)} {u}  ({self.L(x1 - x0)} × {self.L(y1 - y0)})"
            return size, self.coord(*p[0])
        return "", ""

    # ================================================================== hit testing / editing
    def handle_at(self, cx, cy):
        """(index, handle) of the unlocked shape handle under the cursor, newest first"""
        for i in range(len(self.items) - 1, -1, -1):
            it = self.items[i]
            if it["locked"]:
                continue
            P = [self.to_canvas(*p) for p in it["pts"]]
            t = it["type"]
            if t in ("Line", "Scale"):
                for k in (0, 1):
                    if math.hypot(cx - P[k][0], cy - P[k][1]) <= HIT:
                        return i, f"p{k}"
            elif t == "Point":
                if math.hypot(cx - P[0][0], cy - P[0][1]) <= HIT:
                    return i, "p0"
            elif t == "Circle":
                r = math.hypot(P[1][0] - P[0][0], P[1][1] - P[0][1])
                dc = math.hypot(cx - P[0][0], cy - P[0][1])
                if dc <= HIT:
                    return i, "center"
                if abs(dc - r) <= HIT:
                    return i, "rim"
            elif t == "Rect":
                x0, y0 = min(P[0][0], P[1][0]), min(P[0][1], P[1][1])
                x1, y1 = max(P[0][0], P[1][0]), max(P[0][1], P[1][1])
                h = ""
                if y0 - HIT <= cy <= y1 + HIT:
                    if abs(cx - x0) <= HIT: h += "l"
                    elif abs(cx - x1) <= HIT: h += "r"
                if x0 - HIT <= cx <= x1 + HIT:
                    if abs(cy - y0) <= HIT: h += "t"
                    elif abs(cy - y1) <= HIT: h += "b"
                if h:
                    return i, h
        return None

    def apply_edit(self, cx, cy):
        i, h = self.edit
        it = self.items[i]
        x, y = self.to_image(cx, cy)
        t = it["type"]
        if t in ("Line", "Scale", "Point"):
            k = int(h[1])
            if TOOL[t][4 if k else 3]:
                (x, y), b = self.snap_pt(cx, cy)
            else:
                b = None
            it["pts"][k] = (x, y)
            it["blobs"][k] = b
            if t == "Scale":
                d = math.hypot(it["pts"][1][0] - it["pts"][0][0], it["pts"][1][1] - it["pts"][0][1])
                if d > 0.5:
                    self.mm_per_px = it["real"] / d
        elif t == "Circle":
            (ccx, ccy), (ex, ey) = it["pts"]
            if h == "center":
                (x, y), b = self.snap_pt(cx, cy)
                it["pts"] = [(x, y), (ex + x - ccx, ey + y - ccy)]
                it["blobs"][0] = b
            else:
                it["pts"][1] = (x, y)
        elif t == "Rect":
            (ax, ay), (bx, by) = it["pts"]
            x0, y0, x1, y1 = min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
            if "l" in h: x0 = x
            if "r" in h: x1 = x
            if "t" in h: y0 = y
            if "b" in h: y1 = y
            it["pts"] = [(x0, y0), (x1, y1)]
            it.pop("note", None)

    def on_tree_click(self, e):
        if self.tree.identify_region(e.x, e.y) == "cell" and self.tree.identify_column(e.x) == "#1":
            row = self.tree.identify_row(e.y)
            if row:
                it = self.items[int(row)]
                it["locked"] = not it["locked"]
                self.refresh_all()
                return "break"

    def lock_all(self, state):
        for it in self.items:
            it["locked"] = state
        self.refresh_all()

    # ================================================================== interaction
    def snap_pt(self, cx, cy, enabled=True):
        x, y = self.to_image(cx, cy)
        if enabled and (self.snap.get() != self.shift) and self.arr is not None:  # Shift inverts snapping
            b = find_blob(self.arr, x, y, self.tol.get())
            if b:
                return (b.cx, b.cy), b
        return (x, y), None

    def on_press(self, e):
        self.shift = bool(e.state & 0x0001)
        if self.img is None:
            return
        tool = self.tool.get()
        _, _, _, snap1, snap2 = TOOL[tool]
        if tool == "Perspective":
            k = self.quad_corner_at(e.x, e.y)
            if k is not None:            # grab a corner to adjust it
                self.quad_drag = k
            elif len(self.quad) < 4:     # place the next corner
                self.quad.append(self.to_image(e.x, e.y))
            self.redraw()
            self.update_status()
            return
        if self.active:                                     # second click of click-click mode
            p2, b2 = self.snap_pt(e.x, e.y, bool(snap2))
            self.finish(p2, b2)
            return
        hit = self.handle_at(e.x, e.y) if tool not in NO_EDIT_TOOLS else None
        if hit:  # dragging a handle edits that shape; a plain click there still starts a new shape
            self.maybe_edit = (hit, e.x, e.y)
            return
        self.start_new(e)

    def start_new(self, e):
        tool = self.tool.get()
        p, b = self.snap_pt(e.x, e.y, bool(TOOL[tool][3]))
        if tool == "Origin":
            self.snapshot()
            self.origin = p
            self.refresh_all()
            return
        if tool == "Point":
            self.add({"type": "Point", "pts": [p], "blobs": [b]})
            return
        self.active = {"type": tool, "p1": p, "b1": b, "p2": p, "press": (e.x, e.y)}
        self.redraw()

    def quad_corner_at(self, cx, cy):
        for k, p in enumerate(self.quad):
            x, y = self.to_canvas(*p)
            if math.hypot(cx - x, cy - y) <= HIT + 2:
                return k
        return None

    def apply_warp(self):
        if len(self.quad) == 4 and self.perspective(list(self.quad)):
            self.quad = []
        self.redraw()
        self.update_status()

    def on_drag(self, e):
        self.shift = bool(e.state & 0x0001)
        if self.quad_drag is not None:
            self.quad[self.quad_drag] = self.to_image(e.x, e.y)
            self.redraw()
            return
        if self.maybe_edit:
            hit, x0, y0 = self.maybe_edit
            if math.hypot(e.x - x0, e.y - y0) <= 4:
                return
            self.maybe_edit = None
            self.snapshot()
            self.edit = hit
            self.tree.selection_set(str(hit[0]))
        if self.edit:
            self.apply_edit(e.x, e.y)
            self.refresh_all()
        elif self.active:
            self.active["p2"] = self.to_image(e.x, e.y)
            self.redraw()
            self.update_status()

    def on_release(self, e):
        self.shift = bool(e.state & 0x0001)
        if self.quad_drag is not None:
            self.quad_drag = None
            self.update_status()
            return
        if self.maybe_edit:  # clicked a handle without dragging: treat it as a normal click
            self.maybe_edit = None
            self.start_new(e)
            a = self.active
            if a and "press" in a:
                del a["press"]  # click-click mode
            return
        if self.edit:
            self.edit = None
            self.refresh_all()
            return
        a = self.active
        if not a or "press" not in a:
            return
        moved = math.hypot(e.x - a["press"][0], e.y - a["press"][1]) > 4
        del a["press"]
        if moved:                                           # click-drag: finish on release
            p2, b2 = self.snap_pt(e.x, e.y, bool(TOOL[a["type"]][4]))
            self.finish(p2, b2)

    def on_motion(self, e):
        self.shift = bool(e.state & 0x0001)
        self.cursor = (e.x, e.y)
        if (self.active and "press" not in self.active) or self.quad:
            if self.active:
                self.active["p2"] = self.to_image(e.x, e.y)
            self.redraw()
        if self.tool.get() == "Perspective":
            self.cv.config(cursor="fleur" if self.quad_corner_at(e.x, e.y) is not None else "crosshair")
        else:
            hit = None if (self.active or self.tool.get() in NO_EDIT_TOOLS or self.img is None) \
                else self.handle_at(e.x, e.y)
            self.cv.config(cursor=self.CURSORS.get(hit[1], "crosshair") if hit else "crosshair")
        self.update_status()

    def finish(self, p2, b2):
        a, self.active = self.active, None
        p1 = a["p1"]
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) * self.z < 2:
            self.redraw()
            return
        t = a["type"]
        if t == "Scale":
            self.calibrate(p1, p2, a["b1"], b2)
        elif t == "Straighten":
            ang = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))  # clockwise on screen (y down)
            delta = ang - round(ang / 90) * 90
            if abs(delta) < 0.01:
                self.status.config(text="Already straight.")
                self.redraw()
            else:
                self.rotate(delta)
        elif t == "Rect":
            self.add({"type": "Rect", "pts": [(min(p1[0], p2[0]), min(p1[1], p2[1])),
                                              (max(p1[0], p2[0]), max(p1[1], p2[1]))], "blobs": [None, None]})
        else:
            self.add({"type": t, "pts": [p1, p2], "blobs": [a["b1"], b2]})

    def calibrate(self, p1, p2, b1, b2):
        px = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        while True:
            s = simpledialog.askstring(APP, f"Those points are {px:.2f} px apart.\n\nReal distance in mm "
                                            "(math OK, e.g. 3*2.54 = first to last of 4 header pins):", parent=self.root)
            if s is None:
                self.redraw()
                return
            try:
                real = eval_number(s)
                break
            except ValueError as err:
                messagebox.showerror(APP, str(err))
        self.snapshot()
        self.items = [it for it in self.items if it["type"] != "Scale"]
        self.mm_per_px = real / px
        self.items.append({"type": "Scale", "pts": [p1, p2], "blobs": [b1, b2], "real": real,
                           "color": SCALE_COL, "locked": True})
        self.refresh_all()

    def set_scale_manual(self):
        try:
            v = eval_number(self.scale_entry.get())
        except ValueError as err:
            messagebox.showerror(APP, str(err))
            return
        self.snapshot()
        self.items = [it for it in self.items if it["type"] != "Scale"]
        self.mm_per_px = v
        self.refresh_all()

    def clear_scale(self):
        self.snapshot()
        self.mm_per_px = None
        self.items = [it for it in self.items if it["type"] != "Scale"]
        self.refresh_all()

    def reset_origin(self):
        self.snapshot()
        self.origin = None
        self.refresh_all()

    def cancel_active(self):
        self.active = self.edit = self.quad_drag = None
        self.quad = []
        self.redraw()
        self.update_status()

    def add(self, it, snapshot=True):
        if snapshot:
            self.snapshot()
        it["color"] = PALETTE[self.color_i % len(PALETTE)]
        it["locked"] = False
        self.color_i += 1
        self.items.append(it)
        self.refresh_all()
        kids = self.tree.get_children()
        if kids:
            self.tree.see(kids[-1])

    def delete_selected(self):
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        idx = {int(i) for i in self.tree.selection()}
        if not idx:
            return
        self.snapshot()
        if any(self.items[i]["type"] == "Scale" for i in idx):
            self.mm_per_px = None
        self.items = [it for i, it in enumerate(self.items) if i not in idx]
        self.tree.selection_set([])
        self.refresh_all()

    def clear_all(self):
        if self.items and messagebox.askyesno(APP, "Remove all shapes and the scale?"):
            self.snapshot()
            self.items, self.mm_per_px, self.origin, self.color_i = [], None, None, 0
            self.refresh_all()

    def rows(self):
        return [(i + 1, it["type"], *self.describe(it)) for i, it in enumerate(self.items)]

    def copy_table(self):
        hdr = ("#", "shape", f"dimensions ({self.unit})", f"position ({self.unit})")
        txt = "\n".join("\t".join(map(str, r)) for r in [hdr] + self.rows())
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.status.config(text=f"Copied {len(self.items)} rows to the clipboard")

    def csv_text(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["#", "shape", "dimensions", "position", "x1_px", "y1_px", "x2_px", "y2_px", "mm_per_px"])
        for r, it in zip(self.rows(), self.items):
            pts = [f"{c:.3f}" for pt in it["pts"] for c in pt]
            w.writerow(list(r) + pts + [""] * (4 - len(pts)) + [self.mm_per_px or ""])
        return buf.getvalue()

    def export_csv(self):
        if not self.items:
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if p:
            with open(p, "w", newline="", encoding="utf8") as f:
                f.write(self.csv_text())

    # ================================================================== drawing
    def refresh_all(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            tag = f"c{i}"
            self.tree.tag_configure(tag, background=it["color"], foreground=ideal_text(it["color"]))
            self.tree.insert("", "end", iid=str(i), tags=(tag,),
                             values=("🔒" if it["locked"] else "🔓", f"{i + 1}  {it['type']}", *self.describe(it)))
        self.tree.selection_set([s for s in sel if self.tree.exists(s)])
        self.scale_lbl.config(text=f"scale: {self.mm_per_px:.5f} mm/px  ({1 / self.mm_per_px:.3f} px/mm)"
                              if self.mm_per_px else "scale: not set (values in px)")
        self.origin_lbl.config(text=f"origin: px ({self.origin[0]:.1f}, {self.origin[1]:.1f})"
                               if self.origin else "origin: image top-left")
        notes = []
        if self.rotation:
            notes.append(f"rotated {self.rotation:+.2f}°")
        if self.warped:
            notes.append("perspective-corrected")
        self.rot_lbl.config(text="image: " + ", ".join(notes) if notes else "")
        title = APP
        if self.img is not None:
            title += f" - {os.path.basename(self.path)} ({self.img.width}x{self.img.height})"
        self.root.title(title)
        self.redraw()
        self.update_status()

    def update_status(self):
        parts = []
        if self.img is not None and self.cursor:
            x, y = self.to_image(*self.cursor)
            parts += [f"px ({x:.1f}, {y:.1f})", f"pos {self.coord(x, y)} {self.unit}"]
            if self.active:
                (px, py), (qx, qy) = self.active["p1"], self.active["p2"]
                if self.active["type"] == "Straighten":
                    ang = math.degrees(math.atan2(qy - py, qx - px))
                    parts.append(f"rotate by {-(ang - round(ang / 90) * 90):+.2f}°")
                else:
                    parts.append(f"live {self.L(math.hypot(qx - px, qy - py))} {self.unit}")
            if len(self.quad) == 4:
                parts.append("drag corners to adjust, Enter / Apply warp to transform, Esc to cancel")
            elif self.quad:
                parts.append(f"corner {len(self.quad) + 1} of 4")
            if self.shift:
                parts.append("SNAP " + ("OFF" if self.snap.get() else "ON") + " (Shift)")
        parts.append(f"zoom {self.z * 100:.0f}%")
        self.apply_btn.config(state="normal" if len(self.quad) == 4 else "disabled")
        parts.append(f"{self.tool.get()}: {TOOL[self.tool.get()][2]}")
        self.status.config(text="     ".join(parts))

    def _label(self, x, y, text, color):
        c = self.cv
        t = c.create_text(x + 8, y - 6, text=text, anchor="sw", fill=ideal_text(color), font=("Segoe UI", 9, "bold"))
        bb = c.bbox(t)
        if bb:
            c.tag_lower(c.create_rectangle(bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1, fill=color, outline=""), t)

    def _cross(self, x, y, color, s=6, w=1):
        self.cv.create_line(x - s, y, x + s, y, fill=color, width=w)
        self.cv.create_line(x, y - s, x, y + s, fill=color, width=w)

    def _blob(self, b):
        if b:
            a, bb = self.to_canvas(*b.bbox[:2]), self.to_canvas(*b.bbox[2:])
            self.cv.create_rectangle(*a, *bb, outline=BLOB_COL, dash=(2, 2))

    def draw_shape(self, kind, p1, p2, color, width=2, label=None, dash=None, locked=False):
        c = self.cv
        a, b = self.to_canvas(*p1), self.to_canvas(*p2)
        if kind in ("Line", "Scale", "Straighten"):
            c.create_line(*a, *b, fill=color, width=width, dash=dash)
            self._cross(*a, color)
            self._cross(*b, color)
            anchor = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        elif kind == "Rect":
            c.create_rectangle(*a, *b, outline=color, width=width, dash=dash)
            anchor = (min(a[0], b[0]), min(a[1], b[1]))
        elif kind == "Circle":
            r = math.hypot(b[0] - a[0], b[1] - a[1])
            c.create_oval(a[0] - r, a[1] - r, a[0] + r, a[1] + r, outline=color, width=width, dash=dash)
            c.create_line(*a, *b, fill=color, dash=(3, 3))
            self._cross(*a, color)
            anchor = (a[0] + r * 0.7071, a[1] - r * 0.7071)
        else:
            return
        if label:
            self._label(*anchor, ("🔒 " if locked else "") + label, color)

    def redraw(self):
        c = self.cv
        c.delete("all")
        if self.img is None:
            mx, my = c.winfo_width() / 2, c.winfo_height() / 2
            if self._splash:
                c.create_image(mx, my - 60, image=self._splash)
            c.create_text(mx, my + 75, fill="#e8eaed", font=("Segoe UI", 22, "bold"), text=APP)
            c.create_text(mx, my + 110, fill="#9aa0a6", font=("Segoe UI", 12),
                          text="Open an image or session (Ctrl+O), or paste a screenshot (Ctrl+V)")
            return
        W, H = c.winfo_width(), c.winfo_height()
        x0, y0 = max(0, int(math.floor(self.ox))), max(0, int(math.floor(self.oy)))
        x1 = min(self.img.width, int(math.ceil(self.ox + W / self.z)) + 1)
        y1 = min(self.img.height, int(math.ceil(self.oy + H / self.z)) + 1)
        if x1 > x0 and y1 > y0:
            sw, sh = max(1, int(round((x1 - x0) * self.z))), max(1, int(round((y1 - y0) * self.z)))
            crop = self.img.crop((x0, y0, x1, y1)).resize((sw, sh), Image.NEAREST if self.z >= 1 else Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(crop)
            cx, cy = self.to_canvas(x0, y0)
            c.create_image(cx, cy, image=self._photo, anchor="nw")
            if self.z >= 12:
                for gx in range(x0, x1 + 1):
                    X = self.to_canvas(gx, 0)[0]
                    c.create_line(X, cy, X, cy + sh, fill="#000000", stipple="gray25")
                for gy in range(y0, y1 + 1):
                    Y = self.to_canvas(0, gy)[1]
                    c.create_line(cx, Y, cx + sw, Y, fill="#000000", stipple="gray25")

        if self.origin:
            ox, oy = self.to_canvas(*self.origin)
            up = -1 if self.yup.get() else 1
            c.create_line(ox, oy, ox + 45, oy, fill=ORIGIN_COL, width=2, arrow="last")
            c.create_line(ox, oy, ox, oy + 45 * up, fill=ORIGIN_COL, width=2, arrow="last")
            c.create_text(ox + 50, oy, text="x", fill=ORIGIN_COL, anchor="w")
            c.create_text(ox, oy + 52 * up, text="y", fill=ORIGIN_COL)

        sel = {int(i) for i in self.tree.selection()}
        for i, it in enumerate(self.items):
            for b in it["blobs"]:
                self._blob(b)
            if it["type"] == "Point":
                p = self.to_canvas(*it["pts"][0])
                if i in sel:
                    self._cross(*p, SEL_COL, 11, 4)
                self._cross(*p, it["color"], 9, 2)
                self._label(*p, ("🔒 " if it["locked"] else "") + f"{i + 1}  {self.coord(*it['pts'][0])}", it["color"])
                continue
            if i in sel:
                self.draw_shape(it["type"], *it["pts"], SEL_COL, width=5)
            dims = self.describe(it)[0]
            label = f"{i + 1}  " + (f"SCALE {it['real']:g} mm" if it["type"] == "Scale"
                                    else dims.split("  (")[0].split("   [")[0])
            self.draw_shape(it["type"], *it["pts"], it["color"], label=label, locked=it["locked"],
                            dash=(6, 3) if it["type"] == "Scale" else None)

        a = self.active
        if a:
            self._blob(a["b1"])
            self.draw_shape(a["type"], a["p1"], a["p2"], LIVE_COL, width=1, dash=(4, 4))
        if self.quad:
            placed = [self.to_canvas(*p) for p in self.quad]
            if len(placed) == 4:   # complete: solid outline, ready to adjust / apply
                c.create_polygon(*[v for p in placed for v in p], outline=QUAD_COL, fill="", width=2)
                xs, ys = [p[0] for p in placed], [p[1] for p in placed]
                self._label(min(xs), min(ys) - 14, "drag corners to adjust · Enter = apply warp · Esc = cancel",
                            QUAD_COL)
            else:                  # still placing: rubber band to the cursor
                pts = placed + ([self.cursor] if self.cursor else [])
                if len(pts) > 1:
                    c.create_line(*[v for p in pts for v in p], fill=LIVE_COL, dash=(4, 4), width=2)
                if len(pts) == 4:
                    c.create_line(*pts[-1], *pts[0], fill=LIVE_COL, dash=(2, 4))
            for k, p in enumerate(placed):
                col = QUAD_COL if len(placed) == 4 else LIVE_COL
                c.create_oval(p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6, outline=col, width=2,
                              fill="#000000" if k == self.quad_drag else "")
                c.create_line(p[0] - 3, p[1], p[0] + 3, p[1], fill=col)
                c.create_line(p[0], p[1] - 3, p[0], p[1] + 3, fill=col)
                c.create_text(p[0] + 11, p[1] - 11, text=str(k + 1), fill=col, font=("Segoe UI", 10, "bold"))


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)  # crisp on high-DPI Windows displays
        if not getattr(sys, "frozen", False):
            # running from source under pythonw: show the jay on the taskbar instead of the Python icon.
            # (the built exe already has its own identity, and a custom ID would break pinned-shortcut grouping)
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("ImageJay")
    except Exception:
        pass
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
