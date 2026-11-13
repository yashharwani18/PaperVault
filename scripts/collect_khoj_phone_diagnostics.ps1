# Collects minimal, non-sensitive real-device evidence for the iQOO indexing
# investigation (handoff step 1). System-level ADB data only: no PDF contents,
# no Khoj database content, no file paths from the library.
#
# Usage:
#   .\scripts\collect_khoj_phone_diagnostics.ps1                # single device
#   .\scripts\collect_khoj_phone_diagnostics.ps1 -DeviceSerial ABC123    # several devices attached
#
# Requires USB debugging enabled on the phone and one capture per visit:
#   1. capture snapshot while indexing is active
#   2. capture again later (or after the reported slow run)

param(
    [string]$DeviceSerial = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
$adb = Join-Path $repoRoot ".cache\android-tools\sdk\platform-tools\adb.exe"
$package = "org.localknowledge.library"

if (-not (Test-Path $adb)) { Write-Error "ADB not found at $adb"; exit 1 }

$serialArgs = @()
$seen = & $adb devices | Select-Object -Skip 1 | Where-Object { $_.Trim() -ne "" }
Write-Host "adb devices output:`n$seen"
if ($seen.Count -eq 0) { Write-Error "No device attached. Enable USB debugging and connect the phone, then rerun."; exit 1 }
if ($seen.Count -gt 1 -and -not $DeviceSerial) {
    Write-Error ("Multiple devices attached; rerun with -DeviceSerial <serial>. Attached: " + ($seen -join "; ")); exit 1
}
if ($DeviceSerial) { $serialArgs = @("-s", $DeviceSerial) }
$unauth = ($seen | Where-Object { $_ -match "\tunauthorized" })
if ($unauth) { Write-Error "Device is unauthorized: accept the USB-debugging prompt on the phone screen and rerun."; exit 1 }

if (-not $OutDir) { $OutDir = Join-Path $repoRoot ("results\phone-diagnostics\" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function CaptureFile {
    param([string]$Name, [string]$Description, [string]$ShellCommand)
    $path = Join-Path $OutDir $Name
    Write-Host "capturing $Description -> $Name"
    "# $Description" | Out-File -FilePath $path -Encoding utf8
    (& $adb @serialArgs shell $ShellCommand 2>&1 | Out-String) | Out-File -FilePath $path -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Add-Content -Path $path -Value "EXITCODE $LASTEXITCODE (command may be unsupported on this Android version)" }
}

# 1. Device identity + Android version + SoC
CaptureFile "device.txt" "Device identifiers and Android version" "getprop ro.product.brand ro.product.model ro.product.device ro.build.version.release ro.build.version.sdk ro.board.platform ro.product.cpu.abilist"
CaptureFile "cpu.txt" "CPU cores and frequency policy (big/mid/LITTLE layout)" "sh -c 'cat /proc/cpuinfo | grep -E \"processor|Hardware\"; echo ---; for p in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq; do echo \"\$p \$(cat \$p)\"; done'"

# 2. Power, screen, and the Khoj indexing wake lock
CaptureFile "power.txt" "Power state, screen on/off, wake locks (contains Khoj:Indexing entry when indexing is active)" "dumpsys power"
CaptureFile "battery.txt" "Battery and charging state (charging-only restriction relevance)" "dumpsys battery"

# 3. Thermal throttling
CaptureFile "thermals.txt" "Thermal status and throttling level" "dumpsys thermalservice"

# 4. Khoj foreground service lifecycle / kill history
CaptureFile "services.txt" "Khoj services currently registered" "dumpsys activity services $package"
CaptureFile "package.txt" "Installed Khoj version (versionCode must be 10)" "dumpsys package $package"

# 5. Historical process exits: ANRs, low-memory kills, OEM actions, user stops
CaptureFile "exitinfo.txt" "Process exit history (ANR / lowmemorykiller / killed counts)" "dumpsys activity exit-info $package"

# 6. Battery-optimization / Doze treatment of the package
CaptureFile "battery-optimization.txt" "Device idle (Doze) whitelist and restriction status" "dumpsys deviceidle | grep -iE 'whitelist|version'"

# 7. Logcat: crash buffer tail; filtered main-buffer tail mentioning the package.
#    Keeps the capture bounded; app itself emits no Log lines, so hits are
#    system-side events (ANR, process kill, judgement by OEM tools).
CaptureFile "logcat-crash.txt" "Most recent crash-buffer entries" "logcat -d -b crash -t 500"
CaptureFile "logcat-khoj.txt" "Recent main-buffer lines mentioning the Khoj package or process kill reports" "sh -c 'logcat -d -t 2000 | grep -iE \"org\.localknowledge|localknowledge\.library\" | tail -n 400'"

Write-Host ""
Write-Host "Device-side captures saved to: $OutDir"
Write-Host ""
Write-Host "Still needed, cannot be collected from here:"
Write-Host "  * In-app support report: open Khoj -> Support/diagnostics -> save Khoj-support-report.json"
Write-Host "    (auto-excludes document contents, filenames, paths, searches)."
Write-Host "  * On the phone's File progress screen, note: elapsed vs estimated-remaining"
Write-Host "    wording, count completed, and the active stage shown."
Write-Host "  * Ask the phone user: did the 24h figure come from Khoj's estimate, or was"
Write-Host "    indexing actually still running after 24h? Screen on or off? Charger attached?"
