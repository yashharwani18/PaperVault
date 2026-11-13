"""Shared filename lookup rules: whole actual name or name without final extension."""
import unicodedata


def _normalized(value):
    value=unicodedata.normalize('NFKC',value).lower()
    return ' '.join(''.join(c if unicodedata.category(c)[0] in ('L','N','M') else ' ' for c in value).split())


class FilenameMatcher:
    def __init__(self,query):self.requested=_normalized(query)
    def matches(self,filename):
        if not self.requested:return False
        stem=filename.rsplit('.',1)[0] if '.' in filename and not filename.startswith('.') else filename
        return self.requested in (_normalized(filename),_normalized(stem))


def filename_exact(query,filename):
    return FilenameMatcher(query).matches(filename)

def observed_modified_at(signature):
    """Decode a scanner's observed size:mtime_ns signature, or report unknown."""
    from datetime import datetime,timezone
    try:
        size,mtime=str(signature).split(':',1)
        if int(size)<0 or int(mtime)<=0:return None
        return datetime.fromtimestamp(int(mtime)/1_000_000_000,timezone.utc).isoformat()
    except (TypeError,ValueError,OverflowError,OSError):
        return None


def attach_scanned_modified_times(lib,documents):
    """Use stored scan observations only when they describe the referenced source."""
    import os
    from pathlib import Path
    by_path={}
    if lib.db.execute("SELECT 1 FROM sqlite_master WHERE name='watched_files'").fetchone():
        for row in lib.db.execute('''SELECT w.document_id,w.signature,s.path,w.relative_path FROM watched_files w
                                    JOIN watched_sources s ON s.id=w.source_id WHERE w.document_id IS NOT NULL'''):
            if row['document_id']:
                path=os.path.normcase(os.path.normpath(str(Path(row['path'])/row['relative_path'])))
                by_path[(row['document_id'],path)]=observed_modified_at(row['signature'])
    import json
    recorded={}
    if lib.db.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_settings'").fetchone():
        for row in lib.db.execute("SELECT key,value FROM workspace_settings WHERE key LIKE 'khoj.modified:%'"):
            try:recorded[row['key'][len('khoj.modified:'):]]=json.loads(row['value'])
            except (ValueError,TypeError):pass
    for doc in documents:
        path=os.path.normcase(os.path.normpath(str(doc.get('managed_path',''))))
        value=by_path.get((doc['id'],path)) if doc.get('source_mode')=='reference' else None
        observation=recorded.get(doc['id'])
        if value is None and isinstance(observation,dict) and observation.get('sha256')==doc.get('sha256'):
            millis=observation.get('epoch_ms')
            if type(millis) is int and millis>0:value=observed_modified_at(f'0:{millis*1000000}')
        doc['modified_at']=value
    return documents
