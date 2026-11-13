export type BrowseDocument={id:string;filename:string;created_at?:string|null;modified_at?:string|null;size_bytes:number;status:string};
export type BrowseSort='name'|'name_desc'|'added_new'|'added_old'|'modified_new'|'modified_old'|'size_large'|'size_small'|'type'|'recent'|'pages';
const collator=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
const compareText=(a:string,b:string)=>collator.compare(a,b);
const extension=(name:string)=>name.includes('.')?name.slice(name.lastIndexOf('.')+1).toLocaleLowerCase():'';
function compareOptional(a:string|null|undefined,b:string|null|undefined,descending:boolean){
 const left=a?Date.parse(a):NaN,right=b?Date.parse(b):NaN;
 if(!Number.isFinite(left)&&!Number.isFinite(right))return 0;
 if(!Number.isFinite(left))return 1;if(!Number.isFinite(right))return -1;
 return (descending?-1:1)*(left-right);
}
export function initialLetter(filename:string){
 const first=filename.trim().normalize('NFKC').charAt(0).toLocaleUpperCase();
 return /^[A-Z]$/.test(first)?first:'#';
}
export function sortDocuments<T extends BrowseDocument>(docs:readonly T[],sort:string,recent:readonly string[]=[]):T[]{
 const recentRank=new Map(recent.map((id,index)=>[id,index]));
 return [...docs].sort((a,b)=>{
  let order=0;
  switch(sort){
   case 'name':order=compareText(a.filename,b.filename);break;
   case 'name_desc':order=compareText(b.filename,a.filename);break;
   case 'added_old':order=compareOptional(a.created_at,b.created_at,false);break;
   case 'added_new':order=compareOptional(a.created_at,b.created_at,true);break;
   case 'modified_old':order=compareOptional(a.modified_at,b.modified_at,false);break;
   case 'modified_new':order=compareOptional(a.modified_at,b.modified_at,true);break;
   case 'size_large':order=b.size_bytes-a.size_bytes;break;
   case 'size_small':order=a.size_bytes-b.size_bytes;break;
   case 'type':order=compareText(extension(a.filename),extension(b.filename));break;
   case 'recent':order=(recentRank.get(a.id)??Number.MAX_SAFE_INTEGER)-(recentRank.get(b.id)??Number.MAX_SAFE_INTEGER);break;
  }
  // Database paging resolves added/size ties by the document id (SQLite BINARY),
  // so the in-memory list uses the same key and both paths stay in sync.
  if(order)return order;
  if(['added_new','added_old','size_large','size_small'].includes(sort))return a.id<b.id?-1:a.id>b.id?1:0;
  return compareText(a.filename,b.filename)||(a.id<b.id?-1:a.id>b.id?1:0);
 });
}
