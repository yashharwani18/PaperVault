# Indexing multi-GB cybersecurity datasets

The `Downloads/cybersecurity` collection contains about 17 GB of source files.
After SHA-256 de-duplication only about 6.6 GB is unique; the rest is repeated
copies of the same large JSON/JSONL files.

The normal folder importer reads a whole file before extracting it and rejects
files over 100 MB. Files below that limit are indexed in place like any other
folder. The oversized files are handled by
[`scripts/sample_large_cyber_datasets.py`](../scripts/sample_large_cyber_datasets.py),
which streams them without loading them into memory and writes bounded JSONL
shards under `Downloads/cybersecurity/curated/`.

Those shards are inside the already-connected `cybersecurity` collection, so the
watcher picks them up automatically. Do not connect `curated` as a second
collection; that would index the shards twice.

## What is indexed now

The sampler kept 5,000 records from each unique oversized source (fewer when a
file ran out of valid records) for 24,744 records and about 69 million
characters, split into six shards of at most 9,000 records. The per-shard record
cap stays under the importer's 10,000-unit ceiling.

| Source | Size | Records in file | Kept |
| --- | ---: | ---: | ---: |
| `vulnerability-intelligence/cybersec_master.jsonl` | 2.68 GB (4 copies) | 1,807,941 | 5,000 |
| `vulnerability-intelligence/vulnerability-intelligence__cybersec_master__dup1.jsonl` | 2.54 GB | 1,763,326 | 4,983 |
| `aws_pdf_chunks.json` | 660 MB (3 copies) | 106,621 | 5,000 |
| `220426-CyberSec-Dataset_escaped.jsonl` | 431 MB (2 copies) | 99,870 | 5,000 |
| `cyber-defense/CyberSec-Dataset_escaped.jsonl` | 195 MB (2 copies) | 53,201 | 4,761 |

Full details, including every shard's size and record count, are written to
[`results/cyber-bigdata-sample.json`](../results/cyber-bigdata-sample.json).
Sampling is deterministic for a given `--seed`, removes duplicate records by a
normalized hash, drops system prompts and refusal-only answers, and records the
original relative path in each shard's `source` field.

## Why the whole 6.6 GB is not loaded at once

The library uses exact vector search. For every query, `SearchIndex` builds a
float32 matrix of every chunk in scope, verifies each stored embedding's SHA-256,
normalizes the matrix, and multiplies it by the query vector
([`knowledge_library/retrieval.py`](../knowledge_library/retrieval.py)). There is
no approximate index to fall back on.

The tokenizer chunker uses 256-token chunks with 64-token overlap
([`knowledge_library/chunking.py`](../knowledge_library/chunking.py)), roughly
1,000 characters per chunk. A 6.6 GB text corpus is therefore in the range of
6-8 million chunks. At 768 dimensions and float32, that is 18-24 GB of vectors
alone, before SQLite text, the matrix copy, and the per-query checksum pass. This
machine has 15 GB of RAM, so importing everything would either fail during
indexing or make every search unusably slow.

The current library is 222,451 chunks across 2,966 documents after the curated
shards finish, of which 101,551 chunks come from the six curated shards. That is
roughly 0.7 GB of vectors. Warm semantic or hybrid searches take about 4-5
seconds on this machine; the first query after an idle period can take 8-9
seconds.

## Running or tuning the sampler

```bat
.venv\Scripts\python.exe scripts\sample_large_cyber_datasets.py
```

Useful options:

- `--per-file 5000` - records sampled from each unique oversized file. Raising it
  to 10,000 roughly doubles the curated corpus. Increase in steps and measure
  search latency; at 222,000 chunks a warm query already takes about 4-5 seconds,
  so keep the library well under roughly 300,000 chunks on this machine.
- `--max-chars 80000000` - total character budget across all files. `0` removes
  the explicit budget, but the per-file cap and shard limits still apply.
- `--min-bytes 104857600` - only files at least this large are sampled. Smaller
  files continue through the normal importer.
- `--source`, `--output`, `--report`, `--seed`, `--dry-run` - override paths,
  reproduce a sample, or inspect the plan without writing shards.

Re-running the sampler rewrites the shards in place. The watcher notices the new
modification times and reindexes them. Old shards that no longer exist are not
removed from the library automatically; remove them from the collection if you
shrink the sample.

## What full ingestion would require

To index all 6.6 GB while keeping interactive search, the retrieval layer needs
to change, not just the importer:

1. **Approximate nearest-neighbour search.** Build an on-disk HNSW or IVF index
   (for example FAISS) instead of loading a dense matrix per query. Fetch only
   the top candidates and hydrate their text.
2. **Or a two-stage lexical prefilter.** Use SQLite FTS to select a bounded
   candidate set, then load and score only those vectors. This changes
   semantic-only recall and needs evaluation.
3. **Streaming, resumable ingestion.** Chunk and embed in batches, commit
   checkpoints, and resume after restart; the current importer commits per file.
4. **Storage planning.** Roughly 21 GB for float32 vectors at 7 million chunks,
    about 10.5 GB in float16, plus index overhead. This belongs on disk, not in
    RAM.
5. **Incremental maintenance.** Handle updates, deletes, and index compaction,
   then measure recall and latency against the current exact search.

Until that exists, sampling is the safe way to make the large datasets
searchable without degrading the rest of the library.

## Using this for bug bounty work

The oversized files are mostly scraped or synthetic question/answer datasets,
with heavy duplication. They are useful for recall, vocabulary, and brainstorming
attack paths, but volume is not the same as verified expertise. For findings,
confirm every CVE, version range, payload, and remediation against primary
sources such as the NVD, vendor advisories, and the program's own scope. Only
test targets you are authorized to test.
