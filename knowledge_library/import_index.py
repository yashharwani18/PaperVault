"""Cache Transformers 5.20.1's generated import lookup tables as JSON data.

That release scans hundreds of model source files at every fresh import. This
memoizes the resulting tables across processes without changing model code,
dependency checks, weights or the installed package. Unknown versions use the
upstream implementation. The one-shot hook removes itself after import_utils.
"""
import functools
import hashlib
import importlib.abc
import importlib.machinery
import json
from pathlib import Path
import sys
import threading

TARGET='transformers.utils.import_utils'
_guard=threading.Lock()


def _install(module,cache_path):
    original=getattr(module,'define_import_structure',None)
    if original is None:return
    if getattr(original,'_library_cached',False):return
    root=Path(module.__file__).resolve().parent.parent
    initializer=(root/'__init__.py').read_bytes()
    if b'__version__ = "5.20.1"' not in initializer:return
    record=next(root.parent.glob('transformers-5.20.1.dist-info/RECORD'),None)
    if record is None:return
    identity=hashlib.sha256(initializer+Path(module.__file__).read_bytes()+record.read_bytes()).hexdigest()
    signature=dict(root=str(root),version='5.20.1',identity=identity,record_mtime_ns=record.stat().st_mtime_ns)
    entries={}
    try:
        if cache_path.stat().st_size<16*1024*1024:
            saved=json.loads(cache_path.read_text(encoding='utf-8'))
            if saved.get('signature')==signature and isinstance(saved.get('entries'),dict):entries=saved['entries']
    except (OSError,ValueError,KeyError,TypeError,AttributeError):pass

    @functools.wraps(original)
    def cached(module_path,prefix=None):
        path=Path(module_path).resolve()
        if not path.is_relative_to(root):return original(module_path,prefix)
        # Directory metadata invalidates additions/removals; RECORD and source
        # hashes invalidate installed package upgrades/replacements.
        directory=path.parent if path.is_file() else path
        key=json.dumps([str(path),prefix,directory.stat().st_mtime_ns])
        with _guard:
            saved=entries.get(key)
            if saved is not None:
                try:return {frozenset(backends):{name:set(objects) for name,objects in mapping.items()} for backends,mapping in saved}
                except (ValueError,TypeError,AttributeError):entries.pop(key,None)
        result=original(module_path,prefix)
        encoded=[[sorted(backends),{name:sorted(objects) for name,objects in mapping.items()}] for backends,mapping in result.items()]
        with _guard:
            entries[key]=encoded
            try:
                cache_path.parent.mkdir(parents=True,exist_ok=True)
                # Unique temporary names also permit independent app/test processes.
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=cache_path.parent,suffix='.tmp',delete=False) as output:
                    json.dump(dict(signature=signature,entries=entries),output);temporary=Path(output.name)
                temporary.replace(cache_path)
            except OSError:pass  # An unwritable cache must never prevent inference.
        return result
    cached._library_cached=True
    cached.cache_clear=original.cache_clear
    module.define_import_structure=cached


class _Loader(importlib.abc.Loader):
    def __init__(self,loader,cache_path):self.loader=loader;self.cache_path=cache_path
    def create_module(self,spec):return self.loader.create_module(spec)
    def exec_module(self,module):
        self.loader.exec_module(module)
        _install(module,self.cache_path)


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self,cache_path):self.cache_path=cache_path
    def find_spec(self,fullname,path=None,target=None):
        if fullname!=TARGET:return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if self in sys.meta_path:sys.meta_path.remove(self)
        if spec and spec.loader:spec.loader=_Loader(spec.loader,self.cache_path)
        return spec


def enable(cache_path=None):
    cache_path=cache_path or Path(__file__).resolve().parents[1]/'.cache/transformers-import-index.json'
    if TARGET in sys.modules:_install(sys.modules[TARGET],cache_path)
    elif not any(isinstance(f,_Finder) for f in sys.meta_path):sys.meta_path.insert(0,_Finder(cache_path))
