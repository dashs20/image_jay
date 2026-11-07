"""Draws the Image Jay bluejay logo -> logo.png (512px) and image_jay.ico. Run once; the app uses the files."""
import os

from PIL import Image, ImageDraw

S = 4  # supersampling
N = 512 * S
BLUE, DARK, LIGHT, WHITE, BLACK, GREY = "#2f74d0", "#1b4f99", "#7fb2f0", "#f4f7fb", "#141820", "#3a3f4a"


def P(*pts):
    return [(x * S, y * S) for x, y in pts]


img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# round badge
d.ellipse(P((16, 16), (496, 496)), fill="#e9f2ff", outline=DARK, width=10 * S)
# tail (behind body), with black bars
d.polygon(P((150, 330), (40, 430), (75, 455), (195, 360)), fill=BLUE)
for t in (0.35, 0.6, 0.85):
    ax, ay = 150 + (40 - 150) * t, 330 + (430 - 330) * t
    bx, by = 195 + (75 - 195) * t, 360 + (455 - 360) * t
    d.line(P((ax, ay), (bx, by)), fill=BLACK, width=7 * S)
# body
d.ellipse(P((130, 200), (380, 400)), fill=BLUE)
# belly
d.ellipse(P((230, 250), (385, 395)), fill=WHITE)
# wing with white tips and black bars
d.ellipse(P((140, 230), (300, 350)), fill=DARK)
for i, x in enumerate(range(165, 285, 26)):
    d.line(P((x, 300), (x + 14, 345)), fill=BLACK, width=6 * S)
    d.ellipse(P((x + 6, 333), (x + 22, 349)), fill=WHITE)
# head + crest
d.polygon(P((255, 175), (215, 60), (300, 130)), fill=BLUE)
d.polygon(P((262, 150), (245, 85), (290, 132)), fill=LIGHT)
d.ellipse(P((235, 105), (375, 245)), fill=BLUE)
# white face
d.ellipse(P((300, 150), (385, 240)), fill=WHITE)
# black necklace
d.arc(P((250, 150), (395, 290)), start=20, end=150, fill=BLACK, width=12 * S)
# eye
d.ellipse(P((318, 158), (346, 186)), fill=BLACK)
d.ellipse(P((326, 164), (334, 172)), fill=WHITE)
# beak
d.polygon(P((368, 180), (445, 195), (368, 210)), fill=GREY)
# little measurement tick marks under the bird (it's a measuring app)
d.line(P((150, 430), (370, 430)), fill=DARK, width=8 * S)
for i, x in enumerate(range(150, 371, 22)):
    h = 24 if i % 5 == 0 else 13
    d.line(P((x, 430), (x, 430 - h)), fill=DARK, width=5 * S)

logo = img.resize((512, 512), Image.LANCZOS)
here = os.path.dirname(os.path.abspath(__file__))
logo.save(os.path.join(here, "logo.png"))
logo.save(os.path.join(here, "image_jay.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote logo.png and image_jay.ico")
