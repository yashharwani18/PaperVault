export type EvidenceHit={
 source_available?:boolean;
 score_type?:string;
 invoice_match?:{requested_number:string;source:'page_text'|'saved_field'};
 amount_match?:{field:string;value:string;currency?:string|null;requested_value?:string;difference?:string;approximate?:boolean;verified?:boolean;association?:string};
};
export type SearchCoverage={documents:number;searchable:number;needs_attention:number};
const amountText=(value:string)=>Number.isFinite(Number(value))?Number(value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):value;

export function describeEvidence(hit:EvidenceHit):{label:string;detail:string;tone:'exact'|'nearby'}|null {
 const amount=hit.amount_match;
 if(amount){
  const field=amount.field==='subtotal'?'subtotal':'total';
  const actual=`${amount.currency?amount.currency+' ':''}${amountText(amount.value)}`;
  const difference=amount.difference??'0';
  const nearby=amount.approximate||Number(difference)!==0;
  const review=amount.association==='unresolved'?'The amount column needs review.':amount.verified&&hit.source_available!==false?'This field was reviewed against the source.':'This field has not been reviewed; check the original.';
  if(nearby){
   const delta=`${Number(difference)>0?'+':''}${amountText(difference)}`;
   return {label:`Nearby ${field}: ${actual}`,detail:`You searched for ${amountText(amount.requested_value??amount.value)}. Difference: ${delta}. This is not an exact match. ${review}`,tone:'nearby'};
  }
  return {label:`Exact ${field}: ${actual}`,detail:`Amount found in indexed source text. ${review}`,tone:'exact'};
 }
 if(hit.invoice_match)return {label:`Invoice number: ${hit.invoice_match.requested_number}`,detail:hit.invoice_match.source==='page_text'?'Identifier found in indexed page text. Check the original.':'Matched the saved invoice number; not confirmed in indexed page text.',tone:'exact'};
 return null;
}

export function coverageMessage(coverage:SearchCoverage|undefined,reading:boolean):string {
 if(!coverage)return reading?'Files are still being read. Search results may be incomplete.':'';
 if(!reading&&coverage.needs_attention===0&&coverage.searchable===coverage.documents)return '';
 return [`${coverage.searchable} of ${coverage.documents} files have searchable text.`,coverage.needs_attention?`${coverage.needs_attention} files need reading or review.`:'',reading?'Some files are still being read; results may be incomplete.':''].filter(Boolean).join(' ');
}
