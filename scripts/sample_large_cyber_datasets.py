"""Sample oversized JSON/JSONL datasets into bounded, indexable JSONL shards.

Khoj's exact semantic search keeps one float32 vector per chunk in memory for
every query. Indexing multiple gigabytes of source text at once would create
millions of chunks and make search unusable on a normal desktop. This script
streams the oversized files, keeps a deterministic sample of records from each
unique file, removes duplicate/boilerplate records, and writes JSONL shards that
stay well inside the app's per-file limits.

Full source files are never loaded into memory and originals are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

SUPPORTED = {'.json', '.jsonl'}
SKIP_FIELDS = {
    'id', 'chunk_id', 'model', 'category', 'score', 'timestamp', 'created_at',
    'updated_at', 'metadata', 'source_id', 'document_id',
}
PRIORITY_TEXT_FIELDS = (
    'text', 'content', 'question', 'answer', 'instruction', 'input', 'output',
    'user', 'assistant',
)
ROLE_FIELDS = {'from', 'role'}
CONTENT_FIELDS = ('value', 'content', 'text')
REFUSAL_PREFIXES = (
    "i cannot", "i can't", "i can’t", "i'm sorry", "i am sorry", "as an ai",
    "i am unable", "i'm unable",
)
MAX_RECORD_CHARS = 30_000
MIN_RECORD_CHARS = 120
SHARD_MAX_CHARS = 15_000_000
SHARD_MAX_RECORDS = 9_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def count_lines(path: Path) -> int:
    count = 0
    last = b''
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            count += block.count(b'\n')
            last = block[-1:]
    if last and last != b'\n':
        count += 1
    return count


def _generic_text(value, depth: int = 0) -> str:
    if depth > 5:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        pieces = [_generic_text(item, depth + 1) for item in value[:40]]
        return '\n'.join(piece for piece in pieces if piece)
    if isinstance(value, dict):
        pieces = []
        for key, item in list(value.items())[:40]:
            if str(key).casefold() in SKIP_FIELDS:
                continue
            text = _generic_text(item, depth + 1)
            if text:
                pieces.append(f'{key}: {text}')
        return '\n'.join(pieces)
    return ''


def record_text(record) -> str:
    """Flatten one dataset record into readable text, dropping repeated system prompts."""
    if not isinstance(record, dict):
        return _generic_text(record)
    pieces: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            pieces.append(text)

    for field in ('conversations', 'messages'):
        turns = record.get(field)
        if not isinstance(turns, list):
            continue
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = next((str(turn[key]) for key in ROLE_FIELDS if key in turn), '')
            if role.casefold() == 'system':
                continue
            content = next((turn[key] for key in CONTENT_FIELDS if turn.get(key)), '')
            content = _generic_text(content)
            if content:
                add(f'{role}: {content}' if role else content)

    for field in PRIORITY_TEXT_FIELDS:
        value = record.get(field)
        if isinstance(value, str):
            add(value)

    for key, value in record.items():
        if str(key) in PRIORITY_TEXT_FIELDS or str(key) in ('conversations', 'messages', 'system'):
            continue
        if str(key).casefold() in SKIP_FIELDS:
            continue
        text = _generic_text(value)
        if text:
            add(f'{key}: {text}')

    text = '\n'.join(pieces).strip()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:MAX_RECORD_CHARS].strip()


def record_digest(text: str) -> bytes:
    normalized = re.sub(r'\s+', ' ', text).strip().casefold()
    return hashlib.blake2b(normalized.encode('utf-8'), digest_size=16).digest()


def usable_text(text: str) -> bool:
    if not MIN_RECORD_CHARS <= len(text) <= MAX_RECORD_CHARS:
        return False
    return not text.casefold().startswith(REFUSAL_PREFIXES)


def iter_jsonl_lines(path: Path):
    with path.open('r', encoding='utf-8-sig', errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield number, json.loads(line)
            except (ValueError, RecursionError):
                continue


def iter_json_array(path: Path):
    """Stream values from a top-level JSON array without reading the whole file."""
    decoder = json.JSONDecoder()
    with path.open('r', encoding='utf-8-sig', errors='strict') as stream:
        head = ''
        while not head.strip():
            chunk = stream.read(1024 * 1024)
            if not chunk:
                raise ValueError(f'{path.name}: empty JSON file')
            head += chunk
        if head.lstrip()[:1] != '[':
            raise ValueError(f'{path.name}: only top-level JSON arrays are streamed')
        buffer = head[head.index('[') + 1:]
        position = 0
        eof = False
        while True:
            # Skip separators without slicing the whole buffer per record.
            size = len(buffer)
            while position < size and buffer[position] in ' \t\r\n,':
                position += 1
            if position >= size:
                buffer = ''
                position = 0
                if eof:
                    return
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    eof = True
                else:
                    buffer = chunk
                continue
            if buffer[position] == ']':
                return
            try:
                value, end = decoder.raw_decode(buffer, position)
            except (ValueError, RecursionError):
                if eof:
                    raise ValueError(f'{path.name}: truncated or malformed JSON array')
                buffer = buffer[position:] + (stream.read(1024 * 1024) or '')
                position = 0
                if not buffer:
                    eof = True
                continue
            yield value
            position = end
            if position > 8 * 1024 * 1024:
                buffer = buffer[position:]
                position = 0


def sample_jsonl(path: Path, count: int, rng: random.Random):
    total = count_lines(path)
    if not total or count <= 0:
        return [], total
    wanted = set(rng.sample(range(1, total + 1), min(count, total)))
    sample = []
    for number, value in iter_jsonl_lines(path):
        if number in wanted:
            sample.append(value)
    return sample, total


def sample_json_array(path: Path, count: int, rng: random.Random):
    sample = []
    total = 0
    for total, value in enumerate(iter_json_array(path), 1):
        if len(sample) < count:
            sample.append(value)
        else:
            slot = rng.randrange(total)
            if slot < count:
                sample[slot] = value
    return sample, total


class ShardWriter:
    def __init__(self, directory: Path, *, max_chars: int, max_records: int):
        self.directory = directory
        self.max_chars = max_chars
        self.max_records = max_records
        self.files: list[dict] = []
        self.stream = None
        self.chars = 0
        self.records = 0

    def _open(self) -> None:
        self._close()
        path = self.directory / f'cyber-bigdata-{len(self.files) + 1:03d}.jsonl'
        self.stream = path.open('w', encoding='utf-8')
        self.path = path
        self.chars = 0
        self.records = 0

    def _close(self) -> None:
        if self.stream is None:
            return
        self.stream.close()
        self.files.append(dict(path=str(self.path), bytes=self.path.stat().st_size,
                               records=self.records, characters=self.chars))
        self.stream = None

    def add(self, text: str, source: str) -> bool:
        line = json.dumps({'text': text, 'source': source}, ensure_ascii=False) + '\n'
        if self.stream is None or self.records >= self.max_records or (
                self.chars and self.chars + len(line) > self.max_chars):
            self._open()
        self.stream.write(line)
        self.chars += len(line)
        self.records += 1
        return True

    def finish(self) -> list[dict]:
        self._close()
        return self.files


def unique_sources(root: Path, minimum: int, output: Path):
    groups: dict[str, list[Path]] = {}
    for path in sorted(root.rglob('*')):
        try:
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            if path.is_relative_to(output) or path.stat().st_size < minimum:
                continue
            groups.setdefault(sha256_file(path), []).append(path)
        except OSError:
            continue
    return sorted(((digest, paths[0], len(paths)) for digest, paths in groups.items()),
                  key=lambda item: item[1].stat().st_size, reverse=True)


def run(args) -> dict:
    source = args.source.expanduser().resolve()
    output = (args.output or source / 'curated').expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f'Source folder does not exist: {source}')
    output.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        for old in output.glob('cyber-bigdata-*.jsonl'):
            old.unlink()
    sources = unique_sources(source, args.min_bytes, output)
    writer = ShardWriter(output, max_chars=SHARD_MAX_CHARS, max_records=SHARD_MAX_RECORDS)
    seen: set[bytes] = set()
    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=str(source), output=str(output),
        minimum_bytes=args.min_bytes, per_file=args.per_file,
        max_characters=args.max_chars, files=[], output_files=[],
        duplicates_of_files=0, records_read=0, records_kept=0,
        characters_kept=0, stopped_for_budget=False,
    )
    budget = args.max_chars or None
    for raw_digest, path, copies in sources:
        remaining = args.per_file
        if budget is not None:
            remaining = min(remaining, max(0, budget - report['characters_kept']))
        item = dict(path=str(path.relative_to(source)), bytes=path.stat().st_size,
                    copies=copies, records=0, kept=0, duplicate_records=0,
                    skipped=0, error=None)
        report['duplicates_of_files'] += copies - 1
        if not args.dry_run and remaining > 0:
            rng = random.Random(f'{args.seed}:{raw_digest}')
            try:
                if path.suffix.lower() == '.jsonl':
                    sample, total = sample_jsonl(path, remaining, rng)
                else:
                    sample, total = sample_json_array(path, remaining, rng)
                item['records'] = total
                report['records_read'] += total
                for record in sample:
                    text = record_text(record)
                    if not usable_text(text):
                        item['skipped'] += 1
                        continue
                    digest = record_digest(text)
                    if digest in seen:
                        item['duplicate_records'] += 1
                        continue
                    seen.add(digest)
                    if budget is not None and report['characters_kept'] + len(text) > budget:
                        report['stopped_for_budget'] = True
                        break
                    writer.add(text, item['path'])
                    item['kept'] += 1
                    report['characters_kept'] += len(text)
                    report['records_kept'] += 1
            except (OSError, ValueError, RecursionError) as exc:
                item['error'] = str(exc)
        report['files'].append(item)
        if budget is not None and report['characters_kept'] >= budget:
            report['stopped_for_budget'] = True
            break
    report['output_files'] = writer.finish()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.home() / 'Downloads' / 'cybersecurity')
    parser.add_argument('--output', type=Path, default=None,
                        help='Default: <source>/curated')
    parser.add_argument('--per-file', type=int, default=5000,
                        help='Records sampled from each unique oversized file (default: 5000)')
    parser.add_argument('--min-bytes', type=int, default=100 * 1024 * 1024,
                        help='Only files at least this large are sampled (default: 100 MiB)')
    parser.add_argument('--max-chars', type=int, default=80_000_000,
                        help='Total characters written; 0 means no explicit budget (default: 80M)')
    parser.add_argument('--seed', type=int, default=20261111)
    parser.add_argument('--report', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'results' / 'cyber-bigdata-sample.json')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    report = run(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in (
        'duplicates_of_files', 'records_read', 'records_kept',
        'characters_kept', 'stopped_for_budget')}, indent=2))
    for item in report['files']:
        print(f"{item['path']}: {item['bytes'] / 1e6:.1f} MB, "
              f"{item['records']:,} records, {item['kept']:,} kept"
              + (f", error: {item['error']}" if item['error'] else ''))
    print(f"Report: {args.report}")
    print(f"Shards: {len(report['output_files'])} in {report['output']}")


if __name__ == '__main__':
    main()
