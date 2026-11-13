"""Page-contained token chunks with overlap and exact extracted-text offsets."""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class ChunkingConfig:
    tokens: int = 256
    overlap: int = 64
    version: str = "page-sentence-token-v1"

    def __post_init__(self):
        if self.tokens not in (256, 512, 1024):
            raise ValueError("Chunk size must be 256, 512, or 1024 tokens")
        if not 0 <= self.overlap < self.tokens // 2:
            raise ValueError("Overlap must be nonnegative and less than half the chunk size")

    def to_dict(self):
        return asdict(self)


def chunk_page(text, tokenizer, config):
    encoded = tokenizer.encode(text, add_special_tokens=False)
    offsets = encoded.offsets
    if not offsets:
        return
    ends = [end for _, end in offsets]
    boundaries = [m.end() for m in re.finditer(r"\n\s*\n|[.!?][ \t]+|\n", text)]
    start = 0
    while start < len(offsets):
        stop = min(start + config.tokens, len(offsets))
        if stop < len(offsets):
            minimum_char = offsets[start + max(1, int(config.tokens * .6))][0]
            eligible = [b for b in boundaries if minimum_char <= b <= offsets[stop - 1][1]]
            if eligible:
                proposed = bisect_right(ends, eligible[-1], lo=start, hi=stop)
                if proposed > start + config.overlap:
                    stop = proposed
        char_start, char_end = offsets[start][0], offsets[stop - 1][1]
        while char_start < char_end and text[char_start].isspace():
            char_start += 1
        while char_end > char_start and text[char_end - 1].isspace():
            char_end -= 1
        if char_end > char_start:
            passage = text[char_start:char_end]
            # Slicing can change subword boundaries. Enforce the actual final count.
            while len(tokenizer.encode(passage, add_special_tokens=False).ids) > config.tokens:
                stop -= 1
                char_end = offsets[stop - 1][1]
                passage = text[char_start:char_end]
            yield {"text": passage, "char_start": char_start, "char_end": char_end,
                   "token_count": len(tokenizer.encode(passage, add_special_tokens=False).ids)}
        if stop >= len(offsets):
            break
        start = max(start + 1, stop - config.overlap)
