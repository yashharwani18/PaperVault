"""Persist source-selected questions and inspected page evidence BEFORE ranking.

These judgments were made by the coding agent from local PDF text, not by an
independent human assessor. This is an initial diagnostic set, not a benchmark
with exhaustive relevance judgments or guaranteed held-out model training data.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Explicit source references selected during source inspection, not retrieval.
DEV = [
 ("pumping-statement", "Where is the general pumping lemma stated, including the repeatable middle part of an accepted word?", "exact", {"mit-pumping-lemma":[18,19,20,22]}),
 ("alternative-transitions", "How can a state machine consider several successor states for the same input symbol?", "conceptual", {"mit-dfa-nfa":[44,45,46],"mit-nfa-regex":[5,6]}),
 ("time-convolution", "Which rule turns convolution in time into multiplication of frequency spectra?", "conceptual", {"mit-fourier":[10]}),
 ("scaled-attention", "Why are query-key dot products scaled down before the softmax in an attention layer?", "conceptual", {"attention":[4]}),
 ("hidden-token-training", "How is a model trained to guess hidden tokens from words on both sides?", "conceptual", {"bert":[4,12]}),
 ("recursive-stopping", "How do I keep a recursive function from calling itself forever?", "conceptual", {"think-python":[66,67]}),
 ("z-convergence", "Where do the notes define the region of convergence for a Z transform?", "exact", {"mit-z-transform":[20,21]}),
 ("lti-output", "How can I compute an LTI system's output from its impulse response and an arbitrary input?", "conceptual", {"mit-convolution":[21,22,42,49,74]}),
 ("series-decomposition", "Find the Fourier series analysis and synthesis equations for a periodic signal.", "exact", {"mit-fourier-series":[3,4,5,6]}),
 ("negative-sampling", "Find the explanation of negative sampling as an alternative to hierarchical softmax.", "exact", {"word2vec":[3,4]}),
 ("adam-initial-bias", "Why must Adam correct the moving averages that start from zero?", "conceptual", {"adam":[2,3]}),
 ("csf-profiles", "What is the difference between a Current Profile and a Target Profile in the cybersecurity framework?", "exact", {"nist-csf":[11,12]})
]
TEST = [
 ("dfa-components", "Which five components formally define a deterministic finite automaton?", "conceptual", {"mit-dfa-nfa":[8]}),
 ("nfa-equivalence", "Does nondeterminism let finite automata recognize more languages, or can a DFA simulate them?", "conceptual", {"mit-nfa-regex":[20]}),
 ("regex-rules", "Where are regular expressions defined recursively using union, concatenation, and star?", "exact", {"mit-nfa-regex":[39,40]}),
 ("writable-tape", "What extra ability gives a Turing machine unbounded memory beyond a two-way finite automaton?", "conceptual", {"mit-turing":[1]}),
 ("recognizer-decider", "How does always terminating distinguish a decider from a recognizer?", "conceptual", {"mit-decidability":[5,6]}),
 ("parallel-recognizers", "Why must recognizers for a language and its complement be interleaved instead of run one after another?", "conceptual", {"mit-decidability":[9,11]}),
 ("z-bilateral", "Find the bilateral Z transform that includes both negative and positive discrete times.", "exact", {"mit-z-transform":[14]}),
 ("z-delay", "How does delaying a discrete signal by one sample change its Z transform?", "conceptual", {"mit-z-transform":[23]}),
 ("time-invariance", "What does it mean for a system to delay its output by the same amount as its input?", "conceptual", {"mit-convolution":[19]}),
 ("optical-blur", "How can a microscope's point-spread function describe image blurring?", "conceptual", {"mit-convolution":[55,56,57,62]}),
 ("vowel-harmonics", "Which lecture uses the harmonic content of vowel sounds to illustrate Fourier series?", "conceptual", {"mit-fourier-series":[14,15,16]}),
 ("filter-frequencies", "Can an LTI filter create new frequencies or only change existing magnitudes and phases?", "conceptual", {"mit-fourier-series":[20]}),
 ("transform-domain", "How do the Fourier and Laplace transforms differ in whether their input domain is real or complex?", "conceptual", {"mit-fourier":[11,12,13]}),
 ("nyquist", "How fast must I sample a bandlimited signal to reconstruct it without losing information?", "conceptual", {"mit-sampling":[21,60]}),
 ("alias-wrapping", "Find the slides showing how aliasing wraps input frequencies into different output frequencies.", "exact", {"mit-sampling":[31,32,33]}),
 ("position-order", "How does a Transformer know token order when it has no recurrence or convolution?", "conceptual", {"attention":[6]}),
 ("bert-sentence-pairs", "How does BERT build positive and negative sentence pairs for next sentence prediction?", "exact", {"bert":[4,13]}),
 ("frequent-word-discard", "Why does word-vector training randomly discard very frequent words, and how does that help rare words?", "conceptual", {"word2vec":[4,5]}),
 ("flash-io", "Which attention algorithm reduces GPU memory traffic by working in tiles stored in on-chip SRAM?", "conceptual", {"flash-attention":[1,2,4,5]}),
 ("flash-recompute", "How can the attention backward pass save memory by reconstructing intermediates instead of keeping the full matrix?", "conceptual", {"flash-attention":[5]}),
 ("adam-moments", "Find Adam's parameter update using first and second gradient moment estimates.", "exact", {"adam":[2]}),
 ("list-alias", "Why does changing a list through one variable also change what another variable sees?", "conceptual", {"think-python":[118,119]}),
 ("p-value-meaning", "What probability does a p-value describe under a null hypothesis?", "conceptual", {"think-stats":[138,141]}),
 ("multiple-tests", "Why can trying many significance tests produce false discoveries, and how can exploration and testing be separated?", "conceptual", {"think-stats":[152]}),
 ("privacy-without-breach", "Can ordinary data processing harm privacy even when there is no cybersecurity incident?", "conceptual", {"nist-privacy":[7],"nist-csf":[18]}),
 ("unlinkable-processing", "Where are ways to limit identifying and linking people during data processing described?", "conceptual", {"nist-privacy":[28,33,38]}),
 ("http-idempotence", "When is repeating an HTTP request intended to have the same effect as sending it once?", "conceptual", {"rfc-http":[73]}),
 ("http-304", "Why can an HTTP server return 304 Not Modified instead of retransmitting a representation?", "exact", {"rfc-http":[135,136]}),
 ("ambiguous-halting", "Where do the MIT notes discuss the halting problem?", "ambiguous_multi_document", {"mit-turing":[3],"mit-decidability":[46,47,48,50,51]}),
 ("ambiguous-attention-cost", "Which papers discuss attention costs growing quadratically with sequence length?", "ambiguous_multi_document", {"attention":[6],"bert":[13],"flash-attention":[1,4]})
]
NEGATIVE = [
 ("bread", "How do I bake a sourdough loaf with a crisp crust?", "dev"),
 ("garden", "When should I prune a mango tree in my garden?", "dev"),
 ("payroll", "Find my September 2026 salary slip and bank account number.", "dev"),
 ("travel", "Where is my confirmed flight booking to Osaka next week?", "test"),
 ("medical", "Find the discharge summary from my knee surgery.", "test"),
 ("housing", "What rent and deposit did I agree to in my signed apartment lease?", "test"),
 ("sports", "Which document gives the score of yesterday's cricket final?", "test"),
 ("recipe", "How long should I roast a whole chicken with potatoes?", "test")
]


def main():
    destination = ROOT / "evaluation/phase3-queries.json"
    if destination.exists():
        raise SystemExit("Labels already exist; do not overwrite frozen evaluation judgments")
    pages = json.loads((ROOT / "results/phase3-source-pages.json").read_text(encoding="utf-8"))
    queries = []
    evidence = []
    for split, entries in (("dev",DEV),("test",TEST)):
        for ident, query, kind, refs in entries:
            relevant = []
            for corpus_id, numbers in refs.items():
                for page in numbers:
                    text = pages[corpus_id][page-1]
                    if len(text.strip()) < 30:
                        raise ValueError(f"Unusable relevance page {corpus_id}:{page}")
                    relevant.append({"document":corpus_id,"page":page})
                    evidence.append({"query_id":ident,"document":corpus_id,"physical_page":page,
                                     "page_text_sha256":hashlib.sha256(text.encode()).hexdigest(),
                                     "inspected_page_text":text})
            queries.append({"id":ident,"query":query,"split":split,"kind":kind,"relevant":relevant})
    for ident, query, split in NEGATIVE:
        queries.append({"id":"no-answer-"+ident,"query":query,"split":split,"kind":"no_answer","relevant":[]})
    record = {"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
              "judgment_provenance":"Coding-agent source inspection before retrieval. Not independently human annotated. Six Phase 2 topics restricted to dev.",
              "judgment_scope":"Positive page judgments are non-exhaustive; unjudged pages score as non-relevant. Physical 1-based PDF pages. Inspect evidence before interpreting misses.",
              "queries":queries}
    destination.write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
    (ROOT/"evaluation/phase3-label-evidence.json").write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Frozen {len(DEV)} dev + {len(TEST)} test answerable queries and {len(NEGATIVE)} no-answer queries")


if __name__ == "__main__":
    main()
