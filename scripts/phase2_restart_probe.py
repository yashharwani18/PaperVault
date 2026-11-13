"""Search a persisted real index in a fresh process with Python sockets blocked."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_embedding_model import deny_python_network, write_json
blocked=[]
deny_python_network(blocked)
from knowledge_library.embedding import EmbeddingGemma
from knowledge_library.library import Library

model=EmbeddingGemma()
with Library(sys.argv[1],model) as lib:
    response=lib.search("What fact about finite automata lets me repeat part of a long accepted word without leaving the language?")
    if not response["results"] or model.stats["document_texts_encoded"] != 0 or len(blocked) != 1:
        raise AssertionError("Persisted offline search failed or re-encoded documents")
    report={"passed":True,"library":str(lib.root),"documents":len(lib.documents()),"scoped_chunks":response["scoped_chunks"],
            "results":[{k:r[k] for k in ("document_id","filename","page_number","score")} for r in response["results"]],
            "elapsed_s":response["elapsed_s"],"embedding_runtime":model.stats,"blocked_socket_events":len(blocked)}
write_json(Path(sys.argv[2]),report)
print(json.dumps(report,indent=2))
