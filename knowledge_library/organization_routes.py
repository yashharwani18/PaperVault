from pydantic import BaseModel,Field
from . import organization as org


class DocumentsBody(BaseModel):
    document_ids:list[str]=Field(min_length=1,max_length=2000)


class MoveBody(DocumentsBody):
    folder_id:str=Field(min_length=1,max_length=128)


class TopicsBody(DocumentsBody):
    topic_ids:list[str]=Field(max_length=100)


class NameBody(BaseModel):
    name:str=Field(min_length=1,max_length=128)


def install(app,desktop):
    @app.get('/api/organization')
    def catalogue():
        with desktop.lib() as lib:return dict(topics=org.topics(lib))

    @app.post('/api/organization/topics')
    async def create(body:NameBody):return await desktop.work(lambda lib:org.create_topic(lib,body.name))

    @app.patch('/api/organization/topics/{topic_id}')
    async def rename(topic_id:str,body:NameBody):return await desktop.work(lambda lib:org.rename_topic(lib,topic_id,body.name))

    @app.post('/api/organization/topics/assign')
    async def assign(body:TopicsBody):return await desktop.work(lambda lib:org.set_topics(lib,body.document_ids,body.topic_ids))

    @app.post('/api/organization/topics/reset')
    async def reset(body:DocumentsBody):return await desktop.work(lambda lib:org.reset_topics(lib,body.document_ids))

    @app.get('/api/organization/documents/{document_id}')
    def document(document_id:str):
        with desktop.lib() as lib:return org.document_info(lib,document_id)

    @app.put('/api/organization/documents/{document_id}/name')
    async def document_name(document_id:str,body:NameBody):return await desktop.work(lambda lib:org.rename_document(lib,document_id,body.name))

    @app.delete('/api/organization/documents/{document_id}/name')
    async def original_name(document_id:str):return await desktop.work(lambda lib:org.rename_document(lib,document_id,None))

    @app.post('/api/organization/move')
    async def move(body:MoveBody):return await desktop.work(lambda lib:org.move_documents(lib,body.document_ids,body.folder_id))

    @app.post('/api/organization/moves/{token}/undo')
    async def undo(token:str):return await desktop.work(lambda lib:org.undo_move(lib,token))
