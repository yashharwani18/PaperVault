"""Workspace-local Android toolchain and pinned offline model assets."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'.cache/android-tools'


def metadata(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LocalKnowledgeLibrary-build'}),timeout=60) as r:return json.load(r)


def download(url,path,expected=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and (not expected or hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==expected):return path
    temporary=path.with_suffix(path.suffix+'.partial');digest=hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LocalKnowledgeLibrary-build'}),timeout=120) as r,temporary.open('wb') as f:
        while block:=r.read(1024*1024):f.write(block);digest.update(block)
    if expected and digest.hexdigest()!=expected:raise ValueError('Download checksum mismatch: '+path.name)
    temporary.replace(path);print('Downloaded '+path.name,flush=True);return path


def unpack(archive,directory):
    if directory.exists():return
    directory.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if not (directory/item.filename).resolve().is_relative_to(directory.resolve()):raise ValueError('Unsafe archive path')
        z.extractall(directory)


def main():
    TOOLS.mkdir(parents=True,exist_ok=True)
    jdk=metadata('https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows')[0]['binary']['package']
    gradle_url='https://services.gradle.org/distributions/gradle-8.11.1-bin.zip'
    with urllib.request.urlopen(gradle_url+'.sha256',timeout=60) as r:gradle_sha=r.read().decode().strip()
    hf=metadata('https://huggingface.co/api/models/ggml-org/embeddinggemma-2-GGUF?blobs=true')
    candidates=[s for s in hf['siblings'] if 'q8_0' in s['rfilename'].lower() and s['rfilename'].endswith('.gguf') and 'mmproj' not in s['rfilename']]
    if len(candidates)!=1:raise ValueError('Select the text-only EmbeddingGemma 2 Q8_0 model explicitly')
    model=candidates[0];sha=model['lfs']['sha256'];name=model['rfilename']
    model_path=ROOT/'android/model-assets/embeddinggemma-2-q8.gguf'
    tasks=[
        ('jdk',jdk['link'],TOOLS/'downloads/jdk17.zip',jdk['checksum']),
        ('sdk','https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip',TOOLS/'downloads/sdk-tools.zip','90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a'),
        ('gradle',gradle_url,TOOLS/'downloads/gradle.zip',gradle_sha),
        ('llama','https://codeload.github.com/ggml-org/llama.cpp/zip/refs/tags/b11714',TOOLS/'downloads/llama-b11714.zip',None),
        ('embedding','https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/'+hf['sha']+'/'+name,model_path,sha)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        jobs=[pool.submit(download,url,path,checksum) for _,url,path,checksum in tasks]
        for job in jobs:job.result()
    unpack(TOOLS/'downloads/jdk17.zip',TOOLS/'jdk')
    unpack(TOOLS/'downloads/gradle.zip',TOOLS/'gradle')
    unpack(TOOLS/'downloads/llama-b11714.zip',TOOLS/'llama')
    unpack(TOOLS/'downloads/sdk-tools.zip',TOOLS/'sdk/cmdline-tools/bootstrap')
    java=next((TOOLS/'jdk').glob('*/bin/java.exe')).parent.parent
    sdk=TOOLS/'sdk'
    sdkmanager=sdk/'cmdline-tools/bootstrap/cmdline-tools/bin/sdkmanager.bat'
    env=dict(os.environ,JAVA_HOME=str(java),ANDROID_HOME=str(sdk),ANDROID_USER_HOME=str(TOOLS/'android-user'))
    env['PATH']=str(java/'bin')+os.pathsep+env['PATH']
    subprocess.run([str(sdkmanager),'--sdk_root='+str(sdk),'--licenses'],input='y\n'*100,text=True,env=env,check=True)
    subprocess.run([str(sdkmanager),'--sdk_root='+str(sdk),'platforms;android-35','build-tools;35.0.0','platform-tools','ndk;28.2.13676358','cmake;3.22.1'],env=env,check=True)
    record=dict(java_home=str(java),sdk=str(sdk),gradle=str(next((TOOLS/'gradle').glob('*/bin/gradle.bat'))),
        llama=str(next((TOOLS/'llama').glob('llama.cpp-*'))),embedding=dict(repository=hf['id'],revision=hf['sha'],filename=name,sha256=sha,bytes=model_path.stat().st_size),
        sdk_tools_sha256=tasks[1][3],jdk_sha256=jdk['checksum'],gradle_sha256=gradle_sha)
    (TOOLS/'toolchain.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('Android toolchain ready',flush=True)


if __name__=='__main__':main()
