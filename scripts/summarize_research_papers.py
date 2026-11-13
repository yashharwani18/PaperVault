"""Summarize a frozen paper benchmark, including evidence present in returned chunks."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from evaluate_research_papers import norm

def main():
    path=ROOT/'results/research-paper-evaluation/report.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    assert report['status']=='complete','Do not report accuracy for an incomplete run.'
    for row in report['queries']:
        if not row['relevant']:continue
        matches=[i for i,hit in enumerate(row['hits'],1) if any(
            hit['document']==label['document'] and hit['page']==label['page'] and norm(label['anchor']) in norm(hit['text'])
            for label in row['relevant'])]
        row['evidence_anchor_hit1']=bool(matches and matches[0]==1)
        row['evidence_anchor_hit5']=bool(matches)
    for mode,summary in report['summaries'].items():
        positive=[r for r in report['queries'] if r['mode']==mode and r['relevant']]
        for metric in ('evidence_anchor_hit1','evidence_anchor_hit5'):
            summary[metric]=sum(row[metric] for row in positive)/len(positive)
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    baseline=path.with_name('baseline.json')
    if not baseline.exists():baseline.write_bytes(path.read_bytes())
    print(json.dumps(report['summaries'],indent=2))
    lines=['# Research-paper retrieval evaluation','',
           'Six downloaded arXiv papers; 89 physical pages; 24 answerable questions and 3 unrelated controls.',
           'Labels were written and source-verified before retrieval. The library is isolated from personal data.',
           '','| Mode | Correct paper @1 | Labeled page @1 | Labeled page @5 | Evidence anchor in returned chunk @5 |',
           '|---|---:|---:|---:|---:|']
    for mode,s in report['summaries'].items():
        lines.append('| '+mode+' | '+' | '.join(f'{s[k]*100:.1f}%' for k in ('file_hit1','page_hit1','page_hit5','evidence_anchor_hit5'))+' |')
    lines.extend(['','## Interpretation','',
                  'The evidence-anchor check requires the returned chunk to contain a predeclared phrase from the expected source page. It is stricter than page retrieval, but it does not independently prove that the entire answer is present or correct.',
                  '','No-answer controls measure whether candidate passages are returned. A ranked retrieval list is not a claim that an answer exists. No calibrated abstention threshold was introduced.',
                  '','## Limits','',report['limitations'],
                  '','These numbers cover candidate retrieval, not generated-answer accuracy, citation formatting, OCR scans, all scientific disciplines, or user adoption.',
                  '','## Reproduce','',
                  '1. `.venv/Scripts/python.exe scripts/download_research_papers.py`',
                  '2. `.venv/Scripts/python.exe scripts/evaluate_research_papers.py`',
                  '3. `.venv/Scripts/python.exe scripts/summarize_research_papers.py`',
                  '','The downloader reuses existing originals. The evaluator checks hashes and labels, then reuses unchanged indexes without re-embedding. First-run indexing and repeat-run timings differ.',
                  '','## Timings','',
                  f"This scored run reused unchanged indexes ({report['index_seconds']:.2f} s import checks). Full scored run: {report['total_seconds']:.1f} s, including deferred model loading. Device: CUDA.",
                  'First actual six-paper import took 39.0 seconds including initial model load; per-document measurements and harness-restart explanation are in initial-index.json.'])
    lines.extend(['','## Labeled-page misses',''])
    for row in report['queries']:
        if row['mode']=='semantic' and row['relevant'] and not row['page_hit5']:
            lines.append(f"- `{row['id']}`: {row['query']} Expected {[(r['document'],r['page']) for r in row['relevant']]}; returned {[(r['document'],r['page']) for r in row['hits']]}.")
    lines.extend(['','## Manual inspection of semantic evidence-anchor misses','',
                  'The frozen phrase check misses four queries. This follow-up inspection is diagnostic, not a change to frozen labels or scores:',
                  '- `tr-position`: genuine passage failure. Physical page 6 appears at rank 5, but its selected chunk discusses complexity and dependency paths rather than positional encoding. Opening the full source page exposes the answer, but the selected passage does not.',
                  '- `bert-mask`: the returned page-4 chunk explicitly says the training generator chooses 15% of token positions. It answers the question using different wording from the frozen evidence anchor.',
                  '- `rag-variants`: the returned page-3 chunk explains that RAG-Token draws a different latent document for each target token. This covers part of the requested comparison; the same-document RAG-Sequence explanation is elsewhere on that page.',
                  '- `res-shortcut`: the returned page-3 chunk explicitly describes F + x as shortcut connection and element-wise addition. It answers the question without the frozen phrase identity mapping.',
                  '','No retrieval parameters or production retrieval code were changed. The corpus is small and all default semantic searches find a labeled page in their top five; a broad ranking change based on one observed passage miss would risk overfitting.'])
    path.with_name('REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__':main()
