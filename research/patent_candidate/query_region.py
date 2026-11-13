"""R11 exact finite-rectangle planning control, not a source recognizer.

Action rectangles and a nominal perfect matching are supplied. A plan is only
conditional: observations must actually determine the predicate before it can
be returned as graph-level agreement. At most eight observation actions.
Ordinary rectangle enumeration and matching are deliberately transparent controls.
"""
import hashlib
from itertools import product
import json
import math

from research.patent_candidate.assignment_evidence import AssignmentEvidence
from research.patent_candidate.raster_cost import raster_pixels


def union_box(boxes):
    boxes=list(boxes)
    return (min(b[0] for b in boxes),min(b[1] for b in boxes),
            max(b[2] for b in boxes),max(b[3] for b in boxes))


def pixels(rect,scale):
    return raster_pixels(rect,scale)


class QueryRegion:
    def __init__(self,evidence,nominal,actions):
        if not set(actions).issubset(evidence.domains) or len(actions)>8:
            raise ValueError('Control supports at most eight known field actions')
        if set(nominal)!=set(evidence.domains) or len(set(nominal.values()))!=len(nominal):
            raise ValueError('Nominal assignment must be a perfect matching')
        if any(nominal[f] not in evidence.domains[f] for f in nominal):
            raise ValueError('Nominal assignment is outside supplied domains')
        for rect in actions.values():
            if len(rect)!=4 or not all(math.isfinite(x) for x in rect) or rect[2]<=rect[0] or rect[3]<=rect[1]:
                raise ValueError('Invalid action region')
        self.evidence=evidence;self.nominal=dict(nominal);self.actions=dict(actions)

    def identity(self,field,targets):
        raw=[self.evidence.fingerprint(),self.evidence.field_boxes,self.evidence.value_boxes,
             self.nominal,self.actions,field,sorted(targets)]
        return hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()

    def after(self,field,targets,observations):
        if self.evidence.conflict:return dict(status='conflicting_evidence')
        domains={f:set(d) for f,d in self.evidence.domains.items()}
        for f,value in observations.items():
            if f not in self.actions or value not in self.evidence.value_boxes:
                raise ValueError('Observation must identify a known field/value relation')
            domains[f]&={value}
        probe=AssignmentEvidence(domains,self.evidence.field_boxes,self.evidence.value_boxes,
                                 revision=self.evidence.revision)
        return probe.decide(field,targets)

    def conditional_agreement(self,field,targets,fields):
        expected='candidate_match' if self.nominal[field] in targets else 'candidate_nonmatch'
        return self.after(field,targets,{f:self.nominal[f] for f in fields})['status']==expected

    def plan(self,field,targets,*,scale=1,pixel_budget=1_000_000):
        targets=set(targets)
        if not math.isfinite(scale) or scale<=0 or type(pixel_budget) is not int or pixel_budget<0:
            raise ValueError('Invalid raster allowance')
        decision=self.after(field,targets,{})
        if decision['status']!='ambiguous':
            return dict(status='no_observation_plan',decision=decision['status'])
        boxes=list(self.actions.values())
        if not boxes:return dict(status='no_admitted_plan')
        # An optimal nonempty rectangle is tight on the boxes of its contained
        # actions. Enumerate their finite boundary coordinates, not assignments.
        coordinates=[sorted({b[i] for b in boxes}) for i in range(4)]
        rectangles={r for r in product(*coordinates) if r[0]<r[2] and r[1]<r[3]}
        rectangles=sorted(rectangles,key=lambda r:(pixels(r,scale),r))
        tested=0;memo={}
        for rect in rectangles:
            cost=pixels(rect,scale)
            if not cost:continue  # A collapsed raster cannot supply an observation.
            if cost>pixel_budget:break
            fields=tuple(sorted(f for f,b in self.actions.items()
                                if rect[0]<=b[0] and rect[1]<=b[1] and rect[2]>=b[2] and rect[3]>=b[3]))
            if not fields:continue
            if fields not in memo:
                memo[fields]=self.conditional_agreement(field,targets,fields);tested+=1
            if memo[fields]:
                return dict(status='conditional_plan',field=field,targets=sorted(targets),
                    rect=rect,pixels=cost,fields=fields,expected={f:self.nominal[f] for f in fields},
                    revision=self.evidence.revision,identity=self.identity(field,targets),
                    tested_action_sets=tested,scope='Supplied matching domains and full-relation action supports only')
        return dict(status='no_admitted_plan',tested_action_sets=tested)

    def observe(self,plan,observations,*,revision):
        if plan.get('status')!='conditional_plan':raise ValueError('No conditional plan')
        field,targets=plan['field'],set(plan['targets'])
        if revision!=self.evidence.revision or plan['revision']!=revision or plan['identity']!=self.identity(field,targets):
            raise ValueError('Stale source, action geometry or hypothesis state')
        if set(observations)!=set(plan['fields']):raise ValueError('Incomplete observation set')
        result=self.after(field,targets,observations)
        return dict(status=result['status'],nominal_agreement=observations==plan['expected'],
                    scope='Graph-level agreement only; source/recognizer completeness not established')
