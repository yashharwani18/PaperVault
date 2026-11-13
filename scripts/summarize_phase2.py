"""Build a readable Phase 2 report and CSV from executed validation artifacts."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def main():
    report = json.loads((RESULTS/"phase2-validation.json").read_text(encoding="utf-8"))
    corpus = json.loads((ROOT/"evaluation/phase2-corpus.json").read_text(encoding="utf-8"))
    junit_path = RESULTS/"phase2-pytest.xml"
    suites = list(ET.parse(junit_path).getroot().iter("testsuite")) if junit_path.is_file() else []
    tested = sum(int(s.attrib.get("tests",0)) for s in suites)
    errors = sum(int(s.attrib.get("errors",0))+int(s.attrib.get("failures",0))+int(s.attrib.get("skipped",0)) for s in suites)
    baseline = next((r for r in report["runs"] if r["chunk_tokens"]==512), report["runs"][0])
    expected = baseline["searches"][0]["results"]
    actual = report.get("restart",{}).get("results",[])
    restart_matches = len(actual)==len(expected) and bool(actual) and all(
        a["document_id"]==b["document_id"] and a["page_number"]==b["page_number"] and
        abs(a["score"]-b["score"])<=1e-5 for a,b in zip(actual,expected))
    gate = report["status"]=="passed" and tested>0 and errors==0 and restart_matches
    fields = ["chunk_tokens","overlap_tokens","documents","pages","chunks","indexing_s","indexing_s_per_page",
              "query_mean_ms","query_p95_ms","document_smoke_hits_of_6","labeled_page_smoke_hits_of_6","database_bytes","vector_bytes","managed_pdf_bytes"]
    rows = []
    for run in report["runs"]:
        stats = run.get("stats",{})
        pages = stats.get("pages",0)
        rows.append({"chunk_tokens":run["chunk_tokens"],"overlap_tokens":run["overlap_tokens"],"documents":stats.get("documents"),
                     "pages":pages,"chunks":stats.get("chunks"),"indexing_s":run.get("indexing_s"),
                     "indexing_s_per_page":run.get("indexing_s",0)/pages if pages else None,
                     "query_mean_ms":run.get("sample_query_mean_s",0)*1000,"query_p95_ms":run.get("sample_query_p95_s",0)*1000,
                     "document_smoke_hits_of_6":run.get("document_smoke_hits"),"labeled_page_smoke_hits_of_6":run.get("page_smoke_hits"),
                     "database_bytes":stats.get("database_bytes"),"vector_bytes":stats.get("vector_bytes"),"managed_pdf_bytes":stats.get("managed_pdf_bytes")})
    with (RESULTS/"phase2-benchmarks.csv").open("w",newline="",encoding="utf-8") as output:
        writer=csv.DictWriter(output,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    lines=["# Phase 2 — real PDF retrieval engine", "",
           f"**Functional gate: {'PASS' if gate else 'NOT PASSED'}.** Evidence timestamp: {report['recorded_at']}.", "",
           "This phase validates the non-graphical retrieval engine. It does not satisfy the Phase 3 dataset/accuracy targets, "
           "approve a desktop UI, or authorize Android development.", "",
           "## Implemented and executed", "",
           "- Local-only EmbeddingGemma 2 at the Phase 1 pinned revision, text-only encoders, BF16 on the detected RTX 5060 Ti, normalized float32 vectors. "
           "Query prompts use `SearchQuery`; titled passages use Google's title/text format. Model files are verified by SHA256 before local loading.",
           "- SQLite metadata, page text, embedding recipe/version/dimensions and float32 vector BLOBs; bounded batches of exact cosine search. "
           "All original filenames, current folders, one-based physical pages, PDF logical page labels and character offsets accompany results. "
           "Missing PDF labels fall back to the physical page number; printed footers are not inferred.",
           "- 256/512/1024-token, page-contained chunks with overlap. Sentence/newline boundaries are preferred within the token budget. "
           "Long files are extracted page by page, embedded in small batches and staged on disk; the full corpus never becomes one model input.",
           "- Folder creation, rename and empty-folder deletion; import, bulk import, replacement/refresh, document moves, explicit removal and missing-source sync. "
           "Unchanged files skip inference. Identical content and recipe across folders reuses stored embeddings.",
           "- Document replacement commits its new metadata/pages/vectors and completed indexing job atomically. SQL or inference failure leaves the prior index searchable. "
           "Dead-process jobs become interrupted on reopening. Source PDFs are copied locally, never modified.",
           "- A CLI, diagnostic BM25 mode via SQLite FTS5, and an integrity command checking PDF hashes, source pages, vector checksums/unit norms and exact passage offsets.", "",
           "## Actual corpus", "", "| Document | Type | Pages |", "| --- | --- | ---: |"]
    first=report["runs"][0] if report["runs"] else {}
    by_id={d["corpus_id"]:d for d in first.get("documents",[])}
    for doc in corpus["documents"]:
        lines.append(f"| [{doc['title']}]({doc['source_url']}) | {doc['kind']} | {by_id.get(doc['id'],{}).get('pages','not indexed')} |")
    lines += ["", "Original downloads and SHA256 provenance are recorded in `results/phase2-corpus-downloads.json`. "
              "These six files are the functional corpus; synthetic reliability fixtures are separate and are not counted as real evaluation documents.", "",
              "## Measured runs", "", "| Tokens / overlap | PDFs / pages | Chunks | Index s | Mean / p95 search ms | Expected doc in top 5 | Labeled page in top 5 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| {row['chunk_tokens']} / {row['overlap_tokens']} | {row['documents']} / {row['pages']} | {row['chunks']} | "
                     f"{row['indexing_s']:.2f} | {row['query_mean_ms']:.2f} / {row['query_p95_ms']:.2f} | "
                     f"{row['document_smoke_hits_of_6']}/6 | {row['labeled_page_smoke_hits_of_6']}/6 |")
    lines += ["", "Search timings include one actual query embedding and persisted-vector retrieval, with the model already loaded. "
              "There is no query embedding cache. Each mean/p95 uses only six different functional questions, so these are preliminary measurements. "
              "The first chunk-size run includes model initialization during indexing; subsequent runs reuse that model. Index-time comparisons are not controlled benchmarks. "
              "CSV database bytes include SQLite's database, WAL and SHM at measurement time; this is active disk footprint, not a compacted database size.", "",
              "The six questions and preselected source-page relevance labels are in `evaluation/phase2-queries.json`. "
              "Labels were chosen by reading sources before running retrieval. They are small, non-exhaustive functional checks, not the required 30-query ground truth. "
              "Expected-document hits and exact labeled-page hits are reported separately. Source-page integrity checks verify that returned passages originate "
              "at the stated page; they do not establish whether a passage answers the question.", "",
              "## Unmet page labels", ""]
    misses=[]
    for run in report["runs"]:
        for search in run.get("searches",[]):
            if not search["labeled_page_in_top5"]:
                ranked=", ".join(f"{r['filename']} p.{r['page_number']}" for r in search["results"])
                misses.append(f"- {run['chunk_tokens']} tokens, `{search['id']}`: labeled physical pages {search['expected_pages']}; retrieved {ranked}.")
    lines += misses or ["None in this small functional set."]
    lines += ["", "Manual follow-up inspection: the pumping query's top result, physical page 43, applies the pumping lemma "
              "to long accepted words in the finiteness problem; it is relevant to the question even though the small labels "
              "specified the statement/proof on pages 18–19. The original labels and strict miss counts are unchanged. "
              "For convolution, the 512/1024-token runs instead returned a cluster of time-scaling slides, which does not answer "
              "the selected question. This is a real relevance failure. Near-duplicate slide builds can also crowd the top five."]
    lines += ["", "These misses remain recorded. Do not infer general retrieval quality or superiority over BM25 from this phase. "
              "Inspect alternative pages and build complete relevance judgments in Phase 3 before choosing chunk size or a no-match threshold.", "",
              "## Reliability and persistence", "",
              f"pytest: {tested} tests; {errors} combined failures/errors/skips. The final full run includes the Phase 1 regression test. "
              "See `phase2-pytest.xml` and `phase2-pytest.log`.", ""]
    for run in report["runs"]:
        integrity=run.get("integrity",{})
        lines.append(f"- {run['chunk_tokens']} tokens: integrity={integrity.get('passed')}; checked {integrity.get('checked_pages')} pages and "
                     f"{integrity.get('checked_chunks')} chunks. Folder isolation={run.get('folder_isolation')}; empty scope without inference="
                     f"{run.get('empty_scope_no_inference')}; searches did not re-embed documents={run.get('searches_do_not_reembed_documents')}; "
                     f"unchanged reimports generated no new embeddings={run.get('unchanged_reimport',{}).get('no_new_embeddings')}.")
    restart=report.get("restart",{})
    lines += [f"- Fresh-process offline persisted search: {restart.get('passed',False)}; "
              f"{restart.get('documents','?')} documents / {restart.get('scoped_chunks','?')} persisted chunks; "
              f"{restart.get('embedding_runtime',{}).get('document_texts_encoded','?')} document embeddings regenerated. "
              f"Result IDs, pages and scores match the prior search within 1e-5: {restart_matches}. "
              "This comparison is also recomputed directly from the execution artifacts by this report generator. See `phase2-restart.json` and `.log`.", "",
              "Reliability tests use actual embeddings for successful indexing and retrieval. They cover Unicode, page offsets, empty/scanned/mixed PDFs, "
              "malformed/encrypted input, duplicate imports, unusual filenames, refresh/move/removal, missing originals, SQLite rollback, corrupted stored vectors "
              "and dead-job recovery. Allocation failure, SQL write failure and low storage are explicit fault injections; no physical disk-full or real GPU-OOM "
              "stress test was performed. The interrupted-job test terminates a child after creating its job record, not in the middle of a CUDA kernel.", "",
              "## Diagnosed defects", "",
              "- Coordinate text sorting garbled a 90-degree MIT slide and interleaved BERT's two columns. Extraction now preserves PDF content-stream order. "
              "Regression tests assert coherent source phrases; source pages were rendered and visually checked under `results/phase2-qa/`.",
              "- Windows rejected moving a PDF while PyMuPDF held it open. Publication now occurs after closing the document.",
              "- Image-only scans covering less than 40% of a page were initially classified as empty. Image-only pages are now flagged `needs_ocr`.",
              "- Malformed-file native exception tracebacks can keep a Windows handle open. Cleanup errors now remain diagnostic job details and cannot mask "
              "the original parse error. Temporary snapshots may remain in staging until the handle is released; automatic orphan cleanup is not implemented.",
              "", "Original failed test logs are retained as `phase2-attempt-01.*` and `phase2-attempt-02.*`.", "",
              "## Resources and remaining limits", ""]
    memory=report.get("memory",{})
    peak=max(memory.get("sampled_peak_process_rss_bytes",0),memory.get("os_peak_process_working_set_bytes") or 0)
    lines += [f"- Parent validation process peak working set: {peak/2**20:.2f} MiB. "
              f"Torch peak allocated/reserved VRAM: {memory.get('torch_peak_allocated_vram_bytes',0)/2**20:.2f} / "
              f"{memory.get('torch_peak_reserved_vram_bytes',0)/2**20:.2f} MiB. Torch peaks exclude driver/context and other apps; "
              "the child restart's private working set is not included in the parent process peak.",
              "- Tesseract/language data is absent on this machine. Scan detection and OCR failure reporting were executed; positive OCR recognition is implemented "
              "through PyMuPDF's optional API but untested. OCR confidence is unavailable and never fabricated. Pages requiring OCR are excluded from embeddings; "
              "mixed documents expose partial status. Handwritten mathematics and arbitrary layout reconstruction remain unproven.",
              "- Search returns ranked candidates with an explicit uncalibrated-relevance notice. An optional cosine cutoff is supported; no automatic no-match "
              "cutoff has been justified. BM25 exists for diagnostics, but keyword/BM25/hybrid comparisons and dimension ablations remain Phase 3 work.",
              "- Physical network adapters were not disabled. Validation and the restart child use the Phase 1 Python socket guard and local-only model loading. "
              "Full application testing while physically disconnected remains pending.",
              "- Removal deletes document metadata/pages/vectors. Source originals and managed snapshots are retained, including superseded/orphan copies. "
              "Secure erasure and orphan garbage collection are not implemented.",
              "- Page locators contain the actual stored PDF path, physical page and PDF logical label (with physical-number fallback). PDF page integrity is tested; no graphical viewer "
              "or click-to-open navigation has been built or claimed tested.", "",
              "## Reproduce and use", "",
              "Run from the project root: `.venv\\Scripts\\python.exe -m pytest -m phase2 -q --junitxml=results/phase2-pytest.xml`, "
              "then `.venv\\Scripts\\python.exe scripts\\validate_phase2.py` and `.venv\\Scripts\\python.exe scripts\\summarize_phase2.py`. "
              "Cached corpus PDFs and the Phase 1 model are sufficient; inference makes no external API calls. README contains import/search examples.", "",
              "Validated library directories:", ""]
    lines += [f"- `{run['library']}`" for run in report["runs"]]
    lines += ["", "Machine-readable evidence: `phase2-validation.json`, `phase2-benchmarks.csv`, `phase2-restart.json`, "
              "the corpus download manifest, JUnit XML, and corresponding logs. Each library persists its full source pages/vectors in SQLite.", "",
              "## Next gate", "",
              "Phase 3: expand to at least 10 lecture PDFs, 5 papers and 5 additional documents; create at least 30 manually verified relevance queries; "
              "compare keyword, BM25, semantic and hybrid search with chunk/dimension ablations. "
              "The 90% Recall@5 and 80% Recall@3 targets remain unevaluated. Desktop UI and Android remain unstarted.", "",
              "## Primary documentation", "",
              "- [PyMuPDF text extraction](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)",
              "- [PyMuPDF optional OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)",
              "- [Google's EmbeddingGemma 2 inference guide](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers)",
              "- Exact dependency versions: `requirements.lock.txt`; added PyMuPDF 1.28.2. Phase 1 model dependencies were not upgraded.", ""]
    if report.get("error"):
        lines += ["## Validation failure", "", report["error"]["message"], ""]
    (RESULTS/"PHASE2_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"Phase 2 functional gate: {'PASS' if gate else 'NOT PASSED'}")
    print(f"Saved {RESULTS/'PHASE2_REPORT.md'} and phase2-benchmarks.csv")
    return 0 if gate else 1


if __name__=="__main__":
    raise SystemExit(main())
