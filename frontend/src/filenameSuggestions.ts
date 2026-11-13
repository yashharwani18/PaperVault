/** Conservative filename suggestions: content results always remain ahead of these. */
const words=(text:string)=>text.normalize('NFKC').toLocaleLowerCase().match(/[\p{L}\p{M}\p{N}]+/gu)||[];
function oneEdit(a:string,b:string){
 if(Math.abs(a.length-b.length)>1)return false;
 let i=0,j=0,edits=0;
 while(i<a.length&&j<b.length){if(a[i]===b[j]){i++;j++;continue;}if(++edits>1)return false;if(a.length>b.length)i++;else if(b.length>a.length)j++;else{i++;j++;}}
 return edits+Number(i<a.length||j<b.length)<=1;
}
export function filenameSuggestionScore(query:string,filename:string):number {
 const q=words(query),stem=filename.replace(/\.[^.]+$/,'');const name=words(stem);
 if(!q.length||q.length>6||q.some(token=>token.length<2)||!name.length)return 0;
 const used=new Set<number>();let score=0;
 for(const token of q){let best=0,index=-1;
  for(let i=0;i<name.length;i++){if(used.has(i))continue;const word=name[i];let value=0;
   if(token===word)value=1;
   else if(!/\d/u.test(token+word)&&token.length>=3&&word.startsWith(token))value=.82;
   else if(!/\d/u.test(token+word)&&token.length>=5&&word.length>=5&&oneEdit(token,word))value=.72;
   if(value>best){best=value;index=i;}
  }
  if(index<0)return 0;used.add(index);score+=best;
 }
 return score/q.length * Math.min(1,q.length/name.length+.35);
}
export function filenameSuggestions<T extends {id:string;filename:string}>(query:string,docs:readonly T[],excluded:ReadonlySet<string>,limit=5):T[]{
 return docs.filter(doc=>!excluded.has(doc.id)).map(doc=>({doc,score:filenameSuggestionScore(query,doc.filename)})).filter(item=>item.score>=.5).sort((a,b)=>b.score-a.score||a.doc.filename.localeCompare(b.doc.filename,undefined,{numeric:true,sensitivity:'base'})||a.doc.id.localeCompare(b.doc.id)).slice(0,limit).map(item=>item.doc);
}
