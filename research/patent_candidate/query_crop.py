"""R2 experiment: query-disagreement crop selection with explicit evidence scope.

This is a bounded finite-hypothesis experiment, not an OCR correctness guarantee
or a claim of invention. Hypotheses and action observations must be supplied by
an upstream recognizer. It does not manufacture OCR confidence or completeness.
"""
from dataclasses import dataclass
from itertools import combinations
import math
from research.patent_candidate.raster_cost import raster_pixels


@dataclass(frozen=True)
class Cell:
    id: str
    rect: tuple[float,float,float,float]


@dataclass(frozen=True)
class Reading:
    id: str
    # Each hypothesis assigns recognized text to fixed physical image cells.
    text: tuple[tuple[str,str],...]
    field_cell: str
    amount_cell: str

    def values(self):return dict(self.text)

    def matches(self,field,value):
        from knowledge_library.bill_amounts import money
        values=self.values()
        label=values[self.field_cell].strip().casefold()
        if label!=field:return False
        try:return money(values[self.amount_cell])==money(value)
        except ValueError:return False


class CropQuery:
    def __init__(self,cells,readings,field,value,*,revision,max_hypotheses=256):
        if not readings or len(readings)>max_hypotheses:
            raise ValueError('Finite hypothesis budget exceeded or empty input')
        self.cells={c.id:c for c in cells}
        if len(self.cells)!=len(cells):raise ValueError('Duplicate cell')
        self.readings=list(readings)
        if len({r.id for r in readings})!=len(readings):raise ValueError('Duplicate reading')
        for cell in cells:
            x0,y0,x1,y1=cell.rect
            if not all(math.isfinite(x) for x in cell.rect) or x1<=x0 or y1<=y0:
                raise ValueError('Invalid region')
        expected=set(self.cells)
        for r in readings:
            if len(r.text)!=len(expected) or set(r.values())!=expected:
                raise ValueError('Hypotheses must cover the same physical cells')
            if r.field_cell not in expected or r.amount_cell not in expected:
                raise ValueError('Missing anchor')
        if field not in ('subtotal','total'):raise ValueError('Unsupported field')
        from knowledge_library.bill_amounts import money
        money(value)
        self.field,self.value,self.revision=field,value,revision
        self.conflict=False

    def status(self):
        if self.conflict:return 'conflicting_evidence'
        outcomes={r.matches(self.field,self.value) for r in self.readings}
        if len(outcomes)>1:return 'ambiguous'
        return 'candidate_match' if True in outcomes else 'candidate_nonmatch'

    def plan(self,*,scale=3.,pixel_budget=1_000_000):
        if not math.isfinite(scale) or scale<=0 or type(pixel_budget) is not int or pixel_budget<0:
            raise ValueError('Invalid raster budget')
        if self.status()!='ambiguous':return None
        candidates={}
        # Deliberately bounded O(H^2*C). Every action contains both the physical
        # field-label and value anchors of the counterexample pair, plus cells
        # where their recognized text differs. Query guidance alone is known art.
        for a,b in combinations(self.readings,2):
            if a.matches(self.field,self.value)==b.matches(self.field,self.value):continue
            av,bv=a.values(),b.values()
            needed={a.field_cell,a.amount_cell,b.field_cell,b.amount_cell}
            needed|={key for key in self.cells if av[key]!=bv[key]}
            rect=(min(self.cells[x].rect[0] for x in needed),
                  min(self.cells[x].rect[1] for x in needed),
                  max(self.cells[x].rect[2] for x in needed),
                  max(self.cells[x].rect[3] for x in needed))
            covered=tuple(sorted(key for key,c in self.cells.items()
                if rect[0]<=c.rect[0] and rect[1]<=c.rect[1] and rect[2]>=c.rect[2] and rect[3]>=c.rect[3]))
            pixels=raster_pixels(rect,scale)
            if not pixels or pixels>pixel_budget:continue
            # Partition by hypothetical observed cell strings. A reread may still
            # be ambiguous: no assumption that the recognizer is a perfect oracle.
            groups={}
            for r in self.readings:
                key=tuple(r.values()[c] for c in covered)
                groups.setdefault(key,[]).append(r)
            worst=max(self._disagreements(group) for group in groups.values())
            gain=self._disagreements(self.readings)-worst
            if gain<=0:continue
            candidate=dict(rect=rect,cells=covered,pixels=pixels,revision=self.revision,
                worst_disagreement_reduction=gain)
            candidates[covered]=candidate
        if not candidates:return None
        return max(candidates.values(),key=lambda p:(p['worst_disagreement_reduction']/p['pixels'],-p['pixels'],p['cells']))

    def _disagreements(self,readings):
        yes=sum(r.matches(self.field,self.value) for r in readings)
        return yes*(len(readings)-yes)

    def observe(self,plan,observed,*,revision):
        if revision!=self.revision or plan['revision']!=self.revision:
            raise ValueError('Stale source revision')
        # Never treat an absent/partial label as if the whole planned crop was read.
        if set(observed)!=set(plan['cells']):
            raise ValueError('Incomplete crop observation')
        if self.conflict:raise ValueError('Replace hypothesis generation after conflict')
        survivors=[r for r in self.readings if all(r.values()[k] in options for k,options in observed.items())]
        if not survivors:
            self.conflict=True
            # Preserve old readings for diagnostics; never use vacuous all([])
            # to report a match/nonmatch after contradictory recognition output.
            return self.status()
        self.readings=survivors
        return self.status()
