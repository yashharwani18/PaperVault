"""Record Phase 1 hardware and official package/model metadata without ML dependencies."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def command(args: list[str]) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def memory() -> dict:
    if sys.platform != "win32":
        return {"note": "Use psutil in the inference runner for non-Windows memory."}

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                "total_physical", "available_physical", "total_page_file",
                "available_page_file", "total_virtual", "available_virtual", "extended")]

    state = MemoryStatus()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        return {"error": "GlobalMemoryStatusEx failed"}
    return {"physical_total_bytes": state.total_physical,
            "physical_available_bytes": state.available_physical}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Fetch public official metadata, no credentials.")
    parser.add_argument("--output", type=Path, default=ROOT / "results/environment.json")
    args = parser.parse_args()
    report = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version,
        "python_executable": sys.executable, "cpu_identifier": platform.processor(),
        "logical_cpu_count": os.cpu_count(), "memory": memory(),
        "disk": dict(zip(("total_bytes", "used_bytes", "free_bytes"), shutil.disk_usage(ROOT))),
        "gpu": command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,compute_cap",
                        "--format=csv,noheader"]),
        "cuda_compiler": shutil.which("nvcc"),
        "note": "nvidia-smi reports driver capability, not proof of a working PyTorch CUDA runtime.",
        "official_metadata": {},
    }
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                report["cpu_name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError as exc:
            report["cpu_name_error"] = str(exc)
    if args.fetch:
        urls = {
            "model": "https://huggingface.co/api/models/google/embeddinggemma-2?blobs=true",
            "sentence-transformers": "https://pypi.org/pypi/sentence-transformers/json",
            "transformers": "https://pypi.org/pypi/transformers/json",
            "torch": "https://pypi.org/pypi/torch/json",
        }
        for name, url in urls.items():
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "local-knowledge-pc-validation/0.1"})
                with urllib.request.urlopen(request, timeout=40) as response:
                    body = json.load(response)
                if name == "model":
                    selected = {k: body.get(k) for k in ("id", "sha", "gated", "private", "lastModified", "cardData", "siblings")}
                else:
                    selected = {k: body["info"].get(k) for k in ("name", "version", "requires_python", "requires_dist")}
                    selected["windows_cp312_wheels"] = [f["filename"] for f in body.get("urls", [])
                                                          if "cp312" in f["filename"] and "win_amd64" in f["filename"]]
                report["official_metadata"][name] = {"url": url, "data": selected}
                print(f"{name}: " + json.dumps({k: v for k, v in selected.items() if k not in ("siblings", "requires_dist", "cardData")}))
            except (OSError, ValueError, urllib.error.URLError) as exc:
                report["official_metadata"][name] = {"url": url, "error": str(exc)}
                print(f"{name}: FAILED: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "official_metadata"}, indent=2))
    print(f"Saved {args.output}")
    return int(any("error" in item for item in report["official_metadata"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
