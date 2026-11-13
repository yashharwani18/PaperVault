"""R18 audit of production excerpt/payload projection on synthetic text.

The app selects navigation sources, not free-form invoice answers. This audit
does not run a model or establish that retrieval selected the wrong document.
"""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from knowledge_library.search_response import respond


class DB:
    def execute(self,*args):return self
    def fetchone(self):return {'format':'pdf'}


def extract_contract(text):
    """Ordinary closed-format line projection, not a natural-language extractor."""
    keys=('Status','Effective total','Effective currency')
    rows=[]
    for line in text.splitlines(keepends=True):
        value=line.rstrip('\r\n')
        if any(value.startswith(key+': ') for key in keys):
            rows.append(value)
    return rows


def capsule(text,budget):
    # Match exact full lines and retain all occurrences, including conflicts.
    matches=list(re.finditer(r'(?m)^(?:Status|Effective total|Effective currency): [^\r\n]+',text))
    spans=[dict(text=m.group(),start=m.start(),end=m.end()) for m in matches]
    encoded=json.dumps(spans,separators=(',',':'),ensure_ascii=False)
    if len(encoded)>budget:return dict(status='insufficient_character_budget',required_characters=len(encoded))
    return dict(status='all_recognized_fixture_lines_retained',spans=spans,characters=len(encoded))


def run():
    prefix='SYNTHETIC INVOICE\nGrand Total: INR 13600.00\n'
    prefix+=('Packing information is repeated here for a deliberately long source passage.\n'*12)
    endings=[('active','Status: active\nEffective total: 13600.00\nEffective currency: INR\n'),
             ('cancelled','Status: cancelled\nEffective total: 13600.00\nEffective currency: INR\n'),
             ('revised','Status: active\nEffective total: 29074.00\nEffective currency: INR\n'),
             ('usd','Status: active\nEffective total: 13600.00\nEffective currency: USD\n'),
             ('conflict','Status: active\nEffective total: 13600.00\nEffective total: 29074.00\nEffective currency: INR\n')]
    cases=[]
    for name,ending in endings:
        passage=prefix+ending
        hit=dict(document_id='synthetic',chunk_id=1,source_identity=hashlib.sha256(passage.encode()).hexdigest(),
                 filename='synthetic.pdf',page_number=1,passage=passage)
        modes={}
        for mode in ('semantic','bill_fields'):
            supplied=dict(hit)
            if mode=='bill_fields':supplied['amount_match']=dict(evidence='Grand Total: INR 13600.00')
            captured=[]
            def generate(system,payload,schema,**kwargs):
                captured.append(dict(system=system,payload=json.loads(payload),schema=schema))
                return {'choice':1},0.
            response=respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=generate),
                'show current invoice total 13600',dict(mode=mode,results=[supplied]))
            modes[mode]=dict(model_input=captured[0],response=response)
        full=capsule(passage,1000);limited=capsule(passage,30)
        assert full['status']=='all_recognized_fixture_lines_retained'
        structured_prose='\n'.join(extract_contract(passage))
        assert structured_prose.splitlines()==[s['text'] for s in full['spans']]
        assert [s['text'] for s in full['spans']]==extract_contract(passage)
        assert all(passage[s['start']:s['end']]==s['text'] for s in full['spans'])
        assert limited['status']=='insufficient_character_budget'
        cases.append(dict(case=name,passage=passage,modes=modes,full_projection=full,limited_projection=limited,structured_prose_control=structured_prose))
    for mode in ('semantic','bill_fields'):
        inputs=[c['modes'][mode]['model_input'] for c in cases]
        assert all(i==inputs[0] for i in inputs)
        assert all('Effective' not in i['payload']['sources'][0]['text'] for i in inputs)
    assert len({json.dumps(c['full_projection']['spans']) for c in cases})==5
    report=dict(date='2026-10-21',cases=cases,model_calls=0,
        input_capture_calls=10,
        limits=['Production formatter and respond run with an explicitly stubbed source-choice model',
                'Current model chooses navigation sources, not invoice status/total synthesis',
                'No production search, OCR, real invoices or device performance evaluated',
                'Character allowance is not tokenizer allowance, inference speed or memory',
                'Closed fixture grammar is supplied, not discovered; projection is ordinary and not novel',
                'Full-source status claims, source authenticity and extraction completeness remain unverified'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r18-excerpt-context.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(cases),identical_model_inputs_per_mode=True,
        distinct_full_projections=5,all_low_budgets_unresolved=True,
        model_calls=0),indent=2))


if __name__=='__main__':run()
