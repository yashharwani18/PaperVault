package org.localknowledge.library;

import java.io.*;
import java.nio.*;
import java.nio.charset.*;
import java.util.*;

/** Bounded, text-only UTF-8/UTF-16 extraction with lossless section boundaries. */
final class PlainTextDocument {
    static final int MAX_BYTES=10*1024*1024,SECTION_CHARS=16000,MAX_SECTIONS=2000;
    static boolean supports(String extension){return Arrays.asList("txt","md","csv","tsv").contains(extension.toLowerCase(Locale.ROOT));}
    static List<String> read(File file)throws IOException {
        if(file.length()>MAX_BYTES)throw new IOException("Text document exceeds the 10 MB extraction limit.");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(InputStream in=new FileInputStream(file)){byte[] block=new byte[32768];int n,total=0;while((n=in.read(block))!=-1){total+=n;if(total>MAX_BYTES)throw new IOException("Text document exceeds the 10 MB extraction limit.");bytes.write(block,0,n);}}
        byte[] input=bytes.toByteArray();int offset=0;Charset charset=StandardCharsets.UTF_8;
        if(input.length>=3&&(input[0]&255)==0xef&&(input[1]&255)==0xbb&&(input[2]&255)==0xbf)offset=3;
        else if(input.length>=2&&(input[0]&255)==0xff&&(input[1]&255)==0xfe){charset=StandardCharsets.UTF_16LE;offset=2;}
        else if(input.length>=2&&(input[0]&255)==0xfe&&(input[1]&255)==0xff){charset=StandardCharsets.UTF_16BE;offset=2;}
        String text;
        try{text=charset.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(input,offset,input.length-offset)).toString();}
        catch(CharacterCodingException error){throw new IOException("Text encoding is unsupported or invalid. Save the file as UTF-8 or UTF-16.",error);}
        if(text.indexOf('\0')>=0)throw new IOException("Text file contains binary data or an unsupported encoding.");
        return split(text);
    }
    static List<String> split(String text)throws IOException {
        List<String> sections=new ArrayList<>();int start=0;
        while(start<text.length()){
            int end=Math.min(text.length(),start+SECTION_CHARS);
            if(end<text.length()&&end>start&&Character.isHighSurrogate(text.charAt(end-1)))end--;
            if(end<text.length()){int newline=text.lastIndexOf('\n',end-1);if(newline>=start+SECTION_CHARS/2)end=newline+1;}
            sections.add(text.substring(start,end));if(sections.size()>MAX_SECTIONS)throw new IOException("Text document has too many sections.");start=end;
        }
        if(sections.isEmpty())sections.add("");return sections;
    }
}
