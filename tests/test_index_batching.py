"""Cross-page batching must preserve source identity and atomic replacement."""
import pymupdf
import pytest

from knowledge_library.library import Library
from knowledge_library.pdf import PdfOptions
from tests.test_research_implementation import CountingEncoder


def write_pages(path, version):
    with pymupdf.open() as pdf:
        for number in range(9):
            pdf.new_page().insert_text((40, 60), f'Page {number + 1}: {version} material about digital signal processing.')
        pdf.save(path)


def test_batches_span_pages_and_keep_exact_page_offsets(tmp_path):
    path = tmp_path / 'notes.pdf'
    write_pages(path, 'Original')
    model = CountingEncoder()
    original = model.documents
    batches = []
    def documents(title, texts):
        batches.append(list(texts))
        return original(title, texts)
    model.documents = documents
    with Library(tmp_path / 'library', model) as lib:
        folder = lib.create_folder('Notes')['id']
        result = lib.import_pdf(path, folder, pdf_options=PdfOptions(tables=False))
        assert [len(b) for b in batches] == [4, 4, 1]
        rows = lib.db.execute('SELECT * FROM chunks ORDER BY chunk_index').fetchall()
        assert [r['page_number'] for r in rows] == list(range(1, 10))
        assert [r['text'] for r in rows] == [text for batch in batches for text in batch]
        for row in rows:
            text = lib.page(result['document']['id'], row['page_number'])['text']
            assert text[row['char_start']:row['char_end']] == row['text']
        assert lib.verify()['passed']


def test_interrupted_later_batch_retains_previous_committed_document(tmp_path):
    path = tmp_path / 'notes.pdf'
    write_pages(path, 'Original')
    model = CountingEncoder()
    with Library(tmp_path / 'library', model) as lib:
        folder = lib.create_folder('Notes')['id']
        doc = lib.import_pdf(path, folder)['document']
        before = [tuple(r) for r in lib.db.execute('SELECT * FROM chunks ORDER BY id')]
        write_pages(path, 'Revised')
        original = model.documents
        calls = 0
        def interrupted(title, texts):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise InterruptedError('Simulated shutdown at next embedding batch')
            return original(title, texts)
        model.documents = interrupted
        with pytest.raises(InterruptedError):
            lib.import_pdf(path, folder)
        assert calls == 2
        assert lib.document(doc['id'])['version'] == doc['version']
        assert [tuple(r) for r in lib.db.execute('SELECT * FROM chunks ORDER BY id')] == before
        assert not list((lib.root / 'staging').iterdir())
        assert lib.verify()['passed']
