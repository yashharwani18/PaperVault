/** Offline references. No identifiers, metadata or custom styles leave this device. */
import CSL from 'citeproc';
import {DOMParser} from '@xmldom/xmldom';
import assets from '../citation-styles/bundle.js';

export type PaperItem = {
 id: string;
 type: string;
 title?: string;
 author?: {given?: string;family?: string;literal?: string}[];
 issued?: {'date-parts': number[][]};
 [key: string]: unknown;
};
export const REFERENCE_FORMATS = [
 {id:'apa',label:'APA 7th edition'},
 {id:'ieee',label:'IEEE'},
 {id:'mla',label:'MLA 9th edition'},
 {id:'chicago',label:'Chicago 18th edition (author–date)'},
 {id:'harvard',label:'Harvard · Cite Them Right'},
 {id:'vancouver',label:'NLM / Vancouver'},
 {id:'bibtex',label:'BibTeX (.bib)'},
 {id:'ris',label:'RIS (.ris)'},
 {id:'json',label:'CSL JSON (.json)'},
 {id:'custom',label:'Custom CSL style…'},
] as const;
const STYLE_FILES: Record<string,string> = {
 apa:'apa.csl',ieee:'ieee.csl',mla:'modern-language-association.csl',
 chicago:'chicago-author-date.csl',harvard:'harvard-cite-them-right.csl',vancouver:'nlm-citation-sequence.csl',
};
type Options = {styleXml?: string;localeXml?: string};
export type FormattedReference = {text: string;extension: string;mimeType: string};
const clean = (value: unknown) => typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f\u0085\u2028\u2029]+/g,' ').replace(/\s+/g,' ').trim() : '';
const textField = (item:PaperItem,key:string) => clean(item[key]);

function parseXml(xml:string,kind:'style'|'locale') {
 if(!xml?.trim())throw new Error(`Choose a ${kind === 'style' ? 'CSL style' : 'CSL locale'} file first.`);
 if(xml.length>750_000)throw new Error('The CSL file is too large (maximum 750 KB).');
 if(/<!DOCTYPE|<!ENTITY/i.test(xml))throw new Error('CSL files must not contain DOCTYPE declarations or entities.');
 let document;
 try {
  document = new DOMParser({onError:(_level,message)=>{throw new Error(message);}}).parseFromString(xml,'application/xml');
 } catch {throw new Error('Malformed CSL XML. Choose a valid CSL file.');}
 const root=document.documentElement;
 if(!root||root.localName!==kind||root.namespaceURI!=='http://purl.org/net/xbiblio/csl')throw new Error(`Choose a valid CSL ${kind} file.`);
 if(document.getElementsByTagName('*').length>16_000)throw new Error('The CSL file contains too many elements.');
 if(kind==='style'){
  const links=document.getElementsByTagNameNS('http://purl.org/net/xbiblio/csl','link');
  if(Array.from(links).some(link=>link.getAttribute('rel')==='independent-parent'))throw new Error('This is a dependent style. Upload its independent parent CSL style instead.');
  if(!document.getElementsByTagNameNS('http://purl.org/net/xbiblio/csl','bibliography').length)throw new Error('This CSL style has no bibliography. Choose an independent style that defines references.');
 }
 return document;
}

function escapedBib(value:string) {
 const escape:Record<string,string>={'\\':'\\textbackslash{}','{':'\\{','}':'\\}','&':'\\&','%':'\\%','$':'\\$','#':'\\#','_':'\\_','~':'\\textasciitilde{}','^':'\\textasciicircum{}'};
 return clean(value).replace(/[\\{}&%$#_~^]/g,char=>escape[char]);
}

function bibtex(item:PaperItem) {
 const type=item.type==='paper-conference'?'inproceedings':item.type==='book'?'book':item.type==='thesis'?'phdthesis':item.type==='article-journal'?'article':'misc';
 const year=item.issued?.['date-parts']?.[0]?.[0];
 const fields:[string,string][]=[['title',textField(item,'title')]];
 const authors=item.author?.map(a=>a.literal?`{${escapedBib(a.literal)}}`:[clean(a.family),clean(a.given)].filter(Boolean).map(escapedBib).join(', ')).filter(Boolean).join(' and ');
 if(authors)fields.push(['author',authors]);
 if(year)fields.push(['year',String(year)]);
 for(const [field,key] of [['journal','container-title'],['volume','volume'],['number','issue'],['pages','page'],['publisher','publisher'],['doi','DOI'],['url','URL']] as const){
  const value=textField(item,key);if(value)fields.push([field,value]);
 }
 const key=clean(item.id).replace(/[^A-Za-z0-9_-]/g,'').slice(0,100)||'reference';
 return `@${type}{${key},\n${fields.map(([key,value])=>`  ${key} = {${key==='author'?value:escapedBib(value)}}`).join(',\n')}\n}\n`;
}

function ris(item:PaperItem) {
 const kind=item.type==='paper-conference'?'CPAPER':item.type==='book'?'BOOK':item.type==='thesis'?'THES':item.type==='article-journal'?'JOUR':'GEN';
 const lines=[`TY  - ${kind}`,`TI  - ${textField(item,'title')}`];
 for(const author of item.author||[]){const name=author.literal?clean(author.literal):[clean(author.family),clean(author.given)].filter(Boolean).join(', ');if(name)lines.push(`AU  - ${name}`);}
 const date=item.issued?.['date-parts']?.[0];if(date?.[0])lines.push(`PY  - ${date.join('/')}`);
 for(const [field,key] of [['JO','container-title'],['VL','volume'],['IS','issue'],['PB','publisher'],['DO','DOI'],['UR','URL']] as const){const value=textField(item,key);if(value)lines.push(`${field}  - ${value}`);}
 const pages=textField(item,'page');if(pages){const [start,end]=pages.split(/[-–]/,2);lines.push(`SP  - ${start}`);if(end)lines.push(`EP  - ${end}`);}
 return [...lines,'ER  -',''].join('\n');
}

export function formatReference(input:PaperItem,format:string,options:Options={}):FormattedReference {
 if(!input||!clean(input.title))throw new Error('Add a paper title before creating a reference.');
 // CSL mutates some item fields during processing; never mutate saved metadata.
 const item=JSON.parse(JSON.stringify(input)) as PaperItem;
 item.id=clean(item.id)||'reference';item.type=clean(item.type)||'article-journal';
 if(format==='json')return {text:JSON.stringify([item],null,2)+'\n',extension:'json',mimeType:'application/json'};
 if(format==='bibtex')return {text:bibtex(item),extension:'bib',mimeType:'application/x-bibtex'};
 if(format==='ris')return {text:ris(item),extension:'ris',mimeType:'application/x-research-info-systems'};
 const style=format==='custom'?options.styleXml:assets[STYLE_FILES[format]];
 let styleLanguage='en-US';
 if(format==='custom')styleLanguage=parseXml(style||'','style').documentElement!.getAttribute('default-locale')||'en-US';
 else if(!style)throw new Error('Unsupported reference format. Choose one of the available styles.');
 let customLanguage='';
 if(options.localeXml){const doc=parseXml(options.localeXml,'locale');customLanguage=doc.documentElement!.getAttribute('xml:lang')||'';if(!customLanguage)throw new Error('The CSL locale must declare xml:lang.');}
 if(!styleLanguage.startsWith('en')&&customLanguage.split('-')[0]!==styleLanguage.split('-')[0])throw new Error(`This style requires the ${styleLanguage} CSL locale. Upload the matching locale XML as well.`);
 try {
  const processor=new CSL.Engine({
   retrieveLocale(language:string){
    if(options.localeXml&&(language===customLanguage||language.split('-')[0]===customLanguage.split('-')[0]))return options.localeXml;
    if(language==='en-GB')return assets['locales-en-GB.xml'];
    if(language==='en'||language==='en-US'||language==='us')return assets['locales-en-US.xml'];
    return false;
   },
   retrieveItem:()=>item,
  },style!,customLanguage||styleLanguage,true);
  processor.setOutputFormat('text');processor.updateItems([item.id]);
  const bibliography=processor.makeBibliography();
  if(!bibliography||!bibliography[1]?.length)throw new Error('No reference produced');
  return {text:bibliography[1].join('').trim(),extension:'txt',mimeType:'text/plain;charset=utf-8'};
 } catch {
  throw new Error('This CSL style could not format the reference. Check the metadata, or choose another independent CSL style and its required locale.');
 }
}
