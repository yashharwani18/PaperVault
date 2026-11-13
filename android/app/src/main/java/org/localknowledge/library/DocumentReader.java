package org.localknowledge.library;

import android.content.Context;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.graphics.pdf.PdfRenderer;
import android.os.ParcelFileDescriptor;
import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.*;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader;
import com.tom_roush.pdfbox.pdmodel.PDDocument;
import com.tom_roush.pdfbox.pdmodel.PDPage;
import com.tom_roush.pdfbox.io.MemoryUsageSetting;
import com.tom_roush.pdfbox.text.PDFTextStripper;
import com.tom_roush.pdfbox.text.TextPosition;
import org.json.*;
import org.xmlpull.v1.*;
import android.util.Xml;
import java.io.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.zip.*;

final class DocumentReader {
    interface Consumer { void page(int number,int count,String text,String method,JSONArray words,JSONArray warnings,int rotation,float width,float height)throws Exception; }
    final Context context;
    DocumentReader(Context context){this.context=context;PDFBoxResourceLoader.init(context);}

    static class Stripper extends PDFTextStripper {
        JSONArray words=new JSONArray();int row=0;
        interface PageSink {void accept(int number,PDPage page,String text,JSONArray words)throws Exception;}
        PageSink sink;StringWriter pageText;int nextPage;
        Stripper()throws IOException{setSortByPosition(false);}
        void read(PDDocument doc,PageSink consumer)throws Exception {
            sink=consumer;pageText=new StringWriter();nextPage=1;
            try{writeText(doc,pageText);while(nextPage<=doc.getNumberOfPages())emit(nextPage,doc.getPage(nextPage-1),"",new JSONArray());}
            catch(PageFailure failure){throw (Exception)failure.getCause();}
            finally{sink=null;pageText=null;}
        }
        void emit(int number,PDPage page,String text,JSONArray positions)throws IOException {
            try{sink.accept(number,page,text,positions);nextPage=number+1;}
            catch(RuntimeException error){throw error;}
            catch(Exception error){throw new PageFailure(error);}
        }
        @Override public void processPage(PDPage page)throws IOException {
            if(sink==null){super.processPage(page);return;}
            int number=getCurrentPageNo();
            // PDFBox skips pages without content streams; preserve their positions.
            while(nextPage<number)emit(nextPage,document.getPage(nextPage-1),"",new JSONArray());
            words=new JSONArray();row=0;pageText.getBuffer().setLength(0);
            super.processPage(page);
            emit(number,page,pageText.toString(),words);pageText.getBuffer().setLength(0);
        }
        @Override protected void writeString(String text,List<TextPosition> positions)throws IOException {
            StringBuilder word=new StringBuilder();float x0=0,y0=0,x1=0,y1=0,last=0;
            for(TextPosition p:positions){String value=p.getUnicode();float x=p.getXDirAdj(),y=p.getYDirAdj(),right=x+p.getWidthDirAdj(),height=p.getHeightDir();
                if(value.trim().isEmpty()||(word.length()>0&&x-last>Math.max(3,height*.5f))){if(word.length()>0){words.put(Json.arr(x0,y0,x1,y1,word.toString(),0,row,0));word.setLength(0);}}
                if(!value.trim().isEmpty()){if(word.length()==0){x0=x;y0=y-height;x1=right;y1=y;}else{x0=Math.min(x0,x);y0=Math.min(y0,y-height);x1=Math.max(x1,right);y1=Math.max(y1,y);}word.append(value);}last=right;}
            if(word.length()>0)words.put(Json.arr(x0,y0,x1,y1,word.toString(),0,row,0));row++;
            super.writeString(text,positions);
        }
    }
    static final class PageFailure extends IOException {PageFailure(Exception cause){super(cause);}}

    void pdf(File file,boolean ocr,Consumer consumer)throws Exception {
        pdf(file,ocr,false,consumer);
    }
    void pdf(File file,boolean ocr,boolean forceOcr,Consumer consumer)throws Exception {
        try(PDDocument doc=PDDocument.load(file,MemoryUsageSetting.setupTempFileOnly().setTempDir(context.getCacheDir()))){
            if(doc.isEncrypted())throw new IllegalArgumentException("Password-protected PDF: export an unlocked copy first.");
            if(doc.getNumberOfPages()>2000)throw new IllegalArgumentException("This PDF exceeds the 2,000-page import limit.");
            final PdfRenderer[] renderer={null};final ParcelFileDescriptor[] descriptor={null};final TextRecognizer[] recognizer={null};
            try {
                new Stripper().read(doc,(number,page,extracted,positions)->{
                    String text=extracted;JSONArray words=positions,warnings=new JSONArray();String method="native";
                    float width=page.getCropBox().getWidth(),height=page.getCropBox().getHeight();
                    boolean image=page.getResources()!=null&&page.getResources().getXObjectNames().iterator().hasNext();
                    boolean sparse=text.replaceAll("[^\\p{L}\\p{N}]","").length()<40;
                    if(ocr&&(forceOcr||(image&&sparse))){
                        if(renderer[0]==null){descriptor[0]=ParcelFileDescriptor.open(file,ParcelFileDescriptor.MODE_READ_ONLY);renderer[0]=new PdfRenderer(descriptor[0]);recognizer[0]=TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);}
                        try(PdfRenderer.Page rendered=renderer[0].openPage(number-1)){
                            double scale=Math.min(200.0/72,Math.sqrt(6_000_000.0/((double)rendered.getWidth()*rendered.getHeight())));
                            int w=(int)Math.floor(rendered.getWidth()*scale),h=(int)Math.floor(rendered.getHeight()*scale);
                            Bitmap bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.WHITE);
                            try{rendered.render(bitmap,null,null,PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                                Text read=Tasks.await(recognizer[0].process(InputImage.fromBitmap(bitmap,0)),60,TimeUnit.SECONDS);
                                if(!read.getText().trim().isEmpty()){
                                    text=read.getText();words=new JSONArray();int block=0;
                                    for(Text.TextBlock b:read.getTextBlocks()){int line=0;for(Text.Line l:b.getLines()){int n=0;for(Text.Element element:l.getElements()){
                                        Rect r=element.getBoundingBox();if(r!=null)words.put(Json.arr(r.left/scale,r.top/scale,r.right/scale,r.bottom/scale,element.getText(),block,line,n++));}line++;}block++;}
                                    method="ocr";width=rendered.getWidth();height=rendered.getHeight();warnings.put("OCR reading; check the original. Character alternatives and calibrated confidence are unavailable.");
                                }else warnings.put("OCR found no text. Review the source.");
                            }finally{bitmap.recycle();}
                        }
                    }else if(sparse&&image)warnings.put("This page may need OCR. Refresh with OCR enabled.");
                    if(page.getRotation()!=0)warnings.put("Rotated page: field association needs review.");
                    consumer.page(number,doc.getNumberOfPages(),text,method,words,warnings,method.equals("ocr")?0:page.getRotation(),width,height);
                });
            }finally{if(recognizer[0]!=null)recognizer[0].close();if(renderer[0]!=null)renderer[0].close();if(descriptor[0]!=null)descriptor[0].close();}
        }
    }

    List<String> slideTexts(File file)throws Exception {
        try(ZipFile zip=new ZipFile(file)){
            long expanded=0;int entries=0;Enumeration<? extends ZipEntry> items=zip.entries();
            while(items.hasMoreElements()){ZipEntry entry=items.nextElement();if(++entries>10000)throw new IllegalArgumentException("PPTX has too many archive entries");long size=entry.getSize();if(size<0||size>50_000_000)throw new IllegalArgumentException("PPTX entry exceeds safe extraction size");expanded+=size;if(expanded>150_000_000)throw new IllegalArgumentException("PPTX expanded content is too large");}
            Map<String,String> relationships=new HashMap<>();
            try(InputStream in=zip.getInputStream(zip.getEntry("ppt/_rels/presentation.xml.rels"))){XmlPullParser p=parser(in);while(p.next()!=XmlPullParser.END_DOCUMENT)if(p.getEventType()==XmlPullParser.START_TAG&&p.getName().equals("Relationship"))relationships.put(p.getAttributeValue(null,"Id"),p.getAttributeValue(null,"Target"));}
            List<String> names=new ArrayList<>();
            try(InputStream in=zip.getInputStream(zip.getEntry("ppt/presentation.xml"))){XmlPullParser p=parser(in);while(p.next()!=XmlPullParser.END_DOCUMENT)if(p.getEventType()==XmlPullParser.START_TAG&&p.getName().equals("sldId")){
                String id=p.getAttributeValue("http://schemas.openxmlformats.org/officeDocument/2006/relationships","id");String target=relationships.get(id);if(target==null||target.contains(".."))throw new IllegalArgumentException("Unsupported slide relationship");names.add(target.startsWith("/")?target.substring(1):"ppt/"+target);}}
            if(names.size()>2000)throw new IllegalArgumentException("Presentation exceeds 2,000 slides");
            List<String> texts=new ArrayList<>();for(String name:names){ZipEntry entry=zip.getEntry(name);if(entry==null)throw new IllegalArgumentException("Missing slide content");StringBuilder text=new StringBuilder();
                try(InputStream in=zip.getInputStream(entry)){XmlPullParser p=parser(in);while(p.next()!=XmlPullParser.END_DOCUMENT){if(p.getEventType()==XmlPullParser.START_TAG&&p.getName().equals("t"))text.append(p.nextText()).append(' ');else if(p.getEventType()==XmlPullParser.END_TAG&&p.getName().equals("p"))text.append('\n');}}
                texts.add(text.toString());}
            return texts;
        }
    }
    void plainText(File original,Consumer consumer)throws Exception {
        List<String> sections=PlainTextDocument.read(original);
        for(int i=0;i<sections.size();i++)consumer.page(i+1,sections.size(),sections.get(i),"text",new JSONArray(),Json.arr("Plain text extraction; verify formatting in the original file."),0,0,0);
    }
    private XmlPullParser parser(InputStream input)throws Exception {XmlPullParser parser=Xml.newPullParser();parser.setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES,true);parser.setInput(input,"UTF-8");return parser;}
    void pptx(File original,File preview,Consumer consumer)throws Exception {
        List<String> slides=slideTexts(original);if(slides.isEmpty())throw new IllegalArgumentException("Presentation has no slides");
        PdfDocument pdf=new PdfDocument();try{
            Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);paint.setTextSize(12);paint.setColor(Color.BLACK);
            for(int i=0;i<slides.size();i++){
                PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,i+1).create());Canvas canvas=page.getCanvas();
                canvas.drawColor(Color.WHITE);canvas.drawText("Slide "+(i+1)+" — text preview; original layout is in the PPTX",25,30,paint);
                String text=slides.get(i);List<String> lines=new ArrayList<>();for(String line:text.split("\\n")){String current="";for(String word:line.split("\\s+")){if(paint.measureText(current+" "+word)>540&&!current.isEmpty()){lines.add(current);current=word;}else current+=(current.isEmpty()?"":" ")+word;}lines.add(current);}
                // Every indexed slide remains complete; the preview explicitly flags overflow.
                float y=55;for(String line:lines){if(y>810){canvas.drawText("More text is indexed. Open the original PPTX for all content.",25,825,paint);break;}canvas.drawText(line,25,y,paint);y+=16;}
                pdf.finishPage(page);
                consumer.page(i+1,slides.size(),text,"pptx",new JSONArray(),Json.arr("PPTX text extraction. Images, charts and original slide layout require checking the original deck."),0,595,842);
            }
            try(OutputStream out=new FileOutputStream(preview)){pdf.writeTo(out);}
        }finally{pdf.close();}
    }
}
