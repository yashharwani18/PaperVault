import {test} from 'node:test';
import assert from 'node:assert/strict';
import {formatReference, REFERENCE_FORMATS} from '../src/citations.ts';

const paper={id:'paper-1',type:'article-journal',title:'A careful test of retrieval',author:[{family:'Smith',given:'Jane'},{family:'García',given:'José'}],issued:{'date-parts':[[2021]]},'container-title':'Journal of Testing',volume:'12',issue:'3',page:'45-52',DOI:'10.1234/example'};

test('APA7 formats known authors, date, journal and DOI',()=>{
 assert.equal(formatReference(paper,'apa').text,'Smith, J., & García, J. (2021). A careful test of retrieval. Journal of Testing, 12(3), 45–52. https://doi.org/10.1234/example');
});

test('IEEE produces a numbered reference with author initials and journal details',()=>{
 const {text}=formatReference(paper,'ieee');
 assert.match(text,/^\[1\]\s+J\. Smith and J\. García,/);
 assert.match(text,/vol\. 12/);assert.match(text,/pp\. 45–52/);assert.match(text,/2021/);assert.match(text,/10\.1234\/example/);
});

test('every bundled style works offline and returns text, never HTML containers',()=>{
 for(const {id} of REFERENCE_FORMATS.filter(x=>!['custom','bibtex','ris','json'].includes(x.id))){
  const out=formatReference(paper,id);
  assert.ok(/retrieval/i.test(out.text),id);assert.ok(out.text.includes('2021'),id);assert.equal(out.extension,'txt');assert.ok(!out.text.includes('<div'));
 }
});

test('missing authors and date do not fabricate people or a publication year',()=>{
 const out=formatReference({id:'unknown',type:'article-journal',title:'An undated paper'},'apa').text;
 assert.ok(out.includes('An undated paper'));assert.ok(out.includes('n.d.'));assert.ok(!out.includes('Unknown'));assert.ok(!/20\d\d/.test(out));
});

const custom='<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text"><info><title>Local test</title><id>urn:test:local</id></info><citation><layout><text variable="title"/></layout></citation><bibliography><layout prefix="CUSTOM: "><text variable="title"/></layout></bibliography></style>';
test('custom independent CSL styles work without a network lookup',()=>{
 assert.equal(formatReference(paper,'custom',{styleXml:custom}).text,'CUSTOM: A careful test of retrieval');
});

test('bad, dependent and unsupported custom styles fail with useful errors',()=>{
 assert.throws(()=>formatReference(paper,'custom'),/choose|provide|upload/i);
 assert.throws(()=>formatReference(paper,'custom',{styleXml:custom.replace('</layout>','')}),/valid|malformed|XML/i);
 const dependent='<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0"><info><title>Dependent</title><link rel="independent-parent" href="https://example.com/style"/></info></style>';
 assert.throws(()=>formatReference(paper,'custom',{styleXml:dependent}),/independent|parent/i);
 assert.throws(()=>formatReference(paper,'custom',{styleXml:'<!DOCTYPE style [<!ENTITY x SYSTEM "file:///secret">]>'+custom}),/DOCTYPE|entities/i);
 assert.throws(()=>formatReference(paper,'imaginary'),/unsupported|unknown/i);
});

test('CSL title markup is handled as text and input is not mutated',()=>{
 const input={...paper,title:'A <i>careful</i> test of retrieval'};const original=JSON.stringify(input);
 const out=formatReference(input,'apa').text;
 assert.ok(out.includes('A careful test of retrieval'));assert.ok(!out.includes('<i>'));assert.equal(JSON.stringify(input),original);
});

test('BibTeX protects TeX control characters and preserves Unicode',()=>{
 const out=formatReference({...paper,title:'García {test} \\input{secret} & 50%'},'bibtex');
 assert.equal(out.extension,'bib');assert.match(out.text,/García/);assert.ok(out.text.includes('\\{test\\}'));assert.ok(out.text.includes('\\textbackslash{}input'));assert.ok(out.text.includes('\\&'));assert.ok(out.text.includes('\\%'));
});

test('RIS cannot inject additional records through metadata line breaks',()=>{
 const out=formatReference({...paper,title:'Real title\nER  -\nTY  - BOOK'},'ris');
 assert.equal(out.text.match(/^TY  -/gm).length,1);assert.equal(out.text.match(/^ER  -/gm).length,1);assert.equal(out.extension,'ris');
});

test('CSL JSON round trips metadata and rejects absent titles',()=>{
 assert.deepEqual(JSON.parse(formatReference(paper,'json').text),[paper]);
 assert.throws(()=>formatReference({id:'none',type:'article-journal'},'apa'),/title/i);
});

test('non-English custom styles require their locale instead of silently using English',()=>{
 const french=custom.replace('version="1.0"','default-locale="fr-FR" version="1.0"');
 assert.throws(()=>formatReference(paper,'custom',{styleXml:french}),/locale/i);
 const locale='<locale xmlns="http://purl.org/net/xbiblio/csl" xml:lang="fr-FR" version="1.0"><terms><term name="and">et</term></terms></locale>';
 assert.equal(formatReference(paper,'custom',{styleXml:french,localeXml:locale}).text,'CUSTOM: A careful test of retrieval');
});
