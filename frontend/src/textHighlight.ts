/** Return offsets only when the full evidence occurs verbatim in indexed text. */
export function highlightSpan(text:string,evidence:string):[number,number]|null{
 if(!evidence)return null;const start=text.indexOf(evidence);return start<0?null:[start,start+evidence.length];
}
