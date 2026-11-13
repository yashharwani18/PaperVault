"""Index six real PDFs with each chunk size and record functional retrieval evidence."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_embedding_model import ResourceSampler, deny_python_network, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-sizes", type=int, nargs="+", default=[256,512,1024], choices=[256,512,1024])
    parser.add_argument("--output", type=Path, default=ROOT / "results/phase2-validation.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    blocked = []
    deny_python_network(blocked)
    import numpy as np
    import psutil
    sampler = ResourceSampler(psutil)
    sampler.start()
    from knowledge_library.embedding import EmbeddingGemma, LOCK
    from knowledge_library.chunking import ChunkingConfig
    from knowledge_library.library import Library
    manifest = json.loads((ROOT / "evaluation/phase2-corpus.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "evaluation/phase2-queries.json").read_text(encoding="utf-8"))
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    report = {"status":"running", "recorded_at":dt.datetime.now(dt.timezone.utc).isoformat(),
              "scope":"Phase 2 functional validation only; Phase 3 accuracy targets remain unevaluated",
              "model":LOCK, "runs":[], "library_parent":str(ROOT / "data/phase2-validation" / run_id),
              "offline":{"python_socket_guard":True,"physical_disconnection":False}}
    model = EmbeddingGemma(device="cuda", batch_size=8)
    started = time.perf_counter()
    try:
        for size in args.chunk_sizes:
            root = Path(report["library_parent"]) / f"chunk-{size}"
            run = {"chunk_tokens":size,"overlap_tokens":64,"library":str(root),"documents":[],"searches":[]}
            report["runs"].append(run)
            write_json(args.output, report)
            with Library(root, model) as lib:
                folders = {name:lib.create_folder(name)["id"] for name in sorted({d["folder"] for d in manifest["documents"]})}
                ids = {}
                index_start = time.perf_counter()
                for entry in manifest["documents"]:
                    print(f"[{size}] Indexing {entry['id']}", flush=True)
                    source = ROOT / "corpus/pdfs" / f"{entry['id']}.pdf"
                    with source.open("rb") as stream:
                        source_sha = hashlib.file_digest(stream,"sha256").hexdigest()
                    outcome = lib.import_pdf(source, folders[entry["folder"]], title=entry["title"],
                                             chunking=ChunkingConfig(size,64))
                    doc = outcome["document"]
                    ids[entry["id"]] = doc["id"]
                    run["documents"].append({"corpus_id":entry["id"],"document_id":doc["id"],"pages":doc["page_count"],
                                              "chunks":doc["chunk_count"],"status":doc["status"],"source_sha256":source_sha,
                                              "index_s":outcome["elapsed_s"],"page_status_counts":dict(__import__('collections').Counter(p["status"] for p in lib.page_summary(doc["id"]))),
                                              "embeddings_generated":outcome["document_embeddings_generated"]})
                    if doc["status"] not in ("indexed","partial"):
                        raise AssertionError(f"Real document {entry['id']} has no indexed passages")
                    write_json(args.output, report)
                run["indexing_s"] = time.perf_counter() - index_start
                before = model.stats["document_texts_encoded"]
                for label in labels["queries"]:
                    response = lib.search(label["query"],top_k=5)
                    # Ground truth was selected by inspecting sources, never inferred from results.
                    page_hit = any(r["document_id"] == ids[label["document"]] and r["page_number"] in label["pages"] for r in response["results"])
                    doc_hit = any(r["document_id"] == ids[label["document"]] for r in response["results"])
                    compact = [{k:r[k] for k in ("document_id","filename","page_number","page_label","chunk_index","score","rank")} for r in response["results"]]
                    run["searches"].append({"id":label["id"],"query":label["query"],"expected_document":label["document"],
                                             "expected_pages":label["pages"],"document_in_top5":doc_hit,"labeled_page_in_top5":page_hit,
                                             "elapsed_s":response["elapsed_s"],"query_embedding_s":response["query_embedding_s"],"results":compact})
                    print(f"[{size}] {label['id']}: document={doc_hit}, labeled page={page_hit}, {response['elapsed_s']*1000:.1f}ms", flush=True)
                isolated = lib.search("nonregular languages",folder_id=folders["TOC"])
                run["folder_isolation"] = bool(isolated["results"]) and all(r["folder_id"] == folders["TOC"] for r in isolated["results"])
                empty = lib.create_folder("Empty")["id"]
                query_calls = model.stats["query_texts_encoded"]
                run["empty_scope"] = lib.search("anything",folder_id=empty)["empty_reason"] == "empty_scope"
                run["empty_scope_no_inference"] = query_calls == model.stats["query_texts_encoded"]
                run["searches_do_not_reembed_documents"] = before == model.stats["document_texts_encoded"]
                run["integrity"] = lib.verify()
                refresh_before = model.stats["document_texts_encoded"]
                unchanged = [lib.import_pdf(ROOT/"corpus/pdfs"/f"{entry['id']}.pdf", folders[entry["folder"]],
                                            title=entry["title"],chunking=ChunkingConfig(size,64))["action"] for entry in manifest["documents"]]
                run["unchanged_reimport"] = {"actions":unchanged,"no_new_embeddings":refresh_before == model.stats["document_texts_encoded"]}
                run["stats"] = lib.stats()
                run["sample_query_mean_s"] = statistics.mean(s["elapsed_s"] for s in run["searches"])
                run["sample_query_p95_s"] = float(np.percentile([s["elapsed_s"] for s in run["searches"]],95))
                run["document_smoke_hits"] = sum(s["document_in_top5"] for s in run["searches"])
                run["page_smoke_hits"] = sum(s["labeled_page_in_top5"] for s in run["searches"])
                run["functional_checks_passed"] = all((run["folder_isolation"],run["empty_scope"],run["empty_scope_no_inference"],
                     run["searches_do_not_reembed_documents"],run["integrity"]["passed"],run["unchanged_reimport"]["no_new_embeddings"],
                     all(a=="unchanged" for a in unchanged),run["document_smoke_hits"]==len(labels["queries"])))
            write_json(args.output, report)
        if len(blocked) != 1:
            raise AssertionError("An unexpected network attempt occurred during real PDF indexing/search")
        # Restart using persisted SQL/vector files, with no indexing call in the child.
        baseline_run = next((r for r in report["runs"] if r["chunk_tokens"]==512), report["runs"][0])
        restart_output = args.output.with_name("phase2-restart.json")
        child = subprocess.run([sys.executable,str(ROOT/"scripts/phase2_restart_probe.py"),
                                baseline_run["library"],str(restart_output)],cwd=ROOT,capture_output=True,
                               text=True,encoding="utf-8",errors="replace",timeout=180)
        (ROOT/"results/phase2-restart.log").write_text(child.stdout+child.stderr,encoding="utf-8")
        if child.returncode:
            raise AssertionError("Fresh-process persisted search failed: " + child.stdout + child.stderr)
        report["restart"] = json.loads(restart_output.read_text(encoding="utf-8"))
        expected = baseline_run["searches"][0]["results"]
        actual = report["restart"]["results"]
        same = len(actual)==len(expected) and all(
            a["document_id"]==b["document_id"] and a["page_number"]==b["page_number"] and
            abs(a["score"]-b["score"])<=1e-5 for a,b in zip(actual,expected))
        if not same:
            raise AssertionError("Fresh-process result identities or scores differ from the prior persisted search")
        report["restart"]["matches_prior_search"] = True
        report["status"] = "passed" if all(r["functional_checks_passed"] for r in report["runs"]) else "failed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = {"message":str(exc),"traceback":traceback.format_exc()}
        print(traceback.format_exc(),file=sys.stderr)
    finally:
        report["elapsed_s"] = time.perf_counter()-started
        report["memory"] = sampler.stop()
        report["offline"]["blocked_socket_events"] = len(blocked)
        report["embedding_runtime"] = dict(model.stats)
        if model._torch is not None:
            report["memory"].update(torch_peak_allocated_vram_bytes=model._torch.cuda.max_memory_allocated(),
                                     torch_peak_reserved_vram_bytes=model._torch.cuda.max_memory_reserved())
        write_json(args.output, report)
        print(f"Phase 2 functional validation: {report['status']}; evidence: {args.output}",flush=True)
    return 0 if report["status"]=="passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
