"""Freeze new RFC questions and source evidence before querying any ranker."""
import json
import hashlib
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from knowledge_library.library import Library


def main():
    path=ROOT/'evaluation/followup-queries.json'
    if path.exists():raise SystemExit('Frozen questions already exist; do not overwrite after evaluation')
    positive=[
      ('9000',13,'How do the lowest two bits of a QUIC stream identifier tell me its initiator and permitted direction?'),
      ('9000',22,'How does QUIC prevent one stream and a whole connection from exhausting the receiving buffer?'),
      ('9000',53,'When a QUIC peer moves to a new path, what happens to congestion control and round-trip estimates?'),
      ('9000',87,'Which QUIC integer encodings fit in one, two, four, or eight bytes, and how is the length signaled?'),
      ('9001',6,'Why can early application data in a QUIC zero-round-trip handshake be unsafe to repeat?'),
      ('9001',13,'Which TLS version does the QUIC security specification describe?'),
      ('9002',7,'Why does QUIC recommend a minimum congestion window of two packets instead of one?'),
      ('9002',13,'What is the formula for the QUIC probe timeout, including RTT variation and maximum acknowledgment delay?'),
      ('9002',20,'How does a QUIC NewReno sender grow its congestion window during congestion avoidance?'),
      ('9002',21,'What duration and threshold are used to establish persistent congestion in QUIC?')]
    negative=[
      'What was the measured QUIC packet loss percentage on our Jaipur warehouse network on 25 September 2026?',
      'What private TLS key does our production QUIC server currently use?',
      'What probe timeout did our router actually log at 14:32 on 25 September 2026?',
      'What is the negotiated stream ID for the confidential ACME deployment session XZ-987654?',
      'Which engineer approved our company migration to QUIC on 12 October 2026?',
      'How much did our company pay its TLS certificate supplier in September 2026?',
      'What is the customer password for the internal QUIC dashboard account ZETA-771122?',
      'How many mobile devices at our private Nashik branch suffered persistent congestion last Friday?',
      'What exact GPU memory use did our unrecorded QUIC benchmark experiment QX-554433 produce?',
      'What date did our fictional customer BT-000099 sign its private transport agreement?']
    with Library(ROOT/'data/phase4/cuda-20261017-175438-1400') as lib:
        rows=[]
        for i,(rfc,page,query) in enumerate(positive):
            doc=next(d for d in lib.documents() if d['filename']==f'rfc-{rfc}.pdf');text=lib.page(doc['id'],page)['text']
            rows.append(dict(id=f'rfc-positive-{i+1}',query=query,relevant=[dict(document_id=doc['id'],filename=doc['filename'],page=page)],source_evidence=text,source_sha256=doc['sha256']))
        rows += [dict(id=f'rfc-missing-{i+1}',query=q,relevant=[],reason='Requests private deployment facts or secrets absent from this public standards corpus') for i,q in enumerate(negative)]
    record=dict(protocol='Follow-up new questions on previously performance-only RFCs. Fixed current 256-token/768d profile and unchanged cutoff. No tuning on these results.',
                annotation='Source pages checked by coding agent before rankings. Not independent human judgments; positive labels are non-exhaustive.',
                library=str(ROOT/'data/phase4/cuda-20261017-175438-1400'),questions=rows)
    path.write_text(json.dumps(record,indent=2));print('Frozen',len(rows),'queries; SHA256',hashlib.sha256(path.read_bytes()).hexdigest())


if __name__=='__main__':main()
