from pathlib import Path
import pytest
from scripts.build_release import allowed_file,validate_payload


def test_release_allowlist_excludes_private_data_source_and_debug_files():
    for name in ['Library.user.json','data/library/library.sqlite3','app/knowledge_library/server.py',
                 'app/knowledge_library/server.pyc','app/knowledge_library/server.c','app/knowledge_library/__pycache__/server.pyc',
                 'app/frontend/dist/assets/main.js.map','runtime/Lib/site-packages/torch/debug.pdb','app/models/example.pdf']:
        assert not allowed_file(Path(name)),name
    for name in ['Library.exe','app/knowledge_library/server.pyd','runtime/Lib/site-packages/torch/__init__.py',
                 'runtime/Lib/site-packages/torch/utils/data/__init__.py',
                 'app/models/embeddinggemma-2/revision/model.safetensors','app/frontend/dist/assets/main.js']:
        assert allowed_file(Path(name)),name


def test_payload_validation_rejects_source_even_if_compiled_module_exists(tmp_path):
    package=tmp_path/'app/knowledge_library';package.mkdir(parents=True)
    (package/'server.pyd').write_bytes(b'MZ')
    (package/'server.py').write_text('secret implementation')
    with pytest.raises(ValueError,match='source|Forbidden'):validate_payload(tmp_path)
