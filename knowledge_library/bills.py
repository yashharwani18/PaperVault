"""Invoice evidence and date/party lookup. No generated transaction facts.

Regex extraction is a reviewable suggestion, not an accounting determination.
One bill record per PDF; manual corrections retain the physical source page.
"""
import calendar
import datetime as dt
from decimal import Decimal,InvalidOperation
import json
import re
import unicodedata

MONTHS={name.casefold():i for i,name in enumerate(calendar.month_name) if name}
MONTHS.update({name.casefold():i for i,name in enumerate(calendar.month_abbr) if name});MONTHS['sept']=9
MONTH_PATTERN='|'.join(sorted(MONTHS,key=len,reverse=True))


def normalized(text):
    text=unicodedata.normalize('NFKC',text).casefold()
    return ' '.join(re.findall(r'\w+',text,re.UNICODE))


def parse_date(text):
    candidates=[(r'\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b','ymd'),
                (r'\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2}|19\d{2})\b','dmy'),
                (rf'\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}}|19\d{{2}})\b','mdy'),
                (rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?[,]?\s+(20\d{{2}}|19\d{{2}})\b','dmy_words')]
    for pattern,order in candidates:
        match=re.search(pattern,text,re.I)
        if not match:continue
        a,b,c=match.groups()
        try:
            if order=='ymd':year,month,day=int(a),int(b),int(c)
            elif order=='dmy':year,month,day=int(c),int(b),int(a)
            elif order=='mdy':year,month,day=int(c),MONTHS[a.casefold()],int(b)
            else:year,month,day=int(c),MONTHS[b.casefold()],int(a)
            return dt.date(year,month,day).isoformat()
        except (ValueError,KeyError):continue
    return None


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS bill_records(
        document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        party TEXT NOT NULL,party_normalized TEXT NOT NULL,bill_date TEXT,invoice_number TEXT NOT NULL,
        direction TEXT NOT NULL,amount TEXT,currency TEXT NOT NULL,source_page INTEGER NOT NULL,
        source_sha256 TEXT NOT NULL,reviewed INTEGER NOT NULL,origin TEXT NOT NULL,evidence TEXT NOT NULL,
        updated_at TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS bills_party_date ON bill_records(party_normalized,bill_date)')
    db.execute('CREATE TABLE IF NOT EXISTS party_aliases(alias TEXT PRIMARY KEY,display_alias TEXT NOT NULL,party TEXT NOT NULL)')
    db.commit()


def aliases(lib):
    return [dict(r) for r in lib.db.execute('SELECT * FROM party_aliases ORDER BY party,display_alias')]


def save_alias(lib,alias,party):
    alias=' '.join(alias.split());party=' '.join(party.split())
    if not alias or len(alias)>160 or not party or len(party)>160:raise ValueError('Enter an alias and canonical party, at most 160 characters each')
    existing={b['party_normalized'] for b in all_bills(lib)}
    if normalized(party) not in existing:raise ValueError('Choose a party already recorded on a bill')
    if normalized(alias) in existing and normalized(alias)!=normalized(party):raise ValueError('This alias is already another recorded party name')
    previous=lib.db.execute('SELECT party FROM party_aliases WHERE alias=?',(normalized(alias),)).fetchone()
    if previous and normalized(previous[0])!=normalized(party):raise ValueError('Remove the existing alias before assigning it to a different party')
    with lib.db:lib.db.execute('INSERT OR REPLACE INTO party_aliases VALUES(?,?,?)',(normalized(alias),alias,party))
    return aliases(lib)


def date_range(text,today=None):
    """Inclusive dates. Relative dates use the PC's local calendar, never a guessed year."""
    today=today or dt.date.today()
    match=re.search(r'\b(?:from|between)\s+(.+?)\s+(?:to|and|through)\s+(.+?)(?:[?]|$)',text,re.I)
    if match:
        start,end=map(parse_date,match.groups())
        if not start or not end or start>end:raise ValueError('Use an ordered date range with two complete dates, for example from 01/09/2026 to 30/09/2026')
        return start,end
    exact=parse_date(text)
    if exact:return exact,exact
    lower=text.casefold()
    if re.search(r'\b(today|yesterday)\b',lower):
        day=today-dt.timedelta(days=int('yesterday' in lower));return day.isoformat(),day.isoformat()
    if re.search(r'\b(last|this) month\b',lower):
        anchor=today.replace(day=1)
        if 'last month' in lower:anchor=(anchor-dt.timedelta(days=1)).replace(day=1)
        return anchor.isoformat(),anchor.replace(day=calendar.monthrange(anchor.year,anchor.month)[1]).isoformat()
    match=re.search(rf'\b(?:(last|this)\s+)?({MONTH_PATTERN})(?:\s+(20\d{{2}}|19\d{{2}}))?\b',text,re.I)
    if match:
        relative,month,year=match.groups();month=MONTHS[month.casefold()]
        # A day without a year must never silently turn into a whole-month query.
        tail=text[match.end():]
        if re.match(r'\s+\d',tail):raise ValueError('Include a four-digit year for a specific invoice date')
        if not year and not relative:raise ValueError('Include the year, or say last/this before the month')
        year=int(year) if year else today.year-int(relative.casefold()=='last' and month>=today.month)
        return dt.date(year,month,1).isoformat(),dt.date(year,month,calendar.monthrange(year,month)[1]).isoformat()
    return None,None


def suggestions(lib,document_id):
    lib.document(document_id)
    result=dict(party='',bill_date=None,invoice_number='',direction='unspecified',amount=None,currency='',source_page=1,evidence={},detected=False,warnings=[])
    pages=list(lib.db.execute('SELECT page_number,text,method FROM pages WHERE document_id=? ORDER BY page_number LIMIT 50',(document_id,)))
    identifiers=set()
    for page in pages:
        identifiers.update(normalized(m) for m in re.findall(r'(?:invoice|bill)[ \t]*(?:no\.?|number|#)[ \t]*[:#\-]?[ \t]*([A-Z0-9][A-Z0-9/_.\-]{0,49})',page['text'],re.I))
    if len(identifiers)>1:
        result.update(detected=True,warnings=['Multiple invoice numbers detected. Split this PDF into one invoice per document before relying on extracted fields.'])
        return result
    if any(re.search(r'\bcredit\s+note\b',p['text'],re.I) for p in pages):
        result.update(detected=True,warnings=['Credit notes need manual classification; automatic accounting interpretation is unsupported.'])
        return result
    for page in pages:
        text=page['text']
        if not re.search(r'\b(invoice|bill of supply|cash memo|sales bill|purchase bill)\b',text,re.I):continue
        candidate=dict(result);evidence={}
        match=re.search(r'(?:^|\n)[ \t]*(?:bill(?:ed)?[ \t]+to|sold[ \t]+to|customer(?:[ \t]+name)?|buyer|party[ \t]+name|supplier|vendor)[ \t]*[:\-]?[ \t]*\n?[ \t]*([^\n]{2,140})',text,re.I)
        if match:
            candidate['party']=match.group(1).strip();evidence['party']=match.group(0).strip()
        match=re.search(r'(?:^|\n)[ \t]*(?:(?:invoice|bill)[ \t]+date|date)[ \t]*[:\-]?[ \t]*\n?[ \t]*([^\n]{5,45})',text,re.I)
        if match:
            candidate['bill_date']=parse_date(match.group(1));evidence['bill_date']=match.group(0).strip()
        match=re.search(r'(?:invoice|bill)[ \t]*(?:no\.?|number|#)[ \t]*[:#\-]?[ \t]*([A-Z0-9][A-Z0-9/_.\-]{0,49})',text,re.I)
        if match:candidate['invoice_number']=match.group(1);evidence['invoice_number']=match.group(0)
        match=re.search(r'(?:grand[ \t]+total|invoice[ \t]+total|total[ \t]+amount|net[ \t]+payable)[ \t]*[:\-]?[ \t]*(?:(INR|USD|EUR|GBP|₹|Rs\.?)\s*)?([0-9][0-9,.]*)',text,re.I)
        if match:
            raw_amount=match.group(2).rstrip('.')
            if re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?',raw_amount):candidate['amount']=str(Decimal(raw_amount.replace(',','')))
            else:candidate['warnings']=['Unrecognized amount separator convention. Enter the total manually; no amount was inferred.']
            cur=match.group(1) or ''
            candidate['currency']='INR' if cur.casefold() in ('₹','rs','rs.') else cur.upper()
            evidence['amount']=match.group(0)
        if re.search(r'\b(?:sales invoice|sales bill|transaction type\s*:\s*sale)\b',text,re.I):candidate['direction']='sale'
        elif re.search(r'\b(?:purchase invoice|purchase bill|transaction type\s*:\s*purchase)\b',text,re.I):candidate['direction']='purchase'
        candidate.update(source_page=page['page_number'],evidence=evidence,detected=bool(candidate['party'] or candidate['bill_date']),extraction_method=page['method'])
        if candidate['detected']:return candidate
    return result


def save(lib,document_id,fields,*,reviewed=False,origin='manual',transaction=True):
    doc=lib.document(document_id)
    party=' '.join(str(fields.get('party','')).split())
    if len(party)>160:raise ValueError('Party name must be at most 160 characters')
    date=fields.get('bill_date') or None
    if date:
        try:date=dt.date.fromisoformat(date).isoformat()
        except ValueError:raise ValueError('Bill date must be a real date in YYYY-MM-DD format')
    if reviewed and (not party or not date):raise ValueError('Confirm a party and bill date before marking the bill reviewed')
    direction=fields.get('direction','unspecified')
    if direction not in ('sale','purchase','unspecified'):raise ValueError('Choose sale, purchase, or unspecified')
    number=str(fields.get('invoice_number','')).strip()
    currency=str(fields.get('currency','')).strip().upper()
    if len(number)>80 or len(currency)>12:raise ValueError('Invoice number or currency is too long')
    amount=fields.get('amount') or None
    if amount:
        try:
            value=Decimal(str(amount).replace(',',''))
            if not value.is_finite() or value<0 or value>Decimal('999999999999999'):raise InvalidOperation()
            amount=str(value)
        except InvalidOperation:raise ValueError('Total must be a non-negative decimal amount')
    page=int(fields.get('source_page',1))
    if not 1<=page<=doc['page_count']:raise ValueError('Bill source page is outside the PDF')
    evidence=dict(fields.get('evidence',{}) or {})
    # A document-wide review never implicitly verifies a money observation.
    # Retain a prior explicit review only while all its source scope still matches.
    old_review=evidence.get('amount_review',{})
    if old_review and (not amount or old_review.get('source_sha256')!=doc['sha256'] or old_review.get('page_number')!=page or
        old_review.get('value')!=format(Decimal(amount),'.2f')):
        evidence.pop('amount_review',None)
    if fields.get('amount_reviewed'):
        if not reviewed or amount is None:raise ValueError('Check the invoice details and an amount before confirming its field.')
        from .evidence import physical_amounts
        from .bill_amounts import source_amounts
        source=lib.page(document_id,page)
        observations=physical_amounts(source['text'],source['evidence'])
        observations=list(source_amounts(source['text'])) if observations is None else observations
        candidates=[a for a in observations if a['field']=='total' and Decimal(a['value'])==Decimal(amount)]
        if len(candidates)!=1 or candidates[0].get('association')=='unresolved':
            raise ValueError('This amount has no unique indexed total field. Refresh extraction or leave the amount confirmation unchecked.')
        candidate=candidates[0]
        evidence['amount_review']=dict(source_sha256=doc['sha256'],page_number=page,field='total',
            value=candidate['value'],currency=candidate.get('currency'),evidence=candidate['evidence'],bbox=candidate.get('bbox'))
    from contextlib import nullcontext
    with (lib.db if transaction else nullcontext()):
        lib.db.execute('''INSERT INTO bill_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET
            party=excluded.party,party_normalized=excluded.party_normalized,bill_date=excluded.bill_date,
            invoice_number=excluded.invoice_number,direction=excluded.direction,amount=excluded.amount,
            currency=excluded.currency,source_page=excluded.source_page,source_sha256=excluded.source_sha256,
            reviewed=excluded.reviewed,origin=excluded.origin,evidence=excluded.evidence,updated_at=excluded.updated_at''',
            (document_id,party,normalized(party),date,number,direction,amount,currency,page,doc['sha256'],int(reviewed),origin,json.dumps(evidence),dt.datetime.now(dt.timezone.utc).isoformat()))
    return get(lib,document_id)


def get(lib,document_id):
    doc=lib.document(document_id)
    row=lib.db.execute('SELECT * FROM bill_records WHERE document_id=?',(document_id,)).fetchone()
    if row and row['source_sha256']==doc['sha256']:
        result=dict(row);result['evidence']=json.loads(result['evidence']);return result
    return None


def all_bills(lib):
    return [dict(row) for row in lib.db.execute('''SELECT b.*,d.filename,d.title,d.folder_id,f.name folder_name
        FROM bill_records b JOIN documents d ON d.id=b.document_id JOIN folders f ON f.id=d.folder_id
        WHERE b.source_sha256=d.sha256 ORDER BY b.bill_date DESC,d.id''')]


def auto_extract(lib,document_id,force=False):
    if get(lib,document_id):return
    guessed=suggestions(lib,document_id)
    if guessed['detected'] or force:save(lib,document_id,guessed,origin='extracted',reviewed=False)


def parse_query(query,bills,party_aliases=(),today=None):
    norm=normalized(query);party=None;known=False;invoice=None
    for bill in sorted(bills,key=lambda b:len(b['party_normalized']),reverse=True):
        if bill['party_normalized'] and re.search(r'(?<!\w)'+re.escape(bill['party_normalized'])+r'(?!\w)',norm):
            party=bill['party'];known=True;break
    if party is None:
        match=re.search(r'\b(?:to|from|for)\s+(.+?)(?:\s+(?:on|dated|during)\b|[?]|$)',query,re.I)
        if match and len(match.group(1).strip())<=160:
            candidate=match.group(1).strip()
            if not re.match(rf'(?:\d|(?:(?:about|around|approximately)\s+)(?:INR\s+|Rs\.?\s+|₹\s*)?\d|{MONTH_PATTERN}|last\b|this\b|today\b|yesterday\b)',candidate,re.I):party=candidate
    for bill in sorted(bills,key=lambda b:len(b['invoice_number']),reverse=True):
        key=normalized(bill['invoice_number'])
        if key and re.search(r'(?<!\w)'+re.escape(key)+r'(?!\w)',norm):invoice=bill['invoice_number'];break
    intent_text=re.sub(re.escape(invoice),'',query,flags=re.I) if invoice else query
    direction='sale' if re.search(r'\b(sell|selling|sold|sale|sales)\b',intent_text,re.I) else 'purchase' if re.search(r'\b(buy|buying|bought|purchased|purchase)\b',intent_text,re.I) else None
    date=parse_date(intent_text)
    bad_date=not date and bool(re.search(rf'\b(?:on|dated)\s+(?:{MONTH_PATTERN}|\d{{1,4}}[/.\-]\d)',intent_text,re.I))
    if party is None or not known:
        for alias in sorted(party_aliases,key=lambda a:len(a['alias']),reverse=True):
            if re.search(r'(?<!\w)'+re.escape(alias['alias'])+r'(?!\w)',norm):party=alias['party'];known=True;break
    # Only parse calendar expressions for bill-like queries; normal document search
    # must not become a date parser merely because it contains a month name.
    bill_context=known or invoice or re.search(r'\b(bills?|invoices?|sell|selling|sold|sale|sales|buy|bought|purchased|purchase)\b',query,re.I)
    start,end=date_range(intent_text,today) if bill_context and not bad_date else (date,date)
    item=None
    match=re.search(r'\b(?:contained|containing|includes?|including|item(?:s)?(?:\s+named)?)\s+["\']?(.+?)["\']?(?:\s+(?:from|between|on|during|in|to)\s+|[?]|$)',intent_text,re.I)
    if match:item=match.group(1).strip(' "\'.,')
    return dict(party=party,date=date,date_from=start,date_to=end,direction=direction,party_known=known,invalid_date=bad_date,invoice_number=invoice,item=item)


def search(lib,query,*,folder_id=None,document_id=None,force=False,filters=None,amount_override=None,document_ids=None,matching=None):
    from .bill_amounts import query_amount,search_amount
    amount=amount_override or query_amount(query)
    bills=all_bills(lib);intent=parse_query(query,bills,aliases(lib));filters=filters or {}
    for key in ('party','date_from','date_to','direction','invoice_number','item'):
        if filters.get(key):intent[key]=filters[key]
    if intent['party']:
        for alias in aliases(lib):
            if normalized(intent['party'])==alias['alias']:intent['party']=alias['party'];break
    for key in ('date_from','date_to'):
        if intent[key]:
            try:dt.date.fromisoformat(intent[key])
            except ValueError:raise ValueError('Use valid YYYY-MM-DD bill filter dates')
    if intent['date_from'] and intent['date_to'] and intent['date_from']>intent['date_to']:raise ValueError('Start date must not follow end date')
    if intent['direction'] not in (None,'sale','purchase','unspecified'):raise ValueError('Invalid transaction filter')
    explicit=bool(intent['date_from'] or intent['party'] or intent['invoice_number'] or intent['item'] or intent['direction']) and bool(force or re.search(r'\b(bills?|invoices?|sell|selling|sold|sale|sales|buy|bought|purchased|purchase)\b',query,re.I) or intent['party_known'] or intent['invoice_number'])
    if not force and not explicit and not amount:return None
    if intent['invalid_date']:raise ValueError('Use a valid bill date with a four-digit year, for example 25 September 2026 or 25/09/2026.')
    if folder_id:lib._folder(folder_id)
    if document_id:lib.document(document_id)
    if amount:return search_amount(lib,query,intent,amount,bills,folder_id,document_id,document_ids=document_ids,matching=matching)
    found=[]
    for bill in bills:
        if document_ids is not None and bill['document_id'] not in document_ids:continue
        if folder_id and bill['folder_id']!=folder_id:continue
        if document_id and bill['document_id']!=document_id:continue
        if intent['party'] and normalized(intent['party'])!=bill['party_normalized']:continue
        if intent['date_from'] and (not bill['bill_date'] or bill['bill_date']<intent['date_from']):continue
        if intent['date_to'] and (not bill['bill_date'] or bill['bill_date']>intent['date_to']):continue
        if intent['invoice_number'] and normalized(intent['invoice_number'])!=normalized(bill['invoice_number']):continue
        if intent['direction'] and bill['direction']!=intent['direction']:continue
        if not any(intent[k] for k in ('party','date_from','date_to','invoice_number','item','direction')) and normalized(query) not in normalized(bill['party']+' '+bill['invoice_number']) and normalized(query) not in ('find invoices','show invoices','all invoices','invoices','bills','all bills','show bills','find bills'):continue
        # Return the physical source page associated with the evidence, with real
        # indexed text. An OCR/empty page without a chunk cannot invent a passage.
        rows=lib.db.execute('''SELECT c.*,d.filename,d.managed_path,d.status document_status,f.id folder_id,f.name folder_name,
             p.page_label,p.method extraction_method,p.warnings page_warnings FROM chunks c
             JOIN documents d ON d.id=c.document_id JOIN folders f ON f.id=d.folder_id
             JOIN pages p ON p.document_id=c.document_id AND p.page_number=c.page_number
             WHERE c.document_id=? ORDER BY c.chunk_index''',(bill['document_id'],)).fetchall()
        if intent['item']:
            words=normalized(intent['item']).split()
            row=next((r for r in rows if all(w in normalized(r['text']).split() for w in words)),None)
        elif intent['invoice_number']:
            # Prefer a passage containing a labelled identifier over a generic
            # bill source page, which may refer to a total on a different page.
            label=re.compile(r'(?:invoice|bill|inv)[ \t]*(?:no\.?|number|#)[ \t]*[:#\-]?[ \t]*([A-Z0-9][A-Z0-9/_.\-]{0,49})',re.I)
            def identifier_in(text):
                return any(normalized(m.group(1))==normalized(bill['invoice_number']) for m in label.finditer(text))
            row=next((r for r in rows if identifier_in(r['text'])),None)
            if row is None:row=next((r for r in rows if r['page_number']==bill['source_page']),None)
        else:row=next((r for r in rows if r['page_number']==bill['source_page']),None)
        if row:
            score=sum(bool(intent[k]) for k in ('party','date_from','direction','invoice_number','item'))
            hit=lib._result(row,score,'bill_fields');hit['bill']=bill;hit['match_reasons']=[f'{k}: {intent[k]}' for k in ('party','date_from','date_to','direction','invoice_number','item') if intent[k]]
            if intent['invoice_number'] and not intent['item'] and not identifier_in(row['text']):hit['match_reasons'].append('Saved invoice number; verify it against the original source')
            found.append(hit)
    for rank,hit in enumerate(found[:100],1):hit['rank']=rank
    return dict(query=query,folder_id=folder_id,document_id=document_id,mode='bill_fields',scoped_chunks=0,results=found[:100],
                elapsed_s=0.,query_embedding_s=0.,reliability='reviewed_bill_fields' if found and all(x['bill']['reviewed'] for x in found) else 'unreviewed_bill_fields',
                note='Matched bill fields, not a generated answer. Verify unreviewed invoice extraction against the source.',
                bill_intent=intent,bill_matches=len(found),closest_available=False,below_cutoff=False,
                empty_reason=None if found else 'no_matching_bill_fields')
