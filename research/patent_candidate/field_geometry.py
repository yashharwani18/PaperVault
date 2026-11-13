"""R13 ordinary row/proximity controls over actual native or OCR word boxes.

Restricted printed total/subtotal labels. These are unverified relation
candidates, not a complete parser, calibrated confidence or source certificate.
"""
import re

from knowledge_library.bill_amounts import money


def overlap(a,b):
    intersection=max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(.0001,min(a[3]-a[1],b[3]-b[1]))


def bbox(words):
    return (min(w[0] for w in words),min(w[1] for w in words),
            max(w[2] for w in words),max(w[3] for w in words))


def relations(words):
    words=list(words); labels=[];used=set()
    clean=lambda w:re.sub(r'[^a-z-]','',w[4].casefold())
    pairs={'grand':('total','total'),'invoice':('total','total'),
           'net':('payable','total'),'sub':('total','subtotal')}
    for i,w in enumerate(words):
        prefix=clean(w)
        if prefix not in pairs:continue
        following,field=pairs[prefix]
        candidates=[(j,v) for j,v in enumerate(words) if j!=i and clean(v)==following
                    and v[0]>=w[2]-.1 and v[0]-w[2]<=35 and overlap(w,v)>=.5]
        if candidates:
            j,v=min(candidates,key=lambda pair:pair[1][0]);used.update((i,j))
            labels.append(dict(field=field,box=bbox([w,v]),words=[w[4],v[4]]))
    for i,w in enumerate(words):
        if i not in used and clean(w) in ('total','subtotal','sub-total'):
            labels.append(dict(field='total' if clean(w)=='total' else 'subtotal',
                               box=tuple(w[:4]),words=[w[4]]))
    values=[]
    for w in words:
        try:value=format(money(w[4].strip()),'.2f')
        except ValueError:continue
        values.append(dict(value=value,box=tuple(w[:4]),text=w[4]))
    rows=[]
    for label in labels:
        candidates=sorted((v for v in values if v['box'][0]>=label['box'][2]-.1
                           and overlap(label['box'],v['box'])>=.5),key=lambda v:v['box'][0])
        rows.append(dict(**label,candidates=candidates,
            state='unresolved' if not candidates else 'single_candidate' if len(candidates)==1 else 'ambiguous',
            support='Text/box proximity only; header, connector, semantic and recognition verification absent'))
    return rows


def candidate_pairs(rows,*,nearest=False):
    return {(r['field'],v['value']) for r in rows
            for v in (r['candidates'][:1] if nearest else r['candidates'])}


def header_pairs(rows,words):
    """Conventional fixture-specific Amount Due column control, not generic semantics.

    Amount due need not equal invoice total in real paid/part-paid invoices.
    The fixture contract supplies that equivalence; do not deploy it universally.
    """
    headers=[];words=list(words)
    for w in words:
        if w[4].casefold()!='amount':continue
        for v in words:
            if v[4].casefold().strip(':')=='due' and v[0]>=w[2]-.1 and v[0]-w[2]<=35 and overlap(w,v)>=.5:
                headers.append(bbox([w,v]))
    return {(r['field'],v['value']) for r in rows if r['field']=='total' for v in r['candidates']
            if any(h[0]<=((v['box'][0]+v['box'][2])/2)<=h[2]
                   and 0<v['box'][1]-h[3]<8*(h[3]-h[1]) for h in headers)}
