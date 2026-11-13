"""Freeze natural-language queries with explicit source-page category labels."""
from pathlib import Path
import json,re,argparse,hashlib

TOPICS=[
 ('udyam',r'UDYAM REGISTRATION CERTIFICATE', ['Find the Udyam business registration certificate','उद्यम पंजीकरण प्रमाणपत्र दिखाओ','udyam registration ka certificate dikhao']),
 ('itr',r'INCOME TAX RETURN ACKNOWLEDGEMENT',['Find the income tax return filing acknowledgement','आयकर रिटर्न जमा करने की पावती दिखाओ','income tax return bharne ki receipt dikhao']),
 ('sales',r'Sales Register',['Show the sales register listing sales transactions','बिक्री का रजिस्टर दिखाओ','bikri ka register dikhao']),
 ('gst-challan',r'Form GST PMT\s*[–-]?\s*06',['Find the GST tax payment challan','जीएसटी कर भुगतान का चालान दिखाओ','GST tax jama karne ka challan dikhao']),
 ('narayandas',r'(?i)narayan\s*das',['Find invoices for Narayandas','नारायणदास के बिल दिखाओ','narayandas ke bill dikhao']),
 ('bajrang',r'(?i)bajrang',['Find invoices for Bajrang Trading','बजरंग ट्रेडिंग के बिल दिखाओ','bajrang trading ke bills dikhao']),
 ('solapur',r'(?i)solapur fabtex',['Find invoices from Solapur Fabtex','सोलापुर फैबटेक्स से आए बिल दिखाओ','solapur fabtex se aaye hue bill dikhao']),
 ('gauranga',r'(?i)gauranga industries',['Find invoices from Gauranga Industries','गौरांगा इंडस्ट्रीज के बिल दिखाओ','gauranga industries ke invoice dikhao']),
]
parser=argparse.ArgumentParser();parser.add_argument('export',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();pages=[json.loads(l) for l in (args.export/'pages.jsonl').read_text(encoding='utf-8').splitlines()];cases=[]
for topic,pattern,queries in TOPICS:
 expected=[f"{p['document_id']}:{p['page_number']}" for p in pages if re.search(pattern,p['text'],re.I)]
 assert expected,topic
 for lang,query in zip(('en','hi','hinglish'),queries):cases.append(dict(id=topic+'-'+lang,topic=topic,language=lang,query=query,expected=expected,full_backend=topic in ('udyam','itr','sales')))
args.output.mkdir(exist_ok=True,parents=True);p=args.output/'semantic-cases.jsonl';p.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf-8');print(json.dumps(dict(cases=len(cases),queries_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),topics={c['topic']:len(c['expected']) for c in cases})))
