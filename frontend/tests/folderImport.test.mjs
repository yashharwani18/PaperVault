import {test} from 'node:test';
import assert from 'node:assert/strict';
import {scanFolder} from '../src/folderImport.ts';
function file(path){const f=new File(['test'],path.split('/').at(-1));Object.defineProperty(f,'webkitRelativePath',{value:path});return f;}
const inventory=['College/notes.PDF','College/slides.pptx','College/Week 2/slides.pptx','College/Week 2/old.ppt','College/readme.txt','College/photo.png','College/~$slides.pptx','College/.hidden.pdf'].map(file);
test('recursive folder scan filters files without uploading their contents',()=>{
 const result=scanFolder(inventory,true,true);assert.equal(result.name,'College');assert.equal(result.files.length,4);assert.equal(result.ignored,4);assert.equal(result.outsideScope,0);
});
test('subfolder switch restricts scope to the selected folder',()=>{
 const result=scanFolder(inventory,false,true);assert.deepEqual(result.files.map(f=>f.name),['notes.PDF','slides.pptx']);assert.equal(result.outsideScope,2);
});
test('same filename in different subfolders remains independently selectable',()=>{
 const result=scanFolder(inventory,true,true,new Set(['College/slides.pptx']));assert.equal(result.files.length,3);assert(result.files.some(f=>f.webkitRelativePath==='College/Week 2/slides.pptx'));
});
test('PowerPoint availability is explicit and unsupported formats stay out',()=>{
 const result=scanFolder(inventory,true,false);assert.deepEqual(result.files.map(f=>f.name),['notes.PDF']);assert.equal(result.unavailable,3);assert.equal(result.ignored,4);
});
test('folder with no compatible files is an empty review, not an upload',()=>{
 assert.equal(scanFolder([file('Empty/readme.txt')],true,true).files.length,0);assert.equal(scanFolder([],true,true).files.length,0);
});
test('native formats follow the backend capabilities and media stays excluded',()=>{
 const files=['Docs/notes.txt','Docs/book.DOCX','Docs/table.xlsx','Docs/sub/values.csv','Docs/photo.png','Docs/movie.mp4','Docs/audio.mp3','Docs/~$book.docx'].map(file);
 const allowed=['pdf','txt','docx','xlsx','csv'];
 assert.equal(scanFolder(files,true,allowed).files.length,4);
 assert.equal(scanFolder(files,true,allowed).ignored,4);
 assert.equal(scanFolder(files,false,allowed).files.length,3);
 assert.equal(scanFolder(files,true,['pdf','pptx']).files.length,0);
 assert.equal(scanFolder(files,true,allowed,new Set(['Docs/table.xlsx'])).files.length,3);
});
