"""Bounded local indexing benchmark; fresh libraries, real model, same PDFs."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.library import Library
import knowledge_library.library as library_module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--baseline', action='store_true', help='Use the previous bundled implementation before updating it')
    args = parser.parse_args()
    library_class = Library
    if args.baseline:
        spec = importlib.util.spec_from_file_location('knowledge_library._baseline_speed', ROOT / 'output/Local-Library-Desktop/app/knowledge_library/library.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.extract_page = lambda *a, **kw: library_module.extract_page(*a, **kw)
        library_class = module.Library
    model = EmbeddingGemma(device='cuda', batch_size=args.batch_size)
    model.query('Warm up indexing benchmark')
    report = {'label': args.label, 'device': model.device, 'batch_size': args.batch_size, 'documents': []}
    original_extract = library_module.extract_page
    original_documents = model.documents
    counters = {}
    def extract(*a, **kw):
        started = time.perf_counter()
        result = original_extract(*a, **kw)
        counters['extraction_s'] += time.perf_counter() - started
        return result
    def documents(title, texts):
        counters['embedding_calls'] += 1
        counters['batch_sizes'].append(len(texts))
        started = time.perf_counter()
        result = original_documents(title, texts)
        counters['embedding_s'] += time.perf_counter() - started
        return result
    library_module.extract_page = extract
    model.documents = documents
    root = ROOT / '.cache/index-speed' / (args.label + '-' + uuid.uuid4().hex)
    with library_class(root, model) as lib:
        folder = lib.create_folder('Speed benchmark')['id']
        lib.db.execute('CREATE TABLE benchmark_progress(value TEXT)')
        lib.db.execute("INSERT INTO benchmark_progress VALUES('')")
        lib.db.commit()
        def progress(value):
            with lib.db:
                lib.db.execute('UPDATE benchmark_progress SET value=?', (json.dumps(value),))
        for name in ['mit-convolution', 'attention', 'bert']:
            counters = dict(extraction_s=0., embedding_s=0., embedding_calls=0, batch_sizes=[])
            result = lib.import_pdf(ROOT / 'corpus/pdfs' / (name + '.pdf'), folder, progress=progress)
            doc = result['document']
            report['documents'].append(dict(name=name, elapsed_s=result['elapsed_s'], pages=doc['page_count'], chunks=doc['chunk_count'], **counters))
            print(json.dumps(report['documents'][-1]), flush=True)
        report['total_s'] = sum(d['elapsed_s'] for d in report['documents'])
        report['pages_per_s'] = sum(d['pages'] for d in report['documents']) / report['total_s']
        report['embedding_calls'] = sum(d['embedding_calls'] for d in report['documents'])
        report['gpu'] = model._torch.cuda.get_device_name()
    (ROOT / 'results' / ('index-speed-' + args.label + '.json')).write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'documents'}), flush=True)


if __name__ == '__main__':
    main()
