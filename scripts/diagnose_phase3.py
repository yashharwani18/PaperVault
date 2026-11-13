"""Post-evaluation diagnostics only; never revises labels or selected settings."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.metrics import aggregate
from knowledge_library.library import Library
from knowledge_library.retrieval import SearchIndex


def main():
    r=json.loads((ROOT/"results/phase3-validation.json").read_text(encoding="utf-8"))
    s=r["selected"]
    qpath=ROOT/"evaluation/phase3-queries.json"
    assert hashlib.sha256(qpath.read_bytes()).hexdigest()==r["hashes"]["phase3-queries.json"]
    labels={q["id"]:q for q in json.loads(qpath.read_text())["queries"]}
    raw=[json.loads(line) for line in Path(r["raw_rankings"]).read_text().splitlines()]
    selected=[x for x in raw if x["split"]=="test" and all(x[k]==s[k] for k in ("chunk_tokens","dimensions","mode","hybrid")) and "metrics" in x]
    semantic={x["query_id"]:x for x in raw if x["split"]=="test" and x["chunk_tokens"]==s["chunk_tokens"] and x["dimensions"]==s["dimensions"] and x["mode"]=="semantic"}
    out={"labels_unchanged":True,"scope":"Post-test explanation, not a new held-out evaluation or selection", "per_kind":[],"fusion_regressions":[]}
    for mode in ("keyword","bm25_raw","bm25","semantic","hybrid"):
        for kind in ("exact","conceptual","ambiguous_multi_document"):
            group=[x["metrics"] for x in raw if x["split"]=="test" and x["chunk_tokens"]==s["chunk_tokens"] and x["dimensions"]==s["dimensions"] and x["mode"]==mode and "metrics" in x and labels[x["query_id"]]["kind"]==kind]
            out["per_kind"].append({"mode":mode,"kind":kind,"queries":len(group),"metrics":aggregate(group)})
    for x in selected:
        base=semantic[x["query_id"]]
        if x["metrics"]["recall@3"]<base["metrics"]["recall@3"]:
            out["fusion_regressions"].append({"query_id":x["query_id"],"semantic":base["metrics"],"hybrid":x["metrics"],
                                              "semantic_top5":base["results"][:5],"hybrid_top5":x["results"][:5]})
    qs=[q for q in labels.values() if q["split"]=="test" and q["relevant"]]
    out["maximum_possible_page_recall"]={str(k):sum(min(k,len(q["relevant"]))/len(q["relevant"]) for q in qs)/len(qs) for k in (1,3,5)}
    run=next(v for v in r["runs"] if v["chunk_tokens"]==s["chunk_tokens"])
    mapping={d["document_id"]:d["corpus_id"] for d in run["documents"]}
    with Library(run["library"]) as lib:
        index=SearchIndex(lib,vectors=False)
        ranks=index.lexical(labels["z-delay"]["query"])
        out["z_delay_bm25_general_rule_rank"]=next((rank for rank,(i,_) in enumerate(ranks,1)
                                                       if mapping[index.rows[i]["document_id"]]=="mit-z-transform" and index.rows[i]["page_number"]==23),None)
        out["diagnostic_model_loads"]=lib.embedder.stats["model_loads"]
        assert out["diagnostic_model_loads"]==0
    out["source_inspection_findings"]=[
        {"case":"z-delay","finding":"Semantic at the same 256 dimensions places the general delay rule on page 23 first. Fusion demotes it to fifth while a delayed-impulse special case and overview slides move ahead. This is a fusion/lexical regression, not evidence of a missing embedding or wrong page reference."},
        {"case":"parallel-recognizers","finding":"At identical chunk size/dimensions, semantic retrieves both labeled proof pages in the first three; fusion retrieves one in five. Broad closure/enumeration language is promoted by lexical rank fusion."},
        {"case":"regex-rules","finding":"The unjudged page 38 actually includes a recursive regular-expression definition. Frozen labels only include pages 39 and 40. This reveals an annotation omission; the recorded miss is preserved rather than retroactively repaired. Summary slides also precede the full labeled definitions."},
        {"case":"nyquist","finding":"The labeled theorem page 21 is retrieved; the equivalent labeled summary page 60 is missing. Unjudged reconstruction page 22 also contains the sampling theorem, so a 50% page recall does not mean the user gets no answer."},
        {"case":"ambiguous-halting","finding":"Five similar pages from the decidability lecture occupy the top five, excluding the other lecture. There are six labeled pages, so this query cannot achieve 100% page Recall@5. Document coverage and answer-unit utility need separate measurement."},
        {"case":"ambiguous-attention-cost","finding":"Only FlashAttention page 1 of four labeled pages is retrieved. Other introductory/context pages displace the original Transformer's complexity table, BERT's training-cost discussion, and FlashAttention's standard-attention formula. This remains a substantive cross-document coverage failure alongside incomplete judgments."},
        {"case":"alias-wrapping","finding":"Unjudged page 34 repeats the frequency-wrapping explanation on labeled slides 31-33 and appears first. Full labeled coverage occurs only by rank four. Duplicate slide builds and incomplete labels affect the apparent top-three failure."}
    ]
    out["visual_checks"]={"files":["results/phase3-qa/sampling-page-21.png","results/phase3-qa/flash-page-4.png"],
                           "review":"Both local Poppler renders were visually inspected. The sampling inequality and FlashAttention matrix formulas are readable. Poppler emitted missing Symbol/ArialUnicode display-font warnings for the MIT slide, but the rendered theorem was legible. This is source-page inspection, not a viewer navigation test."}
    (ROOT/"results/phase3-diagnostics.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"regressions":len(out["fusion_regressions"]),"z_delay_lexical_rank":out["z_delay_bm25_general_rule_rank"],"page_recall_ceilings":out["maximum_possible_page_recall"]},indent=2))


if __name__=="__main__":
    main()
