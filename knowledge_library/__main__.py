"""JSON CLI: python -m knowledge_library --help."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .chunking import ChunkingConfig
from .embedding import EmbeddingGemma
from .library import Library
from .pdf import PdfOptions


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local PDF knowledge library — real EmbeddingGemma 2, no external inference")
    parser.add_argument("--library", type=Path, default=Path("data/library"))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--dimensions", type=int, choices=(768, 512, 256, 128), default=768)
    parser.add_argument("--batch-size", type=int, default=8)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("folders")
    create = sub.add_parser("folder-create")
    create.add_argument("name")
    rename = sub.add_parser("folder-rename")
    rename.add_argument("id")
    rename.add_argument("name")
    delete = sub.add_parser("folder-delete")
    delete.add_argument("id")
    docs = sub.add_parser("documents")
    docs.add_argument("--folder")
    imp = sub.add_parser("import")
    imp.add_argument("folder")
    imp.add_argument("paths", nargs="+", type=Path)
    imp.add_argument("--chunk-size", choices=(256,512,1024), type=int, default=256)
    imp.add_argument("--overlap", type=int, default=64)
    imp.add_argument("--title")
    imp.add_argument("--replace", metavar="DOCUMENT_ID")
    imp.add_argument("--ocr", action="store_true")
    imp.add_argument("--ocr-language", default="eng")
    imp.add_argument("--tessdata")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--folder")
    search.add_argument("--document")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--min-score", type=float)
    search.add_argument("--mode", choices=("semantic","bm25","bm25_raw","keyword","hybrid"), default="semantic")
    search.add_argument("--search-dimensions", type=int, choices=(128,256,512,768))
    search.add_argument("--semantic-weight", type=float, default=.5, help="Hybrid RRF semantic weight, 0 to 1")
    search.add_argument("--rank-constant", type=int, default=60, help="Positive hybrid RRF rank constant")
    for name in ("show", "refresh", "remove"):
        sub.add_parser(name).add_argument("id")
    move = sub.add_parser("move")
    move.add_argument("id")
    move.add_argument("folder")
    page = sub.add_parser("page")
    page.add_argument("id")
    page.add_argument("page_number", type=int)
    sync = sub.add_parser("sync")
    sync.add_argument("--remove-missing", action="store_true")
    for name in ("jobs", "stats", "verify"):
        sub.add_parser(name)
    args = parser.parse_args()
    try:
        with Library(args.library, EmbeddingGemma(device=args.device, dimensions=args.dimensions, batch_size=args.batch_size)) as library:
            command = args.command
            if command == "folders":
                result = library.folders()
            elif command == "folder-create":
                result = library.create_folder(args.name)
            elif command == "folder-rename":
                result = library.rename_folder(args.id, args.name)
            elif command == "folder-delete":
                result = library.delete_folder(args.id)
            elif command == "documents":
                result = library.documents(args.folder)
            elif command == "import":
                if args.replace and len(args.paths) != 1:
                    raise ValueError("--replace requires exactly one PDF")
                result = []
                for path in args.paths:
                    try:
                        item = library.import_pdf(path, args.folder, document_id=args.replace, title=args.title,
                                                  chunking=ChunkingConfig(args.chunk_size, args.overlap),
                                                  pdf_options=PdfOptions(args.ocr, args.ocr_language, args.tessdata))
                        result.append({"source": str(path), **item})
                    except Exception as exc:
                        result.append({"source": str(path), "action": "failed", "error": f"{type(exc).__name__}: {exc}"})
            elif command == "search":
                result = library.search(args.query, folder_id=args.folder, document_id=args.document,
                                        top_k=args.top_k, min_score=args.min_score, mode=args.mode,
                                        search_dimensions=args.search_dimensions,
                                        hybrid={"semantic_weight":args.semantic_weight,"rank_constant":args.rank_constant,"candidates":100} if args.mode=="hybrid" else None)
            elif command == "show":
                result = {"document": library.document(args.id), "pages": library.page_summary(args.id)}
            elif command == "refresh":
                result = library.refresh(args.id)
            elif command == "remove":
                result = library.remove_document(args.id)
            elif command == "move":
                result = library.move_document(args.id, args.folder)
            elif command == "page":
                result = library.page(args.id, args.page_number)
            elif command == "sync":
                result = library.sync(remove_missing=args.remove_missing)
            elif command == "jobs":
                result = library.jobs()
            elif command == "verify":
                result = library.verify()
            else:
                result = library.stats()
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            failed = command in ("import", "sync") and any(item.get("action") == "failed" for item in result)
            if command == "verify":
                failed = not result["passed"]
            return int(failed)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
