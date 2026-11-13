"""Offline, source-bound bibliography drafts. No metadata is fetched from the web.

Drafts live in the existing settings table so verified backups and recoverable
trash retain corrections without changing the source PDF or embedding recipe.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import pymupdf

PREFIX='khoj.reference:'
VERSION=3
_DOI=re.compile(r'10\.\d{4,9}/[^\s<>"{}]+',re.I)
_ARXIV=re.compile(r'\barXiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?',re.I)
_ABSTRACT=re.compile(r'^\s*(?:abstract|a\s+b\s+s\s+t\s+r\s+a\s+c\s+t)\s*(?:[:.\-—]\s*.*)?$',re.I|re.M)
_REFERENCES=re.compile(r'^\s*(?:\d+[.\s]+)?(?:references|bibliography|literature cited)\s*$',re.I|re.M)
_TEXT_FIELDS={'title','container-title','volume','issue','page','publisher','publisher-place','edition','ISBN','ISSN','language','genre','archive','archive_location','number'}
_TYPES={'article','article-journal','paper-conference','book','chapter','thesis','report','webpage','manuscript'}


def _text(value,limit=2000):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value or ''))).strip()[:limit]


def _doi(value):
    match=_DOI.search(value or '')
    if not match:return ''
    candidate=match[0].rstrip('.,;')
    while candidate.endswith(')') and candidate.count(')')>candidate.count('('):candidate=candidate[:-1]
    return candidate


def _date(value):
    match=re.match(r'^\s*((?:18|19|20|21)\d{2})(?:-(\d{2})(?:-(\d{2}))?)?',value or '')
    if not match:return None
    parts=[int(x) for x in match.groups() if x is not None]
    try:dt.date(parts[0],parts[1] if len(parts)>1 else 1,parts[2] if len(parts)>2 else 1)
    except ValueError:return None
    return {'date-parts':[parts]}


def _person(name):
    name=re.sub(r'[*†‡∗⋆]','',_text(name)).strip(' ,0123456789')
    if not name or '@' in name or len(name)>180:return None
    if re.search(r'\b(?:university|institute|department|laboratory|anonymous|microsoft|latex|unknown)\b',name,re.I):return None
    if ',' in name:
        family,given=(p.strip() for p in name.split(',',1))
        if family and given:return {'family':family,'given':given}
    parts=name.split()
    if 2<=len(parts)<=7 and all(any(c.isalpha() for c in p) for p in parts):
        return {'given':' '.join(parts[:-1]),'family':parts[-1]}
    return {'literal':name} if name else None


def _authors(value):
    if isinstance(value,str):
        # Semicolons and "and" are reliable author separators; a lone comma
        # may mean "family, given" and must not silently create two authors.
        separated=re.split(r'\s*;\s*|\s+and\s+|\s+&\s+',value)
        value=[]
        for entry in separated:
            comma_parts=[part.strip() for part in entry.split(',') if part.strip()]
            # Comma-separated full names are common in PDF author metadata.
            # Short "family, given" pairs remain structured single names.
            if len(comma_parts)>1 and all(len(part.split())>=2 for part in comma_parts):value.extend(comma_parts)
            else:value.append(entry.rstrip(', '))
    return [person for name in (value or []) if (person:=_person(name))][:200]


def _xmp(xml):
    result={}
    if not xml or len(xml)>2_000_000 or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():return result
    try:root=ET.fromstring(xml)
    except ET.ParseError:return result
    fields={'doi':'DOI','publicationName':'container-title','publicationDate':'issued','coverDate':'issued',
            'volume':'volume','number':'issue','issueIdentifier':'issue','pageRange':'page','publisher':'publisher',
            'title':'title','creator':'author'}
    for element in root.iter():
        for key,value in element.attrib.items():
            local=key.rsplit('}',1)[-1]
            if local in fields and _text(value):result.setdefault(fields[local],_text(value))
        local=element.tag.rsplit('}',1)[-1]
        if local not in fields:continue
        values=[_text(''.join(child.itertext())) for child in element.iter() if child.tag.endswith('}li')]
        value=values if local=='creator' and values else values[0] if values else _text(element.text)
        if value:result.setdefault(fields[local],value)
    return result


def _good_title(title):
    return bool(title and len(title)>=8 and not re.match(r'^(?:untitled|microsoft (?:word|powerpoint)|arxiv:|latex|template|anonymous)(?:\b|\s)',title,re.I))


def _layout_title(page):
    """Use prominent horizontal text above the abstract, excluding arXiv stamps."""
    lines=[]
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            if line['bbox'][1]>page.rect.height*.48 or abs(line.get('dir',(1,0))[1])>.1:continue
            text=''.join(span['text'] for span in line['spans']).strip()
            if _ABSTRACT.match(text):continue
            if not text or _ARXIV.search(text) or re.match(r'^(?:\d|proceedings|published|copyright|©)',text,re.I):continue
            size=max((span['size'] for span in line['spans'] if span['text'].strip()),default=0)
            lines.append((size,line['bbox'][1],text))
    if not lines:return ''
    biggest=max(line[0] for line in lines)
    selected=[line for line in lines if line[0]>=biggest*.94]
    return _text(' '.join(line[2] for line in sorted(selected,key=lambda line:line[1])))


def extract(path=None,*,document_id,filename,first_text='',tail_text=''):
    """Extract only observed fields. Indexed text is a safe missing-source fallback."""
    metadata={};xmp={};layout_title='';source_note='indexed text'
    if path is not None:
        with pymupdf.open(path) as pdf:
            if not pdf.is_pdf or pdf.needs_pass:raise ValueError('The source is not a readable PDF.')
            metadata=pdf.metadata or {};xmp=_xmp(pdf.get_xml_metadata())
            first_text=pdf[0].get_text('text',sort=False)[:100_000] if len(pdf) else ''
            tail_text='\n'.join(pdf[index].get_text('text',sort=False)[:60_000] for index in range(max(1,len(pdf)-3),len(pdf)))
            layout_title=_layout_title(pdf[0]) if len(pdf) else ''
            source_note='PDF metadata'
    first_text=unicodedata.normalize('NFKC',first_text[:100_000]);tail_text=unicodedata.normalize('NFKC',tail_text[:180_000])
    front=_REFERENCES.split(first_text,maxsplit=1)[0]
    abstract=bool(_ABSTRACT.search(front))
    references=bool(_REFERENCES.search(tail_text) or _REFERENCES.search(first_text))
    arxiv=_ARXIV.search(front)
    own_doi=_doi(xmp.get('DOI',''))
    if not own_doi:
        labelled=re.search(r'(?:\bdoi\s*[:=]\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>"{}]+)',front,re.I)
        own_doi=_doi(labelled[1]) if labelled else ''
    title=_text(xmp.get('title') or metadata.get('title'))
    if not _good_title(title):title=layout_title if _good_title(layout_title) else ''
    # Some preprints omit an Abstract heading and place References before long
    # appendices. An own versioned/date/category stamp plus Introduction is
    # stronger evidence than a bare arXiv identifier cited in ordinary text.
    own_stamp=bool(re.search(r'^\s*arXiv\s*:\s*\d{4}\.\d{4,5}v\d+\s+\[[A-Za-z0-9. -]+\]\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s*$',front,re.I|re.M))
    introduction=bool(re.search(r'^\s*(?:1[.\s]+)?Introduction\s*$',front,re.I|re.M))
    detected=bool((abstract and (references or arxiv or own_doi)) or (own_stamp and introduction) or (xmp.get('container-title') and own_doi and title))
    item={'id':document_id,'type':'article'};provenance={};warnings=[]
    def add(key,value,source):
        if value:item[key]=value;provenance[key]=source
    if title:add('title',title,'XMP' if xmp.get('title') else source_note if metadata.get('title') else 'First-page heading')
    elif detected:
        # Without page layout, stop before Abstract rather than using arbitrary
        # text from the body. This is visibly a draft, not verified metadata.
        header=_ABSTRACT.split(front,maxsplit=1)[0]
        candidates=[_text(line) for line in header.splitlines() if _good_title(_text(line)) and not _ARXIV.search(line)]
        if candidates:add('title',candidates[0],'Indexed first-page text; review required')
    if 'title' not in item:add('title',Path(filename).stem,'Filename fallback; review required')
    if detected:
        authors=_authors(xmp.get('author') or metadata.get('author'))
        if authors:add('author',authors,'XMP' if xmp.get('author') else 'PDF author metadata; review required')
        elif abstract and title and path is not None:
            # Read only the title-to-abstract block, and only clean full-name
            # lines. Affiliations, addresses, emails and mixed markers are left
            # for the user instead of becoming invented authors.
            heading=_ABSTRACT.split(front,maxsplit=1)[0]
            title_last=title.split()[-1] if title else ''
            start=heading.find(title_last)
            if start>=0:
                candidate_lines=heading[start+len(title_last):].splitlines()
                found=[]
                for line in candidate_lines:
                    line=line.strip()
                    if not line:continue
                    if re.search(r'[@\d]|\b(?:university|institute|department|google|openai|research|laboratory|published|doi|inc|facebook|microsoft|contribution)\b',line,re.I):continue
                    people=_authors(line)
                    if people and all('family' in person for person in people):
                        found.extend(people)
                if found:add('author',found,'First-page author block; review required')
        add('DOI',own_doi,'XMP' if xmp.get('DOI') else 'First-page DOI label')
        if own_doi:add('URL','https://doi.org/'+own_doi,'DOI resolver URL')
        elif arxiv:
            add('URL','https://arxiv.org/abs/'+arxiv[1],'First-page arXiv identifier')
            add('archive','arXiv','First-page arXiv identifier')
            add('archive_location',arxiv[1],'First-page arXiv identifier')
        date=_date(xmp.get('issued',''))
        if date:add('issued',date,'XMP publication date')
        else:
            published=re.search(r'\b(?:published(?:\s+online)?|publication date)\s*[:.]?\s*((?:18|19|20|21)\d{2}(?:-\d{2}(?:-\d{2})?)?)',front,re.I)
            if published:add('issued',_date(published[1]),'First-page publication date')
        conference=re.search(r'Published as a conference paper at\s+([^\n]*?\b((?:19|20)\d{2}))\b',front,re.I)
        if conference:
            item['type']='paper-conference'
            add('container-title',_text(conference[1]),'First-page conference publication statement')
            if 'issued' not in item:add('issued',_date(conference[2]),'First-page conference publication statement')
        if 'issued' not in item and arxiv and re.fullmatch(r'\d{4}\.\d{4,5}',arxiv[1]):
            # The identifier explicitly encodes the preprint submission month,
            # which may differ from eventual proceedings/journal publication.
            short=int(arxiv[1][:2]);year=(1900 if short>=91 else 2000)+short
            add('issued',{'date-parts':[[year]]},'arXiv identifier: preprint submission year, not verified publication year')
            warnings.append('Year is the arXiv preprint submission year; verify the year for the version you intend to cite.')
        for field in ('container-title','volume','issue','page','publisher'):
            add(field,_text(xmp.get(field)), 'XMP')
        if item.get('container-title') and item['type']!='paper-conference':item['type']='article-journal'
        warnings.append('Automatically extracted reference draft. Verify names, publication details, and date before citing.')
        if item.get('author'):warnings.append('The extracted author list and name order may be incomplete or incorrect; compare with the paper before citing.')
        for field,label in (('author','Authors'),('issued','Publication year')):
            if field not in item:warnings.append(label+' could not be established from the document.')
    else:warnings.append('This document was not confidently detected as a research paper. You can enter a reference manually.')
    if path is None:warnings.append('Original PDF is unavailable or changed; this draft uses indexed text only.')
    return dict(detected=detected,item=item,provenance=provenance,warnings=warnings,reviewed=False,extractor_version=VERSION)


def validate_item(item,document_id):
    if not isinstance(item,dict):raise ValueError('Reference details must be an object.')
    allowed=_TEXT_FIELDS|{'id','type','author','editor','issued','DOI','URL'}
    if set(item)-allowed:raise ValueError('Unsupported reference field: '+', '.join(sorted(set(item)-allowed)))
    result={'id':document_id,'type':item.get('type','article')}
    if result['type'] not in _TYPES:raise ValueError('Choose a supported reference type.')
    for key in _TEXT_FIELDS|{'DOI','URL'}:
        if key not in item:continue
        value=item[key]
        if not isinstance(value,str) or len(value)>2000 or any(ord(c)<32 and c not in '\t\r\n' for c in value):raise ValueError('Reference fields must contain at most 2000 printable characters.')
        value=_text(value)
        if not value:continue
        if key=='URL':
            url=urlsplit(value)
            if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password:raise ValueError('Reference URL must be an HTTP or HTTPS address.')
        if key=='DOI' and (not _DOI.fullmatch(value) or len(value)>256):raise ValueError('Enter a valid DOI beginning with 10.')
        result[key]=value
    if not result.get('title'):raise ValueError('A reference needs a title.')
    for role in ('author','editor'):
        if role not in item:continue
        people=item[role]
        if not isinstance(people,list) or len(people)>200:raise ValueError('Reference authors must be a list of at most 200 names.')
        parsed=[]
        for person in people:
            if not isinstance(person,dict) or not person or set(person)-{'family','given','literal','suffix','non-dropping-particle','dropping-particle'}:raise ValueError('Each author needs a supported name object.')
            if any(not isinstance(v,str) or len(v)>200 or any(ord(c)<32 for c in v) for v in person.values()):raise ValueError('Author names must be printable text of at most 200 characters.')
            value={k:_text(v) for k,v in person.items() if _text(v)}
            if not value.get('family') and not value.get('literal'):raise ValueError('Each author needs a family name or a literal name.')
            if value.get('literal') and len(value)>1:raise ValueError('Use either a literal name or structured name fields.')
            parsed.append(value)
        if parsed:result[role]=parsed
    if 'issued' in item:
        issued=item['issued']
        if not isinstance(issued,dict) or set(issued)!={'date-parts'}:raise ValueError('Date must use CSL date-parts.')
        parts=issued['date-parts']
        if not isinstance(parts,list) or len(parts)!=1 or not isinstance(parts[0],list) or not 1<=len(parts[0])<=3 or any(type(x) is not int for x in parts[0]):raise ValueError('Date must contain one year, optionally month and day.')
        values=parts[0]
        try:dt.date(values[0],values[1] if len(values)>1 else 1,values[2] if len(values)>2 else 1)
        except (ValueError,OverflowError):raise ValueError('Reference date is invalid.')
        result['issued']={'date-parts':[list(values)]}
    return result


def _stored(lib,document_id):
    row=lib.db.execute('SELECT value FROM settings WHERE key=?',(PREFIX+document_id,)).fetchone()
    if not row:return None
    try:value=json.loads(row[0])
    except (ValueError,TypeError):return None
    return value if isinstance(value,dict) else None


def _write(lib,document_id,value):
    lib.db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(PREFIX+document_id,json.dumps(value,ensure_ascii=False)))


def _detect(lib,doc):
    pages=lib.db.execute('SELECT page_number,text FROM pages WHERE document_id=? AND (page_number=1 OR page_number>=?) ORDER BY page_number',(doc['id'],max(2,doc['page_count']-2))).fetchall()
    first=next((row['text'] for row in pages if row['page_number']==1),'')
    tail='\n'.join(row['text'] for row in pages if row['page_number']!=1)
    path=None
    if Path(doc['filename']).suffix.lower()=='.pdf':
        try:path=lib.source_path(doc,verify=True)
        except (OSError,ValueError):pass
    value=extract(path,document_id=doc['id'],filename=doc['filename'],first_text=first,tail_text=tail)
    if Path(doc['filename']).suffix.lower()!='.pdf':value['detected']=False
    value['source_sha256']=doc['sha256']
    return value


def record_after_index(lib,doc):
    """Caller owns the transaction; metadata failure cannot abort PDF ingestion."""
    old=_stored(lib,doc['id'])
    if old and old.get('source_sha256')==doc['sha256'] and (old.get('reviewed') or old.get('extractor_version')==VERSION):return
    lib.db.execute('SAVEPOINT paper_reference')
    try:
        value=_detect(lib,doc)
        _write(lib,doc['id'],value)
    except Exception:
        lib.db.execute('ROLLBACK TO paper_reference')
        logging.getLogger(__name__).warning('Reference draft extraction failed; document indexing retained.',exc_info=False)
    finally:lib.db.execute('RELEASE paper_reference')


def reference(lib,document_id):
    doc=lib.document(document_id);old=_stored(lib,document_id)
    if old and old.get('source_sha256')==doc['sha256'] and (old.get('reviewed') or old.get('extractor_version')==VERSION):return old
    value=_detect(lib,doc)
    with lib.db:_write(lib,document_id,value)
    return value


def save_reference(lib,document_id,item,reviewed=True,source_sha256=None):
    doc=lib.document(document_id)
    if source_sha256 is not None and source_sha256!=doc['sha256']:raise ValueError('This document changed. Reload its reference before saving.')
    if type(reviewed) is not bool:raise ValueError('Reference review status must be true or false.')
    valid=validate_item(item,document_id);previous=reference(lib,document_id)
    value={**previous,'item':valid,'reviewed':reviewed,'provenance':{key:'User supplied' for key in valid if key not in {'id','type'}},'warnings':[] if reviewed else ['Reference details are not marked as reviewed.'],'source_sha256':doc['sha256']}
    with lib.db:
        current=lib.document(document_id)
        if current['sha256']!=doc['sha256']:raise ValueError('This document changed. Reload its reference before saving.')
        _write(lib,document_id,value)
    return value


def reset_reference(lib,document_id):
    doc=lib.document(document_id);value=_detect(lib,doc)
    with lib.db:_write(lib,document_id,value)
    return value
