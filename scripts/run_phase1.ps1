[CmdletBinding()]
param([switch]$SkipOnline, [switch]$SkipCpu)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        throw 'Create the project virtual environment and install requirements first. See README.md.'
    }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUNBUFFERED = '1'
    New-Item -ItemType Directory -Path 'results' -Force | Out-Null

    function Invoke-Smoke([string]$Name, [string[]]$Options) {
        # Windows PowerShell 5 treats redirected native stderr (including progress)
        # as error records. The native exit code is the authoritative gate here.
        $previousErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $projectPython tests\test_embedding_model.py @Options --output "results\$Name.json" 2>&1 |
            ForEach-Object { $_.ToString() } |
            Tee-Object -FilePath "results\$Name.log"
        $smokeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorPreference
        if ($smokeExitCode -ne 0) {
            throw "$Name failed. Inspect results\$Name.json and results\$Name.log. Later phases must not proceed."
        }
    }

    if (-not $SkipOnline) {
        Invoke-Smoke -Name 'gpu-online' -Options @('--device', 'cuda')
    }
    Invoke-Smoke -Name 'gpu-offline' -Options @('--device', 'cuda', '--offline', '--compare-with', 'results\gpu-online.json')
    Invoke-Smoke -Name 'gpu-offline-restart' -Options @('--device', 'cuda', '--offline', '--compare-with', 'results\gpu-online.json')
    if (-not $SkipCpu) {
        Invoke-Smoke -Name 'cpu-offline' -Options @('--device', 'cpu', '--offline')
    }
    & $projectPython -m pytest -m integration -q --junitxml=results/phase1-pytest.xml |
        Tee-Object -FilePath results\phase1-pytest.log
    if ($LASTEXITCODE -ne 0) { throw 'Real-model pytest integration failed.' }
    & $projectPython scripts\summarize_phase1.py
    if ($LASTEXITCODE -ne 0) { throw 'Phase 1 report gate did not pass.' }
}
finally {
    Pop-Location
}
