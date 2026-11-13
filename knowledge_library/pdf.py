"""Page-wise PDF extraction. Flag incomplete text instead of fabricating content."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import pymupdf

EXTRACTION_VERSION = f"pymupdf-{pymupdf.VersionBind}-physical-evidence-v3"


def native_text(page):
    # Coordinate sorting scrambled the rotated MIT slides and interleaved BERT's
    # columns in actual validation. Preserve the PDF author's content-stream order.
    # This is not a claim to solve arbitrary PDF reading-order reconstruction.
    return page.get_text("text", sort=False)


@dataclass(frozen=True)
class PdfOptions:
    ocr: bool = False
    ocr_language: str = "eng"
    tessdata: str | None = None
    tables: bool = True
    audit_ocr: bool = False
    max_ocr_pixels: int = 20_000_000
    max_source_pixels: int = 32_000_000
    ocr_retry_limit: int = 2

    def to_dict(self):
        return asdict(self)

    def __post_init__(self):
        if not 0 < self.max_ocr_pixels <= 40_000_000 or not 0 < self.max_source_pixels <= 64_000_000:
            raise ValueError('OCR raster/source pixel limit is outside the supported range')
        if not 0 <= self.ocr_retry_limit <= 4:raise ValueError('OCR retries must be between zero and four')


def open_pdf(path: Path):
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc
    if not document.is_pdf:
        document.close()
        raise ValueError("The supplied file is not a PDF")
    if document.needs_pass:
        document.close()
        raise ValueError("Encrypted PDF requires a password; password handling is not implemented")
    if document.page_count == 0:
        document.close()
        raise ValueError("The PDF contains no pages")
    return document


def extract_page(page, options):
    number = page.number + 1  # Physical PDF pages are always one-based externally.
    result = {"page_number": number, "page_label": page.get_label() or str(number), "text": "",
              "method": "native", "status": "ok", "warnings": [], "ocr_confidence": None,
              "evidence": {"version":1,"frame":"unrotated_page_points","rotation":page.rotation,
                           "bounds":list(page.rect*page.derotation_matrix),"display_bounds":list(page.rect),
                           "words":[],"tables":[],"recipe":options.to_dict(),
                           "ocr_alternatives":None,"coverage":"not_audited"}}
    try:
        text = native_text(page)
        words=page.get_text('words',sort=False)
        directions=[line.get('dir',(1,0)) for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']
                    for line in block.get('lines',[])]
        result['evidence']['non_horizontal_text']=any(abs(d[1])>.1 or d[0]<.9 for d in directions)
        result['evidence']['native_text_length']=len(text)
        if page.rotation:
            result["warnings"].append("rotated_page_source_order_used")
        images = page.get_images(full=True)
        drawings = None
        alphanumeric = sum(c.isalnum() for c in text)
        replacement_ratio = text.count("\ufffd") / max(1, len(text))
        image_coverage = 0.
        for image in page.get_image_info():
            rect = pymupdf.Rect(image["bbox"]) & page.rect
            image_coverage = max(image_coverage, rect.get_area() / max(1, page.rect.get_area()))
        # Include scans with only a page-number/header text layer, not just completely empty scans.
        needs_ocr = (not text.strip() and bool(images)) or (alphanumeric < 40 and image_coverage >= .4) or replacement_ratio > .02
        partial_ocr=bool(options.ocr and not needs_ocr and images and image_coverage>=.15)
        if not text.strip() and not images:
            drawings = len(page.get_drawings())
            needs_ocr = drawings > 20
        if needs_ocr or partial_ocr:
            result["warnings"].append("image_or_garbled_text_requires_review")
            if options.ocr:
                try:
                    import math
                    output_pixels=math.ceil(page.rect.width*200/72)*math.ceil(page.rect.height*200/72)
                    source_pixels=sum(i['width']*i['height'] for i in page.get_image_info())
                    result['evidence']['resource_profile']=dict(ocr_output_pixels=output_pixels,
                        source_pixels=source_pixels,scope='pixel admission only; decoder and OCR memory are additional')
                    if output_pixels>options.max_ocr_pixels or source_pixels>options.max_source_pixels:
                        raise ValueError('OCR work limit reached; source decode is additional to crop output')
                    tp = page.get_textpage_ocr(language=options.ocr_language, dpi=200, full=not partial_ocr,
                                               tessdata=options.tessdata)
                    text = page.get_text("text", textpage=tp, sort=False)
                    words=page.get_text('words',textpage=tp,sort=False)
                    result["method"] = "ocr"
                    if partial_ocr:result['warnings'].append('embedded_images_ocr_with_native_text')
                    result["warnings"].append("ocr_confidence_unavailable_manual_review_required")
                    if options.audit_ocr and not page.rotation:
                        from .ocr_audit import audit
                        try:
                            extra_words,audit_record=audit(page,words,options)
                            result['evidence']['coverage']=audit_record
                            if extra_words:
                                text+='\n[Additional OCR observations]\n'+'\n'.join(w[4] for w in extra_words)
                                words+=extra_words
                            result['warnings'].append('ocr_coverage_audit_is_not_completeness_verification')
                        except Exception as exc:
                            result['evidence']['coverage']=dict(state='audit_failed',complete=False)
                            result['warnings'].append(f'ocr_coverage_audit_failed: {exc}')
                    if not text.strip():
                        result["status"] = "needs_ocr"
                except Exception as exc:
                    if not partial_ocr:result["status"] = "needs_ocr"
                    result["warnings"].append(f"ocr_failed: {exc}")
            else:
                result["status"] = "needs_ocr"
        elif not text.strip():
            result["status"] = "empty"
        elif alphanumeric < 20:
            result["warnings"].append("sparse_text")
        if replacement_ratio > 0:
            result["warnings"].append(f"replacement_character_ratio={replacement_ratio:.4f}")
        if options.tables and result['status']=='ok':
            try:
                rows=[]
                for table in page.find_tables().tables[:20]:
                    extracted=table.extract()[:1000]
                    if len(extracted)<2:continue
                    headers=[str(c or '').replace('\n',' ').strip() for c in extracted[0]]
                    result['evidence']['tables'].append(dict(bbox=list(table.bbox),method='pymupdf_find_tables',
                        derived=True,headers=headers))
                    for row in extracted[1:]:
                        cells=[f'{headers[i] or "Column "+str(i+1)}: {str(cell).replace(chr(10)," ")}' for i,cell in enumerate(row) if cell is not None and i<len(headers)]
                        if cells:rows.append(' | '.join(cells))
                if rows:
                    text+='\n[Table rows extracted from this page]\n'+'\n'.join(rows)[:50000]
                    result['warnings'].append('table_layout_extraction_requires_review')
            except Exception:
                result['warnings'].append('table_extraction_unavailable_native_text_retained')
        result["text"] = text
        result['evidence']['words']=[list(w) for w in words]
        result["image_coverage"] = image_coverage
        # Pages marked needs_ocr retain diagnostic native text but are not indexed.
    except Exception as exc:
        result["status"] = "extraction_failed"
        result["warnings"].append(str(exc))
    return result
