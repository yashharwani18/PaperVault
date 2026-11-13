"""R21 source-response metadata audit and ordinary qualification control.

No source truth, calibrated confidence or production behavior is established by
the control. Optional review records below are synthetic scoped assertions.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from knowledge_library.search_response import respond


class DB:
    def execute(self,*args):return self
    def fetchone(self):return {'format':'pdf'}


def qualify(hit,review=None):
    match=hit.get('amount_match',{})
    scope=dict(source_identity=hit.get('source_identity'),page_number=hit.get('page_number'),
               field=match.get('field'),value=match.get('value'),evidence=match.get('evidence'))
    # A document-wide checkbox is not a scoped observation of this exact field.
    scoped=bool(review and review.get('scope')==scope and review.get('checked') is True
                and all(v is not None for v in scope.values()) and hit.get('source_available') is True)
    return dict(scope=scope,match_kind='nearby' if match.get('approximate') else 'exact_indexed_literal',
        extraction_method=hit.get('extraction_method','unknown'),
        source_available=hit.get('source_available'),warnings=list(hit.get('warnings',[])),
        association_status='scoped_review_assertion' if scoped else 'unverified',
        qualification='Source and recognition correctness are not proved by numeric equality')


def run():
    base=dict(document_id='synthetic',chunk_id=1,source_identity='synthetic-revision:1',
        filename='synthetic.pdf',page_number=1,passage='SYNTHETIC INVOICE\nGrand Total: INR 13600.00\n',
        extraction_method='native',warnings=[],source_available=True,
        amount_match=dict(field='total',value='13600.00',currency='INR',evidence='Grand Total: INR 13600.00'),
        bill=dict(reviewed=False,amount='13600.00',source_page=1))
    variants=[]
    for name,changes in [('native',{}),
            ('ocr',dict(extraction_method='ocr',warnings=['ocr_confidence_unavailable_manual_review_required'])),
            ('partial_ocr',dict(extraction_method='ocr',warnings=['embedded_images_ocr_with_native_text',
                'ocr_confidence_unavailable_manual_review_required'])),
            ('document_reviewed',dict(bill=dict(reviewed=True,amount='13600.00',source_page=1))),
            ('reviewed_other_amount',dict(bill=dict(reviewed=True,amount='13680.00',source_page=1))),
            ('reviewed_other_page',dict(bill=dict(reviewed=True,amount='13600.00',source_page=2))),
            ('source_unavailable',dict(source_available=False))]:
        hit=copy.deepcopy(base);hit.update(changes);captured=[]
        def generate(system,payload,schema,**kwargs):
            captured.append(dict(system=system,payload=json.loads(payload),schema=schema))
            return {'choice':1},0.
        result=dict(mode='bill_fields',results=[hit],note='Check the original, especially for OCR.')
        response=respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=generate),'total 13600',result)
        qualified=qualify(hit)
        assert qualified['association_status']=='unverified'
        assert qualified['warnings']==hit['warnings']
        variants.append(dict(case=name,hit=hit,model_input=captured[0],response=response,
                             control=qualified,input_note=result['note']))
    first=variants[0]
    for case in variants:
        assert case['model_input']==first['model_input']
        assert case['response']==first['response']
    scope=qualify(base)['scope'];review=dict(scope=scope,checked=True)
    assert qualify(base,review)['association_status']=='scoped_review_assertion'
    review_checks=[]
    for key,value in [('source_identity','synthetic-revision:2'),('page_number',2),('field','subtotal'),
                      ('value','13680.00'),('evidence','Total: INR 13600.00')]:
        changed=copy.deepcopy(review);changed['scope'][key]=value
        result=qualify(base,changed)
        assert result['association_status']=='unverified'
        review_checks.append(dict(changed=key,result=result))
    assert qualify({**base,'source_available':False},review)['association_status']=='unverified'
    report=dict(date='2026-10-21',variants=variants,scoped_review_control=qualify(base,review),
        mismatched_review_controls=review_checks,model_calls=0,input_capture_calls=len(variants),
        limits=['Synthetic result objects, not OCR output or live invoice retrieval',
                'Production respond executed with source-choice stub; no Qwen accuracy measured',
                'Response-object qualifier loss does not imply the entire UI hides all warnings',
                'Existing result note, match reasons and viewer OCR cue are separate and remain available',
                'Scoped review is a supplied assertion, not proof that a human checked or that the source is true',
                'Ordinary metadata propagation and exact scope checks, not a new invention or production change'])
    root=Path(__file__).resolve().parents[2]
    (root/'results/patent-r21-response-qualifiers.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(variants=len(variants),identical_response_objects=True,
        identical_model_inputs=True,scoped_mismatches_rejected=len(review_checks),model_calls=0),indent=2))


if __name__=='__main__':run()
