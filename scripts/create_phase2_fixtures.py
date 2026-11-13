"""Create clearly synthetic reliability fixtures, never used as real evaluation PDFs."""
from pathlib import Path
import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tests/fixtures/pdfs"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    pdfmetrics.registerFont(TTFont("FixtureArial", str(font_path)))
    picture = Image.new("RGB", (1100, 550), "white")
    draw = ImageDraw.Draw(picture)
    draw.text((55, 80), "SCANNED TEST FIXTURE", fill="black", font=ImageFont.truetype(str(font_path), 42))
    draw.text((55, 170), "This page contains a raster image only.", fill="black", font=ImageFont.truetype(str(font_path), 35))
    draw.text((55, 250), "OCR must not be silently invented.", fill="black", font=ImageFont.truetype(str(font_path), 35))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")

    def text(c, lines):
        c.setFont("FixtureArial", 13)
        for i, line in enumerate(lines):
            c.drawString(55, 730 - i * 24, line)

    def scan(c):
        c.drawImage(ImageReader(buffer), 35, 200, width=540, height=270)

    c = canvas.Canvas(str(DEST / "native-unicode.pdf"), pagesize=(612,792))
    c.setTitle("Synthetic Unicode reliability fixture")
    text(c, ["SYNTHETIC RELIABILITY FIXTURE - not evaluation evidence", "Unicode: café, naïve, α, β, ∑, ∫.",
             "The Fourier transform decomposes signals into frequency components."])
    c.showPage()
    text(c, ["Second physical page", "The pumping lemma can prove that a language is not regular.",
             "A contradiction to the required repetition property rules out a finite automaton."])
    c.save()
    c = canvas.Canvas(str(DEST / "scanned.pdf"), pagesize=(612,792))
    scan(c)
    c.save()
    c = canvas.Canvas(str(DEST / "mixed.pdf"), pagesize=(612,792))
    c.showPage()  # Intentionally blank physical page 1.
    text(c, ["SYNTHETIC MIXED-PDF FIXTURE", "Fourier analysis represents signals using sinusoidal frequencies."])
    c.showPage()
    scan(c)
    c.save()
    for name, lines in (
        ("replacement-old", ["SYNTHETIC REPLACEMENT FIXTURE", "Old version: nectarines are cultivated in orchard gardens."]),
        ("replacement-new", ["SYNTHETIC REPLACEMENT FIXTURE", "Updated version: superconducting quantum circuits use Josephson junctions."])):
        c = canvas.Canvas(str(DEST / f"{name}.pdf"), pagesize=(612,792))
        c.setTitle("Synthetic replacement fixture")
        text(c, lines)
        c.save()
    c = canvas.Canvas(str(DEST / "encrypted.pdf"), pagesize=(612,792), encrypt=StandardEncryption("fixture-password"))
    text(c, ["Encrypted reliability fixture"])
    c.save()
    c = canvas.Canvas(str(DEST / "empty.pdf"), pagesize=(612,792))
    c.showPage()
    c.save()
    (DEST / "malformed.pdf").write_bytes(b"Not a PDF. Deliberate malformed-file fixture.\n")
    print(f"Created eight synthetic PDF-path fixtures under {DEST}")


if __name__ == "__main__":
    main()
