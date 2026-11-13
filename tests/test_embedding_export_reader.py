import hashlib
import json
import struct
import zipfile

import pytest


def archive(tmp_path, corrupt=False):
    files={
        'documents.jsonl':b'{"id":"d","filename":"bill.pdf","source_sha256":"source"}\n',
        'pages.jsonl':b'{"document_id":"d","page_number":1,"text":"Total 6600"}\n',
        'chunks.jsonl':b'{"id":1,"document_id":"d","page_number":1,"text":"Total 6600","input_hash":"model:input","dimensions":3,"vector_offset_bytes":0}\n',
        'vectors.f32':struct.pack('<3f',1.25,-2,.5),
    }
    manifest={'format':'khoj-embeddings-v1','dtype':'float32','byte_order':'little',
              'counts':{'documents':1,'pages':1,'chunks':1,'vectors':1,'chunks_without_vectors':0},
              'sha256':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
    if corrupt:files['vectors.f32']=b'wrong'
    path=tmp_path/'index.zip'
    with zipfile.ZipFile(path,'w') as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('manifest.json',json.dumps(manifest))
    return path


def test_reads_exported_source_and_vectors(tmp_path):
    from scripts.read_embedding_export import iter_embeddings,verify_export
    path=archive(tmp_path)
    assert verify_export(path)['format']=='khoj-embeddings-v1'
    rows=list(iter_embeddings(path))
    assert len(rows)==1
    assert rows[0]['document']['filename']=='bill.pdf'
    assert rows[0]['chunk']['text']=='Total 6600'
    assert rows[0]['chunk']['input_hash']=='model:input'
    assert rows[0]['vector']==[1.25,-2,.5]


def test_corruption_is_rejected_before_analysis(tmp_path):
    from scripts.read_embedding_export import iter_embeddings
    with pytest.raises(ValueError,match='Checksum'):
        list(iter_embeddings(archive(tmp_path,corrupt=True)))
