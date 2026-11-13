"""Compare inference-only outputs with the original SentenceTransformer pipeline."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from knowledge_library.embedding import EmbeddingGemma,LOCK


def main():
    current=EmbeddingGemma(batch_size=4);current.load()
    import torch
    from sentence_transformers import SentenceTransformer
    reference=SentenceTransformer(str(current.model_dir),device='cuda',local_files_only=True,trust_remote_code=False,
        config_kwargs=LOCK['config_kwargs'],model_kwargs={'torch_dtype':torch.bfloat16,'attn_implementation':'sdpa'})
    reference.eval()
    texts=['pumping lemma','  Leading and trailing whitespace.  ','नियमित भाषा और पम्पिंग लेम्मा',
        'Invoice subtotal 13,600.00, total 14,280.00.','Symbols: aⁿbⁿ, α β, ∀ i ≥ 0.','Tabs\tand\nline breaks.',
        'Equal length!','same length!!','🙂 Unicode emoji and café','x','A longer paragraph. '*200,'']
    reports=[]
    for kind in ('query','document'):
        inputs=texts if kind=='query' else [current.format_document('Compatibility test',t) for t in texts+texts[:9]]
        with torch.inference_mode():
            expected=reference.encode(inputs,convert_to_tensor=True,normalize_embeddings=True,batch_size=4,show_progress_bar=False,
                **({'prompt_name':'SearchQuery'} if kind=='query' else {'prompt':''})).float().cpu().numpy()
        expected=np.asarray(expected/np.linalg.norm(expected,axis=1,keepdims=True),dtype='<f4')
        actual=current._encode(inputs,query=kind=='query')
        delta=float(np.abs(expected-actual).max());cosine=float(np.sum(expected*actual,axis=1).min())
        reports.append(dict(kind=kind,samples=len(inputs),max_absolute_delta=delta,min_cosine=cosine,passed=bool(np.allclose(expected,actual,atol=1e-6,rtol=1e-6))))
    result=dict(reports=reports,passed=all(r['passed'] for r in reports),recipe=current.signature)
    (ROOT/'results/startup-vector-compatibility.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True);assert result['passed']


if __name__=='__main__':main()
