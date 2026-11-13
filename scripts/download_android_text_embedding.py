"""Download the pinned official text-only LiteRT model for Android staging.

Does not change desktop models, installed apps, existing indexes, or APK assets.
"""
import hashlib
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'litert-community/embeddinggemma-2-text-270m-litert-lm'
REVISION = '9be6e8b90982095dc05c2bd162e4b954ee4dbac7'
FILENAME = 'embeddinggemma-2-text-270m.litertlm'
BYTES = 164626432
SHA256 = '2d079ee2f6f066b1f368e8d7c819f55214eaef1d0513b312321901f30ab286fb'


def valid(path):
    if not path.is_file() or path.stat().st_size != BYTES:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == SHA256


def main():
    directory = ROOT / 'android/model-downloads'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / FILENAME
    url = f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{FILENAME}'
    if not valid(target):
        partial = target.with_suffix('.litertlm.partial')
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as out:
                while data := response.read(1024 * 1024):
                    out.write(data)
                out.flush()
                os.fsync(out.fileno())
            if not valid(partial):
                raise RuntimeError('Official Android model size or SHA-256 mismatch')
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    manifest = dict(repository=REPOSITORY, revision=REVISION, filename=FILENAME,
                    bytes=BYTES, sha256=SHA256, source_url=url,
                    intended_platform='android', runtime='LiteRT-LM',
                    modalities=['text'], status='downloaded_and_verified')
    (directory / 'embeddinggemma-text-manifest.json').write_text(
        json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Android text-only model verified: {target}')


if __name__ == '__main__':
    main()
