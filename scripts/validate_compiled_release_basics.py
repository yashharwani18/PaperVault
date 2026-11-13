"""Native Khoj identity and support-report acceptance without user documents."""
import json
from pathlib import Path
import uuid
import pymupdf
from fastapi.testclient import TestClient
from knowledge_library.server import create_app
from knowledge_library import release_info

ROOT=Path(__file__).resolve().parents[1]


def main():
    assert Path(release_info.__file__).suffix=='.pyd'
    root=ROOT/'.cache/compiled-khoj'/uuid.uuid4().hex;root.mkdir(parents=True)
    app=create_app(root/'library','cpu',preload=False)
    private='PRIVATE_DOCUMENT_QUERY_FILENAME_SECRET'
    source=root/(private+'.pdf')
    with pymupdf.open() as pdf:pdf.new_page();pdf.save(source)
    with TestClient(app) as client:
        desktop=app.state.desktop
        client.headers['X-Library-Token']=client.get('/api/state').json()['token']
        with desktop.lib() as lib:
            folder=lib.create_folder(private)['id'];lib.import_pdf(source,folder,retain_source=False)
            with lib.db:
                lib.db.execute('UPDATE pages SET text=?',(private,))
                lib.db.execute("INSERT INTO app_tasks(id,folder_id,source,filename,ocr,status,created_at,error) VALUES('test',?,?,?,0,'failed','2026-10-24',?)",(folder,str(source),source.name,'FileNotFoundError: '+private))
        about=client.get('/api/about').json()
        assert (about['name'],about['version'],about['display_version'])==('Khoj','0.5.0','v0.5')
        response=client.post('/api/diagnostics');assert response.status_code==200,response.text
        data=response.json();assert data['library']['documents']==1 and data['errors']['missing']==1
        assert private not in response.text and str(root) not in response.text
        assert response.headers['cache-control']=='no-store'
    report=dict(passed=True,native_module=str(release_info.__file__),identity='Khoj v0.5',diagnostics_content_excluded=True,manual_updates=True)
    (ROOT/'results/compiled-khoj-validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
