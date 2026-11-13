# Run inside Windows Sandbox or a separate clean Windows x64 computer.
param([string]$InstallerDirectory = 'C:\LibraryInstaller', [string]$ResultsDirectory = 'C:\LibraryValidationResults', [string]$LibraryDirectory = (Join-Path $env:LOCALAPPDATA 'LocalKnowledgeLibrary\library'), [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\Library Validation'))
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $ResultsDirectory -Force | Out-Null
$setup = Join-Path $InstallerDirectory 'Khoj-Setup-0.5.0.exe'
$destination = $InstallDirectory
if (Test-Path -LiteralPath (Join-Path $LibraryDirectory 'library.sqlite3')) { throw 'Existing library detected. Use a clean test computer or a separate LibraryDirectory.' }
$arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="' + $destination + '"'),'/GROUP="Library Release Validation"',('/LOG="' + (Join-Path $ResultsDirectory 'install.log') + '"'))
$process = Start-Process -FilePath $setup -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
$python = Join-Path $destination 'runtime\python.exe'
$validator = Join-Path $InstallerDirectory 'validation\validate_release_runtime.py'
& $python -I -B $validator --device cpu --library $LibraryDirectory --scratch-root (Join-Path $ResultsDirectory 'test-data') --output (Join-Path $ResultsDirectory 'cpu-check.json')
if ($LASTEXITCODE -ne 0) { throw 'Compiled CPU runtime check failed.' }
$sentinel = Join-Path $LibraryDirectory 'keep-library.txt'
Set-Content -LiteralPath $sentinel -Value 'Library data must survive upgrade and uninstall.'
$process = Start-Process -FilePath $setup -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $sentinel)) { throw 'Upgrade failed or removed library data.' }
& $python -I -B $validator --device cpu --existing --library $LibraryDirectory --scratch-root (Join-Path $ResultsDirectory 'test-data') --output (Join-Path $ResultsDirectory 'after-upgrade.json')
if ($LASTEXITCODE -ne 0) { throw 'Existing library could not reopen after upgrade.' }
$database = Join-Path $LibraryDirectory 'library.sqlite3'
$databaseHash = (Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash
$uninstaller = Join-Path $destination 'unins000.exe'
$process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $sentinel)) { throw 'Uninstall failed or removed library data.' }
if ((Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash -ne $databaseHash) { throw 'Uninstall modified the saved library database.' }
@{passed=$true;cpu_runtime=$true;upgrade=$true;uninstall=$true;library_preserved=$true;library_database_unchanged_by_uninstall=$true;separate_clean_computer_not_proven_by_this_script=$true} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ResultsDirectory 'clean-machine-summary.json')
Write-Output 'Offline install, compiled CPU runtime, upgrade and uninstall checks passed.'
