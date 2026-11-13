import numpy as np
import pytest

from research.patent_candidate.engine import EvidenceSearch
from research.patent_candidate.exact_view_baseline import ExactView
from research.patent_candidate.test_engine import record,finish,ids


@pytest.mark.parametrize('seed',range(12))
def test_standard_exact_view_handles_mutations_and_predicate_entry(tmp_path,seed):
    rng=np.random.default_rng(seed)
    engine=EvidenceSearch(tmp_path/'baseline.sqlite3',32)
    for i in range(40):
        engine.replace_document(str(i),[record(str(i),rng.normal(size=32),
            amount='100' if i%2 else '200')])
    q=rng.normal(size=32)
    pred={'field':'subtotal','value':'100','folder':'A'}
    baseline=ExactView(engine)
    view=baseline.start(q,predicate=pred,k=5)
    candidate=engine.start(q,predicate=pred,k=5)
    for i in range(20):
        doc=str(int(rng.integers(0,40)))
        if i%4==0:engine.replace_document(doc,[])
        else:engine.replace_document(doc,[record(doc,rng.normal(size=32),
            amount='100' if i%3 else '200',folder='B' if i%5==0 else 'A')])
        got=baseline.advance(view)
        assert ids(got)==ids(finish(engine,candidate))==engine.exhaustive(q,pred,k=5)
    engine.close()
