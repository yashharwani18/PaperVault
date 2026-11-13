"""Freeze source-checked real-bill fixtures for Android structured-search tests.

Original PDFs and library databases are read only. Generated assets are test-only.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import sqlite3
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={
 'INV-45shiv.pdf':('45','61800.00','64890.00'),
 'INV-127panipat.pdf':('127','27200.00','27200.00'),
 'INV-127dhariwal.pdf':('127','33720.00','33720.00'),
 'INV-329harekirshna.pdf':('329','16620.00','17451.00'),
 'INV36handloomhouse.pdf':('36','29280.00','30744.00'),
 'INV-122mahashukbhai.pdf':('122','61440.00','61440.00'),
 'INV-38banaras.pdf':('38','91470.00','96043.50'),
 'INV-39bhavnahandloom.pdf':('39','13600.00','14280.00'),
 'INV-40shiv.pdf':('40','99600.00','104580.00'),
 'INV-120rankua.pdf':('120','22200.00','23310.00'),
 'INV-120satguru.pdf':('120','22000.00','23100.00'),
 'INV-37jyoti.pdf':('37','14520.00','15246.00'),
 'INV-145nurani.pdf':('145','29074.00','29074.00'),
}


def main():
    library=ROOT/'data/demo-invoices'
    output=ROOT/'.cache/bill-quality/assets/bill-quality'
    output.mkdir(parents=True,exist_ok=True)
    documents=[]
    with sqlite3.connect((library/'library.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for filename,(number,subtotal,total) in EXPECTED.items():
            row=db.execute('SELECT * FROM documents WHERE filename=?',(filename,)).fetchone()
            if row is None:raise ValueError('Missing real bill: '+filename)
            source=library/row['managed_path'];digest=hashlib.sha256(source.read_bytes()).hexdigest()
            if digest!=row['sha256']:raise ValueError('Source changed: '+filename)
            fields={};invoice_pages=[]
            with pymupdf.open(source) as pdf:
                for page_number,page in enumerate(pdf,1):
                    text=page.get_text()
                    if re.search(r'Invoice\s+(?:Number|No\.?)\s*[:#]?\s*INV\s*[- ]*'+re.escape(number)+r'(?!\d)',text,re.I):invoice_pages.append(page_number)
                    for field,want in (('subtotal',subtotal),('total',total)):
                        matches=re.findall(r'(?im)^'+field+r'\s*\n\s*₹?\s*(\d+(?:\.\d{2})?)',text)
                        if want in matches:fields[field]={'value':want,'page_number':page_number}
            if set(fields)!={'total','subtotal'} or not invoice_pages:raise ValueError('Source oracle did not confirm '+filename)
            shutil.copyfile(source,output/(digest+'.pdf'))
            documents.append({'filename':filename,'sha256':digest,'asset':digest+'.pdf','invoice_number':number,'invoice_page':invoice_pages[0],'fields':fields})
    cases=[]
    dev=lambda s:s.translate(str.maketrans('0123456789','०१२३४५६७८९'))
    for document in documents:
        value=document['fields']['total']['value'];number=document['invoice_number']
        forms=[('en',f'total exactly {value}','total',value),('en',f'invoice subtotal of {document["fields"]["subtotal"]["value"]}','subtotal',document['fields']['subtotal']['value']),
               ('hi',f'{value} वाला बिल','total',value),('hi',f'{dev(value)} वाला बिल दिखाओ','total',value),
               ('hinglish',f'mujhe {value} wala bill dikhao','total',value),
               ('en',f'show me the invoice {number}','invoice_number',number),
               ('hi',f'मुझे बिल नंबर {dev(number)} दिखाओ','invoice_number',number)]
        for language,query,field,wanted in forms:
            if any(c['query']==query for c in cases):continue
            expected=[{'filename':d['filename'],'page_number':d['invoice_page'] if field=='invoice_number' else d['fields'][field]['page_number']} for d in documents if (d['invoice_number'] if field=='invoice_number' else d['fields'][field]['value'])==wanted]
            cases.append({'query':query,'language':language,'field':field,'value':wanted,'expected':expected,'matching':'exact'})
    for query,language,field,value in [('total exactly 99999999','en','total','99999999.00'),('99999999 वाला बिल','hi','total','99999999.00'),('show me the invoice 99999999','en','invoice_number','99999999')]:
        cases.append({'query':query,'language':language,'field':field,'value':value,'expected':[],'matching':'exact'})
    corpus={'provenance':'13 real bills, hash-verified against the existing local library; literal field values checked independently in original PDFs with PyMuPDF. Developer-assisted labels, not independent human annotations.',
            'limitations':'Structured invoice-number and amount search with real Android PDF extraction. Does not measure embeddings, semantic recall, OCR, unseen layouts, or 50–100 real-bill coverage.',
            'documents':documents,'cases':cases}
    (output/'corpus.json').write_text(json.dumps(corpus,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Prepared {len(documents)} real PDFs and {len(cases)} frozen queries in {output}')


if __name__=='__main__':main()
