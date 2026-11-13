"""R7 conventional matching control for factorized field-assignment ambiguity.

Only balanced one-to-one assignments with supplied domains are represented.
This is not an OCR recognizer, semantic search engine or invention assertion.
"""
from __future__ import annotations

import hashlib
import json
import math
from research.patent_candidate.raster_cost import raster_pixels


def matching(domains):
    """Ordinary augmenting-path matching; no interpretation enumeration."""
    owners={}
    def augment(field,seen):
        for value in sorted(domains[field]):
            if value in seen:continue
            seen.add(value)
            if value not in owners or augment(owners[value],seen):
                owners[value]=field
                return True
        return False
    for field in sorted(domains,key=lambda f:(len(domains[f]),f)):
        if not augment(field,set()):return None
    return {field:value for value,field in owners.items()}


class AssignmentEvidence:
    def __init__(self,domains,field_boxes,value_boxes,*,revision):
        if not domains or len(domains)>128 or len(domains)!=len(value_boxes):
            raise ValueError('Probe requires 1–128 fields and a balanced one-to-one value set')
        if set(domains)!=set(field_boxes):raise ValueError('Each field needs a source rectangle')
        self.domains={f:set(v) for f,v in domains.items()}
        if any(not v.issubset(value_boxes) for v in self.domains.values()):raise ValueError('Unknown value')
        self.field_boxes=dict(field_boxes);self.value_boxes=dict(value_boxes)
        for rect in [*field_boxes.values(),*value_boxes.values()]:
            if len(rect)!=4 or not all(math.isfinite(x) for x in rect) or rect[2]<=rect[0] or rect[3]<=rect[1]:
                raise ValueError('Invalid source rectangle')
        self.revision=revision;self.conflict=False

    def fingerprint(self):
        raw=json.dumps([self.revision,{f:sorted(v) for f,v in sorted(self.domains.items())}],sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def decide(self,field,targets):
        if field not in self.domains or not set(targets).issubset(self.value_boxes):raise ValueError('Unknown query anchor')
        if self.conflict:return dict(status='conflicting_evidence')
        base=matching(self.domains)
        if base is None:return dict(status='conflicting_evidence')
        targets=set(targets);yes=None
        if base[field] in targets:yes=base
        else:
            for value in sorted(self.domains[field]&targets):
                forced={f:({value} if f==field else d-{value}) for f,d in self.domains.items()}
                yes=matching(forced)
                if yes is not None:break
        avoided={f:(d-targets if f==field else d) for f,d in self.domains.items()}
        no=matching(avoided)
        status='ambiguous' if yes is not None and no is not None else 'candidate_match' if yes is not None else 'candidate_nonmatch'
        return dict(status=status,yes=yes,no=no,scope='Only assignments admitted by the supplied graph')

    def plan(self,field,targets,*,scale=3,pixel_budget=1_000_000):
        if not math.isfinite(scale) or scale<=0 or type(pixel_budget) is not int or pixel_budget<0:
            raise ValueError('Invalid raster budget')
        decision=self.decide(field,targets)
        if decision['status']!='ambiguous':return None
        yes,no=decision['yes'],decision['no'];inverse_no={v:f for f,v in no.items()}
        # A standard alternating cycle isolates one answer-changing witness.
        cycle=[];current=field
        while current not in cycle:
            cycle.append(current);current=inverse_no[yes[current]]
        if current!=field:raise AssertionError('Invalid perfect-matching cycle')
        values={yes[f] for f in cycle}|{no[f] for f in cycle}
        boxes=[self.field_boxes[f] for f in cycle]+[self.value_boxes[v] for v in values]
        rect=(min(r[0] for r in boxes),min(r[1] for r in boxes),max(r[2] for r in boxes),max(r[3] for r in boxes))
        pixels=raster_pixels(rect,scale)
        if not pixels or pixels>pixel_budget:return None  # Remains ambiguous.
        # Flip only this cycle. The other assignments are identical in the pair.
        opposite=dict(yes);opposite.update({f:no[f] for f in cycle})
        return dict(fields=tuple(sorted(cycle)),values=tuple(sorted(values)),rect=rect,pixels=pixels,
            revision=self.revision,fingerprint=self.fingerprint(),yes=yes,no=opposite,
            observation_required='Allowed field-to-value relations, not just reread character strings')

    def observe_relations(self,plan,allowed,*,revision):
        if revision!=self.revision or plan['revision']!=revision or plan['fingerprint']!=self.fingerprint():
            raise ValueError('Stale source or relation state')
        if self.conflict:raise ValueError('Rebuild hypotheses after conflicting evidence')
        if set(allowed)!=set(plan['fields']):raise ValueError('Incomplete relation observation')
        proposed={f:set(d) for f,d in self.domains.items()}
        for field,partners in allowed.items():
            partners=set(partners)
            if not partners.issubset(self.value_boxes):raise ValueError('Observation must identify value anchors')
            proposed[field]&=partners
        if matching(proposed) is None:
            self.conflict=True
            return 'conflicting_evidence'
        self.domains=proposed
        return 'updated'
