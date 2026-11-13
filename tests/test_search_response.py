from types import SimpleNamespace
from knowledge_library.search_response import respond,hinglish


class DB:
    def execute(self,*args):return self
    def fetchone(self):return {'format':'pptx'}


def hit():
    return dict(document_id='d1',chunk_id=1,source_identity='immutable-version',filename='Theory.pptx',page_number=3,
                passage='Pumping lemma: every regular language satisfies the pumping property.')


def test_response_cites_only_real_source_and_slide():
    calls=[]
    def generate(*args,**kwargs):calls.append(args);return {'choice':1},.2
    response=respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=generate),'bhai pumping lemma kis ppt mein hai',dict(mode='semantic',results=[hit()]))
    citation=response['citations'][0]
    assert len(calls)==1 and response['method']=='qwen_source_selection'
    assert citation['location']=='Slide 3' and citation['filename']=='Theory.pptx'
    assert citation['excerpt'] in hit()['passage'] and citation['source_identity']=='immutable-version'
    assert 'slide 3' in response['text']


def test_no_results_still_use_qwen_and_no_invented_answer():
    calls=[]
    def generate(*args,**kwargs):calls.append(args);return {'choice':0},.1
    model=SimpleNamespace(generate=generate);lib=SimpleNamespace(db=DB())
    response=respond(lib,model,'find nonexistent claim',dict(mode='semantic',results=[]))
    assert len(calls)==1 and response['citations']==[] and 'couldn’t find' in response['text']
    response=respond(lib,model,'unknown',dict(mode='semantic',results=[hit()],below_cutoff=True))
    assert not response['citations'] and 'couldn’t confirm' in response['text']


def test_invalid_model_choice_cannot_invent_citation():
    response=respond(SimpleNamespace(db=DB()),SimpleNamespace(generate=lambda *args,**kwargs:({'choice':999,'answer':'invented'},.1)),
        'question',dict(mode='semantic',results=[hit()]))
    assert not response['citations'] and response['method']=='source_fallback' and response['limitation']


def test_english_me_is_not_hindi_and_approximate_hindi_is_recognized():
    assert not hinglish('show me the bill where its 29000')
    assert not hinglish('tell me about pumping lemma')
    assert hinglish('lagbhag 29000 ka bill dikhao')
