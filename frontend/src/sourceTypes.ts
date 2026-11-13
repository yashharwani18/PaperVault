export type SourceLocation={kind:string;label:string;sheet?:string;row_start?:number;row_end?:number};
export type SourceInfo={source_kind?:'pdf'|'presentation'|'text'|'spreadsheet';source_format?:string;preview_kind?:'pdf'|'text';unit_count?:number};
export type LocatedSource=SourceInfo&{source_info?:SourceInfo;filename?:string;page_number?:number;unit_number?:number;location?:SourceLocation|string;location_label?:string};
export type ImportCapabilities={upload_extensions:string[];folder_extensions:string[];scan_extensions:string[];share_extensions:string[]};
export function sourceInfo(source:LocatedSource):SourceInfo{return {...source,...source.source_info};}
export function isTextSource(source:LocatedSource){return sourceInfo(source).preview_kind==='text';}
export function locationLabel(source:LocatedSource){
 if(source.location_label)return source.location_label;
 if(typeof source.location==='string')return source.location;
 if(source.location?.label)return source.location.label;
 const info=sourceInfo(source),number=source.unit_number??source.page_number??1;
 if(info.preview_kind==='text')return `Section ${number}`;
 return `${info.source_kind==='presentation'||/\.pptx?$/i.test(source.filename||'')?'Slide':'PDF page'} ${number}`;
}
export function unitCountLabel(source:LocatedSource&{page_count:number}){
 const info=sourceInfo(source),count=info.unit_count??source.page_count;
 return `${count} ${info.preview_kind==='text'?'source sections':info.source_kind==='presentation'||/\.pptx?$/i.test(source.filename||'')?'slides':'pages'}`;
}
export function importCapabilities(value:ImportCapabilities|undefined,android:boolean,powerpoint:boolean):ImportCapabilities{
 return value??{upload_extensions:android?['pdf','pptx']:powerpoint?['pdf','ppt','pptx']:['pdf'],folder_extensions:android?['pdf','pptx']:powerpoint?['pdf','ppt','pptx']:['pdf'],scan_extensions:['pdf'],share_extensions:android?['pdf']:[]};
}
