[CmdletBinding()]
param([switch]$CheckOnly,[switch]$Offline,[switch]$NoShortcuts,[switch]$Repair)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe'
$lock=Get-Content (Join-Path $projectRoot 'model-lock.json') -Raw|ConvertFrom-Json
$modelPath=Join-Path $projectRoot "models\embeddinggemma-2\$($lock.revision)\$($lock.weight_file)"
$distPath=Join-Path $projectRoot 'frontend\dist\index.html'
$tessPath=Join-Path $projectRoot 'models\tessdata\eng.traineddata'
if($CheckOnly){
 $status=[ordered]@{runtime=(Test-Path $pythonPath);model=(Test-Path $modelPath);interface=(Test-Path $distPath);english_ocr=(Test-Path $tessPath);uv=[bool](Get-Command uv -ErrorAction SilentlyContinue);node=[bool](Get-Command node -ErrorAction SilentlyContinue)}
 $status|ConvertTo-Json
 if(-not($status.runtime -and $status.model -and $status.interface)){exit 1};exit 0
}
Push-Location -LiteralPath $projectRoot
try{
 if($Offline -and (-not(Test-Path $pythonPath) -or -not(Test-Path $modelPath) -or -not(Test-Path $distPath))){throw 'Offline setup requires the runtime, model and built interface to be present. Run online setup once first.'}
 if(-not(Test-Path $pythonPath) -or $Repair){
  if($Offline){throw 'Repair requires online dependency acquisition.'}
  & (Join-Path $PSScriptRoot 'setup.ps1');if($LASTEXITCODE -ne 0){throw 'Runtime setup failed.'}
 }
 if(-not(Test-Path $distPath) -or $Repair){
  if(-not(Get-Command node -ErrorAction SilentlyContinue)){throw 'Install Node.js 24 LTS, then repeat setup. The packaged release already contains a built interface.'}
  & npx --yes pnpm@11.25.0 --dir frontend install --frozen-lockfile
  if($LASTEXITCODE -ne 0){throw 'Frontend dependency installation failed.'}
  & npx --yes pnpm@11.25.0 --dir frontend run build
  if($LASTEXITCODE -ne 0){throw 'Frontend build failed.'}
 }
 if((Test-Path $modelPath) -and -not $Repair){& $pythonPath scripts/prepare_model.py --offline}else{& $pythonPath scripts/prepare_model.py}
 if($LASTEXITCODE -ne 0){throw 'Model acquisition or checksum verification failed.'}
 & $pythonPath scripts/prime_encoder_cache.py
 if($LASTEXITCODE -ne 0){Write-Warning 'Could not prebuild the search import cache; it will be generated on first use.'}
 if(-not(Test-Path $tessPath)){
  if($Offline){Write-Warning 'English OCR is unavailable until its local language data is installed.'}
  else{
   New-Item -ItemType Directory -Force -Path (Split-Path $tessPath)|Out-Null
   Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/eng.traineddata' -OutFile $tessPath
  }
 }
 if(Test-Path $tessPath){if((Get-FileHash -LiteralPath $tessPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'){throw 'OCR language data checksum mismatch.'}}
 if(-not $NoShortcuts){
  $desktopFolder=[Environment]::GetFolderPath('Desktop')
  $shellObject=New-Object -ComObject WScript.Shell
  foreach($entry in @(@('Local Library','Start-Library.cmd'),@('Stop Local Library','Stop-Library.cmd'))){
   $shortcut=$shellObject.CreateShortcut((Join-Path $desktopFolder ($entry[0]+'.lnk')))
   if($shortcut.TargetPath -and $shortcut.TargetPath -ne (Join-Path $projectRoot $entry[1])){throw 'A desktop shortcut with this name already points elsewhere. Rename it or use -NoShortcuts.'}
   $shortcut.TargetPath=Join-Path $projectRoot $entry[1];$shortcut.WorkingDirectory=$projectRoot;$shortcut.Description='Local-first knowledge and bill library';$shortcut.Save()
  }
 }
 Write-Output 'Setup complete. Double-click Start-Library.cmd (or the Local Library desktop shortcut).'
 Write-Output 'Keep this folder in place. Back up your library from Backup & storage in the app.'
}finally{Pop-Location}
