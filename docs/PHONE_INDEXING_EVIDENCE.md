# Real-device evidence playbook — iQOO 9 SE / 24-hour indexing report

Build 10 improves the extraction component on the emulator only; the physical
iQOO report is unresolved and unexplained. This playbook collects the minimal
evidence needed before any next throughput change. Nothing here reads or moves
library contents.

## Step 0 — three questions for the phone user (biggest unknowns first)

1. Was "24 hours" Khoj's *estimated remaining time* shown in the UI, or live
   indexing that was actually still running the next day? (The current ETA
   extrapolates average time per file after only three files and can mislead.)
2. During the slow period: was the screen on or off, and was the charger
   attached? (Screen-off CPU suspension was only addressed in build 10, and the
   dad's phone is likely still on an older build.)3. Roughly how many files were done when it was last checked, and did the progress count advance at a steady pace or in bursts/stalls?If the answer to (1) is "it was an estimate" or to (2) is "screen off, wandering off", then the first suspect is CPU susp/Doze behavior rather than inference throughput, and the Step 2 captures below are the right next move before touching model or batching settings.

If the answer to (1) is "actually 24 hours of wall time while running", then the second capture in Step 2, taken after a measurable interval, gives real progress-per-minute from which throughput can be estimated.

## Step 1 — on the phone (no PC needed)

- Verify installed build: Settings -> Apps -> Khoj -> version 0.5.0 (10). If the
  dad's phone is on a build below 10, indexing behavior differs and must be
  stated before any comparisons.
- Save the in-app support report: Khoj -> diagnostics/support report -> save
  `Khoj-support-report.json`. Per its own disclosure it includes versions,
  memory, CPU processing metrics, file/job counts and **excludes document
  contents, pages, filenames, paths, searches, keys, raw errors and logs**.This single file answers most of handoff item 1: `embedding_performance`
  (calls/microseconds/batches/context creations/model loads), `cpu_features`
  (which CPU extensions are actually supported), indexed documents/pages/db
  size, and interrupted/recovered task counts. Save it while indexing is
  running if possible (metrics accumulate over the run up to that point).

## Step 2 — over USB (bounded, non-sensitive captures)

```powershell
# phone connected, USB debugging enabled
powershell -ExecutionPolicy Bypass -File .\scripts\collect_khoj_phone_diagnostics.ps1
```

Writes `results/phone-diagnostics/<timestamp>/` with:

| file | answers |
|---|---|
| `device.txt`, `cpu.txt` | SoC/cluster layout (needed before any thread-count or kernel claims, handoff item 3) |
| `power.txt` | at capture time: screen on/off and whether `Khoj:Indexing` partial wake lock is held |
| `battery.txt` | charging state vs the charging-only stop metric |
| `thermals.txt` | thermal throttling level (sustained-throughput check, item 3) |
| `exitinfo.txt` | history: ANRs, low-memory kills, OEM process kills (Doze/OEM-era behavior evidence) |
| `battery-optimization.txt` | whether Khoj is exempt from battery optimization |
| `services.txt`, `package.txt` | foreground-service state and installed build |
| `logcat-khoj.txt`, `logcat-crash.txt` | system-side entries mentioning the package only (bounded tails); the app itself emits no log lines |

Capture once while indexing is running and once later; the second capture lets
progress be compared with actual work rather than estimates.

## What each capture is and is not

- The support report and ADB captures above contain no library content.
- These snapshots show instantaneous state and aggregated counters; they do not
  prove per-stage throughput on their own. Dedicated stage-timing (item 2) is a
  separate later step and should only be attempted once we know whether the
  report indicates, e.g., very high model reload/context-creation counts or
  interruption counts — those would change which fix to look for first.
- If `exitinfo.txt` shows repeated ANRs or low-memory-killer entries for the
  package, stop and treat screen-off laspe and OEM kills as the primary suspect
  before any inference tuning.

## Storage and privacy

- Captures stay in `results/phone-diagnostics/` in this workspace.
- The support report is chosen by the phone user via Android's file picker and
  shared voluntarily; it contains no document content or identifiers.
