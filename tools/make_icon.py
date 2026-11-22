# /// script
# requires-python = ">=3.13"
# dependencies = ["cairosvg", "pillow"]
# ///
"""Das App-Icon `moarcoal.svg` als `moarcoal.ico` (16 bis 256 px) daneben in `static/` rendern.

Die .ico liegt im Repo; nach einer Änderung am SVG neu erzeugen (braucht libcairo):

    uv run tools/make_icon.py
"""

import io
from pathlib import Path

import cairosvg
from PIL import Image

STATIC = Path(__file__).resolve().parent.parent / "src" / "moarcoal" / "static"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(svg: bytes, size: int) -> Image.Image:
    png = cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    svg = (STATIC / "moarcoal.svg").read_bytes()
    # Jede Größe aus der Vektorvorlage gerendert, nicht aus dem größten Bild verkleinert.
    images = [render(svg, size) for size in SIZES]
    target = STATIC / "moarcoal.ico"
    images[-1].save(target, sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"{target}: {', '.join(f'{s} px' for s in SIZES)}")


if __name__ == "__main__":
    main()
