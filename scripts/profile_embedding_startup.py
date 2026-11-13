"""Fresh-process load timing and real vectors for startup regression comparison."""
import time
START=time.perf_counter()
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import psutil
from knowledge_library.embedding import EmbeddingGemma

QUERIES=['bhai pumping lemma kis PPT mein hai','How can I prove a language is not regular?',
    'Find Fourier transform frequency components','which invoice had 13600 subtotal?',
    'Explain context free grammar','hello mere bhai mujhe 13800 ka invoice dikha']
DOCS=['The pumping lemma proves that some formal languages are not regular.',
    'Invoice number 39. Subtotal 13600.00 and total 14280.00.',
    'A Fourier transform decomposes signals into frequency components.',
    'Context-free grammars describe languages through production rules.',
    'A long test paragraph. '*150,'Small text.']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--vectors');parser.add_argument('--legacy',action='store_true');args=parser.parse_args()
    if args.legacy:
        import knowledge_library.text_encoder as encoder
        def legacy(path,*,device,config_kwargs,model_kwargs):
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(str(path),device=device,local_files_only=True,trust_remote_code=False,config_kwargs=config_kwargs,model_kwargs=model_kwargs)
        encoder.TextEncoder=legacy
    imported=time.perf_counter()-START;model=EmbeddingGemma();start=time.perf_counter()
    model.load();loaded=time.perf_counter()-start
    elapsed=[];vectors=[]
    for query in QUERIES:
        start=time.perf_counter();vectors.append(model.query(query));elapsed.append(time.perf_counter()-start)
    documents=model.documents('Startup validation',DOCS)
    if args.vectors:np.savez(args.vectors,queries=np.stack(vectors),documents=documents)
    result=dict(backend='original_sentence_transformers' if args.legacy else 'text_encoder_cached_import_index',import_s=imported,load_s=loaded,first_query_s=elapsed[0],query_s=elapsed,
        total_s=time.perf_counter()-START,rss_bytes=psutil.Process().memory_info().rss,stats=model.stats,
        process_note='Fresh process, existing OS disk cache; not a reboot-cold or phone benchmark')
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
