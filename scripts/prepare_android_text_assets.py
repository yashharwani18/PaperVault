"""Stage Android's selected LiteRT model without changing desktop models."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]

def prepare():
    metadata=json.loads((ROOT/'android/model-downloads/embeddinggemma-text-manifest.json').read_text())
    tokenizer=json.loads((ROOT/'android/model-downloads/tokenizer-provenance.json').read_text())
    destination=ROOT/'android/runtime-model-assets';destination.mkdir(exist_ok=True)
    manifest={metadata['filename']:dict(bytes=metadata['bytes'],sha256=metadata['sha256'],model_id='google/embeddinggemma-2-text-270m',revision=metadata['revision'],runtime='litert-lm-0.18.1'),
              tokenizer['file']:dict(bytes=tokenizer['bytes'],sha256=tokenizer['sha256'],model_id='google/embeddinggemma-2 tokenizer',vocabulary_only=True),
              'qwen3-0.6b-q4.gguf':dict(bytes=484220320,sha256='9acfc1e001311f34b4252001b626f2e466d592a42065f66571bff3790d4e1b14',model_id='Qwen/Qwen3-0.6B')}
    for name,entry in manifest.items():
        source=ROOT/('android/model-downloads' if name.endswith('.litertlm') else 'android/model-assets')/name
        with source.open('rb') as file:assert hashlib.file_digest(file,'sha256').hexdigest()==entry['sha256'],name
        target=destination/name
        if not target.exists():
            try:target.hardlink_to(source)
            except OSError:shutil.copy2(source,target)
        assert target.stat().st_size==entry['bytes'],name
    (destination/'offline-models.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return destination

if __name__=='__main__':print(prepare())
