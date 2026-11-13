"""Build import lookup metadata during setup; no model weights or network required."""
from pathlib import Path
import os
import sys
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from knowledge_library.import_index import enable
enable()
from transformers.models.embedding_gemma2.modeling_embedding_gemma2 import EmbeddingGemma2Model
print('Text encoder import index is ready.')
