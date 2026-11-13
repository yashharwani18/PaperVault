"""Freeze public source pages and multilingual queries before Android ranking."""
from pathlib import Path
import hashlib
import json
import pymupdf

ROOT=Path(__file__).resolve().parents[1]
HINDI={
 'pumping-statement':'पंपिंग लेम्मा का सामान्य कथन कहाँ है जिसमें स्वीकृत शब्द का बीच का भाग दोहराया जा सकता है?',
 'alternative-transitions':'एक ही इनपुट चिह्न के लिए अवस्था मशीन कई अगली अवस्थाओं पर कैसे विचार कर सकती है?',
 'scaled-attention':'अटेंशन लेयर में softmax से पहले query और key के dot product को छोटा क्यों किया जाता है?',
 'hidden-token-training':'दोनों तरफ के शब्दों से छिपे हुए टोकन का अनुमान लगाने के लिए मॉडल को कैसे प्रशिक्षित किया जाता है?',
 'adam-initial-bias':'Adam में शून्य से शुरू होने वाले moving averages का bias correction क्यों ज़रूरी है?',
 'csf-profiles':'साइबर सुरक्षा ढाँचे में Current Profile और Target Profile में क्या अंतर है?',
 'dfa-components':'एक deterministic finite automaton को औपचारिक रूप से कौन से पाँच घटक परिभाषित करते हैं?',
 'recognizer-decider':'हमेशा रुक जाने की शर्त decider को recognizer से कैसे अलग करती है?',
 'nyquist':'सीमित bandwidth वाले सिग्नल को बिना जानकारी खोए दोबारा बनाने के लिए कितनी तेज़ी से sample करना चाहिए?',
 'position-order':'Transformer में recurrence या convolution नहीं होता तो उसे टोकन का क्रम कैसे पता चलता है?',
 'p-value-meaning':'null hypothesis के तहत p-value किस घटना की probability बताता है?',
 'http-304':'HTTP server पूरी representation दोबारा भेजने के बजाय 304 Not Modified क्यों लौटा सकता है?',
}


def main():
    corpus=json.loads((ROOT/'evaluation/phase3-corpus.json').read_text(encoding='utf-8'))
    labels=json.loads((ROOT/'evaluation/phase3-queries.json').read_text(encoding='utf-8'))
    prior=json.loads((ROOT/'results/phase3-validation.json').read_text(encoding='utf-8'))
    reference=next(r for r in prior['runs'] if r['chunk_tokens']==256)
    # Existing evaluation source digests are stored in its original library.
    import sqlite3
    with sqlite3.connect((Path(reference['library'])/'library.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        expected={entry['corpus_id']:db.execute('SELECT sha256 FROM documents WHERE id=?',(entry['document_id'],)).fetchone()[0] for entry in reference['documents']}
    documents=[]
    for entry in corpus['documents']:
        source=ROOT/'corpus/pdfs'/(entry['id']+'.pdf');digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=expected[entry['id']]:raise ValueError('Changed evaluation source: '+entry['id'])
        with pymupdf.open(source) as pdf:
            pages=[{'page_number':n,'text':page.get_text()} for n,page in enumerate(pdf,1)]
        documents.append({'id':entry['id'],'title':entry['title'],'sha256':digest,'pages':pages})
    queries=[{**q,'language':'en'} for q in labels['queries']]
    for q in labels['queries']:
        if q['id'] in HINDI:queries.append({**q,'id':q['id']+'-hi','parent_id':q['id'],'query':HINDI[q['id']],'language':'hi'})
    snapshot={'documents':documents,'queries':queries,'annotation':labels['judgment_provenance'],
              'scope':'Same public source pages and actual current Android model for every retrieval candidate. Hindi translations are developer-authored and inherit the English parent split.'}
    output=ROOT/'.cache/rag-quality/assets/retrieval-benchmark';output.mkdir(parents=True,exist_ok=True)
    path=output/'corpus.json';path.write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    protocol={'source_documents':len(documents),'source_pages':sum(len(d['pages']) for d in documents),'queries':len(queries),'corpus_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'labels_sha256':hashlib.sha256((ROOT/'evaluation/phase3-queries.json').read_bytes()).hexdigest(),'hindi_ids':list(HINDI),'spec':'docs/superpowers/specs/2026-10-28-offline-retrieval-upgrade.md'}
    out=ROOT/'results/retrieval-upgrade';out.mkdir(parents=True,exist_ok=True);(out/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    print(json.dumps(protocol,indent=2))


if __name__=='__main__':main()
