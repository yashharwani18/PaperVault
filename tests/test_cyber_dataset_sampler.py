import json
from argparse import Namespace

from scripts.sample_large_cyber_datasets import (
    iter_json_array, record_text, run, sample_jsonl,
)


def test_record_text_skips_system_boilerplate_and_keeps_turns():
    record = {
        'system': 'You are a generic assistant. ' * 1000,
        'conversations': [
            {'from': 'system', 'value': 'Answer in a logical step-by-step manner. ' * 200},
            {'from': 'human', 'value': 'How can I detect encrypted C2 traffic?'},
            {'from': 'gpt', 'value': 'Use TLS metadata, JA3/JA4 fingerprints and beacon timing.'},
        ],
    }
    text = record_text(record)
    assert 'How can I detect encrypted C2 traffic?' in text
    assert 'JA3/JA4' in text
    assert 'generic assistant' not in text
    assert 'step-by-step' not in text


def test_json_array_streams_across_read_boundaries(tmp_path):
    path = tmp_path / 'chunks.json'
    long_text = 'x' * 1_200_000
    path.write_text(json.dumps([{'text': long_text}, {'text': 'second'}]), encoding='utf-8')
    values = list(iter_json_array(path))
    assert len(values) == 2
    assert len(values[0]['text']) == 1_200_000
    assert values[1]['text'] == 'second'


def test_jsonl_sampling_is_deterministic(tmp_path):
    import random
    path = tmp_path / 'data.jsonl'
    path.write_text(''.join(json.dumps({'text': f'record {i}'}) + '\n' for i in range(100)), encoding='utf-8')
    first, total = sample_jsonl(path, 10, random.Random(7))
    second, total_again = sample_jsonl(path, 10, random.Random(7))
    assert total == total_again == 100
    assert first == second and len(first) == 10


def test_run_writes_deduplicated_shards(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    records = [{'user': f'Question {i} about ransomware response?', 'assistant': 'Isolate, preserve logs, and restore from backups. ' * 3}
               for i in range(20)]
    body = ''.join(json.dumps(record) + '\n' for record in records)
    (source / 'a.jsonl').write_text(body, encoding='utf-8')
    (source / 'a-copy.jsonl').write_text(body, encoding='utf-8')
    output = source / 'curated'
    report = run(Namespace(source=source, output=output, per_file=20, min_bytes=1,
                           max_chars=0, seed=1, dry_run=False))
    shards = sorted(output.glob('cyber-bigdata-*.jsonl'))
    assert shards
    lines = [json.loads(line) for shard in shards for line in shard.read_text(encoding='utf-8').splitlines()]
    assert report['duplicates_of_files'] == 1
    assert len(lines) == len({line['text'] for line in lines}) == 20
    assert all(line['source'] in {'a.jsonl', 'a-copy.jsonl'} for line in lines)
