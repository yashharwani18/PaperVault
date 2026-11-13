"""On-demand source page rasters. Never persist PDFs or rendered pages to disk."""
from collections import OrderedDict
from difflib import SequenceMatcher
import math
import re
import threading

from fastapi import HTTPException, Query
from fastapi.responses import Response
import pymupdf


def tokens(text):
    return re.findall(r'\w+',text.casefold())


def passage_boxes(words, passage):
    """Match indexed words, including OCR geometry, to the retrieved passage."""
    page_tokens=[];positions=[]
    for index,word in enumerate(words):
        if len(word)<5:continue
        for token in tokens(str(word[4])):
            page_tokens.append(token);positions.append(index)
    wanted=tokens(passage)
    if not wanted:return []
    selected=set()
    for block in SequenceMatcher(None,page_tokens,wanted,autojunk=False).get_matching_blocks():
        if block.size>=2 or (block.size==1 and len(wanted)==1 and len(wanted[0])>=5):
            selected.update(positions[block.a:block.a+block.size])
    boxes=[]
    for index in sorted(selected):
        word=words[index]
        box=[float(n) for n in word[:4]]
        if all(math.isfinite(n) for n in box) and box[2]>box[0] and box[3]>box[1]:boxes.append(box)
    return boxes


def install(app,desktop):
    # PyMuPDF access is serialized, off the model/search executor. Bound RAM,
    # and verify originals before consulting the cache, including cache hits.
    render_lock=threading.Lock()
    cache=OrderedDict()
    cache_bytes=0

    @app.get('/api/documents/{document_id}/preview')
    def preview(document_id:str,page:int=Query(ge=1),chunk_id:int=Query(ge=1),revision:str=Query(max_length=64)):
        nonlocal cache_bytes
        with desktop.lib() as lib:
            try:doc=lib.document(document_id)
            except ValueError:raise HTTPException(404,'Document is no longer in the library.')
            if doc.get('preview_kind')=='text':raise HTTPException(400,'Native text uses a source-unit preview, not a PDF raster.')
            if doc['sha256']!=revision:raise HTTPException(409,'Source changed. Run search again.')
            chunk=lib.db.execute('SELECT * FROM chunks WHERE id=? AND document_id=? AND page_number=?',
                                 (chunk_id,document_id,page)).fetchone()
            if chunk is None:raise HTTPException(404,'This result does not belong to the requested page. Run search again.')
            try:path=lib.source_path(doc,verify=True)
            except FileNotFoundError:raise HTTPException(404,'Original PDF is unavailable. Reconnect its folder to preview it.')
            except ValueError:raise HTTPException(409,'Original PDF changed. Refresh its index and search again.')
            evidence=lib.page(document_id,page)['evidence']
            passage=chunk['text']
        signature=path.stat()
        key=(str(path),signature.st_size,signature.st_mtime_ns,signature.st_ctime_ns,revision,page,chunk_id)
        with render_lock:
            if key in cache:
                png,headers=cache.pop(key);cache[key]=(png,headers)
            else:
                with pymupdf.open(path) as pdf:
                    source=pdf[page-1]
                    words=evidence.get('words') or source.get_text('words')
                    boxes=passage_boxes(words,passage)
                    bounds=source.rect*source.derotation_matrix
                    visible=[]
                    for box in boxes:
                        rect=pymupdf.Rect(box)&bounds
                        if not rect.is_empty:
                            source.draw_rect(rect,color=None,fill=(1,.84,.12),fill_opacity=.34,overlay=True)
                            visible.append(rect)
                    scale=min(1400/max(1,source.rect.width),math.sqrt(3_000_000/max(1,source.rect.get_area())))
                    raster=source.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                    png=raster.tobytes('png')
                    headers={'X-Highlight-Count':str(len(visible)),'X-Page-Width':str(raster.width),
                             'X-Page-Height':str(raster.height),'Cache-Control':'no-store'}
                # A source changed while rendering must never masquerade as indexed evidence.
                after=path.stat()
                if (after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(signature.st_size,signature.st_mtime_ns,signature.st_ctime_ns):
                    raise HTTPException(409,'Original PDF changed while rendering. Run search again after indexing.')
                if len(png)<=32*1024*1024:
                    cache[key]=(png,headers);cache_bytes+=len(png)
                    while len(cache)>12 or cache_bytes>32*1024*1024:
                        _,(removed,_)=cache.popitem(last=False);cache_bytes-=len(removed)
        return Response(png,media_type='image/png',headers=headers)
