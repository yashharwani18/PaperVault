"""Measure fresh incremental indexing and live search at genuine corpus milestones."""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_embedding_model import ResourceSampler,deny_python_network,write_json


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--device',choices=['cuda','cpu'],default='cuda');parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    blocked=[];deny_python_network(blocked)
    import numpy as np
    import psutil
    from knowledge_library.embedding import EmbeddingGemma
    from knowledge_library.library import Library
    from knowledge_library.chunking import ChunkingConfig
    corpus=json.loads((ROOT/'evaluation/phase4-corpus.json').read_text())['documents'][:args.limit]
    queries=[q['query'] for q in json.loads((ROOT/'evaluation/phase3-queries.json').read_text())['queries'] if q['split']=='test' and q['relevant']][:10]
    output=ROOT/f'results/phase4-{args.device}.json'
    root=ROOT/'data/phase4'/f"{args.device}-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    report=dict(device=args.device,library=str(root),status='running',milestones=[],documents=[],scope='Distinct real PDFs; no duplicated-document scale claims',samples=[])
    sampler=ResourceSampler(psutil);sampler.start();done=threading.Event();process=psutil.Process()
    def sample():
        process.cpu_percent()
        while not done.wait(1):
            row=dict(at_s=time.perf_counter(),process_cpu_percent=process.cpu_percent(),system_cpu_percent=psutil.cpu_percent())
            if args.device=='cuda':
                try:
                    gpu=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
                    row['gpu_utilization_percent'],row['gpu_total_used_MiB']=map(float,gpu.stdout.strip().split(',')[:2])
                except Exception as exc:row['gpu_sampling_error']=str(exc)
            report['samples'].append(row)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    model=EmbeddingGemma(device=args.device,batch_size=8)
    started=time.perf_counter()
    try:
        model.load();report['cold_model_load_s']=model.stats['model_load_s']
        with Library(root,model) as lib:
            folder=lib.create_folder('Performance corpus')['id']
            index_total=0
            for n,e in enumerate(corpus,1):
                out=lib.import_pdf(ROOT/f"corpus/pdfs/{e['id']}.pdf",folder,title=e['title'],chunking=ChunkingConfig(256,64))
                index_total+=out['elapsed_s'];d=out['document']
                report['documents'].append(dict(corpus_id=e['id'],document_id=d['id'],sha256=d['sha256'],pages=d['page_count'],chunks=d['chunk_count'],index_s=out['elapsed_s'],status=d['status']))
                print(f"{args.device}: {n}/{len(corpus)} {e['id']} {out['elapsed_s']:.2f}s",flush=True)
                if n in (10,50,100,500) or n==len(corpus):
                    # One warmup is excluded; reported timings include fresh query inference.
                    lib.search(queries[0])
                    times=[lib.search(q)['elapsed_s'] for q in queries]
                    st=lib.stats()
                    row=dict(documents=n,pages=st['pages'],chunks=st['chunks'],cumulative_index_s=index_total,
                             index_s_per_page=index_total/st['pages'],pages_per_s=st['pages']/index_total,
                             warm_mean_s=statistics.mean(times),warm_p50_s=float(np.percentile(times,50)),warm_p95_s=float(np.percentile(times,95)),warm_max_s=max(times),
                             database_bytes=st['database_bytes'],vector_bytes=st['vector_bytes'],pdf_bytes=st['managed_pdf_bytes'],query_count=len(times),embedding_s=model.stats['document_embedding_s'])
                    report['milestones'].append(row)
                    print('MILESTONE '+json.dumps(row),flush=True)
                write_json(output,report)
            before=model.stats['document_texts_encoded']
            assert lib.import_pdf(ROOT/f"corpus/pdfs/{corpus[0]['id']}.pdf",folder,title=corpus[0]['title'],chunking=ChunkingConfig(256,64))['action']=='unchanged'
            report['unchanged_no_inference']=before==model.stats['document_texts_encoded']
            if args.limit==100:
                extra=lib.import_pdf(ROOT/'corpus/pdfs/rfc-9080.pdf',folder,title='RFC 9080',chunking=ChunkingConfig(256,64))
                report['incremental_101st']=dict(index_s=extra['elapsed_s'],new_embeddings=model.stats['document_texts_encoded']-before,expected_new_chunks=extra['document']['chunk_count'])
                assert report['incremental_101st']['new_embeddings']==report['incremental_101st']['expected_new_chunks']
                lib.remove_document(extra['document']['id'])
            report['integrity']=lib.verify();assert report['integrity']['passed']
        assert len({d['sha256'] for d in report['documents']})==len(corpus)
        assert len(blocked)==1
        report['status']='passed'
    except Exception:
        import traceback
        report['status']='failed';report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        done.set();thread.join(timeout=5)
        report['elapsed_s']=time.perf_counter()-started;report['memory']=sampler.stop();report['embedding_runtime']=dict(model.stats)
        if model._torch is not None and args.device=='cuda':
            report['memory'].update(torch_peak_allocated_vram_bytes=model._torch.cuda.max_memory_allocated(),torch_peak_reserved_vram_bytes=model._torch.cuda.max_memory_reserved())
        report['offline']=dict(blocked_socket_events=len(blocked),physical_disconnection=False)
        write_json(output,report)
        if report['milestones']:
            with output.with_suffix('.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(report['milestones'][0]));writer.writeheader();writer.writerows(report['milestones'])
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
