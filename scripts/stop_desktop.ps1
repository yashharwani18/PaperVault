[CmdletBinding()]
param([string]$LibraryPath='')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
if(-not $LibraryPath){$LibraryPath=Join-Path $projectRoot 'data\desktop'}
$libraryRoot=[IO.Path]::GetFullPath($LibraryPath)
$recordPath=Join-Path $libraryRoot 'server-process.json'
if(-not(Test-Path -LiteralPath $recordPath)){Write-Output 'No launcher-owned server record was found. If started in a terminal, stop it with Ctrl+C.';exit 0}
$record=Get-Content -LiteralPath $recordPath -Raw|ConvertFrom-Json
$serverProcess=Get-Process -Id $record.pid -ErrorAction SilentlyContinue
if(-not $serverProcess){Write-Output 'The local server has already stopped.';exit 0}
$actual=Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"
$recordedStart=if($record.started_at -is [DateTime]){$record.started_at}else{[DateTime]::Parse([string]$record.started_at,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind)}
if(-not $actual.CommandLine.Contains('knowledge_library.server') -or -not $actual.CommandLine.Contains($libraryRoot) -or [Math]::Abs(($serverProcess.StartTime.ToUniversalTime()-$recordedStart.ToUniversalTime()).TotalSeconds) -gt 2){throw 'The recorded process identity changed; no process was stopped.'}
$children=Get-CimInstance Win32_Process -Filter "ParentProcessId=$($record.pid)"
foreach($child in $children){if($child.CommandLine -and $child.CommandLine.Contains('knowledge_library.server') -and $child.CommandLine.Contains($libraryRoot)){Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue}}
Stop-Process -Id $record.pid -Force -ErrorAction SilentlyContinue
Write-Output 'Local Library stopped. Stored documents and indexes are retained.'
