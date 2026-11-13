"""Exercise recovery in the source-free release using generated PDFs only."""
import json
from pathlib import Path
import time
import uuid
import pymupdf
from fastapi.testclient import TestClient
from knowledge_library.server import create_app
from knowledge_library import recovery

ROOT=Path(__file__).resolve().parents[1]


def main():
    assert Path(recovery.__file__).suffix=='.pyd'
    root=ROOT/'.cache/compiled-recovery'/uuid.uuid4().hex;root.mkdir(parents=True)
    source=root/'Original.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40,60),'Recovery verifies original digital signal processing evidence.');pdf.save(source)
    app=create_app(root/'library','cpu',preload=False)
    with TestClient(app) as client:
        desktop=app.state.desktop
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        folder=client.post('/api/folders',json={'name':'Compiled recovery'}).json()['id']
        task=desktop.queue(folder,source,source.name)
        def wait(key):
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                row=desktop.tasks([key])[0]
                if row['status'] not in ('running','queued'):return row
                time.sleep(.1)
            raise AssertionError('Compiled indexing did not finish')
        job=wait(task);assert job['status']=='completed',job
        document=job['result']['document'];key=document['id']
        source.rename(root/'Moved.pdf')
        assert client.get(f'/api/documents/{key}/recovery').json()['source']['code']=='missing'
        response=client.post(f'/api/documents/{key}/reconnect',json={'path':str(root/'Moved.pdf')});assert response.status_code==200,response.text
        assert client.get(f'/api/documents/{key}/file').status_code==200
        with desktop.lib() as lib,lib.db:lib.db.execute("UPDATE documents SET status='extraction_failed' WHERE id=?",(key,))
        retried=client.post(f'/api/documents/{key}/refresh').json()['task_id']
        result=wait(retried);assert result['status']=='completed',result
        assert result['result']['action']!='unchanged'
        assert result['result']['document']['status']=='indexed'
        assert not list((root/'library/files').glob('*.pdf'))
    report=dict(passed=True,native_module=str(recovery.__file__),missing_source_reconnect=True,incomplete_extraction_retried=True,no_pdf_copies=True)
    (ROOT/'results/compiled-recovery-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
