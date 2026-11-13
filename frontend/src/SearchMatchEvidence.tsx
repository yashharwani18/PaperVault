import {describeEvidence} from './searchEvidence';
import type {EvidenceHit} from './searchEvidence';

export default function SearchMatchEvidence({hit}:{hit:EvidenceHit}){
 const evidence=describeEvidence(hit);
 if(!evidence)return null;
 return <div className={`match-evidence ${evidence.tone}`} aria-label="Why this bill matched"><strong>{evidence.label}</strong><p>{evidence.detail}</p></div>;
}
