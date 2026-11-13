"""Read-only corpus diagnostics using actual Android identifier code and exported vectors.

Run with the workspace Python (NumPy required). Private pages never enter APK assets.
Identifier labels are automatically derived; vector probes reuse source vectors and
measure candidate truncation, NOT natural-language semantic accuracy.
"""
from pathlib import Path
from collections import defaultdict
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LABEL = re.compile(r'(?im)\b(?:invoice|bill|inv)\s*(?:number|no\.?|#)\s*[:#：-]?\s*((?:inv[ \t]*[-/]?[ \t]*)?[a-z0-9]+(?:[-/_][a-z0-9]+)*)')
NEGATIVES = ['inventory', 'investment', 'billing', 'invoices', 'invoice', 'bill',
             'invoice total', 'invoice date', 'invoice amount', 'invoice details',
             'show me invoice total 6600', 'invoice 25 and invoice 125',
             '6600 wala bill', 'show invoices', 'find inventory']


def canonical(value):
    value = re.sub(r'[^a-z0-9]', '', value.casefold())
    return re.sub(r'^(?:inv)+(?=[0-9]+$)', '', value)


def benchmark(export, output, invoice_source=None):
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((export/'manifest.json').read_text())
    expected_files = {'documents.jsonl', 'pages.jsonl', 'chunks.jsonl', 'vectors.f32'}
    if manifest.get('format') != 'khoj-embeddings-v1' or set(manifest['sha256']) != expected_files:
        raise ValueError('Unsupported or incomplete export manifest')
    for name, digest in manifest['sha256'].items():
        if name not in {'documents.jsonl', 'pages.jsonl', 'chunks.jsonl', 'vectors.f32'}:
            raise ValueError('Unexpected manifest file')
        if hashlib.sha256((export/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Checksum mismatch: '+name)
    pages = [json.loads(line) for line in (export/'pages.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    chunks = [json.loads(line) for line in (export/'chunks.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(pages) != manifest['counts']['pages'] or len(chunks) != manifest['counts']['chunks']:
        raise ValueError('Export counts differ from manifest')
    labels = defaultdict(set)
    identifiers = {}
    for page in pages:
        for match in LABEL.finditer(page['text']):
            value = match.group(1)
            if not re.search(r'\d', value):
                continue
            key = canonical(value)
            labels[key].add(f"{page['document_id']}:{page['page_number']}")
            identifiers.setdefault(key, value.strip())
    # Fixed corpus-independent sample order, plus the user's reference and observed underscore ID.
    selected = sorted(labels, key=lambda k: hashlib.sha256(k.encode()).hexdigest())[:60]
    selected = sorted(set(selected) | ({'25', 'at65'} & labels.keys()))
    cases = []
    for key in selected:
        value = identifiers[key]
        for query in (f'invoice number {value}', f'find invoice no. {value}', f'inv{key}' if key.isdigit() else f'invoice {value}'):
            cases.append({'query': query, 'expected': sorted(labels[key])})
    cases += [{'query': q, 'expected': [], 'negative': True} for q in NEGATIVES]
    casefile = output/'queries.jsonl'
    casefile.write_text(''.join(json.dumps(c)+'\n' for c in cases), encoding='utf-8')
    config = json.loads((ROOT/'.cache/android-tools/toolchain.json').read_text())
    java = Path(config['java_home'])/'bin'
    jars = sorted((ROOT/'.cache/android-gradle/caches/modules-2/files-2.1/org.json/json').rglob('json-20240303.jar'))
    if not jars:
        raise RuntimeError('Cached org.json dependency not found')
    classes = output/'classes'; classes.mkdir(exist_ok=True)
    source = ROOT/'android/app/src/main/java/org/localknowledge/library'
    invoice_source = invoice_source or source/'InvoiceNumbers.java'
    subprocess.run([str(java/'javac.exe'), '-encoding', 'UTF-8', '-cp', str(jars[0]), '-d', str(classes),
                    str(invoice_source), str(source/'PageCandidates.java'), str(ROOT/'scripts/PhoneCorpusProbe.java')], check=True)
    start = time.perf_counter()
    process = subprocess.run([str(java/'java.exe'), '-Xmx512m', '-cp', os.pathsep.join([str(classes), str(jars[0])]),
                              'org.localknowledge.library.PhoneCorpusProbe', str(export/'pages.jsonl'), str(casefile)],
                             check=True, capture_output=True, encoding='utf-8')
    actual = json.loads(process.stdout)
    identifier_seconds = time.perf_counter()-start
    failures = []; correct = 0; negatives_ok = 0; recalls = []
    for case, result in zip(cases, actual, strict=True):
        expected, found = set(case['expected']), set(result['pages'])
        if case.get('negative'):
            ok = result['parsed'] is None
            negatives_ok += ok
        else:
            ok = found == expected
            recalls.append(len(expected & found)/len(expected))
        correct += ok
        if not ok:
            failures.append({'query': case['query'], 'parsed': result['parsed'], 'missing': sorted(expected-found),
                             'extra': sorted(found-expected), 'negative': case.get('negative', False)})
    # All source vectors as probes; compute chunk scores in bounded batches.
    dims = {c['dimensions'] for c in chunks}
    identities = {c['input_hash'].split(':', 1)[0] for c in chunks}
    if len(dims) != 1 or len(identities) != 1:
        raise ValueError('Cannot compare different embedding recipes')
    dimension = dims.pop(); blob = (export/'vectors.f32').read_bytes()
    if any(type(c['vector_offset_bytes']) is not int or c['vector_offset_bytes'] < 0 or
           c['vector_offset_bytes'] % 4 or c['vector_offset_bytes']+dimension*4 > len(blob) for c in chunks):
        raise ValueError('Invalid vector bounds')
    matrix = np.stack([np.frombuffer(blob, dtype='<f4', count=dimension, offset=c['vector_offset_bytes']) for c in chunks])
    if not np.isfinite(matrix).all():
        raise ValueError('Nonfinite vectors')
    keys = [(c['document_id'], c['page_number']) for c in chunks]
    omissions = short = 0; worst = 20; total = len(chunks); ideals = []
    scorefile = output/'scores.f64'
    keyfile = output/'page-keys.txt'
    keyfile.write_text(''.join(f'{d}:{p}\n' for d,p in keys),encoding='utf-8')
    with scorefile.open('wb') as stream:
        for begin in range(0, total, 64):
            scores = matrix[begin:begin+64] @ matrix.T
            scores.astype('<f8').tofile(stream)
            for row in scores:
                order = np.argsort(-row, kind='stable')
                oldpages = list(dict.fromkeys(keys[i] for i in order[:20]))
                ideal = list(dict.fromkeys(keys[i] for i in order))[:5]; ideals.append(ideal)
                short += len(oldpages) < 5
                omissions += len(set(ideal)-set(oldpages[:5])) > 0
                worst = min(worst, len(oldpages))
    replay = subprocess.run([str(java/'java.exe'), '-Xmx512m', '-cp', os.pathsep.join([str(classes), str(jars[0])]),
                             'org.localknowledge.library.PhoneCorpusProbe', '--rank', str(keyfile), str(scorefile)],
                            check=True, capture_output=True, encoding='utf-8')
    ranked = json.loads(replay.stdout)
    if len(ranked) != len(ideals):
        raise ValueError('Incomplete Java page-ranking replay')
    mismatches = sum([keys[i] for i in result] != ideal for result,ideal in zip(ranked,ideals,strict=True))
    scorefile.unlink()
    report = {'documents': manifest['counts']['documents'], 'pages': len(pages), 'chunks': total,
              'identifier_cases': len(cases), 'identifier_cases_exact': correct, 'negative_controls': len(NEGATIVES),
              'negative_controls_correct': negatives_ok, 'identifier_page_recall': sum(recalls)/len(recalls),
              'identifier_failures': failures, 'java_identifier_seconds': identifier_seconds,
              'invoice_source_sha256': hashlib.sha256(invoice_source.read_bytes()).hexdigest(),
              'manifest_sha256': hashlib.sha256((export/'manifest.json').read_bytes()).hexdigest(),
              'chunk_crowding': {'source_vector_probes': total, 'old_fewer_than_5_pages': short,
                                 'old_missing_top5_pages': omissions, 'old_minimum_unique_pages': worst,
                                 'production_page_selector_oracle_mismatches': mismatches},
              'limitations': ['Automatically derived identifier labels require human review.',
                              'Vector probes measure truncation only; these are not natural-language query embeddings.',
                              'Host JVM diagnostics do not measure full Android search latency or device performance.']}
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'identifier_failures'}, indent=2))
    print('Identifier failures:', len(failures))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--invoice-source', type=Path, help='Optional frozen baseline InvoiceNumbers.java for an ablation')
    parser.add_argument('--check', action='store_true', help='Exit nonzero on any identifier case or page-ranking mismatch')
    args = parser.parse_args()
    report = benchmark(args.export.resolve(), args.output.resolve(), args.invoice_source)
    if args.check and (report['identifier_failures'] or report['chunk_crowding']['production_page_selector_oracle_mismatches']):
        raise SystemExit(1)
