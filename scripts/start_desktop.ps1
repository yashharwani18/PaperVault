[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=8765,[string]$LibraryPath='', [switch]$NoBrowser)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
if(-not $LibraryPath){$LibraryPath=Join-Path $projectRoot 'data\desktop'}
$libraryRoot=[IO.Path]::GetFullPath($LibraryPath)
$pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $pythonPath)){throw 'Run scripts\setup.ps1 to install the local runtime first.'}
if(-not(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))){throw 'Build the frontend first: pnpm --dir frontend install --frozen-lockfile; pnpm --dir frontend run build'}
$url="http://127.0.0.1:$Port"
$ready=$false
try{$existing=Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 2;if($existing.local_only -and $existing.stats.root -eq $libraryRoot){$ready=$true}}catch{}
if(-not $ready){
 New-Item -ItemType Directory -Force -Path $libraryRoot | Out-Null
 $logs=Join-Path $libraryRoot 'logs';New-Item -ItemType Directory -Force -Path $logs | Out-Null
 $arguments=@('-u','-m','knowledge_library.server','--library',('"'+$libraryRoot+'"'),'--port',[string]$Port)
 $serverProcess=Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server-error.log')
 for($attempt=0;$attempt -lt 120;$attempt++){
  if($serverProcess.HasExited){throw "The local server stopped. See $logs\server-error.log"}
  try{$response=Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 2;if($response.local_only -and $response.stats.root -eq $libraryRoot){$ready=$true;break}}catch{}
  Start-Sleep -Milliseconds 250
 }
 if(-not $ready){throw "The local server did not become ready. See $logs\server-error.log"}
 @{pid=$serverProcess.Id;started_at=$serverProcess.StartTime.ToUniversalTime().ToString('o');port=$Port;library=$libraryRoot}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $libraryRoot 'server-process.json') -Encoding utf8
}
Write-Output "Library is ready at $url"
Write-Output 'Semantic search prepares in the background. Exact bill matching remains available; local responses use Qwen.'
if(-not $NoBrowser){Start-Process $url}
