[CmdletBinding()]
param([string]$Python = '3.12')

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'Install uv from https://docs.astral.sh/uv/ before running setup.'
    }
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.cache\python'
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        uv venv --python $Python .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    uv pip install --python .venv\Scripts\python.exe 'torch==2.14.1+cu130' 'torchvision==0.29.1+cu130' --index-url https://download.pytorch.org/whl/cu130
    if ($LASTEXITCODE -ne 0) { throw 'Official CUDA wheel installation failed.' }
    uv pip install --python .venv\Scripts\python.exe -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
    uv pip check --python .venv\Scripts\python.exe
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
}
finally {
    Pop-Location
}
