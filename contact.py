"""contact.py - contact sheet of the iteration renders with their scores (Pillow)."""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCORES = [3, 4, 4, 6, 6, 7, 7, 8, 8]
NIGHT = (15, 10, 25)
TEXT = (241, 238, 247)
COLS = 3
TILE_W, TILE_H = 480, 270
PAD = 16
LABEL_H = 34

def font(size):
    for name in ("CascadiaMono.ttf", "CascadiaCode.ttf", "consola.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def main():
    n = len(SCORES)
    rows = (n + COLS - 1) // COLS
    W = PAD + COLS * (TILE_W + PAD)
    H = PAD + rows * (TILE_H + LABEL_H + PAD)
    sheet = Image.new("RGB", (W, H), NIGHT)
    draw = ImageDraw.Draw(sheet)
    f = font(18)
    for i, score in enumerate(SCORES):
        path = os.path.join(HERE, "renders", "iter_%02d.png" % (i + 1))
        im = Image.open(path).convert("RGB").resize((TILE_W, TILE_H))
        c, r = i % COLS, i // COLS
        x = PAD + c * (TILE_W + PAD)
        y = PAD + r * (TILE_H + LABEL_H + PAD)
        sheet.paste(im, (x, y))
        draw.text((x, y + TILE_H + 8), "iter %02d   score %d/10" % (i + 1, score), fill=TEXT, font=f)
    out = os.path.join(HERE, "contact.png")
    sheet.save(out)
    print("wrote", out, sheet.size)

if __name__ == "__main__":
    main()
