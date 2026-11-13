"""Varied synthetic layouts with generated ground truth; never real transactions."""
from pathlib import Path
import json
import hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import pymupdf
ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'tests/fixtures/invoice-pack';out.mkdir(parents=True,exist_ok=True)
    cases=[
      ('classic','SALES INVOICE','Bill To','Bhagwanti Trading','Invoice Date','25/09/2026','Grand Total','INR 5,310.00','sale'),
      ('columns','SALES INVOICE','Customer Name','Asha Stationers','Bill Date','September 24, 2026','Invoice Total','USD 120.00','sale'),
      ('cash-memo','CASH MEMO','Customer','Bhagwanti Trading','Date','2026-09-26','Net Payable','Rs. 950.00','unspecified'),
      ('purchase','PURCHASE INVOICE','Vendor','North Paper Supply','Invoice Date','27 Sep 2026','Total Amount','INR 12,500.00','purchase'),
      ('wrapped','SALES INVOICE','Bill To','Bhagwanti Trading','Invoice Date','28.09.2026','Grand Total','INR 800.00','sale'),
      ('due-date-trap','SALES INVOICE','Buyer','Asha Stationers','Invoice Date','29/09/2026','Grand Total','INR 4,500.00','sale'),
      ('missing-party','SALES INVOICE',None,'','Invoice Date','30/09/2026','Grand Total','INR 300.00','sale'),
      ('missing-date','SALES INVOICE','Customer','Bhagwanti Trading',None,None,'Grand Total','INR 450.00','sale'),
      ('unknown-direction','INVOICE','Bill To','Bhagwanti Trading','Date','01/10/2026','Invoice Total','EUR 400.00','unspecified'),
      ('uppercase','SALES INVOICE','BUYER','Bhagwanti Trading','BILL DATE','02/10/2026','NET PAYABLE','GBP 64.50','sale'),
      ('multipage','SALES INVOICE','Bill To','Bhagwanti Trading','Invoice Date','03/10/2026','Grand Total','INR 6,000.00','sale'),
      ('scan-clean','SALES INVOICE','Bill To','Bhagwanti Trading','Invoice Date','04/10/2026','Grand Total','INR 531.00','sale'),
      ('scan-low-res','PURCHASE INVOICE','Supplier','North Paper Supply','Bill Date','05/10/2026','Grand Total','INR 200.00','purchase'),
      ('unsupported-credit','CREDIT NOTE','Customer','Bhagwanti Trading','Date','06/10/2026','Grand Total','INR 100.00','unspecified'),
      ('unsupported-euro-decimal','INVOICE','Bill To','Europa Office','Invoice Date','07/10/2026','Grand Total','EUR 1.234,56','unspecified'),
      ('unsupported-bundle','SALES INVOICE','Bill To','Bhagwanti Trading','Invoice Date','08/10/2026','Grand Total','INR 600.00','sale'),
    ]
    truths=[]
    from knowledge_library.bills import parse_date
    for index,(key,heading,label,party,date_label,date_value,total_label,total,direction) in enumerate(cases,1):
        path=out/f'{key}.pdf';c=canvas.Canvas(str(path),pagesize=(595,842));c.setTitle('SYNTHETIC invoice validation - not a real transaction')
        def header(title):
            c.setFillColor(HexColor('#9a3412'));c.setFont('Helvetica-Bold',10);c.drawString(32,807,'SYNTHETIC TEST DOCUMENT - NOT A REAL TRANSACTION')
            c.setFillColor(HexColor('#111827'));c.setFont('Helvetica-Bold',23);c.drawString(32,755,title)
            c.setFont('Helvetica',10);c.drawString(32,730,'Demo Office Supplies | Fictional business | Software testing only')
        header(heading);number=f'PACK-{index:03d}';y=680
        def line(text,x=32):
            nonlocal y
            c.setFont('Helvetica',12);c.drawString(x,y,text);y-=28
        if key=='due-date-trap':line('Due Date: 30/12/2026');line('Ship To: Fictional Warehouse')
        if key=='columns':
            line(f'Invoice Number: {number}')
            line(f'{label}: {party}');c.setFont('Helvetica',11);c.drawString(330,652,f'{date_label}:');c.drawString(330,632,date_value)
        else:
            line(f'Invoice No: {number}')
            if label:
                if key=='wrapped':line(label+':');line(party)
                else:line(f'{label}: {party}')
            if date_label:line(f'{date_label}: {date_value}')
        y-=10;c.setStrokeColor(HexColor('#cbd5e1'));c.line(32,y,563,y);y-=28
        line('DESCRIPTION                                      QTY       UNIT PRICE')
        line('A4 printer paper                                   10        450.00')
        line('Blue ballpoint pens                                12          8.00')
        y-=12;line(f'{total_label}: {total}')
        c.setFont('Helvetica',10);c.setFillColor(HexColor('#9a3412'));c.drawString(32,80,'No goods were sold. No money is owed. No tax liability is represented.')
        c.drawString(32,62,'Amounts and items are software fixtures and need not reconcile.')
        if key in ('multipage','unsupported-bundle'):
            c.showPage();header('ITEM DETAILS' if key=='multipage' else 'SALES INVOICE');y=680
            if key=='multipage':line('Item description: thermal label rolls');line('Quantity: 4 cartons')
            else:line('Invoice No: SECOND-INVOICE');line('Bill To: Different Customer');line('Invoice Date: 09/10/2026');line('Grand Total: INR 999.00')
        c.showPage();c.save()
        if key.startswith('scan-'):
            with pymupdf.open(path) as source:
                pix=source[0].get_pixmap(matrix=pymupdf.Matrix(2 if key=='scan-clean' else 1.1,2 if key=='scan-clean' else 1.1),alpha=False)
            with pymupdf.open() as raster:
                p=raster.new_page(width=595,height=842);p.insert_image(p.rect,stream=pix.tobytes('png'));temporary=path.with_suffix('.raster.pdf');raster.save(temporary)
            temporary.replace(path)
        currency,amount=total.split(' ',1);currency='INR' if currency=='Rs.' else currency
        truths.append(dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),synthetic=True,supported=not key.startswith('unsupported'),
                           expected=dict(party=party,bill_date=parse_date(date_value) if date_value else None,invoice_number=number,direction=direction,amount=amount.replace(',',''),currency=currency),
                           requires_review=key in ('missing-party','missing-date','unknown-direction') or key.startswith('scan-'),
                           limitation='Unsupported credit note, decimal convention, or multi-invoice PDF' if key.startswith('unsupported') else None))
    (out/'ground-truth.json').write_text(json.dumps(dict(provenance='Generated synthetic labels from fixture construction; not independently annotated real invoices',cases=truths),indent=2))
    (out/'README.md').write_text('# Synthetic invoice validation pack\n\n16 fixtures. Every PDF is explicitly synthetic. No transaction is real. Ground truth is generated before extraction. Three deliberately unsupported cases are reported separately, not counted as successes.\n')
    # Contact sheets allow every page/layout to be visually reviewed.
    from PIL import Image,ImageDraw
    qa=ROOT/'results/invoice-pack-qa';qa.mkdir(exist_ok=True)
    for offset in range(0,len(cases),4):
        sheet=Image.new('RGB',(840,660),'#ddd');draw=ImageDraw.Draw(sheet)
        for j,case in enumerate(cases[offset:offset+4]):
            with pymupdf.open(out/f'{case[0]}.pdf') as pdf:
                pix=pdf[0].get_pixmap(matrix=pymupdf.Matrix(.46,.46),alpha=False)
                img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                x=(j%2)*420+12;y=(j//2)*330+22;img.thumbnail((390,300));sheet.paste(img,(x,y));draw.text((x,y-16),case[0],fill='black')
        sheet.save(qa/f'contact-{offset//4+1}.png')
    print(f'Created {len(truths)} synthetic invoices and four visual contact sheets.')


if __name__=='__main__':main()
