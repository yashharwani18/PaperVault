import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sortDocuments,initialLetter} from '../src/libraryBrowse.ts';
const docs=[{id:'b',filename:'Lecture 10.pdf',created_at:'2026-01-02',size_bytes:10,status:'indexed'}, {id:'a',filename:'Lecture 2.pdf',created_at:'2026-01-01',size_bytes:100,status:'indexed'}, {id:'c',filename:'2 Introduction.pdf',created_at:'',size_bytes:20,status:'partial'}];
test('natural filename sort is stable and numeric',()=>{assert.deepEqual(sortDocuments(docs,'name').map(d=>d.filename),['2 Introduction.pdf','Lecture 2.pdf','Lecture 10.pdf']);});
test('date added uses creation time and puts unknown dates last',()=>{assert.deepEqual(sortDocuments(docs,'added_old').map(d=>d.id),['a','b','c']);assert.deepEqual(sortDocuments(docs,'added_new').map(d=>d.id),['b','a','c']);});
test('file size sorting and alphabetical groups',()=>{assert.deepEqual(sortDocuments(docs,'size_large').map(d=>d.id),['a','c','b']);assert.equal(initialLetter('2 Introduction.pdf'),'#');assert.equal(initialLetter('Lecture 2.pdf'),'L');});

test('date sorting handles subsecond ISO timestamps and invalid metadata',()=>{
 const values=[{id:'fraction',filename:'b',created_at:'2026-01-01T00:00:00.100Z',size_bytes:1,status:'indexed'},{id:'whole',filename:'a',created_at:'2026-01-01T00:00:00Z',size_bytes:1,status:'indexed'},{id:'bad',filename:'c',created_at:'not a date',size_bytes:1,status:'indexed'}];
 assert.deepEqual(sortDocuments(values,'added_old').map(d=>d.id),['whole','fraction','bad']);
});
