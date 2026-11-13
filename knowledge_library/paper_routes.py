"""Local, editable bibliographic references for indexed documents."""
from pydantic import BaseModel,Field,ConfigDict
from . import papers


class ReferenceBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    item:dict
    reviewed:bool=True
    source_sha256:str|None=Field(default=None,max_length=64)


def install(app,desktop):
    @app.get('/api/documents/{document_id}/reference')
    def reference(document_id:str):
        with desktop.lib() as lib:return papers.reference(lib,document_id)

    @app.put('/api/documents/{document_id}/reference')
    async def save(document_id:str,body:ReferenceBody):
        return await desktop.work(lambda lib:papers.save_reference(lib,document_id,body.item,body.reviewed,body.source_sha256))

    @app.post('/api/documents/{document_id}/reference/reset')
    async def reset(document_id:str):
        return await desktop.work(lambda lib:papers.reset_reference(lib,document_id))
