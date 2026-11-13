"""R7 representation experiment, with a component-local conventional control."""
from itertools import product
from pathlib import Path
import gc
import json
import time
import tracemalloc

from research.patent_candidate.assignment_evidence import AssignmentEvidence


def explicit_independent_swaps(n,fields,values):
    # Share the existing anchor IDs across all worlds, just as the graph does.
    # Creating repeated strings would unfairly inflate this control's memory.
    return [{fields[i]:values[(i-i%2)+((i%2)^bits[i//2])] for i in range(n)}
            for bits in product((0,1),repeat=n//2)]


def component_local_worlds():
    # All other components are satisfiable and independent in this fixture.
    return [{'f0':'v0','f1':'v1'},{'f0':'v1','f1':'v0'}]


def measured(build,decide):
    gc.collect();tracemalloc.start();start=time.perf_counter()
    object=build();status=decide(object)
    elapsed=time.perf_counter()-start
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return status,peak,elapsed,object


def run():
    root=Path(__file__).resolve().parents[2];rows=[]
    for n in (16,24,32):
        domains={f'f{i}':{f'v{i-i%2}',f'v{i-i%2+1}'} for i in range(n)}
        fboxes={f'f{i}':(0,i*20,20,i*20+10) for i in range(n)}
        vboxes={f'v{i}':(40,i*20,60,i*20+10) for i in range(n)}
        fields=list(domains);value_ids={v:v for d in domains.values() for v in d}
        values=[value_ids[f'v{i}'] for i in range(n)]
        def summarize(worlds):return 'ambiguous' if len({w['f0']=='v0' for w in worlds})==2 else 'not_ambiguous'
        exp=measured(lambda:explicit_independent_swaps(n,fields,values),summarize)
        graph=measured(lambda:AssignmentEvidence(domains,fboxes,vboxes,revision='fixture-r1'),lambda q:q.decide('f0',{'v0'})['status'])
        local=measured(component_local_worlds,summarize)
        assert exp[0]==graph[0]==local[0]=='ambiguous'
        assert len(exp[3])==2**(n//2)
        plan=graph[3].plan('f0',{'v0'})
        rows.append(dict(fields=n,graph_edges=sum(map(len,domains.values())),
            explicit_worlds=len(exp[3]),local_component_worlds=2,
            explicit_python_peak_bytes=exp[1],graph_python_peak_bytes=graph[1],local_python_peak_bytes=local[1],
            exploratory_elapsed_s=dict(explicit=exp[2],graph=graph[2],local=local[2]),
            query_status='ambiguous',witness_fields=plan['fields'],witness_values=plan['values'],
            witness_rect=plan['rect'],estimated_raster_pixels_at_scale3=plan['pixels']))
        del exp,graph,local
    report=dict(date='2026-10-21',cases=rows,
        method='Supplied synthetic one-to-one relations; Python tracemalloc, single observations, no real OCR/model/phone run.',
        interpretation='Known matching and component factorization eliminate an artificial global enumeration cost; no novelty claimed.',
        limits=['Local control exploits disjoint components and is not a general solver',
                'Graph excludes many-to-many links, missing nodes, OCR alternatives, arithmetic and semantic ranking',
                'Peaks measure additional allocations over prebuilt shared graph/anchor inputs, not total representation memory',
                'tracemalloc omits native allocations and is not process RSS or a hardware memory guarantee',
                'Witness crop demonstrates opposing feasible assignments, not guaranteed recognition or resolution'])
    (root/'results/patent-r7-assignment.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':run()
