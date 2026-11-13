"""Copy a validated real 20-PDF library into a new desktop workspace, without inference."""
import json
from pathlib import Path
import shutil
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library


def main():
    target=ROOT/'data/desktop'
    if (target/'library.sqlite3').exists():
        print('Desktop library already exists; user files preserved.');return
    r=json.loads((ROOT/'results/phase3-validation.json').read_text())
    source=Path(next(v['library'] for v in r['runs'] if v['chunk_tokens']==256))
    target.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source/'library.sqlite3') as src,sqlite3.connect(target/'library.sqlite3') as dst:src.backup(dst)
    shutil.copytree(source/'files',target/'files',dirs_exist_ok=True)
    mapping={'TOC':('Theory of Computation','#A78BFA'),'DSP':('Digital Signal Processing','#6BA9F8'),'Research Papers':('Research Papers','#54C8A4'),'Books':('Books & reading','#E5B96C'),'Reference':('Reference','#9AA3B4')}
    with Library(target) as lib:
        for f in lib.folders():
            if f['name'] in mapping:
                name,color=mapping[f['name']];lib.rename_folder(f['id'],name);lib.color_folder(f['id'],color)
            elif f['name']=='Empty':lib.delete_folder(f['id'])
        for name,color in [('Projects','#E18BAF'),('Bills & invoices','#6BA9F8')]:lib.create_folder(name,color)
        assert lib.verify()['passed']
        assert lib.embedder.stats['document_texts_encoded']==0
        print(json.dumps(dict(library=str(target),documents=len(lib.documents()),source='Existing actual Phase 3 PDFs and vectors; no synthetic demo records',document_embeddings_generated=0),indent=2))


if __name__=='__main__':main()
