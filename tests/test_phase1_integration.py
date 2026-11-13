"""Exercise the real standalone inference CLI in a fresh offline process."""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_real_cached_model_in_fresh_offline_process():
    baseline = ROOT / "results/gpu-online.json"
    if not baseline.is_file():
        pytest.skip("Run the online standalone model test first; no checkpoint is mocked or downloaded here")
    # Keep actual execution evidence in the workspace; Windows sandbox temp roots
    # are not consistently writable, and persistent evidence is useful for review.
    output = ROOT / "results/pytest-offline.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/test_embedding_model.py"),
         "--device", "cuda", "--offline", "--compare-with", str(baseline),
         "--output", str(output)], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    (ROOT / "results/pytest-offline.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["restart_comparison"]["passed"] is True
    assert report["offline"]["blocked_socket_event_count"] == 1
    assert report["checks"]["offline_no_model_network_attempts"] is True
    with np.load(report["embeddings_file"], allow_pickle=False) as arrays:
        for name in ("sentences", "documents", "queries"):
            assert arrays[name].shape[1] == 768
            assert np.isfinite(arrays[name]).all()
            np.testing.assert_allclose(np.linalg.norm(arrays[name], axis=1), 1.0, atol=1e-5)
