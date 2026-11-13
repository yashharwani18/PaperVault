"""Acquire the exact pinned public checkpoint during setup, then verify its hash."""
import argparse
import hashlib
import json
from pathlib import Path
import os
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    lock=json.loads((ROOT/'model-lock.json').read_text());directory=ROOT/'models/embeddinggemma-2'/lock['revision']
    if not args.offline:
        os.environ['HF_HOME']=str(ROOT/'.cache/huggingface');os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=lock['model_id'],revision=lock['revision'],local_dir=directory,token=False)
    with (directory/lock['weight_file']).open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=lock['weight_sha256']:raise ValueError('Checkpoint checksum mismatch')
    print('Pinned model verified:',lock['model_id'],lock['revision'])


if __name__=='__main__':main()
