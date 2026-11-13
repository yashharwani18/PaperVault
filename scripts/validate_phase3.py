"""Real offline indexing and frozen-label retrieval comparison. No UI or Android."""
from __future__ import annotations
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_embedding_model import ResourceSampler, deny_python_network, write_json
from evaluation.metrics import aggregate, query_metrics


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def compact(index, ranking, mapping, limit=10):
    return [{"document":mapping[index.rows[i]["document_id"]],"page":index.rows[i]["page_number"],
             "chunk_id":index.rows[i]["id"],"score":float(score),
             "char_start":index.rows[i]["char_start"],"char_end":index.rows[i]["char_end"]}
            for i,score in ranking[:limit]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    output = ROOT/"results/phase3-validation.json"
    blocked = []
    deny_python_network(blocked)
    import numpy as np
    import psutil
    from knowledge_library.library import Library
    from knowledge_library.embedding import EmbeddingGemma, LOCK
    from knowledge_library.chunking import ChunkingConfig
    from knowledge_library.retrieval import SearchIndex, reciprocal_rank_fusion
    from knowledge_library.pdf import open_pdf, native_text
    sampler = ResourceSampler(psutil)
    sampler.start()
    started = time.perf_counter()
    model = EmbeddingGemma(device="cuda",batch_size=8)
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6]
    parent = ROOT/"data/phase3-validation"/run_id
    parent.mkdir(parents=True)
    manifest = json.loads((ROOT/"evaluation/phase3-corpus.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT/"evaluation/phase3-queries.json").read_text(encoding="utf-8"))
    report = {"status":"running","recorded_at":dt.datetime.now(dt.timezone.utc).isoformat(),"model":LOCK,
              "library_parent":str(parent),"runs":[],"development":[],"test":[],"end_to_end":[],
              "hashes":{name:sha(ROOT/"evaluation"/name) for name in ("phase3-corpus.json","phase3-queries.json","phase3-label-evidence.json","PHASE3_PROTOCOL.md")},
              "offline":{"python_socket_guard":True,"physical_disconnection":False},
              "judgment_provenance":labels["judgment_provenance"],"judgment_scope":labels["judgment_scope"]}
    write_json(output,report)
    raw_path = parent/"rankings.jsonl"
    try:
        # Confirm labels refer to the actual cached originals, before any ranking.
        evidence = json.loads((ROOT/"evaluation/phase3-label-evidence.json").read_text(encoding="utf-8"))
        for entry in manifest["documents"]:
            source = ROOT/"corpus/pdfs"/(entry["id"]+".pdf")
            entry["sha256"] = sha(source)
            with open_pdf(source) as pdf:
                entry["pages"] = len(pdf)
                for ev in (ev for ev in evidence if ev["document"]==entry["id"]):
                    assert hashlib.sha256(native_text(pdf[ev["physical_page"]-1]).encode()).hexdigest()==ev["page_text_sha256"]
        report["corpus"] = manifest["documents"]
        report["labels_verified_against_sources"] = len(evidence)
        model.load()
        report["cold_model_load_s"] = model.stats["model_load_s"]
        for size in (256,512,1024):
            run = {"chunk_tokens":size,"overlap_tokens":64,"library":str(parent/f"chunk-{size}"),"documents":[]}
            report["runs"].append(run)
            with Library(run["library"],model) as lib:
                folders = {name:lib.create_folder(name)["id"] for name in sorted({d["folder"] for d in manifest["documents"]})}
                before = dict(model.stats)
                index_start = time.perf_counter()
                for entry in manifest["documents"]:
                    result = lib.import_pdf(ROOT/"corpus/pdfs"/(entry["id"]+".pdf"),folders[entry["folder"]],
                                            title=entry["title"],chunking=ChunkingConfig(size,64))
                    doc = result["document"]
                    run["documents"].append({"corpus_id":entry["id"],"document_id":doc["id"],"pages":doc["page_count"],
                                             "chunks":doc["chunk_count"],"status":doc["status"],"index_s":result["elapsed_s"],
                                             "embeddings_generated":result["document_embeddings_generated"]})
                    assert doc["status"] in ("indexed","partial"), (entry,doc)
                    print(f"[{size}] {entry['id']}: {doc['page_count']} pages, {doc['chunk_count']} chunks, {result['elapsed_s']:.2f}s",flush=True)
                    write_json(output,report)
                run["index_s"] = time.perf_counter()-index_start
                run["document_embedding_s"] = model.stats["document_embedding_s"]-before["document_embedding_s"]
                run["integrity"] = lib.verify()
                assert run["integrity"]["passed"],run["integrity"]
                calls = model.stats["document_texts_encoded"]
                actions = [lib.import_pdf(ROOT/"corpus/pdfs"/(e["id"]+".pdf"),folders[e["folder"]],title=e["title"],
                                         chunking=ChunkingConfig(size,64))["action"] for e in manifest["documents"]]
                run["unchanged_reimports"] = {"all_unchanged":all(a=="unchanged" for a in actions),"new_document_inference":model.stats["document_texts_encoded"]-calls}
                assert run["unchanged_reimports"]=={"all_unchanged":True,"new_document_inference":0}
                empty = lib.create_folder("Empty")["id"]
                calls = dict(model.stats)
                run["empty_scope"] = lib.search("anything at all",folder_id=empty,mode="hybrid")
                assert run["empty_scope"]["empty_reason"]=="empty_scope" and calls==model.stats
                run["stats"] = lib.stats()
            write_json(output,report)
        before_queries = model.stats["document_texts_encoded"]
        query_vectors, query_times = {}, {}
        for q in labels["queries"]:
            t = time.perf_counter()
            query_vectors[q["id"]] = model.query(q["query"])
            query_times[q["id"]] = time.perf_counter()-t
        np.savez_compressed(parent/"query-vectors.npz",**query_vectors)
        report["query_encoding"] = {"count":len(query_vectors),"per_query_s":query_times,
                                    "reuse":"One actual 768-d query embedding per question, reused across all ranking ablations; not end-to-end timings"}

        def evaluate(split, selected=None):
            summary = []
            questions = [q for q in labels["queries"] if q["split"]==split]
            with raw_path.open("a",encoding="utf-8") as raw:
                for run in report["runs"]:
                    mapping = {d["document_id"]:d["corpus_id"] for d in run["documents"]}
                    with Library(run["library"],model) as lib:
                        init = time.perf_counter()
                        index = SearchIndex(lib)
                        snapshot_s = time.perf_counter()-init
                        lexical = {q["id"]:{mode:index.lexical(q["query"],mode=mode) for mode in ("keyword","bm25_raw","bm25")} for q in questions}
                        for dim in (768,512,256,128):
                            settings = [(m,None) for m in ("keyword","bm25_raw","bm25","semantic")]
                            hybrids = [dict(semantic_weight=w,rank_constant=k,candidates=100) for w,k in itertools.product((.25,.5,.75),(10,60))] if split=="dev" else [selected["hybrid"]]
                            settings += [("hybrid",h) for h in hybrids]
                            semantic = {q["id"]:index.semantic(query_vectors[q["id"]],dim) for q in questions}
                            for mode,hybrid in settings:
                                rows, negatives, times = [], [], []
                                for q in questions:
                                    if mode=="hybrid":
                                        ranking = reciprocal_rank_fusion(index.rows,semantic[q["id"]],lexical[q["id"]]["bm25"],**hybrid)
                                    elif mode=="semantic":ranking = semantic[q["id"]]
                                    else:ranking = lexical[q["id"]][mode]
                                    # Time the actual shared rank method, including matrix/lexical work, on a cached snapshot.
                                    t = time.perf_counter()
                                    timed = index.rank(q["query"],mode=mode,vector=query_vectors[q["id"]],dimensions=dim,hybrid=hybrid)
                                    times.append(time.perf_counter()-t)
                                    assert ranking[:5]==timed[:5]
                                    hits = compact(index,ranking,mapping)
                                    rec = {"split":split,"chunk_tokens":run["chunk_tokens"],"dimensions":dim,"mode":mode,"hybrid":hybrid,
                                           "query_id":q["id"],"results":hits,"rank_only_s":times[-1]}
                                    if q["relevant"]:
                                        rec["metrics"] = query_metrics(q["relevant"],hits)
                                        rows.append(rec["metrics"])
                                    else:
                                        neg = {"query_id":q["id"],"candidate_count":min(5,len(hits)),
                                               "maximum_cosine":float(semantic[q["id"]][0][1]) if semantic[q["id"]] else None}
                                        negatives.append(neg)
                                    raw.write(json.dumps(rec)+"\n")
                                summary.append({"chunk_tokens":run["chunk_tokens"],"dimensions":dim,"mode":mode,"hybrid":hybrid,
                                                "answerable_queries":len(rows),"metrics":aggregate(rows),"no_answer":negatives,
                                                "cached_snapshot_init_s":snapshot_s,"rank_only_mean_s":float(np.mean(times)),"rank_only_p95_s":float(np.percentile(times,95))})
                    print(f"{split}: finished chunk size {run['chunk_tokens']}",flush=True)
            return summary

        report["development"] = evaluate("dev")
        hybrids = [r for r in report["development"] if r["mode"]=="hybrid"]
        chunk_counts = {r["chunk_tokens"]:r["stats"]["chunks"] for r in report["runs"]}
        selected = max(hybrids,key=lambda r:(r["metrics"]["recall@5"],r["metrics"]["recall@3"],r["metrics"]["mrr@5"],-r["dimensions"]*chunk_counts[r["chunk_tokens"]],r["chunk_tokens"]))
        report["selected"] = {k:selected[k] for k in ("chunk_tokens","dimensions","mode","hybrid","metrics")}
        selection = {"locked_at":dt.datetime.now(dt.timezone.utc).isoformat(),"selection_split":"dev only; no test ranking run yet",
                     "hashes":report["hashes"],"selected":report["selected"]}
        write_json(parent/"selection-lock.json",selection)
        report["selection_lock_sha256"] = sha(parent/"selection-lock.json")
        write_json(output,report)
        report["test"] = evaluate("test",selected)
        target = next(r for r in report["test"] if all(r[k]==selected[k] for k in ("chunk_tokens","dimensions","mode","hybrid")))
        report["quality_gate"] = {"recall@5_target":.90,"recall@3_target":.80,"observed":target["metrics"],
                                  "passed":target["metrics"]["recall@5"]>=.90 and target["metrics"]["recall@3"]>=.80}
        chosen_run = next(r for r in report["runs"] if r["chunk_tokens"]==selected["chunk_tokens"])
        with Library(chosen_run["library"],model) as lib:
            mapping = {d["document_id"]:d["corpus_id"] for d in chosen_run["documents"]}
            snapshot = SearchIndex(lib)
            for mode in ("keyword","bm25_raw","bm25","semantic","hybrid"):
                times, encode_times = [], []
                for q in (q for q in labels["queries"] if q["split"]=="test" and q["relevant"]):
                    response = lib.search(q["query"],mode=mode,search_dimensions=selected["dimensions"],hybrid=selected["hybrid"])
                    expected = compact(snapshot,snapshot.rank(q["query"],mode=mode,vector=query_vectors[q["id"]],dimensions=selected["dimensions"],hybrid=selected["hybrid"]),mapping,5)
                    assert [(mapping[r["document_id"]],r["page_number"]) for r in response["results"]]==[(r["document"],r["page"]) for r in expected]
                    for result in response["results"]:
                        page = lib.page(result["document_id"],result["page_number"])
                        assert page["text"][result["char_start"]:result["char_end"]]==result["passage"]
                        assert result["source_available"] and result["open_uri"].endswith(f"#page={result['page_number']}")
                    times.append(response["elapsed_s"])
                    encode_times.append(response["query_embedding_s"])
                report["end_to_end"].append({"mode":mode,"queries":len(times),"chunk_tokens":selected["chunk_tokens"],"dimensions":selected["dimensions"],
                                            "mean_s":float(np.mean(times)),"p50_s":float(np.percentile(times,50)),"p95_s":float(np.percentile(times,95)),
                                            "max_s":max(times),"mean_query_embedding_s":float(np.mean(encode_times)),"all_source_offsets_verified":True})
                print(f"Live API {mode}: mean {np.mean(times)*1000:.1f} ms; p95 {np.percentile(times,95)*1000:.1f} ms",flush=True)
            toc = next(f for f in lib.folders() if f["name"]=="TOC")["id"]
            isolation = lib.search("recognizable languages",mode="hybrid",folder_id=toc)
            report["folder_isolation"] = bool(isolation["results"]) and all(r["folder_id"]==toc for r in isolation["results"])
            assert report["folder_isolation"]
        report["search_document_embeddings_generated"] = model.stats["document_texts_encoded"]-before_queries
        assert report["search_document_embeddings_generated"]==0
        assert len(blocked)==1,blocked
        report["raw_rankings"] = str(raw_path)
        report["raw_rankings_sha256"] = sha(raw_path)
        report["status"] = "evaluation_completed" # Quality failure is recorded separately, never hidden.
    except Exception as exc:
        report["status"] = "execution_failed"
        report["error"] = {"message":str(exc),"traceback":traceback.format_exc()}
        print(traceback.format_exc(),file=sys.stderr)
    finally:
        report["elapsed_s"] = time.perf_counter()-started
        report["memory"] = sampler.stop()
        report["embedding_runtime"] = dict(model.stats)
        report["offline"]["blocked_socket_events"] = len(blocked)
        if model._torch is not None:
            report["memory"].update(torch_peak_allocated_vram_bytes=model._torch.cuda.max_memory_allocated(),torch_peak_reserved_vram_bytes=model._torch.cuda.max_memory_reserved())
        write_json(output,report)
        print(f"Phase 3: {report['status']}; quality gate: {report.get('quality_gate',{}).get('passed')}",flush=True)
    return 0 if report["status"]=="evaluation_completed" else 1


if __name__=="__main__":
    raise SystemExit(main())
