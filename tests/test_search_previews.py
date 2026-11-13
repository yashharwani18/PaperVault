import hashlib
from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pymupdf
import pytest
from knowledge_library.library import Library
from tests.test_research_implementation import CountingEncoder


@pytest.fixture
def preview(tmp_path):
    from knowledge_library.search_previews import install
    source=tmp_path/'notes.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40,60),'Digital signal processing uses filters and convolution.')
        pdf.new_page().insert_text((40,60),'Another page without the matching passage.')
        pdf.save(source)
    with Library(tmp_path/'library',CountingEncoder()) as lib:
        doc=lib.import_pdf(source,lib.create_folder('Notes')['id'],retain_source=False)['document']
        chunk=dict(lib.db.execute('SELECT * FROM chunks WHERE document_id=? AND page_number=1',(doc['id'],)).fetchone())
    class Desktop:
        @contextmanager
        def lib(self):
            with Library(tmp_path/'library',CountingEncoder()) as lib:yield lib
    app=FastAPI();install(app,Desktop())
    with TestClient(app) as client:
        yield client,doc,chunk,source


def test_preview_is_actual_highlighted_page_without_modifying_or_copying_pdf(preview):
    client,doc,chunk,source=preview
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    response=client.get(f"/api/documents/{doc['id']}/preview",params=dict(page=1,chunk_id=chunk['id'],revision=doc['sha256']))
    assert response.status_code==200,response.text
    assert response.headers['content-type']=='image/png'
    assert int(response.headers['x-highlight-count'])>0
    image=pymupdf.Pixmap(response.content)
    assert image.width>=1000 and image.height>image.width
    # Yellow pixels prove highlight is present in the returned raster.
    samples=image.samples
    assert any(samples[i]>220 and samples[i+1]>190 and samples[i+2]<180 for i in range(0,len(samples),image.n))
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    assert not list((source.parent/'library/files').glob('*.pdf'))


def test_preview_rejects_wrong_chunk_page_and_stale_or_missing_original(preview):
    client,doc,chunk,source=preview
    url=f"/api/documents/{doc['id']}/preview"
    params=dict(page=1,chunk_id=chunk['id'],revision=doc['sha256'])
    assert client.get(url,params={**params,'page':2}).status_code==404
    assert client.get(url,params={**params,'revision':'stale'}).status_code==409
    assert client.get(url,params={**params,'chunk_id':999999}).status_code==404
    assert client.get(url,params=params).status_code==200
    source.write_bytes(b'changed source')
    assert client.get(url,params=params).status_code==409  # Even after caching.
    source.unlink()
    assert client.get(url,params=params).status_code==404


def test_highlight_uses_ocr_geometry_and_does_not_highlight_unrelated_words():
    from knowledge_library.search_previews import passage_boxes
    words=[[10,10,40,20,'Digital',0,0,0],[45,10,70,20,'signal',0,0,1],
           [75,10,110,20,'processing',0,0,2],[10,30,40,40,'Unrelated',0,1,0]]
    boxes=passage_boxes(words,'Digital signal processing')
    assert boxes and all(box[1]==10 for box in boxes)
    assert not passage_boxes(words,'Completely different content')
