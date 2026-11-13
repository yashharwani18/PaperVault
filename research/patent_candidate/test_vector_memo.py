"""Real PDF extraction, synthetic vector arithmetic: not neural accuracy tests."""
from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace

import numpy as np
import pymupdf
import pytest

from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.library import Library
from knowledge_library.pdf import PdfOptions
from research.patent_candidate.vector_memo import VectorMemo


class Tokenizer:
    def encode(self, text, add_special_tokens=False):
        offsets = [m.span() for m in re.finditer(r"\S+", text)]
        return SimpleNamespace(ids=list(range(len(offsets))), offsets=offsets)


class SyntheticEmbedder:
    """Deterministic test double; never called a model performance measurement."""
    dimensions = 16
    batch_size = 4
    dtype = "float32"
    tokenizer = Tokenizer()
    format_document = staticmethod(EmbeddingGemma.format_document)

    def __init__(self, revision="r1"):
        self.signature = dict(model_id="synthetic-hash-not-neural", revision=revision,
                              configuration_version="memo-probe-v1", dimensions=self.dimensions)
        self.stats = dict(document_texts_encoded=0)
        self.fail = False

    def load(self):
        return self

    def documents(self, title, texts):
        if self.fail:
            raise RuntimeError("Injected inference failure")
        self.stats["document_texts_encoded"] += len(texts)
        rows = []
        for text in texts:
            material = self.signature["revision"] + self.format_document(title, text)
            vector = np.frombuffer(hashlib.sha256(material.encode()).digest(), dtype="<u2").astype("<f4")
            vector /= np.linalg.norm(vector)
            rows.append(vector)
        return np.stack(rows)


def make_pdf(path, numbers):
    with pymupdf.open() as doc:
        for number in numbers:
            page = doc.new_page()
            page.insert_text((60, 60), f"Synthetic invoice {number}\nSubtotal {1000+number}.00\nTotal {1000+number}.00\nReference fixture only.")
        doc.save(path)


def snapshot(lib):
    return [tuple(r) for r in lib.db.execute("""SELECT page_number,chunk_index,title,text,char_start,char_end,
        token_count,vector,vector_sha256 FROM chunks ORDER BY chunk_index""")]


@pytest.mark.parametrize("numbers,expected_new", [
    (list(range(19))+[88], 1),
    (list(reversed(range(20))), 0),
    (list(range(19)), 0),
    ([55]+list(range(20)), 1),
])
def test_changed_pages_and_reordering_match_full_rebuild(tmp_path, numbers, expected_new):
    old, new = tmp_path/"old.pdf", tmp_path/"new.pdf"
    make_pdf(old, range(20)); make_pdf(new, numbers)
    raw = SyntheticEmbedder(); memo = VectorMemo(raw, tmp_path/"memo.sqlite3")
    try:
        with Library(tmp_path/"reuse", memo) as reuse, Library(tmp_path/"full", SyntheticEmbedder()) as full:
            rf, ff = reuse.create_folder("Test")["id"], full.create_folder("Test")["id"]
            prior = reuse.import_pdf(old, rf, title="Fixture")["document"]
            result = reuse.import_pdf(new, rf, document_id=prior["id"], title="Fixture")
            full.import_pdf(new, ff, title="Fixture")
            assert result["document_embeddings_generated"] == expected_new
            assert snapshot(reuse) == snapshot(full)
            assert result["document"]["version"] == 2
            assert result["document"]["sha256"] != prior["sha256"]
    finally:
        memo.close()


def test_title_is_part_of_exact_model_input(tmp_path):
    memo = VectorMemo(SyntheticEmbedder(), tmp_path/"memo.sqlite3")
    try:
        a = memo.documents("Invoice", ["Total 29074"])
        b = memo.documents("College", ["Total 29074"])
        assert memo.misses == 2 and not np.array_equal(a, b)
        assert np.array_equal(memo.documents(" Invoice ", ["Total 29074"]), a)
        assert memo.hits == 1  # Formatter collapses whitespace in metadata.
    finally:
        memo.close()


def test_revision_changes_do_not_reuse_vectors(tmp_path):
    path = tmp_path/"memo.sqlite3"
    memo = VectorMemo(SyntheticEmbedder("r1"), path)
    a = memo.documents("Fixture", ["Total 29074"]); memo.close()
    memo = VectorMemo(SyntheticEmbedder("r2"), path)
    try:
        b = memo.documents("Fixture", ["Total 29074"])
        assert memo.hits == 0 and memo.misses == 1 and not np.array_equal(a, b)
    finally:
        memo.close()


def test_corrupted_cache_entry_is_recomputed(tmp_path):
    memo = VectorMemo(SyntheticEmbedder(), tmp_path/"memo.sqlite3")
    try:
        expected = memo.documents("Fixture", ["Total 29074"])
        with memo.cache:
            memo.cache.execute("UPDATE memo SET vector=?", (b"invalid",))
        assert np.array_equal(memo.documents("Fixture", ["Total 29074"]), expected)
        assert memo.corruptions == 1 and memo.misses == 2
    finally:
        memo.close()


def test_interrupted_replacement_keeps_committed_source(tmp_path):
    a,b = tmp_path/"a.pdf",tmp_path/"b.pdf"
    make_pdf(a,[1,2]);make_pdf(b,[1,88])
    raw=SyntheticEmbedder();memo=VectorMemo(raw,tmp_path/"memo.sqlite3")
    try:
        with Library(tmp_path/"library",memo) as lib:
            folder=lib.create_folder("Test")["id"]
            prior=lib.import_pdf(a,folder,title="Fixture")["document"]
            before=snapshot(lib);raw.fail=True
            with pytest.raises(RuntimeError,match="Injected"):
                lib.import_pdf(b,folder,document_id=prior["id"],title="Fixture")
            assert lib.document(prior["id"])["version"]==prior["version"]
            assert snapshot(lib)==before
    finally:
        memo.close()


def test_reextract_options_never_reuse_page_text(tmp_path):
    path=tmp_path/"fixture.pdf";make_pdf(path,[1,2])
    memo=VectorMemo(SyntheticEmbedder(),tmp_path/"memo.sqlite3")
    try:
        with Library(tmp_path/"library",memo) as lib:
            folder=lib.create_folder("Test")["id"]
            first=lib.import_pdf(path,folder,title="Fixture",pdf_options=PdfOptions(tables=False))["document"]
            pages=[]
            result=lib.import_pdf(path,folder,document_id=first["id"],title="Fixture",pdf_options=PdfOptions(tables=True),progress=lambda p:pages.append(p))
            assert result["document"]["version"]==2
            assert {p["page"] for p in pages if p.get("stage")=="reading"}=={1,2}
            assert result["document_embeddings_generated"]==0
    finally:
        memo.close()


def test_identical_pixels_are_not_identical_native_pdf_text(tmp_path):
    """An OCR pixel cache cannot be used as a whole-page extraction cache."""
    from knowledge_library.pdf import extract_page
    hashes,texts=[],[]
    for value in (13600,13900):
        path=tmp_path/f'hidden-{value}.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page()
            page.insert_text((60,60),'Synthetic visual identity fixture. Visible content is unchanged.')
            page.insert_text((60,100),f'Total {value}.00. Hidden searchable layer for a controlled test.',render_mode=3)
            doc.save(path)
        with pymupdf.open(path) as doc:
            hashes.append(hashlib.sha256(doc[0].get_pixmap().samples).hexdigest())
            texts.append(extract_page(doc[0],PdfOptions(tables=False))['text'])
    assert hashes[0]==hashes[1]
    assert texts[0]!=texts[1]
    assert '13600' in texts[0] and '13900' in texts[1]
