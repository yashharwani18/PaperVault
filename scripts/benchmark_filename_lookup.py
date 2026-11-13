"""Measure real metadata-only API latency on synthetic catalog rows; no PDFs are indexed."""
from pathlib import Path
from tempfile import TemporaryDirectory
from statistics import median
from time import perf_counter
import json,platform,sys
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge_library import server

class MetadataEncoder:
    dimensions=128;batch_size=4;dtype='test';device='cpu';_model=None;_torch=None
    signature=dict(model_id='metadata-benchmark',revision='1',configuration_version='1')
    def __init__(self,**_):self.stats=dict(document_texts_encoded=0,query_texts_encoded=0,model_loads=0)
    def query(self,_):raise AssertionError('Filename lookup must not use embeddings')

server.EmbeddingGemma=MetadataEncoder
base=(ROOT/'.cache'/'filename-benchmark').resolve();base.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(dir=base) as temporary:
    root=Path(temporary).resolve();assert root.is_relative_to(base)
    app=server.create_app(root,device='cpu',preload=False)
    with TestClient(app) as client:
        desktop=app.state.desktop;client.headers['X-Library-Token']=desktop.token
        source=root/'files'/'synthetic.pdf';source.write_bytes(b'synthetic metadata fixture')
        with desktop.lib() as lib:
            folder=lib.create_folder('Synthetic')['id']
        results=[];current=0
        for count in (100,1000,2000,10000):
            with desktop.lib() as lib,lib.db:
                lib.db.executemany('''INSERT INTO documents(id,folder_id,filename,title,original_path,managed_path,sha256,size_bytes,page_count,chunk_count,status,recipe,created_at,updated_at,version,source_mode)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',[(f'{i:032x}',folder,f'Lecture {i}.pdf',f'Lecture {i}',str(source),'files/synthetic.pdf',f'{i:064x}',26,1,0,'indexed','{}','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',1,'managed') for i in range(current,count)])
            current=count;samples=[]
            for _ in range(15):
                start=perf_counter();response=client.post('/api/filename-matches',json=dict(query=f'Lecture {count-1}',folder_id=folder));samples.append((perf_counter()-start)*1000)
                assert response.status_code==200,response.text
                matches=response.json()['matches'];assert len(matches)==1 and matches[0]['available']
            samples.sort();results.append(dict(documents=count,median_ms=round(median(samples),3),p95_ms=round(samples[14],3)))
        print(json.dumps(dict(kind='synthetic_desktop_exact_filename_api',platform=platform.platform(),results=results,limitations='Synthetic metadata rows only; no real PDF extraction, model inference, Android device, battery or thermal measurement.'),indent=2))
