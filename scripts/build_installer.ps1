$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $project '.cache\release-tools\inno\ISCC.exe'
$webview = Join-Path $project '.cache\release-tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Install the pinned Inno Setup compiler under .cache/release-tools/inno first.' }
$signature = Get-AuthenticodeSignature -LiteralPath $webview
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Microsoft offline prerequisite signature validation failed.' }
Push-Location -LiteralPath $project
try {
    & '.venv\Scripts\python.exe' -c 'from pathlib import Path;from scripts.build_release import validate_payload;validate_payload(Path("output/Local-Library-Release"))'
    if ($LASTEXITCODE -ne 0) { throw 'Release payload validation failed.' }
    & $compiler 'desktop\installer.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    & '.venv\Scripts\python.exe' 'scripts\stage_release_validation.py'
    if ($LASTEXITCODE -ne 0) { throw 'Validation kit staging failed.' }
} finally { Pop-Location }
