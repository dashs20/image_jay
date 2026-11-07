<p align="center"><img src="logo.png" width="160" alt="Image Jay logo"></p>

# Image Jay

Measure real-world dimensions from photos and screenshots, sketch-style. Calibrate once against something of
known size, then draw lines, rectangles, circles and points and read their dimensions in mm. Clicks snap to the
centroid of the pad / hole / pin under the cursor, so you get sub-pixel accuracy even from low-res images.

## Features

- **Scale**: click two points of known separation and type the distance (math allowed, e.g. `3*2.54` for the first to
  last of 4 header pins). Or type mm/px directly.
- **Origin**: point and centre coordinates are reported relative to it (Y-up or Y-down).
- **Shapes**: line (length, angle, Δx/Δy), rectangle (corner to corner), circle (centre then radius, like a
  SolidWorks sketch), point. Click-click or click-drag.
- **Snap to blob**: clicks snap to the centroid of the region of similar colour under the cursor (adjustable tolerance).
  Hold **Shift** while clicking to flip snapping for that click.
- **Edit**: drag line ends, rectangle edges/corners, circle rim/centre. A plain click on a handle starts a new shape
  there instead, so you can centre a circle on a line's end. Lock shapes in the table so the mouse can't grab them.
- **Colour-coded dimension table**: each shape's row matches its colour. Copy as text or export CSV.
- **Straighten**: draw along an edge that should be level or plumb, and the image rotates to match.
- **Perspective**: click the 4 corners of something rectangular, drag the corners to fine-tune, then press
  **Enter** (or *Apply warp*), and the image is warped square-on. Optionally type
  its real W × H to set the exact proportions and the scale in one go.
- **Mirror / rotate 90°**, unlimited **undo** (including rotations and warps).
- **Save** (`Ctrl+S`) bundles the image, every shape, the scale and the view into one `.ijay` file. It's a zip with
  `image.png`, `session.json` and `measurements.csv`, so it's readable without the app too.

## Keys

| key | | key | |
|---|---|---|---|
| L | line | K | scale |
| R | rectangle | A | straighten |
| C | circle | W | perspective |
| P | point | S | toggle snap |
| O | origin | F / 1 | fit / 100 % |
| Ctrl+O / V / S / Z | open / paste / save / undo | Del, Esc | delete selected, cancel |
| Shift (hold) | flip snapping | Enter | apply perspective warp |

Mouse wheel zooms around the cursor; right or middle drag pans.

## Run from source

```
pip install -r requirements.txt
python image_jay.py            (or double-click "Image Jay.bat")
```

## Build and install (Windows)

```
build.bat      -> dist\ImageJay\ImageJay.exe   (PyInstaller folder build)
install.bat    -> per-user install, no admin
```

The installer copies the app to `%LOCALAPPDATA%\Programs\Image Jay`, adds a Start Menu shortcut (right-click it →
**Pin to taskbar**), makes `.ijay` files open in Image Jay, and registers an uninstaller under *Apps & features*.
Use `install.bat -Desktop` for a desktop shortcut too.

The build is unsigned. A locally built exe never triggers SmartScreen, since SmartScreen only checks downloaded
files. If you share the exe, others will see "Windows protected your PC" (click *More info → Run anyway*) unless it
is code-signed. The folder build avoids the antivirus false positives that single-file PyInstaller exes often get.

`make_logo.py` regenerates `logo.png` / `image_jay.ico`.
