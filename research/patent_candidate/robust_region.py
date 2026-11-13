"""R14 ordinary paired-MILP control for all-outcome query determination.

Two perfect matchings must have opposite query outcomes and agree on observed
fields. Feasibility supplies a counterexample; solver-reported infeasibility
supports determination only inside the supplied model. Not a formal proof
checker, source recognizer, mobile solver or novelty assertion.
"""
from itertools import product
import math

import numpy as np
from scipy.optimize import Bounds,LinearConstraint,milp
from scipy.sparse import coo_matrix

from research.patent_candidate.assignment_evidence import matching
from research.patent_candidate.query_region import pixels


def opposite_pair(evidence,field,targets,observed,*,time_limit=2):
    targets=set(targets);observed=set(observed)
    if field not in evidence.domains or not targets.issubset(evidence.value_boxes) or not observed.issubset(evidence.domains):
        raise ValueError('Unknown query or observed field')
    if len(evidence.domains)>16:raise ValueError('Research oracle supports at most sixteen fields')
    if not math.isfinite(time_limit) or time_limit<=0:raise ValueError('Invalid solver time limit')
    if evidence.conflict or matching(evidence.domains) is None:return dict(status='conflicting_evidence')
    edges=[(f,v) for f in sorted(evidence.domains) for v in sorted(evidence.domains[f])]
    count=len(edges);columns={edge:i for i,edge in enumerate(edges)}
    rr=[];cc=[];dd=[];rhs=[]
    def equation(terms,value):
        row=len(rhs)
        for col,coefficient in terms:rr.append(row);cc.append(col);dd.append(coefficient)
        rhs.append(value)
    for offset in (0,count):
        for f in evidence.domains:
            equation([(offset+columns[f,v],1) for v in evidence.domains[f]],1)
        for v in evidence.value_boxes:
            equation([(offset+i,1) for i,(f,u) in enumerate(edges) if u==v],1)
    equation([(i,1) for i,(f,v) in enumerate(edges) if f==field and v in targets],1)
    equation([(count+i,1) for i,(f,v) in enumerate(edges) if f==field and v in targets],0)
    for f in observed:
        for v in evidence.domains[f]:
            i=columns[f,v];equation([(i,1),(count+i,-1)],0)
    matrix=coo_matrix((dd,(rr,cc)),shape=(len(rhs),2*count)).tocsc()
    solved=milp(np.zeros(2*count),integrality=np.ones(2*count),bounds=Bounds(0,1),
                constraints=LinearConstraint(matrix,rhs,rhs),options={'time_limit':time_limit})
    if solved.status==2:return dict(status='determines_in_model',variables=2*count)
    if solved.status!=0 or solved.x is None:return dict(status='unknown_solver',solver_status=int(solved.status))
    bits=np.rint(solved.x)
    if not np.allclose(bits,solved.x,atol=1e-7,rtol=0) or not np.allclose(matrix@bits,rhs,atol=1e-7,rtol=0):
        return dict(status='unknown_solver',reason='Returned solution failed discrete constraint checks')
    worlds=[]
    for offset in (0,count):
        world={f:v for i,(f,v) in enumerate(edges) if bits[offset+i]==1}
        if len(world)!=len(evidence.domains) or len(set(world.values()))!=len(world):
            return dict(status='unknown_solver',reason='Invalid matching witness')
        worlds.append(world)
    if worlds[0][field] not in targets or worlds[1][field] in targets or any(worlds[0][f]!=worlds[1][f] for f in observed):
        return dict(status='unknown_solver',reason='Invalid disagreement witness')
    return dict(status='opposite_pair',yes=worlds[0],no=worlds[1],variables=2*count)


def plan_region(planner,field,targets,*,scale=1,pixel_budget=1_000_000,max_solver_calls=64,oracle=None):
    if not math.isfinite(scale) or scale<=0 or type(pixel_budget) is not int or pixel_budget<0:
        raise ValueError('Invalid raster allowance')
    if type(max_solver_calls) is not int or max_solver_calls<1:raise ValueError('Invalid solver call limit')
    targets=set(targets);decision=planner.after(field,targets,{})
    oracle=opposite_pair if oracle is None else oracle
    if decision['status']!='ambiguous':return dict(status='no_observation_plan',decision=decision['status'])
    boxes=list(planner.actions.values())
    if not boxes:return dict(status='no_admitted_plan')
    axes=[sorted({b[i] for b in boxes}) for i in range(4)]
    rectangles={r for r in product(*axes) if r[0]<r[2] and r[1]<r[3]}
    memo={};calls=0;unknown=False
    for rect in sorted(rectangles,key=lambda r:(pixels(r,scale),r)):
        cost=pixels(rect,scale)
        if not cost:continue
        if cost>pixel_budget:break
        observed=tuple(sorted(f for f,b in planner.actions.items()
                              if rect[0]<=b[0] and rect[1]<=b[1] and rect[2]>=b[2] and rect[3]>=b[3]))
        if not observed:continue
        if observed not in memo:
            if calls>=max_solver_calls:return dict(status='search_incomplete',solver_calls=calls)
            memo[observed]=oracle(planner.evidence,field,targets,observed);calls+=1
        outcome=memo[observed]['status']
        if outcome in ('unknown_solver','unknown_work_limit'):unknown=True;continue
        if outcome=='determines_in_model':
            return dict(status='robust_in_model_plan',field=field,targets=sorted(targets),fields=observed,
                rect=rect,pixels=cost,revision=planner.evidence.revision,identity=planner.identity(field,targets),
                solver_calls=calls,minimum_established=not unknown)
    return dict(status='search_incomplete' if unknown else 'no_admitted_plan',solver_calls=calls)


def observe_plan(planner,plan,observations,*,revision):
    if plan.get('status')!='robust_in_model_plan':raise ValueError('No robust model plan')
    field,targets=plan['field'],set(plan['targets'])
    if revision!=planner.evidence.revision or plan['revision']!=revision or plan['identity']!=planner.identity(field,targets):
        raise ValueError('Stale source or model state')
    if set(observations)!=set(plan['fields']):raise ValueError('Incomplete observation set')
    return planner.after(field,targets,observations)
