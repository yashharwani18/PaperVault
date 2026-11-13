"""Source qualifications and conservative, physical invoice field context.

Coordinates describe observations, not recognition confidence or a layout proof.
No arithmetic corrections or guessed OCR alternatives are generated here.
"""
import json
import re
from decimal import Decimal


def qualifications(hit):
    notes=[]
    if hit.get('extraction_method')=='ocr':notes.append('OCR reading; verify the original.')
    if hit.get('source_available') is False:notes.append('Original source is unavailable.')
    for warning in hit.get('warnings',[]):
        if warning not in notes:notes.append(warning)
    match=hit.get('amount_match',{})
    if match and not match.get('verified'):
        notes.append('Amount matched indexed text; the field association has not been reviewed.')
    if match.get('association')=='unresolved':notes.append('Multiple amount columns; field association is unresolved.')
    return notes


def scoped_review(bill,match,revision):
    """Only an explicit field review may qualify the identical source observation."""
    if not bill or not bill.get('reviewed') or not revision:return False
    evidence=bill.get('evidence',{})
    if isinstance(evidence,str):
        try:evidence=json.loads(evidence)
        except (ValueError,TypeError):return False
    review=evidence.get('amount_review',{}) if isinstance(evidence,dict) else {}
    return all(review.get(k)==v for k,v in dict(source_sha256=revision,page_number=match['page_number'],
        field=match['field'],value=match['value'],currency=match.get('currency'),evidence=match['evidence'],bbox=match.get('bbox')).items())


def physical_amounts(text,layout):
    """Resolve only explicit Current/Previous column headers on horizontal rows.

    Return None when geometry is unavailable; otherwise return observed amount
    candidates. Repeated identical strings retain separate physical identities.
    Ambiguous rows remain candidates and never become verified fields.
    """
    from .bill_amounts import money,field,LABEL,CURRENCY,currency_code,source_amounts
    if not layout or layout.get('rotation') or layout.get('non_horizontal_text'):return None
    words=layout.get('words',[])
    lines={}
    for w in words:lines.setdefault(tuple(w[5:7]),[]).append(w)
    rows=[sorted(v,key=lambda w:w[0]) for v in lines.values()]
    # OCR can put each column in a separate block. Merge horizontal baselines.
    merged=[]
    for row in sorted(rows,key=lambda r:(r[0][1],r[0][0])):
        cy=sum((w[1]+w[3])/2 for w in row)/len(row)
        target=next((r for y,r in merged if abs(y-cy)<=max(2,min(w[3]-w[1] for w in row)*.35)),None)
        if target is None:merged.append((cy,list(row)))
        else:target.extend(row)
    headers=[]
    for y,row in merged:
        row.sort(key=lambda w:w[0])
        for i,w in enumerate(row):
            if re.fullmatch('current|previous',w[4],re.I) and i+1<len(row) and re.fullmatch('invoice',row[i+1][4],re.I):
                headers.append((w[4].lower(),(w[0]+row[i+1][2])/2,y))
    observed=[];handled=set()
    for y,row in merged:
        row.sort(key=lambda w:w[0])
        for i in range(min(len(row),4)):
            label=None;label_end=0
            for size in (3,2,1):
                candidate=' '.join(w[4] for w in row[i:i+size]).rstrip(':')
                if re.fullmatch(LABEL,candidate,re.I):label=candidate;label_end=i+size;break
            if not label:continue
            amounts=[]
            for w in row[label_end:]:
                literal=re.sub(rf'^(?:{CURRENCY})\s*','',w[4],flags=re.I)
                try:money(literal)
                except ValueError:continue
                amounts.append((w,literal))
            if len(amounts)<2:continue  # Ordinary source-order path for simple rows.
            current=[h for h in headers if h[0]=='current' and h[2]<y]
            previous=[h for h in headers if h[0]=='previous' and h[2]<y]
            selected=None
            if len(current)==len(previous)==1:
                assignments=[min(range(len(amounts)),key=lambda j:abs((amounts[j][0][0]+amounts[j][0][2])/2-h[1])) for h in (current[0],previous[0])]
                if assignments[0]!=assignments[1]:selected=assignments[0]
            handled.add(field(label))
            for j,(w,literal) in enumerate(amounts):
                if selected is not None and j!=selected:continue
                occurrences=list(re.finditer(r'(?<![\w.,])'+re.escape(w[4])+r'(?![\w.,])',text))
                # Preserve duplicate physical values; offsets are a quote anchor only.
                if not occurrences:continue
                occurrence=occurrences[min(sum(1 for old in words[:words.index(w)] if old[4]==w[4]),len(occurrences)-1)]
                units={currency_code(c) for c in re.findall(CURRENCY,' '.join(a[4] for a in row),re.I)}
                observed.append(dict(field=field(label),value=format(money(literal),'.2f'),
                    currency=next(iter(units)) if len(units)==1 else None,evidence=occurrence[0],
                    start=occurrence.start(),end=occurrence.end(),bbox=w[:4],label=label,
                    headers=[dict(kind=h[0],x=h[1],y=h[2]) for h in headers],
                    association='current_column' if selected is not None else 'unresolved'))
            break
    return [a for a in source_amounts(text) if a['field'] not in handled]+observed
