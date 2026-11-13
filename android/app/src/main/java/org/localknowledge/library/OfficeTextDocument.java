package org.localknowledge.library;

import org.xmlpull.v1.XmlPullParser;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Text-only Office Open XML extraction, with bounded archives and no external entities. */
final class OfficeTextDocument {
    static final int MAX_ENTRY_BYTES=20*1024*1024,MAX_TEXT_CHARS=10*1024*1024,MAX_ENTRIES=10000,MAX_SECTIONS=2000;
    static final long MAX_EXPANDED=150L*1024*1024;
    static final String WORD="http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    static final String SHEET="http://schemas.openxmlformats.org/spreadsheetml/2006/main";
    static final String REL="http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    interface ParserFactory {XmlPullParser create()throws Exception;}
    static final class Section {
        final String text,sheet;final int rowStart,rowEnd;
        Section(String text,String sheet,int rowStart,int rowEnd){this.text=text;this.sheet=sheet;this.rowStart=rowStart;this.rowEnd=rowEnd;}
    }
    static boolean supports(String extension){return "docx".equalsIgnoreCase(extension)||"xlsx".equalsIgnoreCase(extension);}
    static List<Section> read(File file,String format,ParserFactory factory)throws Exception {
        try(ZipFile zip=new ZipFile(file)){
            validateArchive(zip);
            if(format.equalsIgnoreCase("docx"))return word(zip,factory);
            if(format.equalsIgnoreCase("xlsx"))return workbook(zip,factory);
            throw new IOException("Unsupported office document format.");
        }
    }
    private static void validateArchive(ZipFile zip)throws IOException {
        long total=0;int count=0;Set<String> seen=new HashSet<>();Enumeration<? extends ZipEntry> entries=zip.entries();
        while(entries.hasMoreElements()){
            ZipEntry e=entries.nextElement();if(++count>MAX_ENTRIES||!seen.add(e.getName()))throw new IOException("Office archive has too many or duplicate entries.");
            long size=e.getSize();if(size<0||size>50L*1024*1024)throw new IOException("Office archive entry exceeds the extraction limit.");
            total+=size;if(total>MAX_EXPANDED)throw new IOException("Office archive expanded content exceeds the extraction limit.");
        }
    }
    private static InputStream open(ZipFile zip,String name,boolean required)throws IOException {
        ZipEntry entry=zip.getEntry(name);if(entry==null){if(required)throw new IOException("Office document is missing required text data.");return null;}
        if(entry.isDirectory()||entry.getSize()<0||entry.getSize()>MAX_ENTRY_BYTES)throw new IOException("Office text data exceeds the extraction limit.");
        return new FilterInputStream(zip.getInputStream(entry)){
            long total=0;private void add(long n)throws IOException{if(n>0&&(total+=n)>MAX_ENTRY_BYTES)throw new IOException("Office text data exceeds the extraction limit.");}
            @Override public int read()throws IOException{int b=super.read();if(b>=0)add(1);return b;}
            @Override public int read(byte[] b,int off,int len)throws IOException{int n=super.read(b,off,len);add(n);return n;}
        };
    }
    private static XmlPullParser parser(ParserFactory factory,InputStream input)throws Exception {
        XmlPullParser parser=factory.create();parser.setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES,true);parser.setInput(input,null);return parser;
    }
    private static void checkToken(int type)throws IOException {if(type==XmlPullParser.DOCDECL)throw new IOException("Office XML document types are not supported.");}
    private static void append(StringBuilder out,String value)throws IOException {
        if(value==null)return;if((long)out.length()+value.length()>MAX_TEXT_CHARS)throw new IOException("Office document contains too much extractable text.");out.append(value);
    }
    private static List<Section> word(ZipFile zip,ParserFactory factory)throws Exception {
        StringBuilder out=new StringBuilder();boolean text=false;
        try(InputStream in=open(zip,"word/document.xml",true)){
            XmlPullParser p=parser(factory,in);int event;
            while((event=p.nextToken())!=XmlPullParser.END_DOCUMENT){checkToken(event);
                if(event==XmlPullParser.START_TAG&&WORD.equals(p.getNamespace())){
                    String name=p.getName();if(name.equals("t"))text=true;else if(name.equals("tab"))append(out,"\t");else if(name.equals("br")||name.equals("cr"))append(out,"\n");
                }else if((event==XmlPullParser.TEXT||event==XmlPullParser.ENTITY_REF)&&text)append(out,p.getText());
                else if(event==XmlPullParser.END_TAG&&WORD.equals(p.getNamespace())){if(p.getName().equals("t"))text=false;else if(p.getName().equals("p"))append(out,"\n");}
            }
        }
        List<Section> sections=new ArrayList<>();for(String textPart:PlainTextDocument.split(out.toString()))sections.add(new Section(textPart,null,0,0));return sections;
    }
    private static final class Relationship {String target,type;boolean external;}
    private static List<Section> workbook(ZipFile zip,ParserFactory factory)throws Exception {
        Map<String,Relationship> rels=new HashMap<>();
        try(InputStream in=open(zip,"xl/_rels/workbook.xml.rels",true)){
            XmlPullParser p=parser(factory,in);int event;while((event=p.nextToken())!=XmlPullParser.END_DOCUMENT){checkToken(event);if(event==XmlPullParser.START_TAG&&p.getName().equals("Relationship")){
                String id=p.getAttributeValue(null,"Id");if(id==null||rels.containsKey(id))throw new IOException("Invalid workbook relationship.");Relationship r=new Relationship();r.target=p.getAttributeValue(null,"Target");r.type=p.getAttributeValue(null,"Type");r.external="External".equalsIgnoreCase(p.getAttributeValue(null,"TargetMode"));rels.put(id,r);
            }}
        }
        List<String[]> sheets=new ArrayList<>();
        try(InputStream in=open(zip,"xl/workbook.xml",true)){
            XmlPullParser p=parser(factory,in);int event;while((event=p.nextToken())!=XmlPullParser.END_DOCUMENT){checkToken(event);if(event==XmlPullParser.START_TAG&&SHEET.equals(p.getNamespace())&&p.getName().equals("sheet")){
                String name=p.getAttributeValue(null,"name"),id=p.getAttributeValue(REL,"id");Relationship r=rels.get(id);
                if(name==null||name.length()>128||r==null||r.target==null||r.external)throw new IOException("Workbook has an invalid or external sheet relationship.");
                if(r.type!=null&&r.type.endsWith("/worksheet")){sheets.add(new String[]{name,safeSheetPath(r.target)});if(sheets.size()>MAX_SECTIONS)throw new IOException("Workbook has too many sheets.");}
            }}
        }
        if(sheets.isEmpty())throw new IOException("Workbook has no readable worksheets.");
        List<String> shared=sharedStrings(zip,factory);List<Section> result=new ArrayList<>();int[] total={0};
        for(String[] sheet:sheets){worksheet(zip,factory,sheet[0],sheet[1],shared,result,total);if(result.size()>MAX_SECTIONS)throw new IOException("Workbook has too many text sections.");}
        return result;
    }
    private static String safeSheetPath(String target)throws IOException {
        if(target.indexOf('\\')>=0||target.contains(":")||target.contains("?"))throw new IOException("Unsupported workbook sheet path.");
        String path=target.startsWith("/")?target.substring(1):"xl/"+target;
        if(!path.startsWith("xl/worksheets/")||path.contains("..")||!path.endsWith(".xml"))throw new IOException("Unsupported workbook sheet path.");return path;
    }
    private static List<String> sharedStrings(ZipFile zip,ParserFactory factory)throws Exception {
        List<String> values=new ArrayList<>();InputStream raw=open(zip,"xl/sharedStrings.xml",false);if(raw==null)return values;
        try(InputStream in=raw){XmlPullParser p=parser(factory,in);int event,phonetic=0;boolean item=false,text=false;StringBuilder value=new StringBuilder();int total=0;
            while((event=p.nextToken())!=XmlPullParser.END_DOCUMENT){checkToken(event);
                if(event==XmlPullParser.START_TAG&&SHEET.equals(p.getNamespace())){String name=p.getName();if(name.equals("si")){item=true;value.setLength(0);}else if(name.equals("rPh"))phonetic++;else if(name.equals("t")&&item&&phonetic==0)text=true;}
                else if((event==XmlPullParser.TEXT||event==XmlPullParser.ENTITY_REF)&&text)append(value,p.getText());
                else if(event==XmlPullParser.END_TAG&&SHEET.equals(p.getNamespace())){String name=p.getName();if(name.equals("t"))text=false;else if(name.equals("rPh"))phonetic--;else if(name.equals("si")){item=false;total+=value.length();if(total>MAX_TEXT_CHARS||values.size()>=100000)throw new IOException("Workbook shared strings exceed the extraction limit.");values.add(value.toString());}}
            }
        }return values;
    }
    private static void worksheet(ZipFile zip,ParserFactory factory,String name,String path,List<String> shared,List<Section> result,int[] total)throws Exception {
        StringBuilder section=new StringBuilder(),value=new StringBuilder();int row=0,first=0,last=0;String address="",type="",capture="";boolean unknownRow=false;int before=result.size();
        try(InputStream in=open(zip,path,true)){
            XmlPullParser p=parser(factory,in);int event;while((event=p.nextToken())!=XmlPullParser.END_DOCUMENT){checkToken(event);
                if(event==XmlPullParser.START_TAG&&SHEET.equals(p.getNamespace())){
                    String tag=p.getName();if(tag.equals("row")){String n=p.getAttributeValue(null,"r");row=parseRow(n);}
                    else if(tag.equals("c")){address=p.getAttributeValue(null,"r");type=p.getAttributeValue(null,"t");value.setLength(0);}
                    else if(tag.equals("v")||(tag.equals("t")&&"inlineStr".equals(type)))capture=tag;
                }else if((event==XmlPullParser.TEXT||event==XmlPullParser.ENTITY_REF)&&!capture.isEmpty())append(value,p.getText());
                else if(event==XmlPullParser.END_TAG&&SHEET.equals(p.getNamespace())){
                    String tag=p.getName();if(tag.equals(capture))capture="";
                    if(tag.equals("c")){
                        String content=value.toString();if("s".equals(type)&&!content.isEmpty())try{int i=Integer.parseInt(content.trim());if(i<0||i>=shared.size())throw new NumberFormatException();content=shared.get(i);}catch(NumberFormatException error){throw new IOException("Workbook has an invalid shared-string reference.");}
                        if(!content.isEmpty()){
                            int actualRow=cellRow(address);if(actualRow==0)actualRow=row;
                            String line=(address!=null&&!address.isEmpty()?address+": ":"")+content+"\n";total[0]+=line.length();if(total[0]>MAX_TEXT_CHARS)throw new IOException("Workbook contains too much extractable text.");
                            if(section.length()>0&&section.length()+line.length()>PlainTextDocument.SECTION_CHARS){result.add(new Section(section.toString(),name,unknownRow?0:first,unknownRow?0:last));section.setLength(0);first=0;last=0;unknownRow=false;}
                            for(String piece:PlainTextDocument.split(line)){
                                if(section.length()>0&&section.length()+piece.length()>PlainTextDocument.SECTION_CHARS){result.add(new Section(section.toString(),name,unknownRow?0:first,unknownRow?0:last));section.setLength(0);first=0;last=0;unknownRow=false;}
                                if(actualRow==0)unknownRow=true;else {if(first==0||actualRow<first)first=actualRow;if(actualRow>last)last=actualRow;}section.append(piece);
                            }
                        }
                        address="";type="";value.setLength(0);
                    }
                }
                if(result.size()>MAX_SECTIONS)throw new IOException("Workbook has too many text sections.");
            }
        }
        if(section.length()>0||result.size()==before)result.add(new Section(section.toString(),name,unknownRow?0:first,unknownRow?0:last));
    }
    private static int parseRow(String value){try{int n=Integer.parseInt(value);return n>0&&n<=1048576?n:0;}catch(Exception ignored){return 0;}}
    private static int cellRow(String address){if(address==null||!address.matches("[A-Za-z]{1,3}[1-9][0-9]{0,6}"))return 0;int i=0;while(i<address.length()&&Character.isLetter(address.charAt(i)))i++;return parseRow(address.substring(i));}
}

