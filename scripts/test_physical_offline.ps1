[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=8765)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$active=@(Get-NetAdapter -Physical | Where-Object Status -eq 'Up')
if($active.Count -gt 0){throw 'First turn off Wi-Fi and unplug Ethernet using Windows settings. This script never changes your network configuration.'}
$url="http://127.0.0.1:$Port"
& (Join-Path $PSScriptRoot 'stop_desktop.ps1')
$stillRunning=$false
try{$null=Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 2;$stillRunning=$true}catch{}
if($stillRunning){throw 'A manually started server is still running. Stop its terminal with Ctrl+C, then repeat this check so a fresh offline restart is verified.'}
& (Join-Path $PSScriptRoot 'start_desktop.ps1') -Port $Port -NoBrowser
$before=Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 10
$body=@{query='Where is the pumping lemma explained?'}|ConvertTo-Json
$result=Invoke-RestMethod -Uri "$url/api/search" -Method Post -Headers @{'X-Library-Token'=$before.token} -Body $body -ContentType 'application/json' -TimeoutSec 120
if($result.results.Count -eq 0){throw 'Offline search returned no confident source match. Add the evaluation PDFs or adjust this test query for your own library.'}
$hit=$result.results[0]
$source=Invoke-WebRequest -Uri "$url/api/documents/$($hit.document_id)/file" -UseBasicParsing -TimeoutSec 20
if($source.StatusCode -ne 200){throw 'Offline PDF source could not be read.'}
$after=Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 10
if($after.stats.embedding_runtime.document_texts_encoded -ne 0){throw 'Offline restart unexpectedly re-embedded documents.'}
$record=@{passed=$true;provenance='User-executed physical-disconnection check';recorded_at=[DateTime]::UtcNow.ToString('o');active_physical_adapters=$active.Count;fresh_server_restart=$true;query=$result.query;filename=$hit.filename;physical_page=$hit.page_number;pdf_http_status=$source.StatusCode;document_embeddings_generated=$after.stats.embedding_runtime.document_texts_encoded;graphical_viewer_check='Open the app and verify the matching page; this script verifies HTTP access and source references.'}
$record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $projectRoot 'results\physical-offline-check.json') -Encoding utf8
Write-Output 'Physically disconnected restart/search/source access passed. Turn Wi-Fi back on when ready.'
Write-Output "$url — open the result to verify the PDF page visually."
