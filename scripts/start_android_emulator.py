"""Create and start the task-owned headless phone emulator in the workspace."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    c=json.loads((ROOT/'.cache/android-tools/toolchain.json').read_text());sdk=Path(c['sdk']);avd=ROOT/'.cache/android-tools/avd';avd.mkdir(exist_ok=True)
    env=dict(os.environ,JAVA_HOME=c['java_home'],ANDROID_HOME=str(sdk),ANDROID_SDK_ROOT=str(sdk),ANDROID_USER_HOME=str(ROOT/'.cache/android-tools/android-user'),ANDROID_AVD_HOME=str(avd))
    env['PATH']=str(Path(c['java_home'])/'bin')+os.pathsep+env['PATH']
    manager=sdk/'cmdline-tools/latest/bin/avdmanager.bat'
    if not (avd/'library-test.avd').is_dir():subprocess.run([str(manager),'create','avd','--name','library-test','--package','system-images;android-35;google_apis;x86_64','--path',str(avd/'library-test.avd'),'--device','pixel_6'],input='no\n',text=True,env=env,check=True)
    log=(ROOT/'results/android-emulator.log').open('w',encoding='utf-8')
    command=[str(sdk/'emulator/emulator.exe'),'-avd','library-test','-port','5580','-no-window','-no-audio','-no-snapshot','-no-boot-anim','-gpu','swiftshader_indirect','-memory','3072','-cores','2']
    process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    (ROOT/'results/android-emulator-process.json').write_text(json.dumps(dict(pid=process.pid,serial='emulator-5580',avd=str(avd/'library-test.avd'))),encoding='utf-8')
    adb=sdk/'platform-tools/adb.exe';subprocess.run([str(adb),'start-server'],env=env,check=True)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Emulator stopped; inspect results/android-emulator.log')
        r=subprocess.run([str(adb),'-s','emulator-5580','shell','getprop','sys.boot_completed'],capture_output=True,text=True,timeout=10)
        if r.returncode==0 and r.stdout.strip()=='1':print('Emulator ready: emulator-5580',flush=True);return
        time.sleep(2)
    raise TimeoutError('Emulator boot exceeded three minutes; inspect the log')


if __name__=='__main__':main()
