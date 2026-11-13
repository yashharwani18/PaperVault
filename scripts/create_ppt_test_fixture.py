"""Small native-text PPTX used only to verify actual local slide import."""
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches,Pt
root=Path(__file__).resolve().parents[1];out=root/'tests/fixtures/presentations';out.mkdir(parents=True,exist_ok=True)
deck=Presentation();deck.slide_width=Inches(12);deck.slide_height=Inches(6.75)
for index,(title,body) in enumerate([
 ('Theory of computation','SOFTWARE TEST FIXTURE\nFinite automata recognize regular languages.\nDeterministic and nondeterministic finite automata have the same expressive power.'),
 ('Hidden slide must retain its number','SOFTWARE TEST FIXTURE\nThis deliberately hidden slide verifies page numbering.'),
 ('Pumping lemma for regular languages','SOFTWARE TEST FIXTURE\nTo prove a language is not regular, assume it is regular and apply the pumping lemma.\nFor a sufficiently long word split w = xyz, every pumped word xy^i z must remain in the language.\nFind a decomposition-independent contradiction.')]):
 slide=deck.slides.add_slide(deck.slide_layouts[1]);slide.shapes.title.text=title;slide.placeholders[1].text=body
 for shape in slide.shapes:
  if shape.has_text_frame:
   for paragraph in shape.text_frame.paragraphs:
    for run in paragraph.runs:run.font.size=Pt(25 if shape!=slide.shapes.title else 36)
 if index==1:slide._element.set('show','0')
deck.save(out/'college-toc-test.pptx');print(out/'college-toc-test.pptx')
