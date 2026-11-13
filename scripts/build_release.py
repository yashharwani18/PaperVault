"""Build a source-free proprietary backend; third-party dependencies retain notices.

Requires pinned Cython source and Zig under .cache/release-tools. Hardlinks stage
unchanged runtime/model files without duplicating their disk allocation. Never
write through a staged hardlink. Source/development data are not release inputs.
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

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.5.0'


def allowed_file(relative):
    parts=relative.parts
    lower=[p.casefold() for p in parts]
    if not parts or lower[0] not in {'library.exe','library.exe.config','microsoft.web.webview2.core.dll',
            'microsoft.web.webview2.winforms.dll','webview2loader.dll','webview2-license.txt','webview2-notice.txt',
            'app','runtime','release.json','third-party-notices.txt','read-me.txt'}:return False
    blocked={'__pycache__','.git','.cache','uploads','staging','node_modules'}
    if lower[0]!='runtime':blocked|={'data','tests','test'}
    if any(p in blocked for p in lower):return False
    if relative.suffix.casefold() in {'.pdb','.map','.pdf','.sqlite3','.db','.log','.pyc','.pyo','.obj','.ilk','.exp'}:return False
    if lower[:2]==['app','knowledge_library'] and relative.suffix.casefold()!='.pyd':return False
    return True


def validate_payload(root):
    for path in root.rglob('*'):
        if path.is_file() and not allowed_file(path.relative_to(root)):
            raise ValueError('Forbidden release source/data/debug file: '+str(path.relative_to(root)))
    for name in ['Library.exe','app/knowledge_library/server.pyd','app/knowledge_library/library.pyd','app/launch.py','runtime/pythonw.exe','app/frontend/dist/index.html']:
        if not (root/name).is_file():raise ValueError('Required release file missing: '+name)


def stage_file(source,target):
    if target.exists():
        if os.path.samefile(source,target):return
        if source.stat().st_size==target.stat().st_size and hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(target.read_bytes()).digest():return
        target.unlink()  # Detach any previous hardlink before replacing its contents.
    target.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,target)
    except OSError:shutil.copy2(source,target)


def stage_tree(source,target,release):
    for path in source.rglob('*'):
        if path.is_file():
            destination=target/path.relative_to(source)
            if allowed_file(destination.relative_to(release)):stage_file(path,destination)


def write_owned(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_text(text,encoding='utf-8')


def compile_backend(destination,only=None):
    tools=ROOT/'.cache/release-tools'
    sys.path.insert(0,str(tools/'cython-3.1.6'))
    from Cython.Compiler.Main import compile,CompilationOptions,default_options
    from Cython.Compiler import Options
    Options.docstrings=False
    generated=ROOT/'.cache/release-native';generated.mkdir(parents=True,exist_ok=True)
    zig=tools/'zig-x86_64-windows-0.15.2/zig.exe'
    environment=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(tools/'zig-global'),ZIG_LOCAL_CACHE_DIR=str(tools/'zig-local'))
    destination.mkdir(parents=True,exist_ok=True)
    records=[]
    for source in sorted((ROOT/'knowledge_library').glob('*.py')):
        if source.stem=='__main__' or (only and source.stem not in only):continue
        module='knowledge_library' if source.stem=='__init__' else 'knowledge_library.'+source.stem
        generated_c=generated/(source.stem+'.c')
        options=CompilationOptions(default_options,output_file=str(generated_c),compiler_directives={
            'language_level':3,'annotation_typing':False,'binding':True,'emit_code_comments':False,'embedsignature':False})
        result=compile(str(source.relative_to(ROOT)),options=options,full_module_name=module)
        if result.num_errors:raise RuntimeError('Cython compilation failed: '+module)
        target=destination/(source.stem+'.pyd')
        print('Compiling '+module,flush=True)
        command=[str(zig),'cc','-shared','-target','x86_64-windows-gnu','-O2','-s',
                 '-I'+str(Path(sys.base_prefix)/'include'),str(generated_c),str(Path(sys.base_prefix)/'libs/python312.lib'),
                 '-Wl,--out-implib='+str(generated/(source.stem+'.lib')),'-o',str(target)]
        subprocess.run(command,check=True,env=environment,cwd=ROOT)
        previous_import_library=target.with_suffix('.lib')
        if previous_import_library.exists():previous_import_library.replace(generated/previous_import_library.name)
        records.append(dict(module=module,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    return records


def build_host(release):
    compiler=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+','/debug-',
             '/out:'+str(release/'Library.exe'),'/win32manifest:'+str(ROOT/'desktop/Library.manifest'),
             '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Net.Http.dll','/reference:System.Web.Extensions.dll']
    for name in ['Core','WinForms']:command.append('/reference:'+str(release/f'Microsoft.Web.WebView2.{name}.dll'))
    icon=ROOT/'.cache/release-native/Library.ico'
    from PIL import Image,ImageDraw
    picture=Image.new('RGBA',(256,256),'#1b181d');draw=ImageDraw.Draw(picture)
    draw.rounded_rectangle((20,20,236,236),radius=42,fill='#2f2a33')
    draw.line([(66,67),(66,189),(124,177),(124,66)],fill='#d0b5f6',width=12)
    draw.line([(132,66),(132,177),(190,189),(190,67)],fill='#d0b5f6',width=12)
    picture.save(icon,sizes=[(16,16),(32,32),(48,48),(256,256)])
    command+=['/win32icon:'+str(icon),str(ROOT/'desktop/Library.cs')]
    subprocess.run(command,check=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compile-only',action='store_true');parser.add_argument('--only',nargs='*');parser.add_argument('--stage-only',action='store_true')
    args=parser.parse_args()
    release=ROOT/'output/Local-Library-Release';release.mkdir(parents=True,exist_ok=True)
    if args.stage_only:
        records=[]
        for source in sorted((ROOT/'knowledge_library').glob('*.py')):
            if source.stem=='__main__':continue
            binary=release/'app/knowledge_library'/(source.stem+'.pyd')
            if not binary.exists() or binary.stat().st_mtime_ns<source.stat().st_mtime_ns:raise ValueError('Compile changed/missing module first: '+source.stem)
            records.append(dict(module='knowledge_library' if source.stem=='__init__' else 'knowledge_library.'+source.stem,sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
        for import_library in (release/'app/knowledge_library').glob('*.lib'):
            import_library.replace(ROOT/'.cache/release-native'/import_library.name)
    else:records=compile_backend(release/'app/knowledge_library',args.only)
    if args.compile_only:return
    existing=ROOT/'output/Local-Library-Desktop'
    stage_tree(existing/'runtime',release/'runtime',release)
    # Isolate imports from system Python, user site packages, PATH and development source.
    write_owned(release/'runtime/python312._pth','.\nDLLs\nLib\nLib/site-packages\n../app\nimport site\n')
    stage_tree(existing/'app/models',release/'app/models',release)
    stage_tree(ROOT/'frontend/dist',release/'app/frontend/dist',release)
    for name in ['model-lock.json','qwen-lock.json']:
        stage_file(ROOT/name,release/'app'/name)
    stage_file(ROOT/'evaluation/confidence-policy.json',release/'app/evaluation/confidence-policy.json')
    stage_file(ROOT/'scripts/convert_presentation.ps1',release/'app/scripts/convert_presentation.ps1')
    for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll','WebView2-LICENSE.txt','WebView2-NOTICE.txt','Library.exe.config']:
        stage_file(existing/name,release/name)
    write_owned(release/'app/launch.py','from knowledge_library.desktop_runtime import main\nif __name__ == "__main__":\n    main()\n')
    build_host(release)
    # Preserve dependency metadata/licences. This inventory is not a legal clearance.
    notices=['Khoj '+VERSION,'Proprietary application modules are distributed as native binaries.',
             'Third-party software retains its respective licences. See runtime/Lib/site-packages/*.dist-info and app/models notices.',
             'RELEASE REVIEW: PyMuPDF uses AGPL/commercial dual licensing. A suitable commercial redistribution licence is required for a closed-source public release.',
             'This private release candidate is unsigned. Compilation does not prevent determined reverse engineering.','']
    for info in sorted((release/'runtime/Lib/site-packages').glob('*.dist-info')):
        meta=info/'METADATA'
        if meta.exists():
            fields=[line for line in meta.read_text(encoding='utf-8',errors='replace').splitlines() if line.startswith(('Name: ','Version: ','License: ','License-Expression: '))]
            notices.append(' | '.join(fields))
    write_owned(release/'THIRD-PARTY-NOTICES.txt','\n'.join(notices)+'\n')
    write_owned(release/'READ-ME.txt','Khoj v0.5 - offline Windows release candidate\nRun Library.exe. CUDA is used after an execution check; otherwise CPU is selected.\nInstalled library data lives separately under %LOCALAPPDATA%\\LocalKnowledgeLibrary\\library.\nNo user documents are included. Originals found by scanning are never copied.\nPrivate testing build: unsigned; review THIRD-PARTY-NOTICES.txt before public distribution.\n')
    manifest=dict(name='Khoj',display_version='v0.5',version=VERSION,compiled_modules=records,default_device='auto',source_included=False,signed=False,public_release_cleared=False)
    write_owned(release/'release.json',json.dumps(manifest,indent=2))
    # Smoke checks or previous local launches may create bytecode. Remove only
    # these generated release files, never development files or user data.
    for path in release.rglob('*.pyc'):
        if not path.resolve().is_relative_to(release.resolve()):raise ValueError('Release bytecode escaped output directory')
        path.unlink()
    cache=release/'app/.cache'
    if cache.exists():
        for path in cache.rglob('*'):
            if path.is_file():
                if not path.resolve().is_relative_to(release.resolve()):raise ValueError('Release cache escaped output directory')
                path.unlink()
    validate_payload(release)
    print('Validated release payload: '+str(release),flush=True)


if __name__=='__main__':main()
