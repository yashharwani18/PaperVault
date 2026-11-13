"""Exercise the public CLI in a fresh process against the selected persisted index."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_embedding_model import deny_python_network, write_json


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    events=[]
    deny_python_network(events)
    from knowledge_library.embedding import EmbeddingGemma
    # A restart must use persisted passages; fail if any document encoding occurs.
    def forbid_documents(*_args,**_kwargs):
        raise AssertionError("Restart attempted to re-embed documents")
    EmbeddingGemma.documents=forbid_documents
    from knowledge_library.__main__ import main as cli
    r=json.loads((ROOT/"results/phase3-validation.json").read_text(encoding="utf-8"))
    s=r["selected"]
    run=next(v for v in r["runs"] if v["chunk_tokens"]==s["chunk_tokens"])
    labels=json.loads((ROOT/"evaluation/phase3-queries.json").read_text(encoding="utf-8"))["queries"]
    q=next(q for q in labels if q["id"]=="position-order")
    expected=next(v for v in (json.loads(line) for line in Path(r["raw_rankings"]).read_text().splitlines())
                  if v["split"]=="test" and v["query_id"]==q["id"] and all(v[k]==s[k] for k in ("chunk_tokens","dimensions","mode","hybrid")))
    mapping={v["document_id"]:v["corpus_id"] for v in run["documents"]}
    sys.argv=["knowledge_library","--library",run["library"],"search",q["query"],"--mode","hybrid",
              "--search-dimensions",str(s["dimensions"]),"--semantic-weight",str(s["hybrid"]["semantic_weight"]),
              "--rank-constant",str(s["hybrid"]["rank_constant"])]
    start=time.perf_counter()
    with tempfile.TemporaryFile(mode="w+",encoding="utf-8",dir=ROOT/".cache") as captured:
        with contextlib.redirect_stdout(captured):
            code=cli()
        captured.seek(0)
        output=captured.read()
    assert code==0,output
    response=json.loads(output)
    assert [(mapping[v["document_id"]],v["page_number"]) for v in response["results"]]==[(v["document"],v["page"]) for v in expected["results"][:5]]
    assert all(abs(a["score"]-b["score"])<1e-5 for a,b in zip(response["results"],expected["results"]))
    assert len(events)==1
    result={"passed":True,"fresh_process":True,"matches_evaluation_ranks_and_scores":True,
            "document_encoding_forbidden":True,"blocked_socket_events":len(events),"physical_disconnection":False,
            "elapsed_s":time.perf_counter()-start,"response":response}
    write_json(ROOT/"results/phase3-restart.json",result)
    print(json.dumps({k:v for k,v in result.items() if k!="response"},indent=2))


if __name__=="__main__":
    main()
