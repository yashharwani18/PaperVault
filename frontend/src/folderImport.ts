/** Browser-granted folder inventory. File bytes are uploaded only after review. */
export type FolderSummary={name:string;files:File[];ignored:number;outsideScope:number;unavailable:number};
export function scanFolder(inventory:File[],recursive:boolean,supported:readonly string[]|boolean,excluded:ReadonlySet<string>=new Set()):FolderSummary{
 const extensions=typeof supported==='boolean'?(supported?['pdf','ppt','pptx']:['pdf']):supported;
 const path=(file:File)=>file.webkitRelativePath||file.name;
 const files:File[]=[];let ignored=0,outsideScope=0,unavailable=0;
 for(const file of inventory){
  const relative=path(file),parts=relative.split('/');
  if(!recursive&&parts.length>2){outsideScope++;continue;}
  const ext=file.name.toLowerCase().split('.').pop();
  if(file.name.startsWith('~$')||file.name.startsWith('.')){ignored++;continue;}
  if(typeof supported==='boolean'&&!supported&&['ppt','pptx'].includes(ext||'')){unavailable++;continue;}
  if(!extensions.includes(ext||'')){ignored++;continue;}
  if(!excluded.has(relative))files.push(file);
 }
 files.sort((a,b)=>path(a).localeCompare(path(b)));
 return {name:inventory[0]?.webkitRelativePath.split('/')[0]||'Selected folder',files,ignored,outsideScope,unavailable};
}
