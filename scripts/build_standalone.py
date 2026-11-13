"""Build a Windows desktop application folder, including Python and offline models.

No freezer: copying the actual runtime retains the source/metadata required by
Transformers, Torch and the pinned inference loader. No user library is bundled.
Microsoft's WebView2 SDK must be downloaded to the documented cache first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = '1.0.4258.31'


def copy_tree(source, target, excluded=()):
    excluded = set(excluded) | {'__pycache__'}
    def ignore(directory, names):
        return [n for n in names if n in excluded or n.endswith(('.pyc', '.pyo'))]
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / 'Local-Library-Desktop')
    parser.add_argument('--library', type=Path, help='Local installation preference only; source library is never copied.')
    parser.add_argument('--code-only', action='store_true', help='Refresh code/host, reusing an already copied runtime and models.')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'output'):
        raise ValueError('Build output must stay inside the project output directory.')
    sdk = ROOT / '.cache' / 'webview2-sdk' / SDK_VERSION
    if not (sdk / 'lib/net462/Microsoft.Web.WebView2.Core.dll').is_file():
        raise ValueError('Download the official Microsoft.Web.WebView2 SDK to .cache/webview2-sdk/' + SDK_VERSION)
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / 'runtime'
    app = output / 'app'
    runtime.mkdir(exist_ok=True)
    app.mkdir(exist_ok=True)
    begin = time.perf_counter()
    if not args.code_only:
        print('Bundling Python runtime and installed dependencies…', flush=True)
        base = Path(sys.base_prefix)
        for name in ['python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt']:
            shutil.copy2(base / name, runtime / name)
        copy_tree(base / 'DLLs', runtime / 'DLLs')
        copy_tree(base / 'Lib', runtime / 'Lib', ['site-packages', 'test', 'idlelib', 'ensurepip', 'venv', 'turtledemo'])
        copy_tree(base / 'tcl', runtime / 'tcl')
        copy_tree(Path(sys.prefix) / 'Lib/site-packages', runtime / 'Lib/site-packages')
        print('Bundling the installed offline models…', flush=True)
        copy_tree(ROOT / 'models', app / 'models')
    (runtime / 'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n../app\nimport site\n', encoding='utf-8')
    print('Copying the existing interface and application…', flush=True)
    copy_tree(ROOT / 'knowledge_library', app / 'knowledge_library')
    copy_tree(ROOT / 'frontend/dist', app / 'frontend/dist')
    for name in ['model-lock.json', 'qwen-lock.json']:
        shutil.copy2(ROOT / name, app / name)
    (app / 'evaluation').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'evaluation/confidence-policy.json', app / 'evaluation/confidence-policy.json')
    (app / 'scripts').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'scripts/convert_presentation.ps1', app / 'scripts/convert_presentation.ps1')
    for name in ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']:
        shutil.copy2(sdk / 'lib/net462' / name, output / name)
    shutil.copy2(sdk / 'runtimes/win-x64/native/WebView2Loader.dll', output / 'WebView2Loader.dll')
    for name in ['LICENSE.txt', 'NOTICE.txt']:
        shutil.copy2(sdk / name, output / ('WebView2-' + name))
    shutil.copy2(ROOT / 'desktop/Library.exe.config', output / 'Library.exe.config')
    # A code-native book icon, consistent with the existing catalogue mark.
    from PIL import Image, ImageDraw
    icon = Image.new('RGBA', (256, 256), '#1b181d')
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((20, 20, 236, 236), radius=42, fill='#2f2a33')
    draw.line([(66, 67), (66, 189), (124, 177), (124, 66)], fill='#d0b5f6', width=12)
    draw.line([(132, 66), (132, 177), (190, 189), (190, 67)], fill='#d0b5f6', width=12)
    icon_path = ROOT / '.cache/webview2-sdk/Library.ico'
    icon.save(icon_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command = [str(compiler), '/nologo', '/target:winexe', '/platform:x64',
        '/out:' + str(output / 'Library.exe'), '/win32icon:' + str(icon_path),
        '/win32manifest:' + str(ROOT / 'desktop/Library.manifest'),
        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        '/reference:System.Net.Http.dll', '/reference:System.Web.Extensions.dll',
        '/reference:' + str(output / 'Microsoft.Web.WebView2.Core.dll'),
        '/reference:' + str(output / 'Microsoft.Web.WebView2.WinForms.dll'), str(ROOT / 'desktop/Library.cs')]
    subprocess.run(command, check=True)
    if args.library:
        (output / 'Library.user.json').write_text(json.dumps({'library_path': str(args.library.resolve())}, indent=2), encoding='utf-8')
    (output / 'READ-ME.txt').write_text(
        'Double-click Library.exe. Keep this whole application folder together.\n'
        'Includes Python, installed dependencies, the interface, and offline AI models; no separate Python/Node/server commands are needed.\n'
        'Uses Microsoft WebView2 Runtime and .NET Framework 4.7.2+ (already installed on the development PC).\n'
        'Minimize sends Library to the tray and keeps indexing/folder checks running. Closing the window or choosing Exit stops its backend.\n'
        'By default, documents are stored under data/library beside this executable. A local Library.user.json may select an existing library.\n'
        'No user documents are copied into this build. The local installation may refer to an existing library without moving it.\n'
        'Connect folders from the existing interface. Claude is optional and requires an API key; default search is local.\n', encoding='utf-8')
    count = size = 0
    for base, dirs, files in os.walk(output):
        dirs[:] = [d for d in dirs if d != 'data']
        for name in files:
            count += 1
            size += (Path(base) / name).stat().st_size
    report = dict(executable=str(output / 'Library.exe'), files=count, bytes=size,
        elapsed_s=round(time.perf_counter()-begin, 2), sdk_version=SDK_VERSION,
        executable_sha256=hashlib.sha256((output / 'Library.exe').read_bytes()).hexdigest(),
        runtime_bundled=True, offline_models_bundled=True, user_documents_bundled=False,
        requirements=['Windows x64', '.NET Framework 4.7.2+', 'Microsoft WebView2 Runtime'])
    (ROOT / 'results/standalone-build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
