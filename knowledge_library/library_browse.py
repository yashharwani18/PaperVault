"""Bounded metadata browsing; no document content or model inference."""
from datetime import date,datetime
import json
import re
import unicodedata
from .text_documents import source_info
from .organization import decorate_documents
from .filename_search import attach_scanned_modified_times

SQL_ORDERS={
    'added_new':'d.created_at DESC,d.id ASC', 'added_old':'d.created_at ASC,d.id ASC',
    'size_large':'d.size_bytes DESC,d.id ASC', 'size_small':'d.size_bytes ASC,d.id ASC',
}
SORTS=set(SQL_ORDERS)|{'name','name_desc','modified_new','modified_old','type','recent'}
# Sorts and filters the browser can resolve without loading the whole catalog.
PAGE_SORTS=sorted(SORTS)
PAGE_FILTERS=['folder','topic','extension','status','added','modified','size','favorites','recent','name','bills']
ALPHABET=['#']+[chr(code) for code in range(65,91)]
SCOPE_FILTERS={'extension','status','added_from','added_through','modified_from','modified_through',
               'min_size','max_size','favorites','recent','name','bills','bill_party','bill_date_from',
               'bill_date_to','bill_number','bill_direction'}
BILL_COLUMNS=',b.party bill_party,b.bill_date bill_bill_date,b.invoice_number bill_invoice_number,b.direction bill_direction,b.amount bill_amount,b.currency bill_currency,b.reviewed bill_reviewed'


def _natural(value):
    """Deterministic NFKD natural key shared by both platforms: digits compare numerically."""
    text=unicodedata.normalize('NFKC',str(value or '').strip())
    text=''.join(char for char in unicodedata.normalize('NFKD',text) if not unicodedata.combining(char)).casefold()
    parts=[]
    for token in re.findall(r'\d+|\D+',text):
        if token.isdigit():
            digits=token.lstrip('0') or '0'
            parts.append((1,len(digits),digits))
        else:parts.append((0,token))
    return tuple(parts)


def _letter(filename):
    first=unicodedata.normalize('NFKC',str(filename or '').strip())[:1].upper()
    return first if first in ALPHABET[1:] else '#'


def _extension(filename):
    name=str(filename or '')
    return name.rsplit('.',1)[-1].lower() if '.' in name and not name.startswith('.') else ''


def _timestamp(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (TypeError,ValueError):return None


def _reading(lib):
    from .reading_state import state
    return state(lib)


def _validate(body,allow_paging=True):
    sort=body.get('sort','added_new')
    if not isinstance(sort,str) or sort not in SORTS:raise ValueError('This sort is not available for database browsing.')
    limit=body.get('limit',100);offset=body.get('offset',0)
    if allow_paging and (type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000):
        raise ValueError('Choose a valid document page.')
    status=body.get('status','all')
    if status not in ('all','indexed','attention'):raise ValueError('Choose a valid status filter.')
    for key in ('favorites','recent'):
        if key in body and type(body[key]) is not bool:raise ValueError('Choose a valid reading filter.')
    name=body.get('name','')
    if not isinstance(name,str) or len(name)>500:raise ValueError('Choose a valid filename filter.')
    for key in ('modified_from','modified_through'):
        value=body.get(key)
        if value is None or value=='':continue
        try:
            if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:raise ValueError()
        except ValueError:raise ValueError('Choose a valid date.') from None
    return sort


def _conditions(body):
    conditions=[];args=[]
    folder=body.get('folder_id')
    if folder:
        if not isinstance(folder,str):raise ValueError('Choose a valid folder.')
        conditions.append('d.folder_id=?');args.append(folder)
    extension=body.get('extension')
    if extension:
        if not isinstance(extension,str) or len(extension)>16 or not extension.isalnum():raise ValueError('Choose a valid document type.')
        suffix='.'+extension.lower();conditions.append('lower(substr(d.filename,-?))=?');args.extend((len(suffix),suffix))
    status=body.get('status','all')
    if status=='indexed':conditions.append("d.status='indexed'")
    elif status=='attention':conditions.append("d.status!='indexed'")
    for key,column,op in [('added_from','created_at','>='),('added_through','created_at','<='),('min_size','size_bytes','>='),('max_size','size_bytes','<=')]:
        value=body.get(key)
        if value is None or value=='':continue
        if key.startswith('added_'):
            try:
                if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:raise ValueError()
            except ValueError:raise ValueError('Choose a valid date.') from None
            conditions.append(f'd.{column}{op}?');args.append(value+'\uffff' if key=='added_through' else value)
        else:
            if type(value) is not int or value<0:raise ValueError('Choose a valid file size.')
            conditions.append(f'd.{column}{op}?');args.append(value)
    return conditions,args


def _base(body):
    conditions,args=_conditions(body)
    if body.get('bills'):
        bill_conditions,bill_args=_bill_conditions(body)
        conditions+=bill_conditions;args+=bill_args
    join=' JOIN bill_records b ON b.document_id=d.id AND b.source_sha256=d.sha256' if body.get('bills') else ''
    return (' FROM documents d JOIN folders f ON f.id=d.folder_id'+join+(' WHERE '+' AND '.join(conditions) if conditions else '')),args


def _scope(lib,body):
    """Explicit topic/favorites/recent scope, or None when the SQL filters are enough."""
    allowed=None
    linked=body.get('linked_folder_id')
    if linked:
        if not isinstance(linked,str):raise ValueError('Choose a valid topic.')
        from .workspace_features import scope
        allowed=set(scope(lib,linked))
    if body.get('favorites') or body.get('recent'):
        reading=_reading(lib)
        if body.get('favorites'):
            matches={key for key,value in reading['documents'].items() if value['favorite']}
            allowed=matches if allowed is None else allowed & matches
        if body.get('recent'):
            matches=set(reading['recent_ids'])
            allowed=matches if allowed is None else allowed & matches
    return allowed


def _display_names(lib):
    prefix='organization.document_name:';names={}
    for key,value in lib.db.execute('SELECT key,value FROM workspace_settings WHERE key LIKE ?',(prefix+'%',)):
        try:names[key[len(prefix):]]=json.loads(value)
        except (TypeError,ValueError):pass
    return names


def _columns(body):
    return 'd.*,f.name folder_name'+(BILL_COLUMNS if body.get('bills') else '')


def _bill_conditions(body):
    conditions=[];args=[]
    party=body.get('bill_party')
    if party:
        if not isinstance(party,str) or len(party)>160:raise ValueError('Choose a valid bill party.')
        conditions.append('lower(b.party) LIKE ?');args.append('%'+party.casefold()+'%')
    number=body.get('bill_number')
    if number:
        if not isinstance(number,str) or len(number)>80:raise ValueError('Choose a valid invoice number.')
        conditions.append('lower(b.invoice_number) LIKE ?');args.append('%'+number.casefold()+'%')
    direction=body.get('bill_direction')
    if direction:
        if direction not in ('sale','purchase','unspecified'):raise ValueError('Choose a valid bill direction.')
        conditions.append('b.direction=?');args.append(direction)
    for key,column,op in (('bill_date_from','bill_date','>='),('bill_date_to','bill_date','<=')):
        value=body.get(key)
        if not value:continue
        try:
            if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:raise ValueError()
        except ValueError:raise ValueError('Choose a valid bill date.') from None
        conditions.append(f'b.{column}{op}?');args.append(value)
    return conditions,args


def _bill(row):
    if row.get('bill_party') is None:return None
    return dict(party=row['bill_party'] or '',bill_date=row.get('bill_bill_date'),invoice_number=row.get('bill_invoice_number') or '',
                direction=row.get('bill_direction') or 'unspecified',amount=row.get('bill_amount'),currency=row.get('bill_currency') or '',
                reviewed=bool(row.get('bill_reviewed')))


def _filtered(lib,body,columns=None):
    columns=columns or _columns(body)
    """All filters, including the ones SQLite cannot express (display name, modified date)."""
    base,args=_base(body)
    rows=[dict(row) for row in lib.db.execute('SELECT '+columns+base,args)]
    allowed=_scope(lib,body)
    if allowed is not None:rows=[row for row in rows if row['id'] in allowed]
    name=body.get('name','').casefold()
    if name:
        names=_display_names(lib)
        rows=[row for row in rows if name in (str(names.get(row['id']) or row['title'])+' '+row['filename']).casefold()]
    if body.get('modified_from') or body.get('modified_through'):
        attach_scanned_modified_times(lib,rows)
        lower=body.get('modified_from') or '';upper=body.get('modified_through') or ''
        rows=[row for row in rows if row.get('modified_at') and (not lower or row['modified_at'][:10]>=lower) and (not upper or row['modified_at'][:10]<=upper)]
    return rows


def _ordered(rows,sort,reading):
    rows=sorted(rows,key=lambda row:(_natural(row['filename']),row['id']))
    if sort=='name_desc':return list(reversed(rows))
    if sort=='name':return rows
    if sort=='type':
        return sorted(rows,key=lambda row:_extension(row['filename']))
    if sort in ('added_new','added_old'):
        return sorted(rows,key=lambda row:row.get('created_at') or '',reverse=sort=='added_new')
    if sort in ('size_large','size_small'):
        return sorted(rows,key=lambda row:row.get('size_bytes') or 0,reverse=sort=='size_large')
    if sort in ('modified_new','modified_old'):
        known=[row for row in rows if _timestamp(row.get('modified_at')) is not None]
        unknown=[row for row in rows if _timestamp(row.get('modified_at')) is None]
        known.sort(key=lambda row:_timestamp(row['modified_at']),reverse=sort=='modified_new')
        return known+unknown
    if sort=='recent':
        rank={key:index for index,key in enumerate(reading['recent_ids'])}
        return sorted(rows,key=lambda row:(rank.get(row['id'],len(rank)),rank.get(row['id'],0)))
    return rows


def _letters(rows):
    ordered=sorted(rows,key=lambda row:(_natural(row['filename']),row['id']))
    seen=set();letters=[]
    for position,row in enumerate(ordered):
        letter=_letter(row['filename'])
        if letter not in seen:seen.add(letter);letters.append(dict(letter=letter,offset=position))
    return letters


def _types(rows):
    return sorted({_extension(row['filename']) for row in rows if _extension(row['filename'])})


def _needs_full_scan(body,sort):
    return sort not in SQL_ORDERS or bool(body.get('name')) or bool(body.get('modified_from')) or bool(body.get('modified_through'))


def page(lib,body):
    # Keep the count, page, index and saved scope in one SQLite snapshot.
    if lib.db.in_transaction:return _page(lib,body)
    lib.db.execute('BEGIN')
    try:return _page(lib,body)
    finally:lib.db.rollback()


def scope_ids(lib,filters):
    if not isinstance(filters,dict) or set(filters)-SCOPE_FILTERS:raise ValueError('Unsupported library search filter.')
    if lib.db.in_transaction:return _page(lib,filters,ids_only=True)
    lib.db.execute('BEGIN')
    try:return _page(lib,filters,ids_only=True)
    finally:lib.db.rollback()


def _page(lib,body,ids_only=False):
    sort=_validate(body,allow_paging=not ids_only)
    limit=body.get('limit',100);offset=body.get('offset',0)
    reading=_reading(lib)
    base,args=_base(body)
    allowed=_scope(lib,body)
    full=_needs_full_scan(body,sort) or allowed is not None
    if full:
        rows=_filtered(lib,body)
        if sort in ('modified_new','modified_old') and not (body.get('modified_from') or body.get('modified_through')):
            attach_scanned_modified_times(lib,rows)
        rows=_ordered(rows,sort,reading)
        if ids_only:return [row['id'] for row in rows]
        total=len(rows);window=rows[offset:offset+limit]
        index_rows=rows
    else:
        if ids_only:
            return [row['id'] for row in lib.db.execute('SELECT d.id'+base+' ORDER BY '+SQL_ORDERS[sort],args)]
        total=lib.db.execute('SELECT count(*)'+base,args).fetchone()[0]
        window=[dict(row) for row in lib.db.execute('SELECT '+_columns(body)+base+' ORDER BY '+SQL_ORDERS[sort]+' LIMIT ? OFFSET ?',args+[limit,offset])]
        index_rows=[dict(row) for row in lib.db.execute('SELECT d.id,d.filename'+base,args)]
    letters=_letters(index_rows)
    type_rows=index_rows
    if body.get('extension'):
        type_body=dict(body);type_body['extension']=None
        type_rows=_filtered(lib,type_body)
    documents=attach_scanned_modified_times(lib,decorate_documents(lib,[dict(row) for row in window]))
    for document in documents:
        bill=_bill(document)
        if bill is not None:document['bill']=bill
    return dict(documents=documents,total=total,offset=offset,limit=limit,letters=letters,types=_types(type_rows))


def filename_candidates(lib,body):
    """Bounded documents for the conservative filename-suggestion heuristic."""
    query=body.get('query','')
    if not isinstance(query,str) or len(query)>500:raise ValueError('Choose a valid filename search.')
    tokens=[token for token in re.findall(r'[^\W_]+',query.casefold()) if len(token)>=2][:6]
    if not tokens:return dict(documents=[])
    rows=_filtered(lib,{key:value for key,value in body.items() if key!='query'},'d.*,f.name folder_name')
    matches=[]
    for row in sorted(rows,key=lambda row:(_natural(row['filename']),row['id'])):
        text=(str(row.get('display_title') or '')+' '+str(row['title'])+' '+row['filename']).casefold()
        words=re.findall(r'[^\W_]+',text)
        if any(token in text or any(word.startswith(token[:3]) for word in words) for token in tokens):
            matches.append(row)
            if len(matches)>=200:break
    return dict(documents=decorate_documents(lib,matches))
