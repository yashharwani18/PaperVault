"""The exact text-only EmbeddingGemma 2 configuration validated in Phase 1."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
import threading

import numpy as np
from tokenizers import Tokenizer

PROJECT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT / "model-lock.json").read_text(encoding="utf-8"))


class EmbeddingGemma:
    def __init__(self, *, device="cuda", dimensions=768, batch_size=8):
        if device not in ("cuda", "cpu"):
            raise ValueError("Select cuda or cpu explicitly; no silent device fallback")
        if dimensions not in LOCK["supported_dimensions"]:
            raise ValueError(f"Unsupported dimension: {dimensions}")
        if not 1 <= batch_size <= 32:
            raise ValueError("Batch size must be between 1 and 32")
        self.device, self.dimensions, self.batch_size = device, dimensions, batch_size
        self.model_dir = PROJECT / "models/embeddinggemma-2" / LOCK["revision"]
        self._tokenizer = self._model = self._torch = None
        self._load_lock=threading.Lock()
        self._inference_lock=threading.Lock()
        self.dtype = None
        self.stats = {"model_loads": 0, "model_load_s": 0., "document_texts_encoded": 0,
                      "query_texts_encoded": 0, "document_embedding_s": 0., "query_embedding_s": 0.}

    @property
    def signature(self):
        # Used for persistent compatibility checks without loading any model.
        return {"model_id": LOCK["model_id"], "revision": LOCK["revision"],
                "configuration_version": LOCK["configuration_version"], "dimensions": self.dimensions,
                "query_prompt": "SearchQuery", "document_format": "title: {title} | text: {content}",
                "normalization": "float32-l2-after-leading-dimension-truncation-v1"}

    @property
    def tokenizer(self):
        if self._tokenizer is None:
            self._tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
            self._tokenizer.no_truncation()
            self._tokenizer.no_padding()
        return self._tokenizer

    def token_count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def load(self):
        with self._load_lock:return self._load()

    def _load(self):
        if self._model is not None:
            return self._model
        start = time.perf_counter()
        stages={};last=start
        def stage(name):
            nonlocal last
            current=time.perf_counter();stages[name]=current-last;last=current
        os.environ.update(HF_HOME=str(PROJECT / ".cache/huggingface"), HF_HUB_OFFLINE="1",
                          TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                          HF_HUB_DISABLE_PROGRESS_BARS="1", DO_NOT_TRACK="1", TOKENIZERS_PARALLELISM="false")
        weight = self.model_dir / LOCK["weight_file"]
        if not weight.is_file():
            raise FileNotFoundError("Exact model is not cached. Run the Phase 1 model test online first.")
        with weight.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != LOCK["weight_sha256"]:
            raise ValueError("Cached checkpoint failed the pinned SHA256 check")
        stage('checkpoint_verification_s')
        import torch
        stage('torch_import_s')
        from .text_encoder import TextEncoder
        stage('text_encoder_import_s')
        torch.set_num_threads(8)
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable; choose --device cpu explicitly")
        dtype = torch.bfloat16 if self.device == "cuda" and torch.cuda.is_bf16_supported(including_emulation=False) else torch.float32
        stage('device_probe_s')
        model = TextEncoder(self.model_dir, device=self.device,config_kwargs=LOCK["config_kwargs"],
                            model_kwargs={"torch_dtype": dtype, "attn_implementation": "sdpa"})
        model.eval()
        stage('model_construction_s')
        config = model[0].auto_model.config
        if config.vision_config is not None or config.audio_config is not None:
            raise RuntimeError("The model did not load in the validated text-only configuration")
        if model.get_embedding_dimension() != 768 or any(p.dtype == torch.float16 for p in model.parameters()):
            raise RuntimeError("Invalid model dimension or forbidden float16 weights")
        if model.prompts.get("SearchQuery") != "task: search result | query: ":
            raise RuntimeError("The pinned SearchQuery prompt was not found")
        self._model, self._torch, self.dtype = model, torch, str(dtype)
        stage('model_validation_s')
        self.stats['load_stages_s']=stages
        self.stats["model_loads"] += 1
        self.stats["model_load_s"] += time.perf_counter() - start
        return model

    def _encode(self, texts, *, query):
        with self._inference_lock:return self._encode_serial(texts,query=query)

    def _encode_serial(self, texts, *, query):
        if not texts:
            return np.empty((0, self.dimensions), dtype="<f4")
        for text in texts:
            # Include BOS/EOS and leave room beyond the formatted task instruction.
            if self.token_count(text) > 8100:
                raise ValueError("Input exceeds the safe model context budget; split it into smaller chunks")
        model = self.load()
        begin = time.perf_counter()
        options = {"prompt_name": "SearchQuery"} if query else {"prompt": ""}
        with self._torch.inference_mode():
            result = model.encode(texts, convert_to_tensor=True, normalize_embeddings=True,
                                  batch_size=self.batch_size, show_progress_bar=False, **options)
            vectors = result.float().cpu().numpy()[:, :self.dimensions].copy()
        if self.device == "cuda":
            self._torch.cuda.synchronize()
        if vectors.shape != (len(texts), self.dimensions) or not np.isfinite(vectors).all():
            raise ValueError("The model produced invalid embedding shape or non-finite values")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if (norms <= 0).any():
            raise ValueError("The model produced a zero embedding")
        vectors = np.asarray(vectors / norms, dtype="<f4")
        kind = "query" if query else "document"
        self.stats[f"{kind}_texts_encoded"] += len(texts)
        self.stats[f"{kind}_embedding_s"] += time.perf_counter() - begin
        return vectors

    @staticmethod
    def format_document(title, text):
        # Bound metadata overhead without truncating the retrieved passage.
        clean_title = " ".join(title.split())[:256] or "none"
        return f"title: {clean_title} | text: {text}"

    def documents(self, title, texts):
        return self._encode([self.format_document(title, text) for text in texts], query=False)

    def query(self, text):
        return self._encode([text], query=True)[0]
