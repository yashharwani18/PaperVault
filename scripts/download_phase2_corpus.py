"""Download the explicitly listed public PDF sources; preserve originals and provenance."""
from __future__ import annotations
import datetime as dt
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if urllib.parse.urlsplit(href).path.lower().endswith(".pdf"):
                self.links.append(href)


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LocalKnowledge-PCValidation/0.2"}), timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evaluation/phase2-corpus.json")
    parser.add_argument("--evidence", type=Path, default=ROOT / "results/phase2-corpus-downloads.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = ROOT / "corpus/pdfs"
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(), "documents": []}
    for entry in manifest["documents"]:
        destination = output / f"{entry['id']}.pdf"
        resolved = entry["source_url"]
        try:
            if not destination.is_file():
                if not urllib.parse.urlsplit(resolved).path.lower().endswith(".pdf") and "arxiv.org/pdf/" not in resolved:
                    with fetch(resolved) as response:
                        html = response.read(4 * 1024 * 1024).decode("utf-8")
                    parser = PdfLinks()
                    parser.feed(html)
                    if not parser.links:
                        raise ValueError("Official resource page has no PDF download link")
                    resolved = urllib.parse.urljoin(resolved, parser.links[0])
                temporary = destination.with_suffix(".download")
                try:
                    with fetch(resolved) as response, temporary.open("wb") as target:
                        size = 0
                        while block := response.read(1024 * 1024):
                            size += len(block)
                            if size > 50 * 1024 * 1024:
                                raise ValueError("Download exceeded 50 MiB per-file safety bound")
                            target.write(block)
                    with temporary.open("rb") as stream:
                        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                            raise ValueError("Download did not contain a PDF header")
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            with destination.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            record = {**entry, "resolved_url": resolved, "path": str(destination), "bytes": destination.stat().st_size,
                      "sha256": checksum, "status": "downloaded"}
            print(f"{entry['id']}: {record['bytes']:,} bytes", flush=True)
        except Exception as exc:
            record = {**entry, "status": "failed", "error": str(exc)}
            print(f"{entry['id']}: FAILED: {exc}", flush=True)
        evidence["documents"].append(record)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return int(any(d["status"] != "downloaded" for d in evidence["documents"]))


if __name__ == "__main__":
    raise SystemExit(main())
