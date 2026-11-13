"""Source-backed tools for the desktop app."""
import json
from pathlib import Path
from pydantic import BaseModel,Field
from . import workspace_features as features


class CompareBody(BaseModel):
    document_ids:list[str]=Field(min_length=2,max_length=5)
    query:str=Field(default='',max_length=300)


class ProcessingBody(BaseModel):
    paused:bool
    charging_only:bool|None=None


def install(app,desktop):
    @app.get('/api/workspace')
    def workspace():
        import psutil
        with desktop.lib() as lib:
            return dict(linked_folders=features.linked_folders(lib),duplicates=features.duplicate_report(lib),
                processing=dict(**desktop.processing_status(),search_priority=True,process_rss_bytes=psutil.Process().memory_info().rss),
                voice=dict(strategy='android_on_device',available=False,note='Voice requires the Android app and supported on-device languages. This PC app uses typed search. No cloud speech fallback.'),
                models=dict(embedding=desktop.model.signature,query=desktop.interpreter.status()))

    @app.post('/api/linked-folders/rebuild')
    async def rebuild():return await desktop.work(features.rebuild_links)

    @app.post('/api/processing')
    def processing(body:ProcessingBody):
        if body.charging_only is not None:
            if body.charging_only and not desktop.processing_status()['battery_available']:raise ValueError('Battery status is unavailable on this PC. Charging-only mode cannot be enabled.')
            with desktop.lib() as lib:
                with lib.db:lib.db.execute('INSERT OR REPLACE INTO workspace_settings VALUES(?,?)',('charging_only',json.dumps(body.charging_only)))
            desktop.charging_only=body.charging_only
        (desktop.indexing_allowed.clear if body.paused else desktop.indexing_allowed.set)()
        return dict(paused=body.paused,note='Applies at the next page or embedding-batch boundary. Current conversion/OCR/inference may finish first.')

    @app.post('/api/verify-backup-readiness')
    async def verify():
        desktop.require_idle()
        return await desktop.work(lambda lib:lib.verify())

    @app.post('/api/documents/{document_id}/bill/undo')
    async def undo(document_id:str):
        return await desktop.work(lambda lib:features.undo_correction(lib,document_id))

    @app.get('/api/documents/{document_id}/checks')
    async def checks(document_id:str):
        def read(lib):
            lib.document(document_id)
            history=[dict(r) for r in lib.db.execute('SELECT id,created_at,source_sha256 FROM bill_history WHERE document_id=? ORDER BY created_at DESC',(document_id,))]
            return dict(arithmetic=features.arithmetic(lib,document_id),history=history)
        return await desktop.work(read)

    @app.get('/api/documents/{document_id}/tables')
    async def tables(document_id:str,page:int=1,query:str=''):
        if page<1 or len(query)>300:raise ValueError('Choose a valid page and a short table query.')
        def read(lib):
            import pymupdf
            doc=lib.document(document_id)
            if doc.get('preview_kind')=='text':raise ValueError('PDF layout tables are unavailable for native text; use its sheet/row source view.')
            if page>doc['page_count']:raise ValueError('Page is outside the document.')
            with pymupdf.open(lib.root/doc['managed_path']) as pdf:
                source=pdf[page-1];found=source.find_tables()
                results=[]
                for table in found.tables[:20]:
                    rows=table.extract()[:1000]
                    if query:rows=[r for r in rows if all(w in ' '.join(c or '' for c in r).casefold() for w in query.casefold().split())]
                    if rows:results.append(dict(rows=rows,bbox=list(table.bbox),page=page))
            return dict(tables=results,note='Rows detected from the original PDF layout. Image-only tables need OCR/layout review; merged cells may be incomplete.')
        return await desktop.work(read)

    @app.post('/api/compare')
    async def compare(body:CompareBody):
        def read(lib):
            from .bills import get
            ids=list(dict.fromkeys(body.document_ids))
            if len(ids)<2:raise ValueError('Choose at least two different documents.')
            result=[]
            for key in ids:
                doc=lib.document(key);bill=get(lib,key)
                from .bill_amounts import source_amounts
                amounts=[]
                for page in lib.db.execute('SELECT page_number,text FROM pages WHERE document_id=? ORDER BY page_number LIMIT 20',(key,)):
                    amounts.extend(dict(a,page_number=page['page_number']) for a in source_amounts(page['text']))
                # Keyword retrieval deliberately avoids loading the embedding model.
                hits=lib.search(body.query,document_id=key,mode='keyword',top_k=3)['results'] if body.query.strip() else []
                result.append(dict(document=doc,bill=bill,source_amounts=amounts[:30],passages=hits,checks=features.arithmetic(lib,key)))
            words=[set(features.terms(d['document']['title']+' '+' '.join(h['passage'] for h in d['passages']))) for d in result]
            return dict(documents=result,shared_terms=sorted(set.intersection(*words))[:20],
                note='Comparison shows recorded fields and literal matching passages per document. Missing fields remain unknown; this is not a generated explanation.')
        return await desktop.search_work(read)

    @app.get('/api/documents/{document_id}/highlight')
    async def highlight(document_id:str,page:int=1,text:str=''):
        if len(text)>1000 or page<1:raise ValueError('Invalid highlight request.')
        def read(lib):
            import pymupdf
            doc=lib.document(document_id)
            if doc.get('preview_kind')=='text':raise ValueError('PDF highlights are unavailable for native text; use its source location.')
            if page>doc['page_count']:raise ValueError('Page is outside the document.')
            boxes=[]
            with pymupdf.open(lib.root/doc['managed_path']) as pdf:
                source=pdf[page-1]
                candidates=[text.strip()]
                if '\n' in text:candidates.extend(line.strip() for line in text.splitlines() if line.strip())
                for candidate in candidates[:12]:
                    matches=source.search_for(candidate)
                    for box in matches:
                        box=box*source.rotation_matrix
                        boxes.append([box.x0/source.rect.width,box.y0/source.rect.height,box.width/source.rect.width,box.height/source.rect.height])
                    if matches:break
            return dict(boxes=boxes[:60],page=page,note='Literal PDF text highlights. OCR-only text may not have native coordinates.')
        return await desktop.work(read)
