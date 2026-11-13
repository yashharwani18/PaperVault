/** Recent queries are stored only in this device's browser storage. */
export function rememberSearch(history:readonly string[],query:string):string[]{
 const value=query.trim();if(!value)return [...history];
 return [value,...history.filter(item=>item.toLocaleLowerCase()!==value.toLocaleLowerCase())].slice(0,20);
}
export function readSearchHistory():string[]{
 try{const parsed:unknown=JSON.parse(localStorage.getItem('khoj.search.history')||'[]');return Array.isArray(parsed)?parsed.filter((value):value is string=>typeof value==='string'&&value.trim().length>0&&value.length<=4096).slice(0,20):[];}catch{return [];}
}
