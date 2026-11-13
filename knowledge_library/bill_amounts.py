"""Field-specific money lookup with a labelled, bounded nearby fallback."""
from decimal import Decimal
import json
import re

LABEL = r'(?:sub[ \t-]*total|grand[ \t]+total|invoice[ \t]+total|total[ \t]+amount|net[ \t]+payable|total)'
NUMBER = r'(?<![\w.,+\-])\d[\d,]*(?:\.\d+)?(?![\w,]|\.\d)'
CURRENCY = r'(?:(?<!\w)(?:INR|USD|EUR|GBP|Rs\.?)(?![A-Za-z])|₹|\$|€|£)'


def money(raw):
    # Accept plain, Western and Indian grouping; never silently reinterpret commas.
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d{1,2})?',raw):
        raise ValueError('Use an exact amount such as 13600, 13,600.00 or 1,36,000.00.')
    return Decimal(raw.replace(',',''))


def field(label):
    return 'subtotal' if re.match(r'sub',label,re.I) else 'total'


def query_amount(query):
    """Only explicit field/amount pairs route away from semantic search."""
    gap = rf'\s*(?:(?:of|was|is|equals?|equal\s+to|exactly|exact|about|around|approximately|lagbhag|amount|had|at)\b\s*|[:=]\s*)*(?:{CURRENCY}\s*)?'
    patterns = [rf'\b(?P<label>{LABEL})\b{gap}(?P<amount>{NUMBER})',
                rf'(?P<amount>{NUMBER})\s*(?:{CURRENCY}\s*)?(?P<label>{LABEL})\b']
    matches = [m for pattern in patterns for m in re.finditer(pattern,query,re.I)]
    if not matches and re.search(r'\b(?:bill|invoice)s?\b',query,re.I):
        # Narrow English requests without a field mean invoice total. Do not
        # confuse invoice IDs, dates, multiple numbers or arbitrary lecture text.
        simple = re.search(rf'\b(?:bill|invoice)\s+(?:of|for|worth|where\s+(?:its|it\s+is))\s+(?:(?:about|around|approximately)\s+)?(?:{CURRENCY}\s*)?(?P<amount>{NUMBER})',query,re.I)
        if simple and len(list(re.finditer(NUMBER,query)))==1:
            currencies={currency_code(c) for c in re.findall(CURRENCY,query,re.I)}
            if len(currencies)>1:raise ValueError('Please search one currency at a time.')
            if re.search(r'\b(?:over|under|above|below|between|greater|less|more|at\s+least|at\s+most|zyada|jyada|zyaada|kam)\b|[<>~]',query,re.I):
                raise ValueError('Range comparisons are not supported yet.')
            return dict(field='total',value=format(money(simple['amount']),'.2f'),currency=next(iter(currencies),None))
    if not matches:
        if re.search(rf'\b{LABEL}\b\s*(?:[:=<>~]|over|under|above|below|between|about|approximately|of|was|is|equals?|at|least|most|greater|less|more|than|to|{CURRENCY}|\s)*[+\-]?\d',query,re.I):
            raise ValueError('Use an exact field and amount, for example subtotal of 13,600. Range comparisons are not supported yet.')
        return None
    if re.search(r'\b(?:over|under|above|below|between|greater|less|more|at\s+least|at\s+most|zyada|jyada|zyaada|kam)\b|[<>~]',query,re.I):
        raise ValueError('Use an exact subtotal or total amount. Range comparisons are not supported yet.')
    values = {(field(m['label']),money(m['amount'])) for m in matches}
    if len(values)!=1:raise ValueError('Search one exact subtotal or total amount at a time.')
    name,value=values.pop()
    currencies={currency_code(c) for c in re.findall(CURRENCY,query,re.I)}
    if len(currencies)>1:raise ValueError('Please search one currency at a time.')
    currency=next(iter(currencies),None)
    return dict(field=name,value=format(value,'.2f'),currency=currency)


def amount_tolerance(query,value):
    """Nearby fallback is never a replacement for an explicitly exact request."""
    if re.search(r'\b(?:exact|exactly|equals?|equal\s+to|precisely)\b|=',query,re.I):
        return Decimal('0')
    return min(abs(Decimal(value))*Decimal('0.01'),Decimal('500'))


def currency_code(raw):
    raw=raw.upper().rstrip('.')
    return {'₹':'INR','RS':'INR','$':'USD','€':'EUR','£':'GBP'}.get(raw,raw)


def source_amounts(text):
    # Labels must begin a source line: a line item or tax amount is not a subtotal.
    pattern=rf'(?im)^[ \t]*(?P<label>{LABEL})\b[ \t]*(?:\((?P<unit>{CURRENCY})\))?[ \t]*[:=]?[ \t]*\n?[ \t]*(?P<currency>{CURRENCY})?\s*(?P<amount>{NUMBER})'
    for match in re.finditer(pattern,text):
        try:value=money(match['amount'])
        except ValueError:continue
        yield dict(field=field(match['label']),value=format(value,'.2f'),
                   currency=currency_code(match['currency'] or match['unit']) if match['currency'] or match['unit'] else None,
                   evidence=text[match.start('label'):match.end()],start=match.start('label'),end=match.end())


def search_amount(lib,query,intent,amount,bills,folder_id,document_id,*,document_ids=None,matching=None):
    by_id={b['document_id']:b for b in bills}
    pages=lib.db.execute('''SELECT p.*,d.folder_id FROM pages p JOIN documents d ON d.id=p.document_id
        WHERE (? IS NULL OR d.folder_id=?) AND (? IS NULL OR d.id=?)
        ORDER BY d.id,p.page_number''',(folder_id,folder_id,document_id,document_id)).fetchall()
    invoice_docs={p['document_id'] for p in pages if re.search(r'\b(?:invoice|bill of supply|sales bill|purchase bill|cash memo)\b',p['text'],re.I)} | set(by_id)
    found=[];evidence_attempted=set()
    requested=Decimal(amount['value']);tolerance=amount_tolerance(query,requested)
    matching=matching or {'mode':'auto'}
    mode=matching.get('mode','auto')
    if mode not in ('auto','exact','absolute','percent'):raise ValueError('Unknown amount matching mode.')
    if mode=='exact':tolerance=Decimal('0')
    elif mode in ('absolute','percent'):
        try:allowance=Decimal(str(matching.get('value','')))
        except Exception:raise ValueError('Enter a valid amount tolerance.')
        if not allowance.is_finite() or allowance<0 or allowance>(Decimal('50') if mode=='percent' else Decimal('100000')):raise ValueError('Tolerance is outside the supported range.')
        tolerance=(requested*allowance/100 if mode=='percent' else allowance) if amount_tolerance(query,requested) else Decimal('0')
    for page in pages:
        key=page['document_id'];bill=by_id.get(key)
        if document_ids is not None and key not in document_ids:continue
        if key not in invoice_docs:continue
        # Existing structured filters remain mandatory; missing fields never pass.
        if any(intent[k] and (not bill or intent[k]!=bill[column]) for k,column in (
            ('direction','direction'),)):continue
        if intent['party'] and (not bill or _normalized(intent['party'])!=bill['party_normalized']):continue
        if intent['invoice_number'] and (not bill or _normalized(intent['invoice_number'])!=_normalized(bill['invoice_number'])):continue
        if intent['date_from'] and (not bill or not bill['bill_date'] or bill['bill_date']<intent['date_from']):continue
        if intent['date_to'] and (not bill or not bill['bill_date'] or bill['bill_date']>intent['date_to']):continue
        if intent['item'] and not any(all(w in _normalized(p['text']).split() for w in _normalized(intent['item']).split()) for p in pages if p['document_id']==key):continue
        from .evidence import physical_amounts,scoped_review
        layout=json.loads(page['evidence']) if 'evidence' in page.keys() else {}
        if not layout and callable(getattr(lib,'upgrade_evidence',None)):
            relevant=False
            for number in re.finditer(NUMBER,page['text']):
                try:
                    if abs(money(number[0])-requested)<=tolerance:relevant=True;break
                except ValueError:continue
            if not relevant:continue
            # Transparent one-time migration for existing indexed documents.
            # Never regenerate embeddings or overwrite differing source text here.
            if key not in evidence_attempted:
                evidence_attempted.add(key)
                try:lib.upgrade_evidence(key,include_ocr=True)
                except (OSError,ValueError):pass  # Indexed passages remain available without the source.
            layout=lib.page(key,page['page_number'])['evidence']
        source_text=page['text'].split('\n[Table rows extracted from this page]')[0]
        observations=physical_amounts(source_text,layout)
        for evidence in observations if observations is not None else source_amounts(source_text):
            delta=Decimal(evidence['value'])-requested
            if evidence['field']!=amount['field'] or abs(delta)>tolerance:continue
            if amount['currency'] and evidence['currency']!=amount['currency']:continue
            row=lib.db.execute('''SELECT c.*,d.filename,d.managed_path,d.status document_status,f.id folder_id,f.name folder_name,
                p.page_label,p.method extraction_method,p.warnings page_warnings FROM chunks c
                JOIN documents d ON d.id=c.document_id JOIN folders f ON f.id=d.folder_id
                JOIN pages p ON p.document_id=c.document_id AND p.page_number=c.page_number
                WHERE c.document_id=? AND c.page_number=? AND c.char_start<=? AND c.char_end>=?
                ORDER BY c.char_start DESC LIMIT 1''',(key,page['page_number'],evidence['start'],evidence['end'])).fetchone()
            if row is None:continue  # Never fabricate a source passage or chunk identity.
            hit=lib._result(row,1,'bill_fields')
            if bill:hit['bill']=bill
            hit['amount_match']={**evidence,'page_number':page['page_number'],
                'requested_value':amount['value'],'difference':format(delta,'.2f'),'approximate':bool(delta)}
            hit['amount_match']['association']=evidence.get('association','unresolved' if layout.get('rotation') or layout.get('non_horizontal_text') else 'label_sequence')
            hit['amount_match']['verified']=bool(hit.get('source_available',True) and scoped_review(bill,hit['amount_match'],hit.get('source_sha256')))
            hit['amount_match']['context_available']=bool(layout.get('words'))
            if evidence.get('bbox') and layout.get('bounds') and not layout.get('rotation'):
                x0,y0,x1,y1=evidence['bbox'];left,top,right,bottom=layout['bounds']
                if right>left and bottom>top:
                    hit['amount_match']['highlight_box']=[(x0-left)/(right-left),(y0-top)/(bottom-top),
                        (x1-x0)/(right-left),(y1-y0)/(bottom-top)]
            if not layout.get('words'):hit.setdefault('warnings',[]).append('Physical field context unavailable; refresh extraction to review the layout.')
            hit['match_tier']='nearby' if delta else 'exact'
            reason=(f"Nearby {amount['field']}: {evidence['value']} (requested {amount['value']}; difference {delta:+.2f})"
                    if delta else f"Exact {amount['field']}: {amount['value']} (source text)")
            hit['match_reasons']=[reason]+[f'{k}: {intent[k]}' for k in ('party','date_from','date_to','direction','invoice_number','item') if intent[k]]
            if page['method']=='ocr':hit['match_reasons'].append('OCR text; verify the original')
            if bill and not bill.get('reviewed'):hit['match_reasons'].append('Saved invoice fields are unreviewed')
            found.append(hit)
    # Unreviewed literal equality must not conceal a different document's nearby
    # amount. Only a review scoped to this revision/page/field/value can suppress it.
    exact=[hit for hit in found if not hit['amount_match']['approximate']]
    verified=any(hit['amount_match']['verified'] for hit in exact)
    found=sorted((exact if verified else found),key=lambda h:(abs(Decimal(h['amount_match']['difference'])),h['document_id'],h['page_number']))
    unique={}
    for hit in found:unique.setdefault(hit['document_id'],hit)
    found=list(unique.values())
    nearby=bool(found and not exact)
    mixed=bool(exact and any(h['amount_match']['approximate'] for h in found))
    visible=found[:100]
    if mixed and len(found)>100:
        near=[h for h in found if h['amount_match']['approximate']]
        equality=[h for h in found if not h['amount_match']['approximate']]
        # Reserve space for alternatives even when 100 literal equalities exist.
        quota=min(5,len(near));visible=equality[:100-quota]+near[:max(quota,100-len(equality))]
    for rank,hit in enumerate(visible,1):hit['rank']=rank
    return dict(query=query,folder_id=folder_id,document_id=document_id,mode='bill_fields',scoped_chunks=0,
        results=visible,elapsed_s=0.,query_embedding_s=0.,reliability='mixed_source_amounts' if mixed else 'nearby_source_amount' if nearby else 'exact_source_amount',
        note=('Exact text matches and nearby alternatives are shown because the exact field reading is unreviewed. '
              if mixed else f'No exact amount found. Showing nearby source amounts within {tolerance:.2f} currency units. Actual totals are unchanged. '
              if nearby else 'Exact field and amount in indexed source text. ')+ 'Check the original, especially for OCR.',
        amount_tolerance=format(tolerance,'.2f'),
        bill_intent={**intent,'amount':amount},bill_matches=len(found),closest_available=False,below_cutoff=False,
        empty_reason=None if found else 'no_matching_amount')


def _normalized(text):
    from .bills import normalized
    return normalized(text)
