"""Generate the Phase 1 report and CSV only from actual inference JSON artifacts."""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RUNS = ("gpu-online", "gpu-offline", "gpu-offline-restart", "cpu-offline")


def main() -> int:
    env = json.loads((RESULTS / "environment.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "model-lock.json").read_text(encoding="utf-8"))
    reports = {}
    for name in RUNS:
        path = RESULTS / f"{name}.json"
        if path.is_file():
            reports[name] = json.loads(path.read_text(encoding="utf-8"))
    required = ("gpu-online", "gpu-offline", "gpu-offline-restart", "cpu-offline")
    passed = all(reports.get(name, {}).get("status") == "passed" for name in required)
    junit_path = RESULTS / "phase1-pytest.xml"
    suites = ET.parse(junit_path).getroot() if junit_path.is_file() else None
    pytest_passed = suites is not None and all(
        int(s.attrib.get("tests", 0)) > 0 and all(int(s.attrib.get(k, 0)) == 0 for k in ("failures", "errors", "skipped"))
        for s in suites.iter("testsuite"))
    passed = passed and pytest_passed
    fields = ["run", "status", "device", "dtype", "dependency_import_s", "model_load_s",
              "download_or_cache_check_s", "first_sentence_batch_s", "query_mean_ms", "query_p95_ms",
              "peak_process_rss_mib", "peak_torch_allocated_vram_mib", "peak_torch_reserved_vram_mib"]
    rows = []
    for name in RUNS:
        run = reports.get(name, {})
        timing, runtime, mem = (run.get(k, {}) for k in ("timings", "runtime", "memory"))
        warm = run.get("warm_single_query", {})
        row = {"run": name, "status": run.get("status", "not run"), "device": runtime.get("device"), "dtype": runtime.get("dtype")}
        row.update({field: timing.get(field) for field in fields[4:8]})
        row.update({"query_mean_ms": warm.get("mean_s", 0) * 1000 if warm else None,
                    "query_p95_ms": warm.get("p95_s", 0) * 1000 if warm else None,
                    "peak_process_rss_mib": max(mem.get("sampled_peak_process_rss_bytes", 0), mem.get("os_peak_process_working_set_bytes") or 0) / 2**20 if mem else None,
                    "peak_torch_allocated_vram_mib": mem.get("torch_peak_allocated_vram_bytes", 0) / 2**20 if runtime.get("device") == "cuda" else None,
                    "peak_torch_reserved_vram_mib": mem.get("torch_peak_reserved_vram_bytes", 0) / 2**20 if runtime.get("device") == "cuda" else None})
        rows.append(row)
    with (RESULTS / "phase1-benchmarks.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    def cell(value):
        return f"{value:.2f}" if isinstance(value, (int, float)) else str(value) if value is not None else "—"

    lines = ["# Phase 1 — PC model validation", "",
             f"Generated from execution artifacts at {dt.datetime.now(dt.timezone.utc).isoformat()}.", "",
             f"**Phase 1 smoke gate: {'PASS' if passed else 'NOT PASSED'}.** This is not approval for Android or evidence of real-PDF retrieval quality.", "",
             "## Machine and model", "",
             f"- OS: {env['platform']}.",
             f"- CPU: {env.get('cpu_name', env['cpu_identifier'])}; {env['logical_cpu_count']} logical processors.",
             f"- System RAM: {env['memory']['physical_total_bytes'] / 2**30:.2f} GiB; {env['memory']['physical_available_bytes'] / 2**30:.2f} GiB available during initial probe.",
             f"- GPU/driver/VRAM/compute capability: `{env['gpu'].get('stdout', 'unavailable')}`.",
             f"- Python: `{env['python'].splitlines()[0]}`.",
             f"- Model: `{lock['model_id']}` at immutable revision `{lock['revision']}`.",
             f"- Official checkpoint SHA256: `{lock['weight_sha256']}`; checked against downloaded bytes on every run.",
             "- Text-only configuration: `config_kwargs={'vision_config': None, 'audio_config': None}`; no remote model code allowed.", "",
             "## Executed measurements", "",
             "| Run | Status | Precision | Import s | Load s | Warm mean ms | Warm p95 ms | Process peak MiB | Torch VRAM allocated / reserved MiB |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        lines.append("| " + " | ".join(cell(row.get(k)) for k in (
            "run", "status", "dtype", "dependency_import_s", "model_load_s", "query_mean_ms", "query_p95_ms", "peak_process_rss_mib"))
            + f" | {cell(row['peak_torch_allocated_vram_mib'])} / {cell(row['peak_torch_reserved_vram_mib'])} |")
    lines += ["", "Warm latency measures one short query embedding, not an end-to-end search. Each run uses ten repetitions by default. "
              "Load time excludes dependency import, download, checkpoint hashing, and first forward pass. Fresh Python processes were used; "
              "the OS disk cache was not flushed. These are measurements on a busy personal PC, not controlled product benchmarks. "
              "Memory sampling is every 50 ms, supplemented by the Windows process working-set high watermark. "
              "Torch VRAM excludes driver/context and other applications; system RAM includes other applications.", "",
              "## Assertions and restart evidence", ""]
    for name, run in reports.items():
        checks = ", ".join(f"{key}={value}" for key, value in run.get("checks", {}).items()) or "none completed"
        lines.append(f"- **{name}**: {checks}.")
        if "restart_comparison" in run:
            lines.append(f"  - Maximum absolute vector differences: `{json.dumps(run['restart_comparison']['max_absolute_difference'])}`.")
        if run.get("error"):
            lines.append(f"  - Failed at {run['stage']}: `{run['error']['type']}: {run['error']['message']}`.")
    online = reports.get("gpu-online", {})
    if "sentence_similarity" in online:
        scores = online["sentence_similarity"]["scores"][0]
        lines += ["", f"Actual GPU sentence cosine scores: paraphrase {scores[1]:.6f}; unrelated formal-language passage {scores[2]:.6f}; unrelated astronomy passage {scores[3]:.6f}.",
                  "The retrieval smoke suite uses three handwritten questions and four short passages, with explicit expected document IDs. "
                  "It checks the native 768d output and re-normalized leading 512/256/128 dimensions. These are deliberately small inference sanity checks; "
                  "they are not the required 30-query relevance dataset."]
    if "storage" in online:
        lines += ["", f"Downloaded checkpoint: {online['storage']['checkpoint_bytes']:,} bytes. Model directory including tokenizer/configuration: "
                  f"{online['storage']['model_directory_bytes']:,} bytes. Text-only loading reduces runtime parameters, not the full upstream checkpoint download.",
                  f"Observed text-only parameter count: {online.get('model', {}).get('parameter_count', 'unavailable'):,}." if online.get('model', {}).get('parameter_count') else "Observed parameter count unavailable."]
    lines += ["", "## Diagnosed failures", ""]
    for path in sorted(RESULTS.glob("attempt-*.json")):
        attempt = json.loads(path.read_text(encoding="utf-8"))
        lines.append(f"- [{path.name}]({path.name}): {attempt['status']} at `{attempt['stage']}`; "
                     f"{attempt.get('error', {}).get('message', 'See saved log').splitlines()[0]}. "
                     f"Matching raw log: `{path.with_suffix('.log').name}`.")
    lines += ["", "The initial minimal text installation lacked Pillow, then torchvision, both required by the "
              "upstream multimodal processor even with text-only model encoders. Installing the image extra "
              "and a torchvision wheel matching CUDA PyTorch fixed these failures. Failed attempts have not been "
              "counted as passes. The first checkpoint download took "
              + cell(json.loads((RESULTS / 'attempt-01-missing-pillow.json').read_text(encoding='utf-8')).get('timings', {}).get('download_or_cache_check_s'))
              + " seconds." if (RESULTS / 'attempt-01-missing-pillow.json').is_file() else "See any failure logs above for installation diagnostics."]
    if suites is not None:
        lines += ["", "## Repeatable integration test", "",
                  f"pytest JUnit result: `{junit_path.name}`. "
                  + "; ".join(f"{suite.attrib.get('tests', '?')} tests, {suite.attrib.get('failures', '?')} failures, "
                               f"{suite.attrib.get('errors', '?')} errors, {suite.attrib.get('skipped', '?')} skipped" for suite in suites.iter('testsuite'))
                  + ". The integration test spawns the actual offline inference CLI, compares real vectors, and checks unit norms.",
                  "Reproduce with `.venv\\Scripts\\python.exe -m pytest -m integration -q --junitxml=results/phase1-pytest.xml`. "
                  "Raw pytest output is in `results/phase1-pytest.log`."]
    if (RESULTS / "pytest-attempt-01.xml").is_file():
        lines += ["", "The first pytest attempt failed in fixture setup because the Windows sandbox's default temporary "
                  "directory was unwritable. No inference ran in that attempt. The test now writes retained evidence "
                  "under the project results directory. Original failure: `pytest-attempt-01.xml` / `pytest-attempt-01.log`."]
    lines += ["", "## Offline scope", "",
              "Offline runs start fresh Python processes using only local model files, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, "
              "and `local_files_only=True`. A Python audit hook denies DNS/connect/sendto operations before ML imports and verifies itself "
              "with one deliberately blocked DNS call. Any additional intercepted network attempt fails the run. "
              "The PC's network adapters were not disabled. Native libraries/child processes are outside that Python hook; "
              "a physical-disconnection or OS-firewall integration test remains necessary for the later whole-application offline gate.", "",
              "## Dependencies, compatibility, and sources", "",
              "- Exact installed dependency versions: [requirements.lock.txt](../requirements.lock.txt); each run also records all package versions.",
              "- [Official model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2): 270M text backbone, 8192-token context, "
              "768d output with supported truncation; BF16 or FP32 only. Actual measurements above take precedence over theoretical weight-memory estimates.",
              "- [Google inference guide](https://ai.google.dev/gemma/docs/embeddinggemma/inference-embeddinggemma-with-sentence-transformers): "
              "selective encoder loading and retrieval prompts. Titled passages use an explicit title/text prefix; queries use `SearchQuery`.",
              "- [Official repository](https://huggingface.co/google/embeddinggemma-2): public Apache-2.0 checkpoint; the captured API reports `gated=false`. "
              "This download used `token=False`; no Hugging Face login or acceptance flow was required. Preserve upstream licensing when redistributing.",
              "- [PyTorch installation](https://pytorch.org/get-started/locally/) supports Windows and Linux. This run validates only the detected Windows machine. "
              "The installed wheel uses CUDA 13.0; `nvidia-smi` driver capability is reported separately. A standalone CUDA toolkit/nvcc was not installed or required for this wheel.",
              "- [Sentence Transformers installation](https://www.sbert.net/docs/installation.html) and captured PyPI metadata specify Python >=3.10. "
              "The model tutorial does not pin a minimum library release for this model: use the exact tested versions rather than infer support from older generic minimums.",
              "- [Hugging Face offline loading](https://huggingface.co/docs/transformers/installation#offline-mode) describes cached local inference. "
              "No hosted inference APIs are used by the test.", "",
              "## Limits and phase status", "",
              "| Work | Status |", "| --- | --- |",
              "| Environment probe, immutable download, CUDA kernel check, real text embeddings | Executed; see per-run status above |",
              "| Offline process reload, vector parity, CPU FP32 inference | Executed only where the corresponding run is passed |",
              "| Locked Windows setup script | Implemented; packages were installed successfully, but a second clean-environment reinstall was not tested |",
              "| Physical-disconnection offline test | Pending; network adapters were not changed |",
              "| FP16 inference | Unsupported by this prototype; excluded due to documented numerical failure risk |",
              "| Full multimodal inference and Linux execution | Not tested; the validated configuration is Windows text-only |",
              "| Mock inference, substitute model, fabricated benchmark metrics | None |",
              "| Real PDF extraction, persistent index, 20-document corpus and 30 manually verified queries | Planned; not implemented or tested in Phase 1 |",
              "| BM25/hybrid accuracy, bulk indexing, 10/50/100/500-PDF scaling | Planned; no measurements yet |",
              "| Desktop UI, document navigation and context PDF export | Not started; retrieval gate remains closed |",
              "| Android implementation | Blocked until complete PC validation and explicit user approval |", "",
              "Known limits: synthetic smoke coverage is small; no no-match threshold has been calibrated; raw cosine scores are not probabilities. "
              "Long technical text, scans, Unicode math, retrieval accuracy and stability are untested. Only short-input memory was measured. "
              "CPU and GPU use different precision and have not been asserted numerically equivalent. Mobile runtime/model support and mobile hardware performance remain unverified.", "",
              "## Reproduction and next gate", "",
              "From the project root in PowerShell, run `powershell -ExecutionPolicy Bypass -File scripts/run_phase1.ps1`. "
              "Use `-SkipOnline` to reuse an existing passed online baseline without contacting Hugging Face. See README for clean environment installation.", "",
              "Machine-readable results: `results/environment.json`, `results/phase1-benchmarks.csv`, and each run's JSON. "
              "Raw stdout/stderr is in the matching `.log`; actual arrays are in `.embeddings.npz`. "
              "The command, model revision, dtype, parameter count, scores, timings and failures are retained in each run report.", "",
              "Next: implement and validate page-preserving PDF extraction and incremental local retrieval against real documents, then build the manually labeled evaluation corpus. "
              "Do not open the UI gate until retrieval tests pass. Do not start Android without the full PC report and approval.", ""]
    (RESULTS / "PHASE1_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Phase 1 smoke gate: {'PASS' if passed else 'NOT PASSED'}")
    print(f"Saved {RESULTS / 'PHASE1_REPORT.md'}")
    print(f"Saved {RESULTS / 'phase1-benchmarks.csv'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
