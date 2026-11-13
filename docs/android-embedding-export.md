# Export Android embeddings for PC analysis

In Khoj Android, open **More > Settings > Export embeddings to PC > Export embeddings**. Wait for file reading to finish first. Choose Downloads or another location in Android's save picker, then copy the ZIP to your PC with USB or your usual file-sharing app. Cancelling the picker keeps the library unchanged.

The ZIP is unencrypted and contains document names and indexed text. It contains no original PDF/Office files or model weights. A missing original does not prevent exporting its stored index. Trashed documents are excluded. Pending chunks without vectors are retained with a null vector offset, and counted separately. This is an analysis format, not a PC library restore archive.

Contents:

- `manifest.json`: format, model metadata, counts and SHA-256 checksums.
- `documents.jsonl`: IDs, names, source hashes, folders, versions and indexing status; no phone file paths.
- `pages.jsonl`: indexed page text and extraction evidence.
- `chunks.jsonl`: text, page/chunk locations, input/model hash, dimensions and vector byte offsets.
- `vectors.f32`: concatenated little-endian float32 vectors.

Verify an export with ordinary Python, without installing packages:

```powershell
python scripts/read_embedding_export.py "C:\Users\Yash\Downloads\Khoj-embeddings-2026-10-28.zip"
```

For Python analysis from the project directory:

```python
from scripts.read_embedding_export import iter_embeddings
for item in iter_embeddings("Khoj-embeddings-2026-10-28.zip"):
    document = item["document"]
    chunk = item["chunk"]
    vector = item["vector"]
    # Compare only vectors with the same input_hash model prefix and dimensions.
```

Export uses one database transaction and streams rows to bound memory use. The Android save action stages a complete ZIP before copying it to your selected destination. It neither rebuilds embeddings nor modifies the library.
