"""Authenticated folder connections for the loopback desktop app."""
from pydantic import BaseModel, Field


class ConnectBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    ocr: bool = False


class EnableBody(BaseModel):
    enabled: bool


class ComputerScanBody(BaseModel):
    confirm: bool = False
    ocr: bool = False
    excluded_paths: list[str] = Field(default_factory=list, max_length=64)


def fixed_drives():
    import os
    if os.name != 'nt':
        return []
    import ctypes
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    return [f'{chr(65+i)}:\\' for i in range(26)
        if mask & (1 << i) and kernel.GetDriveTypeW(ctypes.c_wchar_p(f'{chr(65+i)}:\\')) == 3]


def pick_directory():
    # Tk runs in a separate process: its event loop must own its main thread.
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = '''import json
import tkinter as tk
from tkinter import filedialog
root=tk.Tk()
root.withdraw()
root.attributes('-topmost',True)
try:
    path=filedialog.askdirectory(title='Connect a folder to Library',mustexist=True,parent=root)
    print(json.dumps({'path':path or None}))
finally:
    root.destroy()
'''
    try:
        console_python = Path(sys.executable).with_name('python.exe')
        interpreter = str(console_python) if os.name == 'nt' and console_python.is_file() else sys.executable
        result = subprocess.run([interpreter, '-c', code], capture_output=True, text=True,
            timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise ValueError('The folder picker is unavailable. Paste a full folder path instead.')
        import json
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Folder selection timed out. Try again or paste a full folder path.') from exc


def install(app, desktop):
    @app.get('/api/connections')
    def connections():
        from .discovery import sources, INTERVAL
        with desktop.lib() as lib:
            items=sources(lib)
            for item in items:item['scan_progress']=desktop.discovery.progress.get(item['id'])
            return dict(sources=items, interval_seconds=INTERVAL)

    @app.get('/api/computer-scan')
    def computer_scan_plan():
        with desktop.lib() as lib:
            choice=lib.db.execute("SELECT value FROM workspace_settings WHERE key='computer_scan_choice'").fetchone()
        return dict(drives=fixed_drives(), choice=choice[0] if choice else None,
            exclusions=['Windows and application folders','AppData and dependency caches','Protected locations and this library'],
            rescan_seconds=3600)

    @app.post('/api/computer-scan/skip')
    def skip_computer_scan():
        with desktop.lib() as lib:
            with lib.db:lib.db.execute("INSERT OR REPLACE INTO workspace_settings VALUES('computer_scan_choice','folders')")
        return dict(choice='folders')

    @app.post('/api/computer-scan')
    def start_computer_scan(body:ComputerScanBody):
        from pathlib import Path
        if not body.confirm:raise ValueError('Confirm the computer scan before indexing any drives.')
        drives=fixed_drives()
        if not drives:raise ValueError('No fixed local drives are available. Choose a folder instead.')
        excluded=[]
        for p in body.excluded_paths:
            if len(p)>4096 or not Path(p).is_absolute():raise ValueError('Excluded folders need full absolute paths.')
            excluded.append(str(Path(p).resolve()))
        if body.ocr:
            from .embedding import PROJECT
            if not (PROJECT/'models/tessdata/eng.traineddata').is_file():raise ValueError('English OCR data is not installed.')
        # Do not partly supersede existing source connections or index a drive twice.
        with desktop.lib() as lib:
            if lib.db.execute('SELECT 1 FROM watched_sources').fetchone():
                raise ValueError('Folder connections already exist. Keep using them, or disconnect them before choosing a whole-PC scan. Indexed copies are retained.')
        with desktop.discovery.lock:
            added=[desktop.discovery.add(path,body.ocr,computer=True,excluded_paths=excluded) for path in drives]
        with desktop.lib() as lib:
            with lib.db:lib.db.execute("INSERT OR REPLACE INTO workspace_settings VALUES('computer_scan_choice','computer')")
        return dict(sources=added,choice='computer')

    @app.post('/api/connections/pick')
    def pick():
        return pick_directory()

    @app.post('/api/connections')
    def connect(body: ConnectBody):
        if body.ocr:
            from .embedding import PROJECT
            if not (PROJECT / 'models/tessdata/eng.traineddata').is_file():
                raise ValueError('English OCR data is not installed. Connect without OCR or install it first.')
        return desktop.discovery.add(body.path.strip(), body.ocr)

    @app.patch('/api/connections/{key}')
    def change(key: str, body: EnableBody):
        return desktop.discovery.change(key, enabled=body.enabled)

    @app.delete('/api/connections/{key}')
    def disconnect(key: str):
        return desktop.discovery.change(key, disconnect=True)

    @app.post('/api/connections/{key}/scan')
    def scan(key: str):
        desktop.discovery.request(key)
        return dict(scheduled=True)

    @app.post('/api/connections/{key}/retry')
    def retry(key: str):
        desktop.discovery.retry(key)
        return dict(scheduled=True)
