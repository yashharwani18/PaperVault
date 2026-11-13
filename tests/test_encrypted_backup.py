import os
import pytest
from knowledge_library.encrypted_backup import encrypt,decrypt,encrypted,HEADER_BYTES


def test_stream_roundtrip_is_randomized_and_not_plaintext(tmp_path):
    source=tmp_path/'source.zip';source.write_bytes(b'PRIVATE BACKUP CONTENT\n'+os.urandom(2*1024*1024+137))
    first=encrypt(source,tmp_path/'first.llbackup','long test password one')
    second=encrypt(source,tmp_path/'second.llbackup','long test password one')
    assert encrypted(first) and first.read_bytes()!=second.read_bytes()
    assert b'PRIVATE BACKUP CONTENT' not in first.read_bytes()
    output=decrypt(first,tmp_path/'restored.zip','long test password one')
    assert output.read_bytes()==source.read_bytes()


@pytest.mark.parametrize('mutation',['password','header','ciphertext','tag','truncate'])
def test_wrong_password_and_tampering_never_publish_plain_archive(tmp_path,mutation):
    source=tmp_path/'source.zip';source.write_bytes(b'Not a production backup. Testing authentication only.'*100)
    archive=encrypt(source,tmp_path/'test.llbackup','long test password two')
    data=bytearray(archive.read_bytes());password='long test password two'
    if mutation=='password':password='wrong test password here'
    elif mutation=='header':data[10]^=1
    elif mutation=='ciphertext':data[HEADER_BYTES+3]^=1
    elif mutation=='tag':data[-1]^=1
    else:data=data[:-25]
    archive.write_bytes(data)
    target=tmp_path/'restored.zip'
    with pytest.raises(ValueError):decrypt(archive,target,password)
    assert not target.exists() and not target.with_suffix('.zip.partial').exists()


def test_short_password_and_existing_output_rejected(tmp_path):
    source=tmp_path/'source.zip';source.write_bytes(b'test')
    with pytest.raises(ValueError):encrypt(source,tmp_path/'out.llbackup','short')
    target=tmp_path/'existing';target.write_bytes(b'keep')
    with pytest.raises(ValueError):encrypt(source,target,'long test password three')
    assert target.read_bytes()==b'keep'
