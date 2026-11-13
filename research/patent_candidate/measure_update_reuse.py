"""Reproducible R5 work-count probe. No real neural or phone timing claim."""
from pathlib import Path
import json
import sqlite3
import uuid

from knowledge_library.library import Library
from research.patent_candidate.vector_memo import VectorMemo
from research.patent_candidate.test_vector_memo import SyntheticEmbedder, make_pdf, snapshot


def run():
    root=Path(__file__).resolve().parents[2]
    work=root/'data/patent-research'/('r5-reuse-'+uuid.uuid4().hex)
    work.mkdir(parents=True)
    cases=[('one_page_changed',list(range(19))+[88],'Fixture'),
           ('pages_reordered',list(reversed(range(20))),'Fixture'),
           ('one_page_deleted',list(range(19)),'Fixture'),
           ('one_page_inserted',[55]+list(range(20)),'Fixture'),
           ('title_changed',list(range(20)),'Different title')]
    results=[]
    for name,numbers,title in cases:
        case=work/name;case.mkdir()
        old,new=case/'old.pdf',case/'new.pdf'
        make_pdf(old,range(20));make_pdf(new,numbers)
        memo=VectorMemo(SyntheticEmbedder(),case/'memo.sqlite3')
        try:
            with Library(case/'full',SyntheticEmbedder()) as full,Library(case/'reuse',memo) as reuse:
                ff,rf=full.create_folder('Synthetic')['id'],reuse.create_folder('Synthetic')['id']
                fd=full.import_pdf(old,ff,title='Fixture')['document']
                rd=reuse.import_pdf(old,rf,title='Fixture')['document']
                f=full.import_pdf(new,ff,document_id=fd['id'],title=title)
                r=reuse.import_pdf(new,rf,document_id=rd['id'],title=title)
                equal=snapshot(full)==snapshot(reuse)
                assert equal
                results.append(dict(case=name,pages=len(numbers),full_new_vectors=f['document_embeddings_generated'],
                    reuse_new_vectors=r['document_embeddings_generated'],committed_payload_equal=equal,
                    full_version=f['document']['version'],reuse_version=r['document']['version'],
                    source_revision_changed=r['document']['sha256']!=rd['sha256'],
                    note='All pages still parsed. Vector generation is a deterministic synthetic test double.'))
        finally:
            memo.close()
    output=dict(date='2026-10-21',work_directory=str(work),cases=results,
        method='Actual Library ingestion and PyMuPDF extraction; synthetic hash vectors, not EmbeddingGemma inference.',
        novelty='Not claimed. Ordinary exact-input cache control.',
        limits=['No OCR savings measured','No model latency, memory, energy or retrieval accuracy measured',
                'No production integration; no live library mutated','No eviction or concurrent-writer cache support'])
    path=root/'results/patent-r5-update-reuse.json'
    path.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    run()
