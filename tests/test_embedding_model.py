"""Real EmbeddingGemma 2 inference; run as a standalone script, not a mocked test.

Online: python tests/test_embedding_model.py --device cuda --output results/gpu-online.json
Offline: python tests/test_embedding_model.py --device cuda --offline \
  --compare-with results/gpu-online.json --output results/gpu-offline.json

Exit 0 means all smoke assertions passed. An exception writes a failed report and
exits nonzero. These handwritten examples do not measure real-PDF retrieval quality.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "model-lock.json").read_text(encoding="utf-8"))
SENTENCES = [
    "The chef prepared a delicious meal for the guests.",
    "A tasty dinner was cooked by the chef for the visitors.",
    "The pumping lemma can show that a formal language is not regular.",
    "The orbit of Neptune is far from the Sun.",
]
DOCUMENTS = [
    {"id": "toc", "title": "Regular languages",
     "text": "To prove a language is not regular, assume a pumping length and choose a word. "
             "The pumping lemma says any sufficiently long word in a regular language can be "
             "split into xyz so that xy^iz stays in the language for every nonnegative i. "
             "A contradiction for all valid splits proves nonregularity."},
    {"id": "dsp", "title": "Frequency analysis",
     "text": "The Fourier transform decomposes a time-domain signal into sinusoidal frequency "
             "components. Its spectrum describes the amplitudes and phases of these frequencies."},
    {"id": "ml", "title": "Training classifiers",
     "text": "Cross-entropy loss compares a predicted probability distribution against a target "
             "label distribution. Minimizing this objective trains a classification model."},
    {"id": "cooking", "title": "Baking bread",
     "text": "Mix flour, water, yeast and salt. Knead the dough, allow it to rise, and bake it "
             "until the crust is golden."},
]
QUERIES = [
    {"text": "How can I prove a language is not regular?", "relevant_id": "toc"},
    {"text": "How do I find which frequencies are present in a signal?", "relevant_id": "dsp"},
    {"text": "Which objective penalizes a classifier for assigning low probability to the true label?",
     "relevant_id": "ml"},
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def deny_python_network(events: list) -> None:
    """Block socket DNS/connect before importing HF. No changes to system networking."""
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            events.append({"event": event, "time_s": time.perf_counter()})
            raise PermissionError("Offline inference test forbids network access")

    sys.addaudithook(audit)
    try:
        socket.getaddrinfo("huggingface.co", 443)
    except PermissionError:
        pass
    else:
        raise AssertionError("Offline socket guard did not block the deliberate DNS probe")


class ResourceSampler:
    """50ms RSS/system RAM sampling, plus OS process high watermark when available."""
    def __init__(self, psutil):
        self.psutil = psutil
        self.process = psutil.Process()
        self.done = threading.Event()
        self.peak_rss = self.peak_system_used = self.os_peak_rss = 0
        self.minimum_available = psutil.virtual_memory().available
        self.errors = []
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def sample(self):
        try:
            info = self.process.memory_info()
            mem = self.psutil.virtual_memory()
            self.peak_rss = max(self.peak_rss, info.rss)
            self.os_peak_rss = max(self.os_peak_rss, getattr(info, "peak_wset", 0))
            self.peak_system_used = max(self.peak_system_used, mem.total - mem.available)
            self.minimum_available = min(self.minimum_available, mem.available)
        except Exception as exc:
            self.errors.append(str(exc))

    def loop(self):
        while not self.done.is_set():
            self.sample()
            self.done.wait(0.05)

    def start(self):
        self.sample()
        self.thread.start()

    def stop(self):
        self.done.set()
        self.thread.join(timeout=2)
        self.sample()
        return {"sample_interval_s": 0.05, "sampled_peak_process_rss_bytes": self.peak_rss,
                "os_peak_process_working_set_bytes": self.os_peak_rss or None,
                "sampled_peak_system_used_bytes": self.peak_system_used,
                "minimum_system_available_bytes": self.minimum_available,
                "sampling_errors": self.errors}


def gpu_snapshot():
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                                 "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return {"returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--compare-with", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "results/model-smoke.json")
    args = parser.parse_args()
    if args.repeats < 2 or args.threads < 1:
        parser.error("--repeats must be >= 2 and --threads >= 1")

    os.environ["HF_HOME"] = str(ROOT / ".cache/huggingface")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    network_events = []
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        deny_python_network(network_events)
    report = {
        "schema_version": 1, "status": "running", "stage": "imports",
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pid": os.getpid(), "command": sys.argv, "model_lock": LOCK,
        "environment": {"platform": platform.platform(), "python": sys.version,
                        "python_executable": sys.executable, "gpu_before": gpu_snapshot()},
        "offline": {"requested": args.offline, "hf_local_files_only": True,
                    "python_socket_guard": args.offline, "physical_network_adapter_disabled": False,
                    "guard_probe_blocked": bool(network_events)},
        "scope": "Handwritten smoke examples only; not a PDF accuracy evaluation or Phase 3 result.",
        "timings": {}, "checks": {},
    }
    write_json(args.output, report)
    sampler = None
    torch = None
    started = time.perf_counter()
    try:
        import psutil
        sampler = ResourceSampler(psutil)
        sampler.start()
        import numpy as np
        import torch
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer

        report["timings"]["dependency_import_s"] = time.perf_counter() - started
        report["environment"]["packages"] = {
            dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
        torch.set_num_threads(args.threads)
        torch.manual_seed(42)
        device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
        if device == "auto":
            device = "cpu"
        if device == "cuda":
            require(torch.cuda.is_available(), "CUDA requested but torch.cuda.is_available() is false")
        dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported(including_emulation=False) else torch.float32
        report["runtime"] = {"device": device, "dtype": str(dtype), "threads": args.threads,
                             "torch_cuda_runtime": torch.version.cuda,
                             "cuda_available": torch.cuda.is_available()}
        if device == "cuda":
            report["runtime"].update({"gpu_name": torch.cuda.get_device_name(0),
                                      "compute_capability": list(torch.cuda.get_device_capability(0)),
                                      "torch_compiled_architectures": torch.cuda.get_arch_list(),
                                      "native_bfloat16": torch.cuda.is_bf16_supported(including_emulation=False)})
            # Actual CUDA arithmetic verifies the wheel, not merely the NVIDIA driver.
            probe = torch.ones((32, 32), device=device, dtype=dtype)
            require(bool(torch.isfinite(probe @ probe).all()), "CUDA arithmetic produced non-finite values")
            torch.cuda.synchronize()
            del probe
            torch.cuda.reset_peak_memory_stats()

        model_dir = ROOT / "models/embeddinggemma-2" / LOCK["revision"]
        report["model_directory"] = str(model_dir)
        report["stage"] = "download"
        write_json(args.output, report)
        download_start = time.perf_counter()
        if args.offline:
            require((model_dir / LOCK["weight_file"]).is_file(), "Offline model cache is missing; run once online first")
        else:
            print(f"Downloading exact model {LOCK['model_id']}@{LOCK['revision']}", flush=True)
            snapshot_download(repo_id=LOCK["model_id"], revision=LOCK["revision"],
                              local_dir=str(model_dir), token=False)
        report["timings"]["download_or_cache_check_s"] = time.perf_counter() - download_start
        # Protect the immutable model identity; never silently replace the model or revision.
        weight_path = model_dir / LOCK["weight_file"]
        require(weight_path.stat().st_size == LOCK["weight_bytes"], "Checkpoint file size differs from official metadata")
        digest = hashlib.sha256()
        hash_start = time.perf_counter()
        with weight_path.open("rb") as weights:
            for block in iter(lambda: weights.read(8 * 1024 * 1024), b""):
                digest.update(block)
        require(digest.hexdigest() == LOCK["weight_sha256"], "Checkpoint SHA256 differs from official metadata")
        report["checks"]["official_weight_sha256"] = True
        report["timings"]["checkpoint_hash_s"] = time.perf_counter() - hash_start
        report["storage"] = {"checkpoint_bytes": weight_path.stat().st_size,
                             "model_directory_bytes": sum(p.stat().st_size for p in model_dir.rglob("*") if p.is_file())}

        print(f"Loading text-only model on {device} with {dtype}", flush=True)
        report["stage"] = "load"
        write_json(args.output, report)
        load_start = time.perf_counter()
        model = SentenceTransformer(str(model_dir), device=device, local_files_only=True,
                                    trust_remote_code=False, config_kwargs=LOCK["config_kwargs"],
                                    model_kwargs={"torch_dtype": dtype, "attn_implementation": "sdpa"})
        model.eval()
        if device == "cuda":
            torch.cuda.synchronize()
        report["timings"]["model_load_s"] = time.perf_counter() - load_start
        backbone = model[0].auto_model
        require(backbone.config.vision_config is None, "Vision encoder was not disabled")
        require(backbone.config.audio_config is None, "Audio encoder was not disabled")
        parameter_count = sum(p.numel() for p in model.parameters())
        require(200_000_000 < parameter_count < 300_000_000, f"Unexpected text-only parameter count: {parameter_count}")
        require(all(p.dtype != torch.float16 for p in model.parameters()), "Forbidden float16 weights found")
        require(model.get_embedding_dimension() == 768, "Unexpected native embedding dimension")
        require(model.prompts.get("SearchQuery") == "task: search result | query: ", "SearchQuery prompt changed")
        require(model.prompts.get("SentenceSimilarity") == "task: sentence similarity | query: ", "Similarity prompt changed")
        report["model"] = {"parameter_count": parameter_count, "vision_config": None, "audio_config": None,
                           "parameter_dtypes": sorted({str(p.dtype) for p in model.parameters()}),
                           "max_sequence_length": model.max_seq_length, "prompts": model.prompts}
        report["checks"].update({"text_only_encoders": True, "no_float16": True,
                                  "native_dimension_768": True, "documented_prompts": True})

        def encode(texts, **kwargs):
            begin = time.perf_counter()
            with torch.inference_mode():
                values = model.encode(texts, normalize_embeddings=True, convert_to_tensor=True,
                                      show_progress_bar=False, batch_size=4, **kwargs).float().cpu().numpy()
            if device == "cuda":
                torch.cuda.synchronize()
            duration = time.perf_counter() - begin
            require(bool(np.isfinite(values).all()), "Embeddings contain NaN or infinity")
            require(values.ndim == 2 and values.shape == (len(texts), 768), "Unexpected embedding shape")
            norms = np.linalg.norm(values, axis=1, keepdims=True)
            require(bool((norms > 0).all()), "Zero embedding encountered")
            require(bool(np.allclose(norms, 1.0, atol=0.015)), "encode(normalize_embeddings=True) did not produce unit vectors")
            # BF16 output normalization has rounding; store/scoring use float32 unit vectors.
            values = values / norms
            return values, duration

        report["stage"] = "inference"
        write_json(args.output, report)
        sentence_vectors, report["timings"]["first_sentence_batch_s"] = encode(SENTENCES, prompt_name="SentenceSimilarity")
        sentence_scores = sentence_vectors @ sentence_vectors.T
        require(sentence_scores[0, 1] > max(sentence_scores[0, 2], sentence_scores[0, 3]),
                "Paraphrase did not rank above unrelated sentences")
        report["sentence_similarity"] = {"sentences": SENTENCES, "scores": sentence_scores.tolist(),
                                         "embedding_shape": list(sentence_vectors.shape)}
        document_texts = [f"title: {d['title']} | text: {d['text']}" for d in DOCUMENTS]
        # Empty explicit prompt prevents accidental duplicate/default document prefixes.
        document_vectors, report["timings"]["document_embedding_batch_s"] = encode(document_texts, prompt="")
        query_vectors, report["timings"]["query_embedding_batch_s"] = encode([q["text"] for q in QUERIES], prompt_name="SearchQuery")
        report["retrieval_smoke"] = {"documents": DOCUMENTS, "queries": QUERIES, "dimensions": {}}
        for dimension in LOCK["supported_dimensions"]:
            docs = document_vectors[:, :dimension].copy()
            queries = query_vectors[:, :dimension].copy()
            docs /= np.linalg.norm(docs, axis=1, keepdims=True)
            queries /= np.linalg.norm(queries, axis=1, keepdims=True)
            scores = queries @ docs.T
            rankings = np.argsort(-scores, axis=1)
            cases = [{"query": q["text"], "expected": q["relevant_id"],
                      "ranking": [{"document_id": DOCUMENTS[int(j)]["id"], "score": float(scores[i, j])} for j in rankings[i]],
                      "top1_correct": DOCUMENTS[int(rankings[i, 0])]["id"] == q["relevant_id"]}
                     for i, q in enumerate(QUERIES)]
            report["retrieval_smoke"]["dimensions"][str(dimension)] = {
                "method": "Leading dimensions of full vectors, L2 re-normalized without re-inference", "cases": cases}
            require(all(case["top1_correct"] for case in cases), f"A retrieval smoke case failed at {dimension} dimensions")

        latencies = []
        for _ in range(args.repeats):
            _, elapsed = encode([QUERIES[0]["text"]], prompt_name="SearchQuery")
            latencies.append(elapsed)
        report["warm_single_query"] = {"repeats": args.repeats, "latencies_s": latencies,
                                        "mean_s": statistics.mean(latencies), "median_s": statistics.median(latencies),
                                        "p95_s": float(np.percentile(latencies, 95)),
                                        "scope": "Encoding one short query only; excludes PDF/index retrieval"}
        report["checks"].update({"finite_nonzero_embeddings": True, "paraphrase_above_unrelated": True,
                                  "retrieval_smoke_top1_all_dimensions": True})
        artifact_path = args.output.with_suffix(".embeddings.npz")
        np.savez_compressed(artifact_path, sentences=sentence_vectors, documents=document_vectors, queries=query_vectors)
        report["embeddings_file"] = str(artifact_path.resolve())
        if args.compare_with:
            baseline = json.loads(args.compare_with.read_text(encoding="utf-8"))
            require(baseline["status"] == "passed", "Comparison baseline did not pass")
            require(baseline["model_lock"] == LOCK, "Baseline model/configuration differs")
            require(baseline["runtime"]["dtype"] == str(dtype), "Use the same dtype for restart comparison")
            with np.load(baseline["embeddings_file"], allow_pickle=False) as previous:
                differences = {}
                for name, values in (("sentences", sentence_vectors), ("documents", document_vectors), ("queries", query_vectors)):
                    require(previous[name].shape == values.shape, f"Restart shape mismatch for {name}")
                    differences[name] = float(np.max(np.abs(previous[name] - values)))
                    require(bool(np.allclose(previous[name], values, atol=1e-4, rtol=1e-4)), f"Restart embeddings changed for {name}")
            report["restart_comparison"] = {"baseline": str(args.compare_with.resolve()),
                                              "max_absolute_difference": differences, "passed": True}
        if args.offline:
            # The first event is the intentional guard verification, all others are unexpected.
            require(len(network_events) == 1, "Model attempted network access during offline execution")
            report["checks"]["offline_no_model_network_attempts"] = True
        report["status"] = "passed"
        report["stage"] = "complete"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        print(report["error"]["traceback"], file=sys.stderr, flush=True)
    finally:
        report["timings"]["total_process_work_s"] = time.perf_counter() - started
        if sampler:
            report["memory"] = sampler.stop()
        if torch is not None and report.get("runtime", {}).get("device") == "cuda":
            try:
                report.setdefault("memory", {}).update({
                    "torch_peak_allocated_vram_bytes": torch.cuda.max_memory_allocated(),
                    "torch_peak_reserved_vram_bytes": torch.cuda.max_memory_reserved(),
                    "vram_note": "PyTorch allocator peaks exclude CUDA context, driver, and other processes."})
            except Exception as exc:
                report["vram_error"] = str(exc)
        report["offline"]["blocked_socket_event_count"] = len(network_events)
        report["environment"]["gpu_after"] = gpu_snapshot()
        write_json(args.output, report)
        print(json.dumps({"status": report["status"], "stage": report["stage"],
                          "runtime": report.get("runtime"), "model": report.get("model", {}).get("parameter_count"),
                          "timings": report["timings"], "warm_single_query": report.get("warm_single_query"),
                          "memory": report.get("memory"), "error": report.get("error", {}).get("message"),
                          "report": str(args.output.resolve())}, indent=2), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
