import {test} from 'node:test';
import assert from 'node:assert/strict';
import {importCapabilities,isTextSource,locationLabel,unitCountLabel} from '../src/sourceTypes.ts';

test('native locators display actual sheet rows and sections',()=>{
 assert.equal(locationLabel({preview_kind:'text',page_number:2,location:{kind:'sheet_rows',label:'Accounts · rows 12–25',sheet:'Accounts',row_start:12,row_end:25}}),'Accounts · rows 12–25');
 assert.equal(locationLabel({source_info:{preview_kind:'text'},page_number:3}),'Section 3');
 assert.equal(unitCountLabel({preview_kind:'text',unit_count:4,page_count:4}),'4 source sections');
 assert(isTextSource({source_info:{source_kind:'spreadsheet',preview_kind:'text'}}));
});
test('existing PDF and presentation records retain truthful fallback labels',()=>{
 assert.equal(locationLabel({filename:'notes.pdf',page_number:7}),'PDF page 7');
 assert.equal(locationLabel({filename:'slides.pptx',page_number:2}),'Slide 2');
 assert.equal(unitCountLabel({filename:'slides.pptx',page_count:3}),'3 slides');
 assert(!isTextSource({filename:'notes.pdf'}));
});
test('older Android keeps its actual ingress capabilities; explicit state wins',()=>{
 const android=importCapabilities(undefined,true,true);
 assert.deepEqual(android.upload_extensions,['pdf','pptx']);
 assert.deepEqual(android.folder_extensions,['pdf','pptx']);
 assert.deepEqual(android.scan_extensions,['pdf']);
 assert.deepEqual(android.share_extensions,['pdf']);
 const desktop={upload_extensions:['pdf','txt','xlsx'],folder_extensions:['pdf','txt','xlsx'],scan_extensions:['pdf','txt','xlsx'],share_extensions:[]};
 assert.equal(importCapabilities(desktop,false,false),desktop);
 assert.deepEqual(importCapabilities(undefined,false,false).upload_extensions,['pdf']);
});
