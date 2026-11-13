"""Phase 2 reliability tests. All successful embeddings come from the actual model."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

import numpy as np
import pymupdf
import pytest

from knowledge_library.chunking import ChunkingConfig, chunk_page
from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.library import Library
from knowledge_library.pdf import PdfOptions, extract_page, open_pdf

pytestmark = pytest.mark.phase2
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/pdfs"


@pytest.fixture
def scratch():
    path = ROOT / ".cache/phase2-tests" / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture(scope="module")
def model():
    return EmbeddingGemma(device="cuda", batch_size=4)


def test_rotated_lecture_preserves_reading_order():
    with open_pdf(ROOT / "corpus/pdfs/mit-pumping-lemma.pdf") as doc:
        assert doc[17].rotation == 90
        page = extract_page(doc[17], PdfOptions())
        assert page["page_number"] == 18
        assert "Use Pigeonhole Principle" in page["text"]
        assert "Let L be a regular language" in page["text"]
        assert page["status"] == "ok"


def test_two_column_paper_keeps_coherent_text():
    with open_pdf(ROOT / "corpus/pdfs/bert.pdf") as doc:
        text = extract_page(doc[3], PdfOptions())["text"]
        assert "we mask 15% of all WordPiece" in text


def test_empty_and_scanned_pages_are_separate():
    with open_pdf(FIXTURES / "mixed.pdf") as doc:
        pages = [extract_page(page, PdfOptions()) for page in doc]
    assert [p["status"] for p in pages] == ["empty", "ok", "needs_ocr"]
    assert pages[2]["method"] == "native"
    assert pages[2]["text"] == ""
    assert pages[2]["ocr_confidence"] is None


def test_missing_ocr_language_data_is_reported(scratch):
    with open_pdf(FIXTURES / "scanned.pdf") as doc:
        page = extract_page(doc[0], PdfOptions(ocr=True, tessdata=str(scratch / "missing-tessdata")))
    assert page["status"] == "needs_ocr"
    assert any("ocr_failed" in warning for warning in page["warnings"])
    assert page["text"] == ""


def test_invalid_and_encrypted_pdf_errors():
    for name, phrase in (("malformed.pdf", "Cannot open PDF"), ("encrypted.pdf", "password")):
        with pytest.raises(ValueError, match=phrase):
            open_pdf(FIXTURES / name)


def test_bulk_cli_continues_after_malformed_pdf(scratch):
    root = scratch / "bulk-library"
    with Library(root) as lib:
        folder = lib.create_folder("Bulk")["id"]
    child = subprocess.run([sys.executable,"-m","knowledge_library","--library",str(root),"import",folder,
                            str(FIXTURES/"empty.pdf"),str(FIXTURES/"malformed.pdf"),str(FIXTURES/"empty.pdf")],
                           cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert child.returncode == 1
    outcomes = json.loads(child.stdout)
    assert [r["action"] for r in outcomes] == ["added","failed","unchanged"]
    assert "Cannot open PDF" in outcomes[1]["error"]


@pytest.mark.parametrize("size", [256, 512, 1024])
def test_token_chunks_preserve_unicode_and_coverage(size):
    embedder = EmbeddingGemma()
    text = ("Unicode café αβ and ∑ mathematics. A formal proof must preserve its assumptions.\n\n" * 150)
    chunks = list(chunk_page(text, embedder.tokenizer, ChunkingConfig(size, 64)))
    covered = np.zeros(len(text), dtype=bool)
    for chunk in chunks:
        assert chunk["text"] == text[chunk["char_start"]:chunk["char_end"]]
        assert 0 < embedder.token_count(chunk["text"]) <= size
        covered[chunk["char_start"]:chunk["char_end"]] = True
    assert len(chunks) > 1
    assert all(covered[i] for i, char in enumerate(text) if not char.isspace())
    assert embedder.stats["model_loads"] == 0


def test_real_index_search_isolation_restart_and_duplicates(scratch, model):
    root = scratch / "library"
    with Library(root, model) as lib:
        toc, dsp, empty = [lib.create_folder(name)["id"] for name in ("TOC", "DSP", "Empty")]
        imported = lib.import_pdf(FIXTURES / "native-unicode.pdf", toc)
        doc_id = imported["document"]["id"]
        calls = model.stats["document_texts_encoded"]
        assert imported["document"]["page_count"] == 2
        assert "café" in lib.page(doc_id, 1)["text"]
        assert lib.import_pdf(FIXTURES / "native-unicode.pdf", toc)["action"] == "unchanged"
        copied_name = scratch / "lecture notes [α] & review.pdf"
        shutil.copyfile(FIXTURES / "native-unicode.pdf", copied_name)
        assert lib.import_pdf(copied_name, toc)["action"] == "duplicate"
        cross_folder = lib.import_pdf(copied_name, dsp)
        assert cross_folder["reused_embeddings"] is True
        assert model.stats["document_texts_encoded"] == calls
        result = lib.search("How can a language be shown not to be regular?", folder_id=toc)
        assert result["results"][0]["document_id"] == doc_id
        assert result["results"][0]["page_number"] == 2
        assert all(hit["folder_id"] == toc for hit in result["results"])
        assert lib.search("language", folder_id=empty)["empty_reason"] == "empty_scope"
        assert len(lib.search("pumping lemma", mode="bm25")["results"]) == 2
        assert not lib.search("pumping lemma", min_score=1.)["results"]
        assert lib.verify()["passed"] is True
        assert model.stats["document_texts_encoded"] == calls
    # A fresh CLI process reads the persisted metadata/FTS without loading any model.
    process = subprocess.run([sys.executable, "-m", "knowledge_library", "--library", str(root),
                              "search", "pumping lemma", "--mode", "bm25"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["results"][0]["page_number"] == 2
    with Library(root, model) as reopened:
        assert len(reopened.documents()) == 2
        assert reopened.verify()["passed"] is True


def test_replace_move_delete_and_missing_source(scratch, model):
    source = scratch / "tracked.pdf"
    shutil.copyfile(FIXTURES / "replacement-old.pdf", source)
    with Library(scratch / "library", model) as lib:
        first, second = [lib.create_folder(n)["id"] for n in ("First", "Second")]
        doc_id = lib.import_pdf(source, first)["document"]["id"]
        old_hash = lib.document(doc_id)["sha256"]
        shutil.copyfile(FIXTURES / "replacement-new.pdf", source)
        update = lib.refresh(doc_id)
        assert update["action"] == "updated"
        assert update["document"]["id"] == doc_id
        assert update["document"]["sha256"] != old_hash
        assert "Josephson" in lib.search("Josephson junctions", mode="bm25")["results"][0]["passage"]
        assert not lib.search("nectarines", mode="bm25")["results"]
        encoded = model.stats["document_texts_encoded"]
        lib.move_document(doc_id, second)
        assert not lib.search("Josephson", folder_id=first)["results"]
        assert lib.search("Josephson", folder_id=second)["results"][0]["document_id"] == doc_id
        assert model.stats["document_texts_encoded"] == encoded
        lib.rename_folder(second, "Renamed")
        with pytest.raises(ValueError, match="contains documents"):
            lib.delete_folder(second)
        source.unlink()
        assert lib.sync()[0]["action"] == "source_missing"
        assert lib.search("Josephson", mode="bm25")["results"][0]["source_available"] is True
        lib.sync(remove_missing=True)
        assert not lib.documents()
        assert not lib.search("Josephson", mode="bm25")["results"]
        lib.delete_folder(second)


def test_partial_empty_and_failed_imports_do_not_invent_text(scratch, model):
    with Library(scratch / "library", model) as lib:
        folder = lib.create_folder("Reliability")["id"]
        for name, status, chunks in (("empty.pdf", "empty", 0), ("scanned.pdf", "needs_ocr", 0), ("mixed.pdf", "partial", 1)):
            result = lib.import_pdf(FIXTURES / name, folder)
            assert result["document"]["status"] == status
            assert result["document"]["chunk_count"] == chunks
        for name in ("malformed.pdf", "encrypted.pdf"):
            with pytest.raises(ValueError):
                lib.import_pdf(FIXTURES / name, folder)
        assert len(lib.documents()) == 3
        assert sum(j["status"] == "failed" for j in lib.jobs()) == 2
        assert lib.verify()["passed"] is True
        assert all(r["page_number"] == 2 for r in lib.search("sinusoidal frequencies")["results"])


def test_failed_inference_keeps_previous_index(scratch, model, monkeypatch):
    with Library(scratch / "library", model) as lib:
        folder = lib.create_folder("Atomic")["id"]
        original = lib.import_pdf(FIXTURES / "replacement-old.pdf", folder)["document"]
        def fail(*_):
            raise MemoryError("Injected allocation failure; no replacement embeddings supplied")
        monkeypatch.setattr(model, "documents", fail)
        with pytest.raises(MemoryError):
            lib.import_pdf(FIXTURES / "replacement-new.pdf", folder, document_id=original["id"])
        assert lib.document(original["id"])["sha256"] == original["sha256"]
        assert lib.search("nectarines", mode="bm25")["results"]
        assert lib.verify()["passed"] is True
        assert lib.jobs()[0]["status"] == "failed"


def test_sql_failure_rolls_back_deleted_old_chunks(scratch, model):
    with Library(scratch / "library", model) as lib:
        folder = lib.create_folder("Atomic SQL")["id"]
        original = lib.import_pdf(FIXTURES / "replacement-old.pdf", folder)["document"]
        with lib.db:
            lib.db.execute("CREATE TRIGGER injected BEFORE UPDATE ON documents BEGIN SELECT RAISE(ABORT,'injected SQL write failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected SQL"):
            lib.import_pdf(FIXTURES / "replacement-new.pdf", folder, document_id=original["id"])
        assert lib.document(original["id"])["sha256"] == original["sha256"]
        assert lib.search("nectarines", mode="bm25")["results"]
        assert lib.verify()["passed"] is True


def test_storage_guard_and_invalid_folder(scratch, model, monkeypatch):
    with Library(scratch / "library", model) as lib:
        folder = lib.create_folder("Storage")["id"]
        with pytest.raises(ValueError, match="Folder not found"):
            lib.import_pdf(FIXTURES / "empty.pdf", "invalid")
        with pytest.raises(ValueError):
            lib.create_folder("   ")
        with pytest.raises(ValueError):
            lib.search("  ")
        usage = shutil.disk_usage(scratch)
        monkeypatch.setattr("knowledge_library.library.shutil.disk_usage", lambda _: usage._replace(free=0))
        with pytest.raises(OSError, match="Insufficient free storage"):
            lib.import_pdf(FIXTURES / "empty.pdf", folder)
        assert not lib.documents()


def test_corrupt_vector_is_detected(scratch, model):
    with Library(scratch / "library", model) as lib:
        folder = lib.create_folder("Integrity")["id"]
        lib.import_pdf(FIXTURES / "replacement-old.pdf", folder)
        row = lib.db.execute("SELECT id,vector FROM chunks LIMIT 1").fetchone()
        damaged = bytearray(row["vector"])
        damaged[0] ^= 1
        with lib.db:
            lib.db.execute("UPDATE chunks SET vector=? WHERE id=?", (bytes(damaged), row["id"]))
        with pytest.raises(ValueError, match="checksum"):
            lib.search("orchards")
        assert lib.verify()["passed"] is False


def test_dead_index_job_is_marked_interrupted(scratch, model):
    root = scratch / "library"
    with Library(root, model) as lib:
        folder = lib.create_folder("Interrupted")["id"]
        lib.import_pdf(FIXTURES / "replacement-old.pdf", folder)
    code = """import os,sys,psutil
from knowledge_library.library import Library,now
with Library(sys.argv[1]) as lib:
    with lib.db:
        lib.db.execute('INSERT INTO index_attempts(id,folder_id,original_path,status,started_at,owner_pid,owner_created) VALUES(?,?,?,?,?,?,?)',
            ('abrupt-job',sys.argv[2],'fixture.pdf','indexing',now(),os.getpid(),psutil.Process().create_time()))
    os._exit(7)
"""
    child = subprocess.run([sys.executable, "-c", code, str(root), folder], cwd=ROOT, timeout=20)
    assert child.returncode == 7
    with Library(root, model) as reopened:
        job = next(j for j in reopened.jobs() if j["id"] == "abrupt-job")
        assert job["status"] == "interrupted"
        assert reopened.search("nectarines", mode="bm25")["results"]
