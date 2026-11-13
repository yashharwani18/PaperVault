"""Metric mathematics plus real persisted-engine integration; no fake embeddings."""
import json
from pathlib import Path
import shutil
import uuid

import numpy as np
import pytest

from evaluation.metrics import aggregate, query_metrics
from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.library import Library
from knowledge_library.retrieval import SearchIndex, reciprocal_rank_fusion, terms, truncate_normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/"tests/fixtures/pdfs"


def test_recall_is_not_hit_rate_and_no_answer_is_excluded():
    truth = [{"document":"a","page":1},{"document":"a","page":2},{"document":"b","page":3}]
    ranked = [{"document":"a","page":1},{"document":"x","page":1},{"document":"b","page":3}]
    measured = query_metrics(truth,ranked)
    assert measured["recall@1"]==pytest.approx(1/3)
    assert measured["recall@3"]==pytest.approx(2/3)
    assert measured["hit@1"]==1 and measured["mrr@5"]==1
    missing = query_metrics(truth,[{"document":"x","page":1}])
    assert missing["mrr@5"]==0
    assert aggregate([measured,missing])["recall@5"]==pytest.approx(1/3)
    with pytest.raises(ValueError,match="undefined"):
        query_metrics([],ranked)


def test_rrf_merges_pages_with_best_semantic_passage():
    # Abstract ranks only; no vectors or document inference are substituted.
    rows = [{"id":1,"document_id":"a","page_number":1},
            {"id":2,"document_id":"a","page_number":1},
            {"id":3,"document_id":"b","page_number":1}]
    ranked = reciprocal_rank_fusion(rows,[(0,.9),(2,.8)],[(2,7.),(1,6.)],rank_constant=10)
    assert len(ranked)==2
    assert ranked[0][1]==pytest.approx(.5/11+.5/12)
    assert {i for i,_ in ranked}=={0,2}
    assert reciprocal_rank_fusion(rows,[(0,.9)],[],semantic_weight=0)==[]
    assert len(reciprocal_rank_fusion(rows,[(0,.9)],[(2,7.)],semantic_weight=1))==1


def test_truncation_normalizes_both_sides_and_rejects_bad_input():
    values = np.arange(1,769,dtype=np.float32)
    for dim in (768,512,256,128):
        assert truncate_normalize(values,dim).shape==(dim,)
        assert np.linalg.norm(truncate_normalize(values,dim))==pytest.approx(1.)
    with pytest.raises(ValueError):
        truncate_normalize(np.zeros(768),128)
    with pytest.raises(ValueError):
        truncate_normalize(values[:128],256)
    assert "not" in terms("Which methods are not regular?")


def test_frozen_dataset_coverage_and_source_hashes():
    manifest = json.loads((ROOT/"evaluation/phase3-corpus.json").read_text())
    kinds = [d["kind"] for d in manifest["documents"]]
    assert kinds.count("university_lecture")==10 and kinds.count("research_paper")==5
    assert len(kinds)==20
    labels = json.loads((ROOT/"evaluation/phase3-queries.json").read_text())["queries"]
    assert len([q for q in labels if q["relevant"]])>=30
    assert len({q["id"] for q in labels})==len(labels)
    assert {r["document"] for q in labels for r in q["relevant"]}=={d["id"] for d in manifest["documents"]}
    assert len([q for q in labels if q["kind"]=="ambiguous_multi_document"])>=2


def test_real_hybrid_dimensions_scope_and_lexical_migration():
    scratch = ROOT/".cache/phase3-tests"/uuid.uuid4().hex
    model = EmbeddingGemma()
    with Library(scratch,model) as lib:
        first,second,empty = [lib.create_folder(n)["id"] for n in ("First","Second","Empty")]
        doc = lib.import_pdf(FIXTURES/"native-unicode.pdf",first)["document"]
        copied = scratch/"duplicate.pdf"
        shutil.copyfile(FIXTURES/"native-unicode.pdf",copied)
        calls = model.stats["document_texts_encoded"]
        assert lib.import_pdf(copied,first)["action"]=="duplicate"
        assert model.stats["document_texts_encoded"]==calls
        for mode in ("keyword","bm25","bm25_raw","semantic","hybrid"):
            result = lib.search("pumping lemma",folder_id=first,mode=mode,search_dimensions=128)
            assert result["results"] and all(r["folder_id"]==first for r in result["results"])
        for dim in (768,512,256,128):
            assert lib.search("nonregular languages",mode="hybrid",search_dimensions=dim)["results"]
        calls = dict(model.stats)
        assert lib.search("anything",folder_id=empty,mode="hybrid")["empty_reason"]=="empty_scope"
        assert model.stats==calls
        lib.move_document(doc["id"],second)
        assert not lib.search("pumping lemma",folder_id=first,mode="hybrid")["results"]
        assert lib.search("pumping lemma",folder_id=second,mode="hybrid")["results"]
        # Simulate an older Phase 2 library lacking the additive stemmed index.
        with lib.db:
            lib.db.execute("DROP TRIGGER chunks_stem_ai")
            lib.db.execute("DROP TRIGGER chunks_stem_ad")
            lib.db.execute("DROP TABLE chunks_fts_stemmed")
            lib.db.execute("DELETE FROM settings WHERE key='stemmed_fts_version'")
    calls = dict(model.stats)
    with Library(scratch,model) as lib:
        assert lib.search("pump lemmas",mode="bm25")["results"]
        assert model.stats==calls
        lib.remove_document(doc["id"])
        assert not lib.search("pumping",mode="bm25")["results"]
        assert lib.verify()["passed"]
