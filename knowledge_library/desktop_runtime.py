"""Backend owned by the standalone Windows window; no browser or external Python."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time


def serve(library, ready_file, parent_pid=0, device=None, preload=True):
    import psutil
    import uvicorn
    from .server import create_app, offline_guard

    library = Path(library).resolve()
    ready_file = Path(ready_file).resolve()
    if not ready_file.is_relative_to(library):
        raise ValueError('The readiness file must stay inside the selected library.')
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    ready_file.unlink(missing_ok=True)
    offline_guard()
    from .hardware import select_device,system_report
    selection=select_device() if device is None else dict(device=device,gpu_name=None,reason='Device selected explicitly.')
    device=selection['device']
    app = create_app(library, device, preload=preload)
    app.state.hardware=system_report(library,selection)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False))

    @app.post('/api/desktop/shutdown')
    def shutdown():
        # Existing origin/token middleware authenticates this request.
        server.should_exit = True
        return dict(stopping=True)

    # create_app mounts static files last; register this control before that mount.
    control = app.router.routes.pop()
    app.router.routes.insert(0, control)
    parent_created = None
    if parent_pid:
        parent_created = psutil.Process(parent_pid).create_time()
    finished = threading.Event()

    def monitor():
        published = False
        while not finished.wait(.3):
            if parent_pid:
                try:
                    parent_alive = psutil.Process(parent_pid).create_time() == parent_created
                except psutil.Error:
                    parent_alive = False
                if not parent_alive:
                    server.should_exit = True
                    return
            if server.started and not published:
                record = dict(pid=os.getpid(), url=f'http://127.0.0.1:{port}',
                    library=str(library), token=app.state.desktop.token, device=device)
                temporary = ready_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(record), encoding='utf-8')
                temporary.replace(ready_file)
                published = True

    worker = threading.Thread(target=monitor, name='native-owner-monitor', daemon=True)
    worker.start()
    try:
        server.run(sockets=[sock])
    finally:
        finished.set()
        worker.join(timeout=3)
        sock.close()
        ready_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--ready-file', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, default=0)
    parser.add_argument('--device', choices=['cuda', 'cpu'])
    parser.add_argument('--no-preload', action='store_true')
    args = parser.parse_args()
    logs = args.library / 'native'
    logs.mkdir(parents=True, exist_ok=True)
    # pythonw has no console streams; keep failures reviewable in the library.
    with (logs / 'backend.log').open('a', encoding='utf-8', buffering=1) as log:
        sys.stdout = log
        sys.stderr = log
        try:
            serve(args.library, args.ready_file, args.parent_pid, args.device, not args.no_preload)
        except BaseException:
            import traceback
            traceback.print_exc()
            raise


if __name__ == '__main__':
    main()
