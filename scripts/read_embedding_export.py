"""Verify and read a Khoj Android embedding ZIP using only Python's standard library.

Usage: python scripts/read_embedding_export.py PATH_TO_ZIP
For notebooks: from scripts.read_embedding_export import iter_embeddings
"""
from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

FILES={'documents.jsonl','pages.jsonl','chunks.jsonl','vectors.f32'}


def verify_export(path):
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist())!=5 or set(archive.namelist())!=FILES|{'manifest.json'}:
            raise ValueError('Unexpected or missing export files')
        if archive.getinfo('manifest.json').file_size>1_000_000:
            raise ValueError('Oversized manifest')
        manifest=json.loads(archive.read('manifest.json'))
        if (manifest.get('format'),manifest.get('dtype'),manifest.get('byte_order'))!=('khoj-embeddings-v1','float32','little'):
            raise ValueError('Unsupported embedding export format')
        if set(manifest.get('sha256',{}))!=FILES:
            raise ValueError('Missing export checksums')
        for name in sorted(FILES):
            digest=hashlib.sha256()
            with archive.open(name) as file:
                while block:=file.read(1024*1024):digest.update(block)
            if digest.hexdigest()!=manifest['sha256'][name]:
                raise ValueError('Checksum mismatch: '+name)
        return manifest


def _rows(archive,name):
    with archive.open(name) as file:
        for line in file:
            if line.strip():yield json.loads(line)


def iter_embeddings(path):
    """Yield {document, chunk, vector}; skip chunks whose vectors are not ready.

    Group by the model prefix of chunk['input_hash'] and dimensions before
    comparing vectors. Coordinates from different model recipes are not interchangeable.
    """
    verify_export(path)
    with zipfile.ZipFile(path) as archive:
        documents={row['id']:row for row in _rows(archive,'documents.jsonl')}
        total_bytes=archive.getinfo('vectors.f32').file_size
        with archive.open('vectors.f32') as vectors:
            for chunk in _rows(archive,'chunks.jsonl'):
                offset=chunk['vector_offset_bytes'];dimensions=chunk['dimensions']
                if offset is None:
                    if dimensions!=0:raise ValueError('Missing vector has nonzero dimensions')
                    continue
                if (type(offset) is not int or type(dimensions) is not int or
                    offset<0 or offset%4 or not 1<=dimensions<=65536 or offset+dimensions*4>total_bytes):
                    raise ValueError('Invalid vector bounds')
                vectors.seek(offset)
                vector=list(struct.unpack('<'+str(dimensions)+'f',vectors.read(dimensions*4)))
                if not all(math.isfinite(value) for value in vector):raise ValueError('Invalid vector value')
                if chunk['document_id'] not in documents:raise ValueError('Chunk has no source document')
                yield {'document':documents[chunk['document_id']],'chunk':chunk,'vector':vector}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    manifest=verify_export(args.archive)
    groups=Counter((row['chunk']['input_hash'].split(':',1)[0],len(row['vector'])) for row in iter_embeddings(args.archive))
    count=sum(groups.values())
    if count!=manifest['counts']['vectors']:raise ValueError('Vector count differs from manifest')
    print(json.dumps({'verified':True,'counts':manifest['counts'],
                      'vector_groups':[{'model_identity':model,'dimensions':dimension,'vectors':n} for (model,dimension),n in groups.items()]},indent=2))


if __name__=='__main__':main()
