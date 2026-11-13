"""Verify the signed standalone APK and publish only the reviewed artifact locally."""
import argparse
import re
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def verify_model_assets(apk, model_variant):
    manifest=json.loads(apk.read('assets/offline-models.json'))
    assert manifest, 'Model metadata must remain bundled'
    weights={name for name in apk.namelist() if name.lower().endswith(('.gguf','.litertlm'))}
    if model_variant=='update':
        assert not weights, 'Small update APK must not bundle model weights'
    else:
        assert weights=={'assets/'+name for name in manifest}, 'Unexpected/missing bundled weights'
        for name,model in manifest.items():
            digest=hashlib.sha256()
            with apk.open('assets/'+name) as file:
                while block:=file.read(1024*1024):digest.update(block)
            assert digest.hexdigest()==model['sha256'], name
            assert apk.getinfo('assets/'+name).file_size==model['bytes'], name
    return manifest


def ui_source_files(frontend):
    paths=[path for folder in ('src','public') if (frontend/folder).is_dir() for path in (frontend/folder).rglob('*') if path.is_file()]
    paths+=[frontend/name for name in ('index.html','vite.config.js','copy-pdf-assets.mjs','package.json','pnpm-lock.yaml','tsconfig.json') if (frontend/name).is_file()]
    return sorted(paths,key=lambda path:str(path.relative_to(frontend)))


def ui_source_digest(frontend):
    digest=hashlib.sha256()
    for path in ui_source_files(frontend):
        digest.update(str(path.relative_to(frontend)).replace(os.sep,'/').encode('utf-8'));digest.update(b'\0')
        digest.update(path.read_bytes());digest.update(b'\0')
    return digest.hexdigest()


def verify_frontend(apk,frontend=None):
    """The packaged interface must equal frontend/dist and its recorded sources."""
    frontend=frontend or ROOT/'frontend';dist=frontend/'dist'
    built=[path for path in dist.rglob('*') if path.is_file()]
    assert built,'No built interface in frontend/dist; run scripts/build_android.py'
    for path in built:
        relative=str(path.relative_to(dist)).replace(os.sep,'/');name='assets/'+relative
        assert name in apk.namelist(),'Packaged interface is missing '+relative
        assert hashlib.sha256(apk.read(name)).hexdigest()==hashlib.sha256(path.read_bytes()).hexdigest(), \
            'Packaged interface differs from frontend/dist/'+relative+'; rebuild with scripts/build_android.py'
    receipt='assets/khoj-ui.json'
    assert receipt in apk.namelist(),'Packaged interface has no build receipt; rebuild with scripts/build_android.py'
    recorded=json.loads(apk.read(receipt));current=ui_source_digest(frontend)
    assert recorded.get('source_sha256')==current,'Packaged interface was built from different frontend sources; rebuild with scripts/build_android.py'
    return current


def archive_previous_release(root=ROOT):
    destination=root/'output/Khoj-0.5.0-android.apk'
    previous_report=root/'results/android-apk.json'
    if not destination.is_file() or not previous_report.is_file():return
    previous=json.loads(previous_report.read_text())
    if previous.get('version_code')!=5:return
    archive=root/'output/previous-android-v0.5-build5'
    with destination.open('rb') as file:old_sha=hashlib.file_digest(file,'sha256').hexdigest()
    assert old_sha==previous['sha256'], 'Existing APK differs from its verified report'
    if (archive/destination.name).exists():return
    archive.mkdir(exist_ok=True)
    saved=archive/destination.name
    shutil.copy2(destination,saved)
    checksum_file=destination.with_suffix('.apk.sha256')
    if checksum_file.exists() and not (archive/checksum_file.name).exists():shutil.copy2(checksum_file,archive/checksum_file.name)
    (archive/'audit.json').write_text(json.dumps(previous,indent=2),encoding='utf-8')


def build_version():
    source=(ROOT/'android/app/build.gradle').read_text()
    code=re.search(r'versionCode\s+(\d+)',source);name=re.search(r"versionName\s+'([^']+)'",source)
    assert code and name, 'Could not find versionCode/versionName in android/app/build.gradle'
    return code.group(1),name.group(1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--variant',choices=['release','debug'],default='release')
    parser.add_argument('--models',choices=['full','update'],default='full')
    parser.add_argument('--apk',type=Path,help='Exact APK to audit; defaults to the latest Gradle output')
    args=parser.parse_args()
    c=json.loads((ROOT/'.cache/android-tools/toolchain.json').read_text());sdk=Path(c['sdk']);env=dict(os.environ,JAVA_HOME=c['java_home']);env['PATH']=str(Path(c['java_home'])/'bin')+os.pathsep+env['PATH']
    source=args.apk or ROOT/f'android/app/build/outputs/apk/{args.variant}/app-{args.variant}.apk';build=sdk/'build-tools/35.0.0'
    signature=subprocess.run([str(build/'apksigner.bat'),'verify','--verbose','--print-certs',str(source)],env=env,capture_output=True,text=True,check=True)
    alignment=subprocess.run([str(build/'zipalign.exe'),'-c','-P','16','4',str(source)],env=env,capture_output=True,text=True,check=True)
    badging=subprocess.run([str(build/'aapt2.exe'),'dump','badging',str(source)],env=env,capture_output=True,text=True,check=True)
    assert "uses-permission: name='android.permission.INTERNET'" not in badging.stdout
    assert "minSdkVersion:'26'" in badging.stdout and "targetSdkVersion:'35'" in badging.stdout
    assert "org.localknowledge.library" in badging.stdout
    version_code,version_name=build_version()
    assert f"versionName='{version_name}'" in badging.stdout
    assert f"versionCode='{version_code}'" in badging.stdout
    assert "application-label:'Khoj'" in badging.stdout
    if args.variant=='release':assert "application-debuggable" not in badging.stdout
    with zipfile.ZipFile(source) as z:
        names=z.namelist();manifest=verify_model_assets(z,args.models)
        expected=json.loads((ROOT/'android/runtime-model-assets/offline-models.json').read_text())
        assert manifest==expected, 'APK model recipe differs from the reviewed offline model recipe'
        assert 'assets/index.html' in names and 'assets/APACHE-2.0.txt' in names and 'assets/NOTICE.txt' in names
        verify_frontend(z)
        assert 'assets/KLEIDIAI-LICENSES.txt' in names
        assert not any(name.endswith('.sqlite3') or 'synthetic-' in name for name in names)
        assert any('lib/arm64-v8a/liblibrary_models.so'==name for name in names)
        assert any('lib/x86_64/liblibrary_models.so'==name for name in names)
        for abi in ('arm64-v8a','x86_64'):
            assert b'KHOJ_NATIVE_BATCHES = 1' in z.read(f'lib/{abi}/liblibrary_models.so')
        assert b'kleidiai: primary q8 kernel' in z.read('lib/arm64-v8a/libggml-cpu-android_armv8.2_2.so')
        assert b'kleidiai: primary q8 kernel' not in z.read('lib/x86_64/libggml-cpu.so')
        # Dynamic dispatch must ship both the portable fallback and faster kernels.
        for variant in ('android_armv8.0_1','android_armv8.2_1','android_armv8.2_2','android_armv8.6_1'):
            assert f'lib/arm64-v8a/libggml-cpu-{variant}.so' in names
        for abi in ('arm64-v8a','x86_64'):
            for library in ('libggml-base.so','libggml.so','libllama.so'):
                assert f'lib/{abi}/{library}' in names
        for name in names:
            if not (name.startswith('lib/') and name.endswith('.so')):continue
            data=z.read(name)
            assert data[:6]==b'\x7fELF\x02\x01',name
            phoff=struct.unpack_from('<Q',data,32)[0]
            entsize,count=struct.unpack_from('<HH',data,54)
            for i in range(count):
                header=phoff+i*entsize
                if struct.unpack_from('<I',data,header)[0]==1:
                    assert struct.unpack_from('<Q',data,header+48)[0]>=16384,name
    suffix='-update' if args.models=='update' else ''
    destination=ROOT/f'output/Khoj-0.5.0-android{suffix}.apk';destination.parent.mkdir(exist_ok=True)
    if args.models=='full':archive_previous_release()
    # Check the certificate against the retained signing key, not merely a self-signed APK.
    key=ROOT/'android/signing/local-development.keystore'
    keyinfo=subprocess.run([str(Path(c['java_home'])/'bin/keytool.exe'),'-list','-v','-keystore',str(key),'-storepass','android','-alias','androiddebugkey'],env=env,capture_output=True,text=True,check=True)
    fingerprint=re.search(r'SHA256:\s*([0-9A-Fa-f:]+)',keyinfo.stdout)
    cert=re.search(r'certificate SHA-256 digest:\s*([0-9a-fA-F]+)',signature.stdout)
    assert fingerprint and cert and fingerprint[1].replace(':','').lower()==cert[1].lower(), 'APK does not use the retained signing key'
    if source.resolve()!=destination.resolve():shutil.copy2(source,destination)
    with destination.open('rb') as file:checksum=hashlib.file_digest(file,'sha256').hexdigest()
    report=dict(apk=str(destination),bytes=destination.stat().st_size,MiB=round(destination.stat().st_size/2**20,1),sha256=checksum,
        package='org.localknowledge.library',version=version_name,version_code=int(version_code),min_sdk=26,target_sdk=35,
        no_internet_permission=True,models=manifest,model_variant=args.models,model_weights_bundled=args.models=='full',signature_verified=True,signing_certificate_sha256=cert[1].lower(),zip_alignment_16KB=True,
        interface_matches_source=True,interface_source_sha256=ui_source_digest(ROOT/'frontend'),
        debuggable="application-debuggable" in badging.stdout,signing_key="local-development",release_shrunk=args.variant=='release' and 'minifyEnabled true' in (ROOT/'android/app/build.gradle').read_text(),synthetic_test_documents_bundled=False,
        runtime_arm_cpu_dispatch=True,portable_arm_fallback=True,native_elf_alignment_16KB=True,
        kleidiai_arm_compiled=True,kleidiai_arm_execution_verified=False,experimental_native_batches=True,native_embedding_batch_max=4,batching_runtime_scalar_gate=True,
        permissions=[line for line in badging.stdout.splitlines() if line.startswith('uses-permission:')])
    (ROOT/f'results/android-apk{suffix}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/f'results/android-apk{suffix}-signature.log').write_text(signature.stdout+signature.stderr,encoding='utf-8')
    (destination.with_suffix('.apk.sha256')).write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
