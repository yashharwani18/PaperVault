"""Product information and allowlisted diagnostics: never export document data."""
import platform
import sys
import psutil
from . import APP_NAME, __version__, DISPLAY_VERSION


def about():
    return dict(name=APP_NAME,version=__version__,display_version=DISPLAY_VERSION,
        updates=dict(mode='manual',automatic_checks=False,
            instructions='Back up your library, close PaperVault, then run the newer PaperVault installer from the publisher. Install in the same location to keep your files and settings. Updates are never checked or downloaded automatically. Older versions may not support a newer database; restore a separate backup instead of downgrading in place.'),
        privacy=[
            'Searching and reading PDFs work on your computer. PaperVault does not send your files or searches to a server for local search.',
            'Scanned files stay where they are. Files you add manually may be copied into your library so they remain available.',
            'Searchable text, file locations and your changes are saved locally. This local database is not encrypted. You can make a password-protected backup.',
            'Cloud explanations are optional and off by default. If you enable Claude, your question and the selected text passages are sent to Anthropic. Local Ollama explanations go to the local service you configure.',
            'There is no automatic analytics upload. A support report is downloaded only when you ask; you choose whether to share it.'],
        diagnostics=dict(includes='App and Python versions, Windows/system type, memory, storage sizes, processing device, and counts of files, jobs and error categories.',
            excludes='Document text, PDF pages, file or folder names, paths, searches, feedback, API keys, raw errors and logs.',automatic_upload=False))


def counts(lib,table,known):
    result={key:0 for key in known}
    if not lib.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():return result
    for status,count in lib.db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'):
        if status in result:result[status]=count
        else:result['other']=result.get('other',0)+count
    return result


def diagnostics(lib,desktop):
    from .recovery import task_issue
    errors={key:0 for key in ('missing','permission','memory','unreadable','interrupted','failed')}
    if lib.db.execute("SELECT 1 FROM sqlite_master WHERE name='app_tasks'").fetchone():
        for status,error in lib.db.execute("SELECT status,error FROM app_tasks WHERE status IN ('failed','interrupted')"):
            errors[task_issue(dict(status=status,error=error))['code']]+=1
    config=desktop.assistant.config
    memory=psutil.virtual_memory()
    return dict(schema='papervault-diagnostics-v1',product=dict(name=APP_NAME,version=__version__,display_version=DISPLAY_VERSION),
        system=dict(os='Windows' if sys.platform=='win32' else 'macOS' if sys.platform=='darwin' else 'Linux' if sys.platform.startswith('linux') else 'other',
            architecture='64-bit' if sys.maxsize>2**32 else '32-bit',python='.'.join(map(str,sys.version_info[:3])),
            ram_bytes=int(memory.total),available_ram_bytes=int(memory.available),process_memory_bytes=int(psutil.Process().memory_info().rss)),
        runtime=dict(device='cuda' if desktop.model.device=='cuda' else 'cpu',
            model_state=desktop.warmup_status['state'] if desktop.warmup_status['state'] in ('not_loaded','loading','ready','error') else 'other',
            explanation_provider=config['provider'] if config['provider'] in ('builtin','ollama','claude') else 'other',cloud_enabled=bool(config.get('cloud_enabled'))),
        library=dict(documents=lib.db.execute('SELECT count(*) FROM documents').fetchone()[0],pages=lib.db.execute('SELECT count(*) FROM pages').fetchone()[0],
            chunks=lib.db.execute('SELECT count(*) FROM chunks').fetchone()[0],database_bytes=(lib.root/'library.sqlite3').stat().st_size,
            statuses=counts(lib,'documents',('indexed','partial','empty','needs_ocr','extraction_failed'))),
        tasks=counts(lib,'app_tasks',('queued','running','completed','failed','interrupted','recovered')),errors=errors)


def install(app,desktop):
    from fastapi.responses import JSONResponse
    @app.get('/api/about')
    def information():return about()

    @app.post('/api/diagnostics')
    async def download():
        report=await desktop.work(lambda lib:diagnostics(lib,desktop))
        return JSONResponse(report,headers={'Content-Disposition':'attachment; filename="khoj-diagnostics-v0.5.json"','Cache-Control':'no-store'})
