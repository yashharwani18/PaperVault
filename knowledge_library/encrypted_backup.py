"""Streaming password-protected backup envelope. Plain ZIP restore stays separate."""
import os
from pathlib import Path
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'LLBK01\r\n'
HEADER_BYTES=len(MAGIC)+16+12
BLOCK=1024*1024


def key(password,salt):
    if not 12<=len(password)<=1024:raise ValueError('Use a backup password of 12-1024 characters.')
    # Fixed format parameters: an untrusted file cannot request arbitrary KDF work.
    return Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password.encode('utf-8'))


def encrypted(path):
    with Path(path).open('rb') as source:return source.read(len(MAGIC))==MAGIC


def encrypt(source,target,password):
    source=Path(source);target=Path(target)
    salt=os.urandom(16);nonce=os.urandom(12);header=MAGIC+salt+nonce
    context=Cipher(algorithms.AES(key(password,salt)),modes.GCM(nonce)).encryptor()
    context.authenticate_additional_data(header)
    partial=target.with_suffix(target.suffix+'.partial')
    if target.exists() or partial.exists():raise ValueError('Backup destination already exists.')
    try:
        with source.open('rb') as inp,partial.open('xb') as out:
            out.write(header)
            while block:=inp.read(BLOCK):out.write(context.update(block))
            out.write(context.finalize());out.write(context.tag)
        partial.replace(target)
        return target
    finally:partial.unlink(missing_ok=True)


def decrypt(source,target,password):
    source=Path(source);target=Path(target);partial=target.with_suffix(target.suffix+'.partial')
    if target.exists() or partial.exists():raise ValueError('Restore staging destination already exists.')
    size=source.stat().st_size
    if size<HEADER_BYTES+16:raise ValueError('Encrypted backup is truncated.')
    try:
        with source.open('rb') as inp:
            header=inp.read(HEADER_BYTES)
            if not header.startswith(MAGIC):raise ValueError('Unsupported encrypted backup format.')
            salt=header[len(MAGIC):len(MAGIC)+16];nonce=header[-12:]
            inp.seek(-16,2);tag=inp.read(16);inp.seek(HEADER_BYTES)
            context=Cipher(algorithms.AES(key(password,salt)),modes.GCM(nonce,tag)).decryptor()
            context.authenticate_additional_data(header)
            remaining=size-HEADER_BYTES-16
            with partial.open('xb') as out:
                while remaining:
                    block=inp.read(min(BLOCK,remaining))
                    if not block:raise ValueError('Encrypted backup is truncated.')
                    remaining-=len(block);out.write(context.update(block))
                out.write(context.finalize())
        # No ZIP parsing, extraction or database opening before authentication.
        partial.replace(target)
        return target
    except InvalidTag as exc:raise ValueError('Wrong backup password or corrupted encrypted backup.') from exc
    finally:partial.unlink(missing_ok=True)


def backup(lib,password):
    # Validate before creating a plaintext archive; never persist the password.
    if not 12<=len(password)<=1024:raise ValueError('Use a backup password of 12-1024 characters.')
    from .maintenance import backup as plain_backup
    archive=plain_backup(lib)
    try:return encrypt(archive,archive.with_suffix('.llbackup'),password)
    finally:archive.unlink(missing_ok=True)
