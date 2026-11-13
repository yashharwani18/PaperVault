"""Package only release validation tools; never map the development workspace."""
from pathlib import Path
import hashlib
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'output/Library-Installer';validation=output/'validation';validation.mkdir(parents=True,exist_ok=True)
    for name in ['validate_release_runtime.py','clean_machine_release_test.ps1']:
        shutil.copy2(ROOT/'scripts'/name,validation/name)
    results=ROOT/'output/Library-CleanMachine-Results';results.mkdir(exist_ok=True)
    config=ET.Element('Configuration')
    ET.SubElement(config,'Networking').text='Disable'
    ET.SubElement(config,'ClipboardRedirection').text='Disable'
    folders=ET.SubElement(config,'MappedFolders')
    for host,destination,read_only in [(output,r'C:\LibraryInstaller',True),(results,r'C:\LibraryValidationResults',False)]:
        folder=ET.SubElement(folders,'MappedFolder')
        ET.SubElement(folder,'HostFolder').text=str(host)
        ET.SubElement(folder,'SandboxFolder').text=destination
        ET.SubElement(folder,'ReadOnly').text=str(read_only).lower()
    command=ET.SubElement(config,'LogonCommand')
    ET.SubElement(command,'Command').text=r'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\LibraryInstaller\validation\clean_machine_release_test.ps1'
    ET.indent(config)
    (output/'Test-Offline-In-Sandbox.wsb').write_text(ET.tostring(config,encoding='unicode'),encoding='utf-8')
    (output/'README.txt').write_text('''Khoj v0.5 offline Windows installer - private release candidate

Copy and run Khoj-Setup-0.5.0.exe. This single installer includes everything; no .bin files or other companion downloads are needed.
Includes Python, dependencies, AI models and the Microsoft WebView2 offline prerequisite. No Python, Node or CUDA installation is needed. A usable CUDA GPU is selected after an execution check; otherwise the CPU is selected.

The library is stored separately under %LOCALAPPDATA%\\LocalKnowledgeLibrary\\library. Upgrade/uninstall preserve it and your original PDFs. No scan begins before consent.

Proprietary backend modules are native binaries, without shipped Python sources, bytecode, generated C or debug files. Third-party dependencies retain their licence notices. Compilation does not prevent determined reverse engineering.

PRIVATE TEST BUILD: unsigned. Resolve PyMuPDF commercial redistribution licensing and complete a separate clean-computer test before closed-source public distribution.

Validation: on this build machine, Test-Offline-In-Sandbox.wsb mounts only this installer folder read-only, disables networking and writes reports to the dedicated Library-CleanMachine-Results folder. Windows Sandbox is unavailable on the build machine, so that VM test has not been run here. If moving the test kit to another computer, update the two HostFolder paths in the .wsb file first. Alternatively, run validation/clean_machine_release_test.ps1 with explicit InstallerDirectory and ResultsDirectory paths on a clean Windows computer. Do not point it at an existing library.
''',encoding='utf-8')
    rows=[]
    for path in sorted(output.iterdir()):
        if path.suffix in ('.exe','.bin'):
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            rows.append(digest+'  '+path.name)
    (output/'SHA256SUMS.txt').write_text('\n'.join(rows)+'\n')
    print('Validation kit and installer hashes written.')


if __name__=='__main__':main()
