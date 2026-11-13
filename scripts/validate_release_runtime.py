"""Run with the bundled python.exe -I -B: genuine compiled API/inference smoke."""
import argparse
import importlib
import json
from pathlib import Path
import sys
import time
import uuid


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--device',choices=['auto','cpu'],default='auto');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scratch-root',type=Path)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--existing',action='store_true')
    args=parser.parse_args()
    import pymupdf
    from fastapi.testclient import TestClient
    from knowledge_library.hardware import select_device,system_report
    from knowledge_library.server import create_app,offline_guard
    root=Path(__file__).resolve().parents[1]
    scratch=(args.scratch_root or root/'.cache/release-runtime-tests')/uuid.uuid4().hex;scratch.mkdir(parents=True)
    source=scratch/'release-signal-notes.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40,60),'Digital signal processing uses filters and convolution to analyze discrete signals.')
        pdf.new_page().insert_text((40,60),'Transmission lines carry electromagnetic waves. Impedance matching reduces reflections.')
        pdf.save(source)
    offline_guard()
    selection=select_device() if args.device=='auto' else dict(device='cpu',gpu_name=None,reason='Forced CPU acceptance check.')
    library=args.library or scratch/'library'
    app=create_app(library,selection['device'],preload=False)
    app.state.hardware=system_report(library,selection)
    started=time.perf_counter()
    with TestClient(app) as client:
        state=client.get('/api/state').json();client.headers['X-Library-Token']=state['token']
        assert bool(state['documents'])==args.existing
        assert not client.get('/api/connections').json()['sources']
        assert client.get('/api/system').json()['device']==selection['device']
        if not args.existing:
            folder=client.post('/api/folders',json={'name':'Release acceptance'}).json()['id']
            with source.open('rb') as stream:
                response=client.post('/api/uploads',data={'folder_id':folder},files=[('files',(source.name,stream,'application/pdf'))])
            assert response.status_code==200,response.text
            ids=response.json()['task_ids'];deadline=time.monotonic()+240
            while True:
                state=client.get('/api/state').json();tasks=[t for t in state['tasks'] if t['id'] in ids]
                if tasks and all(t['status'] not in ('queued','running') for t in tasks):break
                assert time.monotonic()<deadline,'Indexing timed out'
                time.sleep(.2)
            assert all(t['status']=='completed' for t in tasks),tasks
        response=client.post('/api/search',json={'query':'digital signal processing'})
        assert response.status_code==200,response.text
        result=response.json();hit=result['results'][0]
        assert hit['page_number']==1
        preview=client.get(f"/api/documents/{hit['document_id']}/preview",params={'page':1,'chunk_id':hit['chunk_id'],'revision':hit['source_sha256']})
        assert preview.status_code==200,preview.text
        assert preview.content.startswith(b'\x89PNG') and int(preview.headers['x-highlight-count'])>0
        assert client.get(f"/api/documents/{hit['document_id']}/file").content.startswith(b'%PDF')
        with app.state.desktop.lib() as lib:assert lib.verify()['passed']
        modules={name:module.__file__ for name,module in sys.modules.items() if name.startswith('knowledge_library') and getattr(module,'__file__',None)}
        assert modules and all(Path(path).suffix=='.pyd' for path in modules.values()),modules
        report=dict(passed=True,device=selection['device'],gpu_name=selection.get('gpu_name'),runtime=sys.executable,
                    compiled_modules_loaded=len(modules),index_and_search_elapsed_s=time.perf_counter()-started,
                    search_elapsed_s=result['elapsed_s'],highlighted_preview=True,source_access=True,
                    no_development_imports=True,fresh_library=not args.existing,automatic_scan_before_consent=False)
    args.output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
