"""Workspace-local release APK build; --update reuses installed private models."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def node_binary():
    """Use Node from PATH, with a fallback to the bundled workspace runtime."""
    found=shutil.which('node')
    if found:return found
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin'/('node.exe' if os.name=='nt' else 'node')
    return str(bundled) if bundled.exists() else None


def build_frontend():
    """Rebuild the interface and record its source digest, so the audit can prove what shipped."""
    from audit_android_apk import ui_source_digest
    node=node_binary()
    if not node:raise RuntimeError('Install Node.js 24 and make it available on PATH before building the interface.')
    cwd=ROOT/'frontend'
    for script in (['copy-pdf-assets.mjs'],['node_modules/typescript/bin/tsc','-b'],['node_modules/vite/bin/vite.js','build']):
        subprocess.run([node,*script],cwd=cwd,check=True)
    receipt={'format':'khoj-ui-v1','source_sha256':ui_source_digest(cwd)}
    (cwd/'dist'/'khoj-ui.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print('Interface rebuilt (source '+receipt['source_sha256'][:12]+')',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update',action='store_true',help='Omit model weights; existing verified private models are required')
    args,gradle_args=parser.parse_known_args()
    update=args.update or any(value.lower()=='-pkhojbundlemodels=off' for value in gradle_args)
    config=json.loads((ROOT/'.cache/android-tools/toolchain.json').read_text())
    env=dict(os.environ,JAVA_HOME=config['java_home'],ANDROID_HOME=config['sdk'],ANDROID_USER_HOME=str(ROOT/'.cache/android-tools/android-user'))
    env['PATH']=str(Path(config['java_home'])/'bin')+os.pathsep+env['PATH']
    (ROOT/'android/local.properties').write_text('sdk.dir='+config['sdk'].replace('\\','/')+'\n',encoding='utf-8')
    qwen=ROOT/'android/model-assets/qwen3-0.6b-q4.gguf'
    if not update and not qwen.exists():
        original=ROOT/'models/qwen3-0.6b/Qwen_Qwen3-0.6B-Q4_K_M.gguf'
        try:os.link(original,qwen)
        except OSError:shutil.copy2(original,qwen)
    models={'qwen3-0.6b-q4.gguf':dict(bytes=484220320,sha256='9acfc1e001311f34b4252001b626f2e466d592a42065f66571bff3790d4e1b14',model_id='Qwen/Qwen3-0.6B'),
        'embeddinggemma-2-q8.gguf':dict(bytes=config['embedding']['bytes'],sha256=config['embedding']['sha256'],model_id='google/embeddinggemma-2',revision=config['embedding']['revision'])}
    (ROOT/'android/model-assets/offline-models.json').write_text(json.dumps(models,indent=2),encoding='utf-8')
    from prepare_android_text_assets import prepare
    prepare()
    if not gradle_args or any(value.startswith('assemble') for value in gradle_args):build_frontend()
    key=ROOT/'android/signing/local-development.keystore'
    key.parent.mkdir(parents=True,exist_ok=True)
    old_key=ROOT/'.cache/android-tools/debug.keystore'
    if not key.exists() and old_key.exists():shutil.copy2(old_key,key)
    if not key.exists():raise RuntimeError('The existing Khoj signing key is missing. Restore it before building an update; a replacement key cannot update installed Khoj.')
    # Always pass the variant explicitly so a prior small build cannot affect a full build.
    command=[config['gradle'],'--no-daemon','--console','plain','--gradle-user-home',str(ROOT/'.cache/android-gradle'),'-PllamaSource='+config['llama'],'-PkhojBundleModels='+('OFF' if update else 'ON')]+(gradle_args or ['assembleRelease'])
    subprocess.run(command,cwd=ROOT/'android',env=env,check=True)
    source=ROOT/'android/app/build/outputs/apk/release/app-release.apk'
    if source.is_file() and (not gradle_args or 'assembleRelease' in gradle_args):
        from audit_android_apk import archive_previous_release
        if not update:archive_previous_release()
        suffix='-update' if update else ''
        destination=ROOT/f'output/Khoj-0.5.0-android{suffix}.apk';destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source,destination);print('APK (audit required): '+str(destination),flush=True)


if __name__=='__main__':main()
