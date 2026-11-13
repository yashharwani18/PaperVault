"""Freeze multilingual cases from the private phone export before changing parsers."""
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import re
import argparse
from benchmark_phone_export import LABEL, canonical

ROOT = Path(__file__).resolve().parents[1]
DIGITS = str.maketrans('0123456789', '०१२३४५६७८९')
INVOICE = {
 'en': ['invoice number {id}', 'show me the invoice {id}', 'find invoice no. {id}', 'open bill number {id}'],
 'hi': ['बिल नंबर {id} दिखाओ', 'मुझे इनवॉइस नंबर {id} दिखाओ', '{id} नंबर का बिल दिखाओ',
        'इनवॉइस संख्या {id} खोजो', 'कृपया बिल क्रमांक {id} दिखाइए', 'मुझे {id} नंबर वाला बिल चाहिए',
        'बिल नम्बर {id} दिखाना', 'नमस्ते, मुझे बिल नंबर {id} दिखा दो'],
 'hinglish': ['invoice {id} dikhao', 'mujhe invoice number {id} dikhao', '{id} number ka bill dikhao',
              'bhai inv{id} dikha do', 'bill no {id} chahiye', 'namaste mujhe invoice no {id} dikhana',
              'mera bill number {id} kholo', 'please {id} number wala invoice nikaalo'],
}
AMOUNT = {
 'en': ['total {value}', 'show me the invoice for {value}', 'invoice subtotal {value}'],
 'hi': ['मुझे {value} रुपये वाला बिल दिखाओ', 'कुल राशि {value} का बिल दिखाओ',
        '{value} रुपए का बिल चाहिए', 'कर से पहले {value} वाला बिल',
        'बिल का कुल {value} है', 'नमस्ते, {value} रुपये का बिल दिखाइए'],
 'hinglish': ['mujhe {value} wala bill dikhao', 'bhai {value} rupaye ka bill dikha do',
              '{value} ka invoice chahiye', 'tax se pehle {value} wala bill',
              'namaste mujhe total {value} ka bill dikhao', 'bil ka total {value} hai'],
}
UNSAFE = {
 'en': ['total under 6600', 'subtotal 6600 and total 7700', 'total INR 6600 USD',
        '6600 or 7700 wala bill', 'total 6600 and 7700', 'invoice for -6600', 'invoice total 6600.001'],
 'hi': ['6600 वाला बिल से कम', '6600 से ज्यादा का बिल', 'कुल 6600 और 7700 वाला बिल',
        '6600 या 7700 का बिल दिखाओ', '6600 और 7700 के बीच वाला बिल', 'कुल ६६०० और ७७०० वाला बिल'],
 'hinglish': ['6600 se kam ka bill', '6600 se zyada wala invoice', '6600 ya 7700 wala bill',
              '6600 aur 7700 ke beech ka bill', 'total 6600 ya 7700', '6600 wala bill aur 7700 wala bill'],
}


def prepare(export, output):
 output.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((export/'manifest.json').read_text())
 for name in ('documents.jsonl','pages.jsonl','chunks.jsonl','vectors.f32'):
  assert hashlib.sha256((export/name).read_bytes()).hexdigest()==manifest['sha256'][name]
 pages=[json.loads(l) for l in (export/'pages.jsonl').read_text(encoding='utf-8').splitlines()]
 ids=defaultdict(set);values={};amounts=defaultdict(set)
 # Independent, explicit single-value source lines only; avoid table/layout guesses.
 money=re.compile(r'(?im)^\s*(subtotal|total|grand total|total amount)\s*[:=]?\s*(?:₹|INR|Rs\.?)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*$')
 for p in pages:
  key=f"{p['document_id']}:{p['page_number']}"
  for m in LABEL.finditer(p['text']):
   if re.search(r'\d',m.group(1)):
    k=canonical(m.group(1));ids[k].add(key);values.setdefault(k,m.group(1).strip())
  if not re.search(r'(?i)\binvoice\b',p['text']):continue
  for m in money.finditer(p['text']):
   field='subtotal' if m.group(1).casefold()=='subtotal' else 'total'
   value=f"{Decimal(m.group(2).replace(',','')):.2f}";amounts[(field,value)].add(key)
 cases=[]
 for k in sorted(ids):
  identifier=values[k]
  # Prefix-free numeric form also covers INV-inv25 without changing source text.
  forms=[identifier]+([k] if k.isdigit() and identifier!=k else [])
  for value in forms:
   for lang,templates in INVOICE.items():
    for template in templates:
     if template=='bhai inv{id} dikha do' and not value.isdigit():continue
     query=template.format(id=value)
     cases.append(dict(kind='invoice',language=lang,query=query,identifier=k,expected=sorted(ids[k])))
   if value.isdigit():
    for template in INVOICE['hi'][:4]:
     cases.append(dict(kind='invoice',language='hi',query=template.format(id=value.translate(DIGITS)),identifier=k,expected=sorted(ids[k])))
 for (field,value),targets in sorted(amounts.items()):
  for lang,templates in AMOUNT.items():
   for template in templates:
    wanted='subtotal' if any(s in template for s in ('subtotal','tax se pehle','कर से पहले')) else 'total'
    if wanted!=field:continue
    query=template.format(value=value)
    cases.append(dict(kind='amount',language=lang,query=query,field=field,value=value,expected=sorted(targets)))
    if lang=='hi':cases.append(dict(kind='amount',language=lang,query=query.translate(DIGITS),field=field,value=value,expected=sorted(targets)))
 for lang,templates in UNSAFE.items():
  for query in templates:cases.append(dict(kind='unsafe',language=lang,query=query,expected=[]))
 for lang,templates in INVOICE.items():
  for template in templates:
   cases.append(dict(kind='invoice',language=lang,query=template.format(id='987654321098765'),identifier='987654321098765',expected=[]))
 # Stable per-identifier/value split, so paraphrases never leak between development and holdout.
 for i,c in enumerate(cases):
  group=c.get('identifier',c.get('value',c['query']))
  c['split']='holdout' if int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%4==0 else 'development'
  c['id']=f"ml-{i:05d}"
 (output/'cases.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf-8')
 # Small full-backend subset, stratified by language/kind and frozen before fixes.
 subset=[]
 for lang in INVOICE:
  for kind in ('invoice','amount'):
   pool=[c for c in cases if c['language']==lang and c['kind']==kind and c['expected'] and len({k.split(':')[0] for k in c['expected']})<=4]
   templates={}
   for c in pool:
    pattern=re.sub(r'[0-9०-९]+(?:[.,][0-9०-९]+)*','#',c['query'])
    templates.setdefault(pattern,c)
   subset.extend(list(templates.values())[:16])
 (output/'device-cases.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in subset),encoding='utf-8')
 counts=defaultdict(int)
 for c in cases:counts[c['language']+':'+c['kind']]+=1
 protocol=dict(documents=manifest['counts']['documents'],pages=len(pages),distinct_identifiers=len(ids),distinct_field_amounts=len(amounts),cases=len(cases),by_language_kind=dict(counts),device_cases=len(subset),cases_sha256=hashlib.sha256((output/'cases.jsonl').read_bytes()).hexdigest(),labels='Auto-derived explicit identifiers and single-value amount lines; no OCR corrections or human relevance claims')
 (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n');print(json.dumps(protocol,indent=2))
 return cases

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('export',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();prepare(args.export,args.output)
