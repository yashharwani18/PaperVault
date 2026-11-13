"""Compare legacy 900-character chunking with new whole-page + token-driven paragraph packing."""
import re
import json

def legacy_chunk(text: str, max_tokens=512):
    """Replicates legacy PageIndexer logic."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(text_len, start + 900)
        c_text = text[start:end]
        # Token estimation (approx 4 chars/token or gemma tokens)
        while len(c_text) // 4 > max_tokens:
            end = start + len(c_text) // 2
            c_text = text[start:end]
        chunks.append({"start": start, "end": end, "text": c_text, "tokens": max(1, len(c_text) // 4)})
        if end >= text_len:
            break
        start = max(start + 1, end - 80)
    return chunks

def segment_text(text: str):
    spans = []
    length = len(text)
    start = 0
    while start < length:
        while start < length and text[start] in '\r\n':
            start += 1
        if start >= length:
            break
        next_idx = text.find("\n\n", start)
        if next_idx < 0:
            next_idx = text.find("\r\n\r\n", start)
        end = next_idx if next_idx >= 0 else length
        if next_idx < 0 and end - start > 1200:
            line = text.find("\n", start + 300)
            if 0 <= line < end:
                end = line
        if end - start > 1200:
            sent = -1
            for i in range(start + 300, min(length, start + 1200)):
                if text[i] in '.!?' and i + 1 < length and text[i + 1].isspace():
                    sent = i + 1
                    break
            if sent > start:
                end = sent
        spans.append((start, end))
        start = end
    return spans

def new_chunk(text: str, max_tokens=512):
    """Replicates new PageIndexer logic."""
    if not text.strip():
        return []
    
    # 1. Whole-page check
    est_tokens = max(1, (len(text) + 30) // 4)
    if len(text) <= 2000 and est_tokens <= max_tokens:
        return [{"start": 0, "end": len(text), "text": text, "tokens": est_tokens, "type": "whole_page"}]
    
    # 2. Token-driven paragraph packing
    spans = segment_text(text)
    if not spans:
        spans = [(0, len(text))]
    
    chunks = []
    seg_idx = 0
    while seg_idx < len(spans):
        chunk_start = spans[seg_idx][0]
        chunk_end = spans[seg_idx][1]
        last_included = seg_idx
        
        c_text = text[chunk_start:chunk_end]
        while len(c_text) // 4 > max_tokens:
            chunk_end = chunk_start + len(c_text) // 2
            c_text = text[chunk_start:chunk_end]
            
        if chunk_end == spans[seg_idx][1]:
            for k in range(seg_idx + 1, len(spans)):
                test_end = spans[k][1]
                test_text = text[chunk_start:test_end]
                test_tokens = max(1, (len(test_text) + 30) // 4)
                if test_tokens <= max_tokens:
                    chunk_end = test_end
                    last_included = k
                else:
                    break
        
        c_text = text[chunk_start:chunk_end]
        chunks.append({
            "start": chunk_start,
            "end": chunk_end,
            "text": c_text,
            "tokens": max(1, (len(c_text) + 30) // 4),
            "type": "paragraph_packed"
        })
        
        if chunk_end >= len(text):
            break
            
        if last_included > seg_idx:
            seg_idx = last_included
        else:
            next_start = max(chunk_start + 1, chunk_end - 120)
            while seg_idx < len(spans) and spans[seg_idx][1] <= next_start:
                seg_idx += 1
            if seg_idx < len(spans) and spans[seg_idx][0] < next_start:
                spans[seg_idx] = (next_start, spans[seg_idx][1])
                
    return chunks

def main():
    benchmarks = {}
    
    # Fixture 1: 1-Page Invoice (>900 chars, ~1250 chars)
    invoice_lines = ["Invoice #INV-2026-9821", "Vendor: Acme Commercial Supplies Ltd.", "Date: 2026-10-26\n"]
    for i in range(1, 13):
        invoice_lines.append(f"Item {i:02d}: Industrial heavy duty laser printing paper reams - Qty: {i} Rate: 45.00 Total: {i*45:.2f}")
    invoice_lines.append("\nSubtotal: 3510.00\nTax (GST 18%): 631.80\nGrand Total: 4141.80\nPayment Terms: Net 30 days")
    invoice_text = "\n".join(invoice_lines)
    
    old_inv = legacy_chunk(invoice_text)
    new_inv = new_chunk(invoice_text)
    benchmarks["single_page_invoice"] = {
        "text_chars": len(invoice_text),
        "legacy_passages": len(old_inv),
        "new_passages": len(new_inv),
        "passage_reduction_pct": round((1 - len(new_inv)/len(old_inv)) * 100, 1)
    }
    
    # Fixture 2: 10-Page Slide Deck (600 - 1100 chars per slide)
    deck_old = 0
    deck_new = 0
    for s in range(10):
        slide_text = f"Slide {s+1}: Deep Learning Neural Architectures\n\n" + (
            "Convolutional layers extract spatial hierarchies. "
            "Pooling layers downsample feature maps to reduce computation and variance. "
            "Residual connections mitigate gradient vanishing across deep backpropagation steps. "
        ) * (2 + s % 3)
        deck_old += len(legacy_chunk(slide_text))
        deck_new += len(new_chunk(slide_text))
        
    benchmarks["10_page_slide_deck"] = {
        "slides": 10,
        "legacy_passages": deck_old,
        "new_passages": deck_new,
        "passage_reduction_pct": round((1 - deck_new/deck_old) * 100, 1)
    }
    
    # Fixture 3: Multi-page Standard PDF (10 pages, 1400-1600 chars/page)
    doc_old = 0
    doc_new = 0
    for p in range(10):
        page_text = f"Chapter {p+1}: Signals and Transforms\n\n" + (
            "Discrete Fourier transforms map discrete signals to frequencies. "
            "Fast Fourier Transform algorithms compute DFT in O(N log N) time complexity. "
            "Spectral filtering enables noise cancellation in acoustic signal pipelines.\n\n"
        ) * 5
        doc_old += len(legacy_chunk(page_text))
        doc_new += len(new_chunk(page_text))
        
    benchmarks["10_page_standard_pdf"] = {
        "pages": 10,
        "legacy_passages": doc_old,
        "new_passages": doc_new,
        "passage_reduction_pct": round((1 - doc_new/doc_old) * 100, 1)
    }
    
    # Fixture 4: Dense Oversized Multi-page PDF (5 pages, ~4200 chars/page, 6 paragraphs each)
    dense_old = 0
    dense_new = 0
    for p in range(5):
        paras = []
        for pr in range(6):
            paras.append(f"Section {p+1}.{pr+1} Detailed System Specification\n" + (
                "The storage engine utilizes Write-Ahead Logging (WAL) for durability and concurrent snapshot reads. "
                "B-tree index nodes maintain balanced depth across variable key length distributions. "
                "Page cache evictions prioritize clean buffers and enforce checkpoint boundaries under memory constraints."
            ) * 2)
        dense_text = "\n\n".join(paras)
        dense_old += len(legacy_chunk(dense_text))
        dense_new += len(new_chunk(dense_text))
        
    benchmarks["5_page_dense_oversized_pdf"] = {
        "pages": 5,
        "legacy_passages": dense_old,
        "new_passages": dense_new,
        "passage_reduction_pct": round((1 - dense_new/dense_old) * 100, 1)
    }
    
    print(json.dumps(benchmarks, indent=2))
    with open("results/chunking-before-after-benchmark.json", "w", encoding="utf-8") as f:
        json.dump(benchmarks, f, indent=2)

if __name__ == "__main__":
    main()
