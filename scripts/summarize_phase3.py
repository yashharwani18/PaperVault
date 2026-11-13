"""Render measured Phase 3 results, keeping failed acceptance gates visible."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    r = json.loads((ROOT/"results/phase3-validation.json").read_text(encoding="utf-8"))
    if r["status"]!="evaluation_completed":
        raise SystemExit("Evaluation has not completed; do not summarize partial results as final")
    s = r["selected"]
    rows = r["test"]
    selected = next(v for v in rows if all(v[k]==s[k] for k in ("chunk_tokens","dimensions","mode","hybrid")))
    labels = json.loads((ROOT/"evaluation/phase3-queries.json").read_text(encoding="utf-8"))["queries"]
    by_id = {q["id"]:q for q in labels}
    records = [json.loads(line) for line in Path(r["raw_rankings"]).read_text(encoding="utf-8").splitlines()]
    chosen = [v for v in records if v["split"]=="test" and all(v[k]==s[k] for k in ("chunk_tokens","dimensions","mode","hybrid"))]
    pct = lambda v:f"{v*100:.1f}%"
    mib = lambda v:f"{v/1024**2:.2f}"
    output = ROOT/"results/phase3-benchmarks.csv"
    fields = ["chunk_tokens","dimensions","mode","semantic_weight","rank_constant","answerable_queries","recall@1","recall@3","recall@5","hit@1","hit@3","hit@5","mrr@5","rank_only_mean_s","rank_only_p95_s"]
    with output.open("w",newline="",encoding="utf-8") as stream:
        writer = csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for v in rows:
            writer.writerow({**{k:v[k] for k in ("chunk_tokens","dimensions","mode","answerable_queries","rank_only_mean_s","rank_only_p95_s")},
                             "semantic_weight":(v["hybrid"] or {}).get("semantic_weight"),"rank_constant":(v["hybrid"] or {}).get("rank_constant"),**v["metrics"]})
    native = next(v for v in rows if v['chunk_tokens']==256 and v['dimensions']==768 and v['mode']=='semantic')
    lines = ["# Phase 3 — retrieval quality evaluation", "",
             f"Execution: **completed**. Predeclared selected-hybrid acceptance gate: **{'PASSED' if r['quality_gate']['passed'] else 'FAILED'}**.","",
             f"The configuration selected using development questions alone was {s['chunk_tokens']}-token chunks, 64-token overlap, {s['dimensions']} dimensions, weighted RRF with semantic weight {s['hybrid']['semantic_weight']} and rank constant {s['hybrid']['rank_constant']} (100 page candidates per ranker). On 30 test questions it achieved page Recall@3 **{pct(selected['metrics']['recall@3'])}** and Recall@5 **{pct(selected['metrics']['recall@5'])}** against targets of 80% and 90%. MRR@5 was {selected['metrics']['mrr@5']:.3f}.","",
             f"The native 768-dimensional semantic baseline with 256-token chunks reached {pct(native['metrics']['recall@3'])} Recall@3 and {pct(native['metrics']['recall@5'])} Recall@5, meeting both numerical page targets on this set. This is a descriptive baseline result; it does not turn the failed development-selected hybrid into a pass, validate a calibrated no-answer policy, or provide a new independent test after selecting settings from this table. The default search method remains semantic and hybrid is available explicitly; default import chunk size remains 512, whose quality results are listed below.","",
             "This is a coding-agent source-checked diagnostic set, **not independently human annotated**. Positive page labels are non-exhaustive. A retrieved but unjudged useful page counts as a miss. Neither the source selection nor model pretraining is guaranteed independent. Results are local evidence, not a general accuracy estimate. Labels were fixed before rankings; two physical-page mistakes were corrected during the pre-ranking source audit and recorded in the label file. No labels were revised after retrieval.","",
             "## Corpus and reproducibility", "",
             f"20 public PDFs: 10 university lecture PDFs, 5 research papers, and 5 additional documents. {sum(d['pages'] for d in r['corpus'])} physical pages, with documents ranging from {min(d['pages'] for d in r['corpus'])} to {max(d['pages'] for d in r['corpus'])} pages. Synthetic reliability fixtures are excluded from these counts. There are 42 answerable questions (12 development, 30 test) and 8 no-answer questions (3 development, 5 test). Multiple-page and multiple-document relevance and ambiguous questions are included.","",
             f"Exact model: `{r['model']['model_id']}` revision `{r['model']['revision']}`. Text-only configuration, CUDA BF16, float32 stored vectors, native 768 dimensions. Leading dimensions were sliced and re-normalized on both sides. The 50 ablation queries were each embedded once and reused. No document was re-embedded during search.","",
             "Environment: Windows 11, Ryzen 7 9700X, 16 GB RAM, RTX 5060 Ti 16 GB; exact environment and dependency pins remain in `results/environment.json` and `requirements.lock.txt`. See `evaluation/PHASE3_PROTOCOL.md`, `phase3-corpus.json`, `phase3-queries.json`, and `phase3-label-evidence.json` for the protocol, source URLs, judgments, and inspected page text. Source file hashes and label/protocol SHA256 digests are in `results/phase3-validation.json`.","",
             f"Raw ranked pages, scores and exact passage offsets: `{r['raw_rankings']}`. The immutable development selection is in `{r['library_parent']}\\selection-lock.json` (SHA256 `{r['selection_lock_sha256']}`). Test scores were computed only after writing this lock. All 12 chunk/dimension combinations are descriptive ablations; test results were not used to choose the reported selected hybrid.","",
             "## Metrics and comparisons", "",
             "Page Recall@k = retrieved labeled distinct document/page pairs divided by all labeled relevant pairs for each query, then macro-averaged. Hit@k = queries with any labeled page in the first k results. MRR@5 uses the first relevant page within five results, zero if absent. No-answer questions have undefined recall and are excluded from these positive metrics. One best passage is returned per physical page.","",
             "Keyword = count of distinct non-stoplisted query words in passage text. Raw BM25 preserves the Phase 2 unfiltered FTS5 query. BM25 uses FTS5 Porter stemming, a fixed query stop list, and text/title weights 1.0/0.3. Hybrid fuses semantic and improved BM25 page ranks. No generative model, query rewriting, fabricated passages, or substitute embeddings are used. [SQLite documents the stemming and BM25 functions](https://sqlite.org/fts5.html).", "",
             f"Same chunk size ({s['chunk_tokens']}) and dimensions ({s['dimensions']}) as the development-selected hybrid:","",
             "| Method | Recall@1 | Recall@3 | Recall@5 | Hit@3 | Hit@5 | MRR@5 |",
             "|---|---:|---:|---:|---:|---:|---:|" ]
    for v in rows:
        if v["chunk_tokens"]==s["chunk_tokens"] and v["dimensions"]==s["dimensions"]:
            m=v["metrics"]
            lines.append(f"| {v['mode']} | {pct(m['recall@1'])} | {pct(m['recall@3'])} | {pct(m['recall@5'])} | {pct(m['hit@3'])} | {pct(m['hit@5'])} | {m['mrr@5']:.3f} |")
    diagnostic_path=ROOT/'results/phase3-diagnostics.json'
    diagnostic=json.loads(diagnostic_path.read_text()) if diagnostic_path.is_file() else None
    if diagnostic:
        lines += ["", "Question categories at the selected chunk size/dimensions:", "",
                  "| Method | Category | Queries | Recall@3 | Recall@5 | Hit@5 |", "|---|---|---:|---:|---:|---:|"]
        for row in diagnostic['per_kind']:
            m=row['metrics']
            lines.append(f"| {row['mode']} | {row['kind']} | {row['queries']} | {pct(m['recall@3'])} | {pct(m['recall@5'])} | {pct(m['hit@5'])} |")
    lines += ["", "Full chunk/dimension comparison (same locked fusion parameters for every test configuration):", "",
              "| Tokens | Dimensions | Semantic R@3 / R@5 | BM25 R@3 / R@5 | Hybrid R@3 / R@5 |", "|---:|---:|---:|---:|---:|"]
    for size in (256,512,1024):
        for dim in (768,512,256,128):
            vals = {v["mode"]:v["metrics"] for v in rows if v["chunk_tokens"]==size and v["dimensions"]==dim}
            pair = lambda name:f"{pct(vals[name]['recall@3'])} / {pct(vals[name]['recall@5'])}"
            lines.append(f"| {size} | {dim} | {pair('semantic')} | {pair('bm25')} | {pair('hybrid')} |")
    lines += ["", "## Latency and indexing", "",
              "Warm end-to-end measurements use all 30 answerable test questions through the live Library API, including SQLite reads, vector validation and query inference where required. Each live API ranking was checked against the evaluation snapshot. Cached ablation rank-only timing is separate in the CSV and must not be interpreted as user query latency.","",
              "| Method | Mean ms | p50 ms | p95 ms | Max ms | Mean query encoding ms |", "|---|---:|---:|---:|---:|---:|"]
    for v in r["end_to_end"]:
        lines.append(f"| {v['mode']} | {v['mean_s']*1000:.1f} | {v['p50_s']*1000:.1f} | {v['p95_s']*1000:.1f} | {v['max_s']*1000:.1f} | {v['mean_query_embedding_s']*1000:.1f} |")
    lines += ["", f"Cold local model load: {r['cold_model_load_s']:.2f} s, measured before indexing. All 20 documents were freshly indexed for each chunk size; this run did not copy Phase 2 vectors. Native 768-dimensional indexing:", "",
              "| Tokens | Pages | Chunks | Index s | Embedding s | Pages/s | Chunks/s | Database MiB | Vector MiB | Managed PDFs MiB |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for v in r["runs"]:
        st=v["stats"]
        lines.append(f"| {v['chunk_tokens']} | {st['pages']} | {st['chunks']} | {v['index_s']:.2f} | {v['document_embedding_s']:.2f} | {st['pages']/v['index_s']:.2f} | {st['chunks']/v['index_s']:.2f} | {mib(st['database_bytes'])} | {mib(st['vector_bytes'])} | {mib(st['managed_pdf_bytes'])} |")
    mem=r["memory"]
    lines += ["",f"Peak parent-process RSS: {mib(mem['sampled_peak_process_rss_bytes'])} MiB (50 ms sampling); Torch peak allocated VRAM: {mib(mem['torch_peak_allocated_vram_bytes'])} MiB, reserved: {mib(mem['torch_peak_reserved_vram_bytes'])} MiB. Minimum system available RAM during the run: {mib(mem['minimum_system_available_bytes'])} MiB. These are observed on an active desktop and are not guaranteed minimum hardware requirements. Model cache remains approximately 1.53 GB including multimodal checkpoint weights, despite text-only inference.","",
              "The dimensional sweep uses the native stored vectors, so actual database sizes above are for 768 dimensions. A standalone vector payload would use 4 × chunks × dimensions bytes; the 512/256/128-d payloads are 2/3, 1/3, and 1/6 of 768-d storage. This is an exact byte projection, not a measured smaller SQLite database. Total index size also includes text, two FTS indexes, metadata and SQLite pages/WAL.","",
              "## Integrity and reliability", "",
              f"Verified {sum(v['integrity']['checked_pages'] for v in r['runs'])} persisted page records and {sum(v['integrity']['checked_chunks'] for v in r['runs'])} chunk vectors across the three libraries. All source hashes, physical page numbers, exact passage character offsets, embedding checksums/shapes/finiteness/norms, SQLite foreign keys and both FTS indexes passed. Every live benchmark result's source offsets and `#page=N` URI were checked. **Actual graphical PDF opening/navigation remains untested**; a desktop viewer has not been built.","",
              "All fresh bulk imports completed without a crash. Reimporting all 20 unchanged documents at every chunk size generated zero document embeddings. Empty folders generated no query inference, and hybrid folder isolation passed. Offline model and corpus use were enforced by local-only loading and a Python socket audit guard; the sole blocked event was the deliberate guard probe. Physical network adapters were not disabled, and native-library/child-process networking is outside this guard.", ""]
    statuses = [(v['chunk_tokens'],d['corpus_id'],d['status']) for v in r['runs'] for d in v['documents'] if d['status']!='indexed']
    lines.append("Real-corpus documents with unresolved extraction pages: " + (str(statuses) if statuses else "none classified as partial or failed by the extractor. Formula and reading-order fidelity still need human review."))
    if diagnostic:
        lines += ['',diagnostic['visual_checks']['review']+' Rendered images are retained in `results/phase3-qa/`.']
    restart_path=ROOT/'results/phase3-restart.json'
    if restart_path.is_file():
        restart=json.loads(restart_path.read_text())
        assert restart['passed']
        lines += ['',f"Fresh-process public CLI hybrid search passed in {restart['elapsed_s']:.2f} s including cold startup. It reused the persisted selected index, matched the prior ranked pages/scores, and succeeded with document encoding explicitly forbidden. The Python socket guard recorded only its deliberate probe. See `results/phase3-restart.json` and `.log`. The first harness attempt used a non-reconfigurable stdout buffer and failed before inference; its log is retained as `phase3-restart-attempt01.log`, and the harness was corrected to use a real text stream."]
    xml_path=ROOT/"results/phase3-regression.xml"
    if xml_path.is_file():
        suite=ET.parse(xml_path).getroot()
        suites=list(suite.iter('testsuite'))
        lines += ["",f"Executed regression checks: {sum(int(x.get('tests',0)) for x in suites)} tests, {sum(int(x.get('failures',0))+int(x.get('errors',0)) for x in suites)} failures/errors. See `results/phase3-regression.log` and `.xml`. These include actual model indexing/search, all four dimensions, FTS migration without re-embedding, duplicate upload, updates/removals, folder scope, scanned/empty/malformed files, injected failures, and corruption detection. Injected failures are fault tests, not real OOM/disk-exhaustion measurements. Positive OCR remains untested because language data are absent."]
    lines += ["", "## No-answer behavior", "",
              "There is no calibrated reliable-match threshold. These methods return candidates rather than an answer/no-answer decision. Withholding source-grounded confidence in the CLI remains necessary. Five test no-answer questions:","",
              "| Method | Questions returning candidates | Candidate false-positive rate if treated as answers |", "|---|---:|---:|"]
    for v in rows:
        if v['chunk_tokens']==s['chunk_tokens'] and v['dimensions']==s['dimensions']:
            count=sum(n['candidate_count']>0 for n in v['no_answer'])
            lines.append(f"| {v['mode']} | {count}/{len(v['no_answer'])} | {pct(count/len(v['no_answer']))} |")
    lines += ["", "No-answer maximum semantic cosines for the selected configuration:", ""]
    for n in selected['no_answer']:
        lines.append(f"- `{n['query_id']}`: {n['maximum_cosine']:.4f}")
    lines += ["", "## Failures to inspect", "",
              "Lowest-recall selected-hybrid test queries (labels kept unchanged; missing labeled pages can include redundant alternatives):", ""]
    failures=sorted((v for v in chosen if 'metrics' in v and v['metrics']['recall@5']<1),key=lambda v:(v['metrics']['recall@5'],v['query_id']))
    for v in failures[:10]:
        q=by_id[v['query_id']]
        expected=', '.join(f"{x['document']} p{x['page']}" for x in q['relevant'])
        actual=', '.join(f"{x['document']} p{x['page']}" for x in v['results'][:5])
        lines += [f"- **{v['query_id']}**: {q['query']} Page R@5 {pct(v['metrics']['recall@5'])}. Labeled: {expected}. Retrieved: {actual}."]
    if diagnostic:
        lines += ['', 'Source-checked failure investigation (post-test diagnostics; settings and labels are unchanged):','']
        for finding in diagnostic['source_inspection_findings']:
            lines.append(f"- **{finding['case']}**: {finding['finding']}")
        lines += ['',f"The general Z-delay rule has improved-BM25 rank {diagnostic['z_delay_bm25_general_rule_rank']}, so it is inside the 100-page fusion pool. Its demotion is caused by fusion ranking rather than candidate truncation. Across the test set, fusion lowers Recall@3 on {len(diagnostic['fusion_regressions'])} questions relative to semantic search at the same dimensions. The mathematical maximum mean page Recall@3 for these labels is {pct(diagnostic['maximum_possible_page_recall']['3'])}, and Recall@5 is {pct(diagnostic['maximum_possible_page_recall']['5'])}; the actual failure is not explained solely by the five-result limit. Full diagnostics are in `results/phase3-diagnostics.json`."]
    lines += ["", "## Decision and limits", "",
              "Do not declare the retrieval gate passed merely because all code executed or hit rate is high. The strict gate status above follows the frozen page-recall targets. The small, non-exhaustive judgments need independent review; broad questions with more than five labeled relevant pages cannot reach full Recall@5, and redundant slide builds can occupy several results. Query confidence/rejection is not solved by reciprocal rank fusion. The snapshot-based engine loads the scoped corpus into RAM for each live query; larger-library memory behavior is a Phase 4 measurement, not established here.","",
              "Next experiments: independently audit a pool of top-ten results from every ranker and expand relevance judgments while preserving this run; evaluate passage/answer-unit relevance in addition to page recall; test fusion with a broader development set, requiring Recall@3 >=80% without reducing Recall@5 below 90% on a new held-out set; evaluate document diversity and duplicate-aware presentation with separate coverage/utility metrics, since suppressing labeled duplicate pages can lower page recall. Calibrate a no-answer policy with in-domain missing-fact questions as well as unrelated negatives, using separate development/test sets and reporting rejection errors. Inspect mathematical text extraction and compare page-aware section context. Do not tune further on these test labels and call the result held-out. Scaling to 50/100/500 PDFs, CPU retrieval comparisons, positive OCR, physical-disconnection testing, UI and end-to-end viewer navigation remain outstanding. Android remains blocked pending the full PC validation report and explicit approval.","",
              "Reproduce (PowerShell, from the project directory):", "", "```powershell",
              ".venv\\Scripts\\python.exe scripts\\download_phase2_corpus.py --manifest evaluation/phase3-corpus.json --evidence results/phase3-corpus-downloads.json",
              ".venv\\Scripts\\python.exe -m pytest tests/test_phase2.py tests/test_phase3.py -q --junitxml=results/phase3-regression.xml",
              ".venv\\Scripts\\python.exe scripts\\validate_phase3.py",
              ".venv\\Scripts\\python.exe scripts\\diagnose_phase3.py",
              ".venv\\Scripts\\python.exe scripts\\phase3_restart_probe.py",
              ".venv\\Scripts\\python.exe scripts\\summarize_phase3.py", "```", "",
              "Each validation creates a new library directory. Frozen labels are stored evaluation inputs; do not rerun the label-preparation helper over an existing set. All searches/indexing after the one-time downloads run from cached local files. CSV/JSON/raw ranks/logs are retained under `results/` and the run directory.", ""]
    (ROOT/"results/PHASE3_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"gate":r['quality_gate'],"selected":s,"report":str(ROOT/'results/PHASE3_REPORT.md')},indent=2))


if __name__=="__main__":
    main()
