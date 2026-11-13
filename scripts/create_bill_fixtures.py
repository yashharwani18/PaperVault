"""Clearly synthetic invoices for exact-party/date, type, and scanned OCR tests."""
import json
from pathlib import Path
import pymupdf
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'tests/fixtures/bills';folder.mkdir(parents=True,exist_ok=True)
    pdfmetrics.registerFont(TTFont('FixtureArial','C:/Windows/Fonts/arial.ttf'))
    cases=[('sale-bhagwanti-2026-09-25','Bhagwanti Trading','25/09/2026','sale'),
           ('sale-bhagwanti-2026-09-24','Bhagwanti Trading','24/09/2026','sale'),
           ('sale-asha-2026-09-25','Asha Stationers','25/09/2026','sale'),
           ('purchase-bhagwanti-2026-09-25','Bhagwanti Trading','25/09/2026','purchase')]
    for ident,party,date,direction in cases:
        c=canvas.Canvas(str(folder/f'{ident}.pdf'),pagesize=(595,842));c.setTitle('Synthetic invoice test fixture — not a real transaction')
        c.setFillColor(colors.HexColor('#8b3c00'));c.setFont('FixtureArial',12);c.drawString(42,794,'SYNTHETIC TEST FIXTURE - NOT A REAL TRANSACTION')
        c.setFillColor(colors.black);c.setFont('FixtureArial',23);c.drawString(42,739,'SALES INVOICE' if direction=='sale' else 'PURCHASE INVOICE')
        c.setFont('FixtureArial',12)
        lines=[f'Invoice No: SYN-{ident.upper()}',f'Invoice Date: {date}',f'Transaction Type: {direction}',f'{"Bill To" if direction=="sale" else "Supplier"}: {party}',
               '','Item description: A4 printer paper','Quantity: 10 boxes','Unit price: INR 450.00','Subtotal: INR 4,500.00','GST: INR 810.00','Grand Total: INR 5,310.00','','This document exists only to validate software.','It is not evidence of an actual sale, purchase, payment, or tax liability.']
        for n,line in enumerate(lines):c.drawString(42,694-n*27,line)
        c.showPage();c.save()
    with pymupdf.open(folder/'sale-bhagwanti-2026-09-25.pdf') as source:
        pix=source[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
        with pymupdf.open() as scan:
            page=scan.new_page(width=595,height=842);page.insert_image(page.rect,stream=pix.tobytes('png'))
            scan.save(folder/'scanned-sale-bhagwanti.pdf')
    (folder/'README.md').write_text('All invoices here are SYNTHETIC SOFTWARE TEST FIXTURES. They do not represent real transactions.\n',encoding='utf-8')
    print('Created four synthetic native PDFs and one raster-only scanned invoice.')


if __name__=='__main__':main()
