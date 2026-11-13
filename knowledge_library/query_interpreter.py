"""Optional offline Qwen interpreter. Model output is never invoice evidence."""
from __future__ import annotations
import datetime as dt
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from functools import lru_cache

from .embedding import PROJECT
from .bill_amounts import money,CURRENCY,currency_code

LOCK=json.loads((PROJECT/'qwen-lock.json').read_text())
SCHEMA={'type':'object','properties':{
    'action':{'type':'string','enum':['search','clarify','other']},
    'field':{'type':'string','enum':['total','subtotal']},
    'amount':{'type':'string'},'party':{'type':'string'},
    'date':{'type':'string'},'direction':{'type':'string','enum':['','sale','purchase']}},
    'required':['action','field','amount','party','date','direction'],'additionalProperties':False}
SYSTEM='''Extract invoice search filters from English, Hindi or Romanized Hindi (Hinglish).
Return JSON only with action, field, amount, party, date, direction. Empty strings mean absent.
Ignore greetings and politeness. Never answer the request or invent invoice facts.
action=search for finding an invoice, including about/around/lagbhag amounts; clarify for ambiguous/multiple/range amounts, other for unrelated requests.
For approximate requests, copy the stated amount unchanged. The search engine controls nearby matching; do not round or adjust it.
field=total unless the user explicitly says subtotal/sub-total/before tax. "13600 ka invoice" means total 13600.
Copy amount digits exactly from the request; remove grouping commas only. Do not change its value.
party is only a business name explicitly in the request, never "bhai", "mujhe", "wo" or greetings.
date is YYYY-MM-DD only for an explicitly complete date with year; otherwise empty.
direction=sale for sold/becha, purchase for bought/kharida, otherwise empty.
Examples:
mujhe 13600 wala bill dikha -> {"action":"search","field":"total","amount":"13600","party":"","date":"","direction":""}
bhai 13600 ka subtotal kis invoice mein tha -> {"action":"search","field":"subtotal","amount":"13600","party":"","date":"","direction":""}
Bhagwanti Trading ko 25 September 2026 pe 13600 ka maal becha tha invoice dikhao -> {"action":"search","field":"total","amount":"13600","party":"Bhagwanti Trading","date":"2026-09-25","direction":"sale"}
'''


def expand_amount_shorthand(query):
    """Expand explicit magnitude suffixes only in a bill/invoice request."""
    if not re.search(r'\b(?:bill|invoice)s?\b|बिल|इनवॉइस',query,re.I):return query
    def expand(match):
        scale=Decimal('100000') if match['unit'].casefold() in ('lakh','lakhs','lac','lacs') else Decimal('1000')
        return format(Decimal(match['value'])*scale,'f')
    return re.sub(r'(?<![\w.,+\-])(?P<value>\d+(?:\.\d{1,2})?)\s*(?P<unit>k|thousand|lakh|lakhs|lac|lacs)\b',expand,query,flags=re.I)


def candidate(query):
    context=re.search(r'\b(?:invoices?|bills?|bil|inv|becha|bechi|kharida)\b|बिल|इनवॉइस|इनवाइस',query,re.I)
    literal=re.search(r'(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\w,]|\.\d)',query)
    wording=re.search(r'\b(?:ka|ki|ke|wala|wali|dikha|dikhao|mujhe|muje|chahiye|bana|ban|amount|worth|rupees|rs|total|around|about|approximately|lagbhag)\b|₹|दिखा|वाला|चाहिए|रुपये|\b(?:invoice|bill)\s+(?:of|for)\s+\d|\d\s+(?:invoice|bill)\b',query,re.I)
    return bool(context and literal and wording)


def simple_request(query):
    """A narrow whole-request fast path; extra party/date words cannot be dropped."""
    match=re.fullmatch(r'\s*(?:(?:mujhe|muje|bhai)\s+)?(?:(?:lagbhag|around|about|approximately)\s+)?(\d[\d,]*(?:\.\d{1,2})?)\s+(?:ka|wala|wali)\s+(?:invoice|bill)\s*(?:dikhao|dikha|chahiye)?[?!.]*\s*',query,re.I)
    if not match:return None
    value=format(money(match[1]),'.2f')
    return dict(amount=dict(field='total',value=value,currency=None),filters={},description=f'Searching total {value}',
                method='hinglish_rules',elapsed_s=0.,assumed_field=True)


def request_schema(query):
    """Constrain generated fields with deterministic evidence before decoding."""
    from .bills import parse_date
    schema=json.loads(json.dumps(SCHEMA))
    subtotal=bool(re.search(r'\bsub[ -]?total\b|before tax|tax se pehle',query,re.I))
    schema['properties']['field']={'type':'string','enum':['subtotal' if subtotal else 'total']}
    schema['properties']['date']={'type':'string','enum':[parse_date(query) or '']}
    directions=[key for key,pattern in {
        'sale':r'\b(sold|sell|selling|sale|sales|becha|bechi|beche|bikri)\b|बेचा|बेची',
        'purchase':r'\b(bought|buy|purchase|purchased|kharida|kharidi|kharide)\b|खरीदा|खरीदी'}.items() if re.search(pattern,query,re.I)]
    schema['properties']['direction']={'type':'string','enum':directions or ['']}
    return schema


def validate(query,data):
    """Reject fabricated literals, unsupported comparisons and dropped clear filters."""
    from .bills import normalized,parse_date
    if set(data)!=set(SCHEMA['required']) or any(not isinstance(v,str) for v in data.values()):raise ValueError('Could not interpret the request safely. Try invoice total 13600.')
    # Small models sometimes label a salutation as a customer. These exact
    # conversational words cannot establish a business-party constraint.
    conversational=set('hello hi hey arre arey are bhaiya ji zara chalo aap mere mera bhai yaar mujhe muje mereko wo woh vo wala wali wale please plz jis jiska jisme jismen jismein kis iska uska ka ki ke ko se pe par me mein mai hai hain tha thi the ho kaisa jaha jahan na de do dikha dikhao dikhaao dikhana chahiye chahie chaiye mil sakta kya nikal invoice invoices bill bills total subtotal sub amount rupee rupees rupaye rupay rs inr lagbhag around about approximately'.split())
    entity_words=[w for w in normalized(data['party']).split() if w not in conversational and not w.isnumeric()]
    if data['party'] and not entity_words:data={**data,'party':''}
    if data['party'] and not any(c.isalpha() for c in data['party']):
        # A copied amount is not a party name; all-numeric party lookup needs the explicit filter.
        if re.fullmatch(r'[\d,.\s]+',data['party']) and money(data['party'].strip())==money(data['amount']):data={**data,'party':''}
        else:raise ValueError('Please enter the business name using the party filter.')
    if data['action']!='search':raise ValueError('Please specify one invoice total or subtotal, for example invoice total 13600.')
    if data['field'] not in ('total','subtotal') or data['direction'] not in ('','sale','purchase'):raise ValueError('Invalid search interpretation. Please use the bill filters.')
    if re.search(r'\b(over|under|above|below|between|greater|less|more|at\s+least|at\s+most|zyada|jyada|zyaada|kam)\b|[<>~]',query,re.I):raise ValueError('Range comparisons are not supported yet. Use one amount, optionally with about, around or lagbhag.')
    literals=[]
    for match in re.finditer(r'(?<![\w.,+\-])\d[\d,]*(?:\.\d+)?(?![\w,]|\.\d)',query):
        try:literals.append(money(match.group()))
        except ValueError:raise ValueError('Please write a complete amount such as 13,600.00.')
    value=money(data['amount'])
    if value not in literals:raise ValueError('The interpreted amount was not in your request. Please specify it explicitly.')
    if re.search(r'\bsub[ -]?total\b|before tax|tax se pehle',query,re.I) and data['field']!='subtotal':raise ValueError('Please specify the subtotal explicitly, for example subtotal 13600.')
    if data['field']=='subtotal' and not re.search(r'\bsub[ -]?total\b|before tax|tax se pehle',query,re.I):raise ValueError('Please specify whether you mean total or subtotal.')
    if data['party'] and (' '+normalized(data['party'])+' ') not in (' '+normalized(query)+' '):raise ValueError('The interpreted party was not in your request. Please use the party filter.')
    date=parse_date(query)
    if data['date']:
        try:dt.date.fromisoformat(data['date'])
        except ValueError:raise ValueError('Please include a valid complete invoice date.')
        if date!=data['date']:raise ValueError('Please write the date explicitly, for example 25 September 2026.')
    if date and data['date']!=date:raise ValueError('The date could not be preserved. Please use the date filter.')
    directions={'sale':r'\b(sold|sell|selling|sale|sales|becha|bechi|beche|bikri)\b|बेचा|बेची',
                'purchase':r'\b(bought|buy|purchase|purchased|kharida|kharidi|kharide)\b|खरीदा|खरीदी'}
    mentioned=[key for key,pattern in directions.items() if re.search(pattern,query,re.I)]
    if len(mentioned)>1 or (mentioned and data['direction']!=mentioned[0]) or (data['direction'] and data['direction'] not in mentioned):raise ValueError('Please choose sale or purchase using the bill filter.')
    # Multiple numeric amounts must not silently become one; complete date tokens are excluded.
    remaining=query
    if date:
        remaining=re.sub(r'\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b','',remaining)
        remaining=re.sub(r'\b(?:19|20)\d{2}\b','',remaining)
        remaining=re.sub(r'\b\d{1,2}\s+(?:Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\b','',remaining,flags=re.I)
    distinct=set()
    for raw in re.findall(r'(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\w,]|\.\d)',remaining):
        distinct.add(money(raw))
    if distinct!={value}:raise ValueError('Please search one amount at a time and use the filters for dates or invoice numbers.')
    currencies={currency_code(c) for c in re.findall(CURRENCY,query,re.I)}
    if len(currencies)>1:raise ValueError('Please search one currency at a time.')
    return dict(field=data['field'],value=format(value,'.2f'),currency=next(iter(currencies),None)),{key:val for key,val in (
        ('party',data['party']),('date_from',data['date']),('date_to',data['date']),('direction',data['direction'])) if val}


class QueryInterpreter:
    def __init__(self):
        self.model_path=PROJECT/'models/qwen3-0.6b'/LOCK['filename']
        self.runtime_dir=PROJECT/'models/qwen-runtime'/LOCK['runtime_tag']
        self._verified=False
        self._lock=threading.Lock()
        self.stats={'calls':0,'elapsed_s':0.}

    @property
    def executable(self):return next(self.runtime_dir.rglob('llama-completion.exe'),None) or next(self.runtime_dir.rglob('llama-cli.exe'),None)

    def status(self):return dict(available=self.model_path.is_file() and self.executable is not None,model='Qwen3 0.6B',quantization='Q4_K_M',download_bytes=LOCK['size_bytes'],thinking=False,resident=False)

    @lru_cache(maxsize=32)
    def token_count(self,text):
        tokenizer=next(self.runtime_dir.rglob('llama-tokenize.exe'),None)
        if tokenizer is None:raise ValueError('Local tokenizer is unavailable; cannot admit a bounded Qwen request.')
        try:
            run=subprocess.run([str(tokenizer),'-m',str(self.model_path),'--stdin','--ids','--offline'],
                input=text,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            tokens=json.loads(run.stdout.strip())
            if run.returncode or not isinstance(tokens,list) or any(type(t) is not int for t in tokens):raise ValueError()
            return len(tokens)
        except (OSError,ValueError,subprocess.TimeoutExpired):raise ValueError('Could not count Qwen tokens locally.')

    def generate(self,system,user,schema,*,max_tokens=160):
        """One bounded offline request; used by interpretation and source selection."""
        if not self.status()['available']:raise ValueError('The local Qwen model is not installed. Run scripts/setup_qwen.py online.')
        with self._lock:
            if not self._verified:
                with self.model_path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if digest!=LOCK['sha256']:raise ValueError('Qwen model checksum mismatch. Run scripts/setup_qwen.py again.')
                self._verified=True
            started=time.perf_counter()
            temporary_root=PROJECT/'.cache/query-temp'
            temporary_root.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='library-query-',dir=temporary_root) as temporary:
                path=Path(temporary);prompt=path/'prompt.txt';schema_path=path/'schema.json'
                complete_prompt=f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
                if len(complete_prompt)>20000:raise ValueError('Qwen context budget exceeded; showing source matches.')
                count=self.token_count(complete_prompt)
                # The JSON schema is an out-of-band grammar, not prompt text.
                # Reserve the full output allowance plus a small runtime margin.
                if not 1<=max_tokens<=256 or count+max_tokens+32>1024:
                    raise ValueError('Qwen context budget exceeded; showing source matches.')
                self.stats['last_prompt_tokens']=count
                prompt.write_text(complete_prompt,encoding='utf-8')
                schema_path.write_text(json.dumps(schema),encoding='utf-8')
                command=[str(self.executable),'-m',str(self.model_path),'-f',str(prompt),'-c','1024','-n',str(max_tokens),'-t','4','-b','256','-ub','128','--no-repack',
                    '--temp','0','--seed','42','--no-display-prompt','--simple-io','--no-conversation',
                    '--json-schema-file',str(schema_path),'-ngl','0','--offline']
                try:
                    completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                except (OSError,subprocess.TimeoutExpired):raise ValueError('Local Qwen did not finish. Please retry with a shorter request.')
                if completed.returncode:raise ValueError('Local Qwen could not run. Please retry.')
            raw=completed.stdout;start=raw.find('{')
            try:data,end=json.JSONDecoder().raw_decode(raw[start:]) if start>=0 else ({},0)
            except json.JSONDecodeError:raise ValueError('Local Qwen returned an incomplete response.')
            elapsed=time.perf_counter()-started
            self.stats['calls']+=1;self.stats['elapsed_s']+=elapsed
            return data,elapsed

    def interpret_general(self,query):
        """Rewrite a search locally without treating generated text as evidence."""
        schema={'type':'object','properties':{'phrase':{'type':'string','maxLength':500}},'required':['phrase'],'additionalProperties':False}
        system=('Rewrite the document search as a concise search phrase for any subject. '
                'Preserve names, identifiers, dates, numbers and constraints; do not answer or invent facts. '
                'Return JSON with only the phrase.')
        data,_=self.generate(system,query,schema,max_tokens=96)
        phrase=data.get('phrase')
        if not isinstance(phrase,str) or not phrase.strip() or len(phrase)>500:
            raise ValueError('Local Qwen returned an invalid search phrase.')
        return phrase.strip()

    def interpret(self,query):
        if len(query)>500:raise ValueError('Please keep invoice requests under 500 characters or use the bill filters.')
        data,elapsed=self.generate(SYSTEM,query,request_schema(query))
        amount,filters=validate(query,data)
        description=f"Searching {amount['field']} {amount['value']}"+''.join(f' · {k}: {v}' for k,v in filters.items() if k!='date_to')
        return dict(amount=amount,filters=filters,description=description,method='qwen3_0.6b_q4_k_m',elapsed_s=elapsed,
            assumed_field=not bool(re.search(r'\b(?:sub[ -]?total|total)\b|before tax|tax se pehle',query,re.I)))
